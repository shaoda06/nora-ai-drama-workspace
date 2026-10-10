import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote
from zipfile import ZipFile

from fastapi.testclient import TestClient
from backend import main
from backend.services import episode_downloads
from backend.services.projects import ProjectStore


class EpisodeDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / '示例项目'
        self.project.mkdir()
        self.episode = {'name': 'EP001', 'productionComplete': True, 'scenes': ['C001', 'C002'],
                        'segments': {'C001': [], 'C002': []}}
        data = {'catalogues': {'09-剧集制作': {'children': [self.episode]}}}
        for override in (patch.object(main, 'store', ProjectStore(self.root)),
                         patch.object(main, 'entry', return_value={'data': data}),
                         patch.object(episode_downloads, 'DOWNLOAD_DIRECTORY', self.root / 'downloads')):
            override.start()
            self.addCleanup(override.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.url = '/api/projects/示例项目/episodes/EP001/downloads'

    def source(self, relative, content):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def video(self, stage, scene, number, approved=True):
        filename = f'EP001-{scene}-{number}-R001-{stage}.mp4'
        relative = f'09-剧集制作/EP001/06-阶段采用视频/{episode_downloads.STAGES[stage]}/{scene}-场次/{filename}'
        path = self.source(relative, (stage + scene + number).encode())
        stat = path.stat()
        self.episode['segments'][scene].append({'id': number, 'videos': [{
            'approved': approved, 'stage': stage, 'key': relative,
            'fileRevision': str(stat.st_mtime_ns) + '-' + str(stat.st_size)}]})
        return scene + '-场次/' + filename, path.read_bytes()

    def archive(self, stage, kind):
        response = self.client.get(self.url + '/' + stage + '/' + kind)
        self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else '')
        self.assertEqual(response.headers['content-type'], 'application/zip')
        self.assertEqual(int(response.headers['content-length']), len(response.content))
        self.assertIn('示例项目-EP001-' + stage, unquote(response.headers['content-disposition']))
        with ZipFile(BytesIO(response.content)) as bundle:
            return {item.filename: bundle.read(item) for item in bundle.infolist()}

    def test_videos_include_all_scenes_only_approved_and_selected_stage(self):
        expected = {}
        for stage in episode_downloads.STAGES:
            expected[stage] = dict([self.video(stage, 'C001', 'P001'), self.video(stage, 'C002', 'P002')])
            self.video(stage, 'C001', 'P003', approved=False)
        self.source('09-剧集制作/EP001/06-阶段采用视频/01-一采/C001-场次/未选定.mp4', b'unselected')
        self.source('09-剧集制作/EP002/06-阶段采用视频/01-一采/C001-场次/EP002-C001-P001-R001-一采.mp4', b'other episode')
        manifest = self.client.get(self.url).json()
        for stage in episode_downloads.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(manifest[stage]['videos']['count'], 2)
                self.assertEqual(self.archive(stage, 'videos'), expected[stage])

    def test_director_and_canvas_download_original_files_without_outer_zip(self):
        expected = {stage: {'director': {}, 'canvas': {}} for stage in episode_downloads.STAGES}
        for stage, folder in episode_downloads.STAGES.items():
            for scene in self.episode['scenes']:
                for kind, suffix in [('director', '-导演包.mmxpack.zip'), ('canvas', '.workflow.json')]:
                    filename = f'EP001-{scene}-P001-{stage}定稿' + suffix
                    path = self.source(f'09-剧集制作/EP001/06-阶段采用视频/{folder}/{scene}-场次/导演包/{filename}',
                                       (stage + scene + kind).encode())
                    expected[stage][kind][filename] = path.read_bytes()
            self.source(f'09-剧集制作/EP001/06-阶段采用视频/{folder}/C001-场次/导演包/EP002-C001-导演包.mmxpack.zip', b'wrong episode')
            self.source(f'09-剧集制作/EP001/06-阶段采用视频/{folder}/C003-场次/导演包/EP001-C003-导演包.mmxpack.zip', b'not indexed')
        manifest = self.client.get(self.url).json()
        for stage in episode_downloads.STAGES:
            for kind in ('director', 'canvas'):
                with self.subTest(stage=stage, kind=kind):
                    resource = manifest[stage][kind]
                    self.assertIsNone(resource['url'])
                    self.assertEqual(resource['count'], 2)
                    self.assertEqual([file['name'] for file in resource['files']], list(expected[stage][kind]))
                    for file in resource['files']:
                        response = self.client.get(file['url'])
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.content, expected[stage][kind][file['name']])
                        self.assertIn(file['name'], unquote(response.headers['content-disposition']))
                    self.assertEqual(self.client.get(self.url + '/' + stage + '/' + kind).status_code, 422)
        self.assertFalse((self.root / 'downloads').exists())

    def test_empty_stage_has_no_link_and_does_not_reuse_first_pass(self):
        self.source('09-剧集制作/EP001/06-阶段采用视频/01-一采/C001-场次/导演包/EP001-C001-定稿-导演包.mmxpack.zip', b'first pass')
        manifest = self.client.get(self.url).json()
        self.assertEqual(manifest['一采']['director']['count'], 1)
        for stage in ('后处理', '二采'):
            for kind in episode_downloads.KINDS:
                self.assertEqual(manifest[stage][kind], {'count': 0, 'url': None, 'files': []})
                self.assertEqual(self.client.get(self.url + '/' + stage + '/' + kind).status_code, 404 if kind == 'videos' else 422)

    def test_legacy_stage_directory_is_read_without_copying_files(self):
        relative = '09-剧集制作/EP001/其他资料/阶段采用视频/02-二采/C001-场次/导演包/EP001-C001-定稿.workflow.json'
        self.source(relative, b'legacy canvas')
        resource = self.client.get(self.url).json()['二采']['canvas']
        self.assertEqual(resource['files'][0]['name'], 'EP001-C001-定稿.workflow.json')
        self.assertEqual(self.client.get(resource['files'][0]['url']).content, b'legacy canvas')
        self.assertFalse((self.project / '09-剧集制作/EP001/06-阶段采用视频').exists())

    def test_invalid_request_and_missing_episode(self):
        for suffix in ('/其他/videos', '/一采/other'):
            self.assertEqual(self.client.get(self.url + suffix).status_code, 422)
        self.assertEqual(self.client.get(self.url.replace('EP001', 'invalid')).status_code, 422)
        self.assertEqual(self.client.get(self.url.replace('EP001', 'EP002')).status_code, 404)

    def test_missing_selected_video_is_reported_instead_of_partial_zip(self):
        self.video('一采', 'C001', 'P001')
        self.video('一采', 'C002', 'P002')
        key = self.episode['segments']['C002'][0]['videos'][0]['key']
        (self.project / key).unlink()
        self.assertEqual(self.client.get(self.url + '/一采/videos').status_code, 404)

    def test_bundle_uses_project_file_boundary(self):
        (self.root / 'outside.mp4').write_bytes(b'outside project')
        self.episode['segments']['C001'] = [{'videos': [{'approved': True, 'stage': '一采',
                                                       'key': '../outside.mp4', 'fileRevision': ''}]}]
        self.assertEqual(self.client.get(self.url + '/一采/videos').status_code, 404)

    def test_video_archive_uses_dedicated_directory_and_is_removed_after_sending(self):
        self.video('一采', 'C001', 'P001')
        self.archive('一采', 'videos')
        self.assertTrue((self.root / 'downloads').is_dir())
        self.assertEqual(list((self.root / 'downloads').iterdir()), [])

    def test_zip_creation_error_removes_partial_file(self):
        with self.assertRaises(FileNotFoundError):
            episode_downloads.zip_response([(self.root / 'missing.mp4', 'missing.mp4')], 'test.zip')
        self.assertEqual(list((self.root / 'downloads').iterdir()), [])

    def test_sending_error_removes_file(self):
        source = self.source('original.mp4', b'original bytes')
        response = episode_downloads.zip_response([(source, source.name)], 'test.zip')
        self.assertEqual(Path(response.path).parent, self.root / 'downloads')
        self.assertTrue(Path(response.path).exists())

        async def send(message):
            raise OSError('client disconnected')

        with self.assertRaises(OSError):
            asyncio.run(response({'type': 'http', 'method': 'GET', 'headers': []}, None, send))
        self.assertFalse(Path(response.path).exists())
        self.assertEqual(source.read_bytes(), b'original bytes')

    def test_request_cancellation_removes_file(self):
        source = self.source('original.mp4', b'original bytes')
        response = episode_downloads.zip_response([(source, source.name)], 'test.zip')

        async def cancel_transfer():
            sending = asyncio.Event()

            async def send(message):
                if message['type'] == 'http.response.body':
                    sending.set()
                    await asyncio.Event().wait()

            task = asyncio.create_task(response({'type': 'http', 'method': 'GET', 'headers': []}, None, send))
            await sending.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(cancel_transfer())
        self.assertFalse(Path(response.path).exists())

    def test_startup_clears_only_service_video_packages(self):
        directory = self.root / 'downloads'
        directory.mkdir()
        (directory / 'videos-interrupted.zip').write_bytes(b'interrupted')
        (directory / 'keep.txt').write_bytes(b'keep')
        episode_downloads.clear_downloads()
        self.assertEqual([path.name for path in directory.iterdir()], ['keep.txt'])

    def completed_download(self):
        return self.client.get(self.url.replace('/downloads', '/download'))

    def test_completed_zip_contains_all_scenes_in_script_and_storyboard_order(self):
        expected = [self.video('后处理', 'C001', number) for number in ('P005', 'P012', 'P006')]
        expected += [self.video('后处理', 'C002', 'P001')]
        segment = self.episode['segments']['C001'][0]
        segment['videos'].append(dict(segment['videos'][0], approved=False, key='候选视频.mp4'))
        # Script order is authoritative, even when dictionary insertion order differs.
        self.episode['scenes'] = ['C002', 'C001']
        expected = expected[-1:] + expected[:-1]
        response = self.completed_download()
        self.assertEqual(response.status_code, 200)
        self.assertIn('示例项目-EP001-后处理-正式版视频.zip', unquote(response.headers['content-disposition']))
        self.assertEqual(int(response.headers['content-length']), len(response.content))
        with ZipFile(BytesIO(response.content)) as bundle:
            self.assertEqual(bundle.namelist(), [member for member, _ in expected])
            self.assertEqual([bundle.read(member) for member in bundle.namelist()], [content for _, content in expected])

    def test_completed_download_requires_finished_episode_and_every_scene(self):
        self.assertEqual(self.completed_download().status_code, 409)
        self.video('后处理', 'C001', 'P001')
        self.assertEqual(self.completed_download().status_code, 409)
        self.video('后处理', 'C002', 'P001', approved=False)
        self.assertEqual(self.completed_download().status_code, 409)
        video = self.episode['segments']['C002'][0]['videos'][0]
        video.update(approved=True, stage='二采')
        self.assertEqual(self.completed_download().status_code, 409)
        video['stage'] = '后处理'
        self.episode['productionComplete'] = False
        self.assertEqual(self.completed_download().status_code, 409)
        self.episode['productionComplete'] = True
        self.assertEqual(self.completed_download().status_code, 200)
        self.episode['scenes'] = []
        self.assertEqual(self.completed_download().status_code, 409)

    def test_completed_download_rejects_ambiguous_approval_and_any_scene_issue(self):
        self.video('后处理', 'C001', 'P001')
        self.video('后处理', 'C002', 'P001')
        segment = self.episode['segments']['C001'][0]
        segment['videos'].append(dict(segment['videos'][0]))
        self.assertEqual(self.completed_download().status_code, 409)
        segment['videos'].pop()
        self.episode['productionIssues'] = [{'scene': 'C002', 'message': 'other scene'}]
        self.assertEqual(self.completed_download().status_code, 409)
        self.episode['productionIssues'] = [{'message': 'index invalid'}]
        self.assertEqual(self.completed_download().status_code, 409)

    def test_completed_download_missing_or_changed_file_does_not_return_partial_or_history_zip(self):
        self.video('后处理', 'C001', 'P001')
        self.video('后处理', 'C002', 'P001')
        video = self.episode['segments']['C002'][0]['videos'][0]
        path = self.project / video['key']
        path.write_bytes(b'changed')
        self.assertEqual(self.completed_download().status_code, 409)
        path.unlink()
        self.assertEqual(self.completed_download().status_code, 404)

    def test_completed_download_validates_request_and_project_file_boundary(self):
        self.assertEqual(self.client.get(self.url.replace('EP001/downloads', 'invalid/download')).status_code, 422)
        self.assertEqual(self.client.get(self.url.replace('EP001/downloads', 'EP002/download')).status_code, 404)
        self.video('后处理', 'C001', 'P001')
        self.video('后处理', 'C002', 'P001')
        self.episode['segments']['C002'][0]['videos'][0]['key'] = '../outside.mp4'
        (self.root / 'outside.mp4').write_bytes(b'outside')
        self.assertEqual(self.completed_download().status_code, 404)


if __name__ == '__main__':
    unittest.main()
