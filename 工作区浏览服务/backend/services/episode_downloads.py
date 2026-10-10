"""Download selected approved videos and stage-specific director files."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_STORED, ZipFile

from fastapi.responses import FileResponse

STAGES = {'后处理': '03-后处理', '二采': '02-二采', '一采': '01-一采'}
KINDS = {'videos': '正式版视频', 'director': '导演包', 'canvas': '画布'}
DOWNLOAD_DIRECTORY = Path(__file__).resolve().parents[2] / 'runtime' / 'downloads'


def indexed_episode(episode, data):
    selected = next((item for item in data['catalogues']['09-剧集制作']['children']
                     if item['name'] == episode), None)
    if selected is None:
        raise FileNotFoundError('剧集不存在')
    return selected


def completed_episode_videos(store, name, episode, data):
    selected = indexed_episode(episode, data)
    if not selected['productionComplete']:
        raise ValueError('本集制作尚未完成')
    if not selected['scenes'] or selected.get('productionIssues'):
        raise ValueError('本集分段资料尚未齐备')
    files = []
    for scene in selected['scenes']:
        segments = selected['segments'][scene]
        if not segments:
            raise ValueError('本集分段资料尚未齐备')
        for segment in segments:
            videos = [video for video in segment['videos'] if video['stage'] == '后处理' and video['approved']]
            if len(videos) != 1:
                raise ValueError('本集尚未全部批准后处理正式版')
            video = videos[0]
            path = store.file(name, video['key'])
            stat = path.stat()
            if video['fileRevision'] != str(stat.st_mtime_ns) + '-' + str(stat.st_size):
                raise ValueError('正式版文件已变化，请等待页面同步后重新下载')
            files.append((path, scene + '-场次/' + Path(video['key']).name))
    return files


def resources(store, name, episode, data):
    selected = indexed_episode(episode, data)
    result = {stage: {kind: [] for kind in KINDS} for stage in STAGES}
    for scene, segments in selected['segments'].items():
        for segment in segments:
            for video in segment['videos']:
                if video['approved']:
                    path = store.file(name, video['key'], video['fileRevision'])
                    result[video['stage']]['videos'].append((path, scene + '-场次/' + Path(video['key']).name))

    root = store.project(name)
    episode_root = root / '09-剧集制作' / episode
    for stage, folder in STAGES.items():
        stage_root = next((base / folder for base in (
            episode_root / '06-阶段采用视频', episode_root / '其他资料/阶段采用视频',
            episode_root / '06-生成结果') if (base / folder).is_dir()), None)
        if stage_root is None:
            continue
        for scene in selected['scenes']:
            directory = stage_root / (scene + '-场次') / '导演包'
            for pattern, kind in (('*-导演包.mmxpack.zip', 'director'), ('*.workflow.json', 'canvas')):
                for source in sorted(directory.glob(episode + '-' + scene + '-' + pattern)):
                    path = store.file(name, source.relative_to(root).as_posix())
                    result[stage][kind].append((path, scene + '-场次/导演包/' + source.name))
    return result


class VideoZipResponse(FileResponse):
    """Remove the request's ZIP after sending, failure, or cancellation."""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            Path(self.path).unlink()


def clear_downloads():
    """Called once at service startup, before it accepts download requests."""
    DOWNLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for path in DOWNLOAD_DIRECTORY.glob('videos-*.zip'):
        path.unlink()


def zip_response(files, filename):
    # Videos are already compressed. Keep their original bytes.
    DOWNLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        with NamedTemporaryFile(dir=DOWNLOAD_DIRECTORY, prefix='videos-', suffix='.zip', delete=False) as archive:
            path = Path(archive.name)
        stack.callback(path.unlink)
        with ZipFile(path, 'w', compression=ZIP_STORED) as bundle:
            for source, member in files:
                bundle.write(source, member)
        response = VideoZipResponse(archive.name, media_type='application/zip', filename=filename)
        stack.pop_all()
    return response
