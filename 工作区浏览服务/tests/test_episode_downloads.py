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
        self.episode = {'name': 'EP001', 'scenes': ['C001', 'C002'],
                        'segments': {'C001': [], 'C002': []}}
        data = {'catalogues': {'09-剧集制作': {'children': [self.episode]}}}
        for override in (patch.object(main, 'store', ProjectStore(self.root)),
                         patch.object(main, 'entry', return_value={'data': data})):
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

    def test_director_and_canvas_are_separate_stage_specific_archives(self):
        expected = {stage: {'director': {}, 'canvas': {}} for stage in episode_downloads.STAGES}
        for stage, folder in episode_downloads.STAGES.items():
            for scene in self.episode['scenes']:
                for kind, suffix in [('director', '-导演包.mmxpack.zip'), ('canvas', '.workflow.json')]:
                    filename = f'EP001-{scene}-P001-{stage}定稿' + suffix
                    path = self.source(f'09-剧集制作/EP001/06-阶段采用视频/{folder}/{scene}-场次/导演包/{filename}',
                                       (stage + scene + kind).encode())
                    expected[stage][kind][scene + '-场次/导演包/' + filename] = path.read_bytes()
            self.source(f'09-剧集制作/EP001/06-阶段采用视频/{folder}/C001-场次/导演包/EP002-C001-导演包.mmxpack.zip', b'wrong episode')
            self.source(f'09-剧集制作/EP001/06-阶段采用视频/{folder}/C003-场次/导演包/EP001-C003-导演包.mmxpack.zip', b'not indexed')
        for stage in episode_downloads.STAGES:
            for kind in ('director', 'canvas'):
                with self.subTest(stage=stage, kind=kind):
                    self.assertEqual(self.archive(stage, kind), expected[stage][kind])

    def test_empty_stage_has_no_link_and_does_not_reuse_first_pass(self):
        self.source('09-剧集制作/EP001/06-阶段采用视频/01-一采/C001-场次/导演包/EP001-C001-定稿-导演包.mmxpack.zip', b'first pass')
        manifest = self.client.get(self.url).json()
        self.assertEqual(manifest['一采']['director']['count'], 1)
        for stage in ('后处理', '二采'):
            for kind in episode_downloads.KINDS:
                self.assertEqual(manifest[stage][kind], {'count': 0, 'url': None})
                self.assertEqual(self.client.get(self.url + '/' + stage + '/' + kind).status_code, 404)

    def test_legacy_stage_directory_is_read_without_copying_files(self):
        relative = '09-剧集制作/EP001/其他资料/阶段采用视频/02-二采/C001-场次/导演包/EP001-C001-定稿.workflow.json'
        self.source(relative, b'legacy canvas')
        self.assertEqual(self.archive('二采', 'canvas'), {'C001-场次/导演包/EP001-C001-定稿.workflow.json': b'legacy canvas'})
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

    def test_temporary_archive_is_closed_after_download(self):
        self.video('一采', 'C001', 'P001')
        archive = tempfile.TemporaryFile()
        with patch.object(episode_downloads, 'TemporaryFile', return_value=archive):
            self.archive('一采', 'videos')
        self.assertTrue(archive.closed)


if __name__ == '__main__':
    unittest.main()
