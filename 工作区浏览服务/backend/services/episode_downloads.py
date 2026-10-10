"""Download selected approved videos and stage-specific director files."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryFile
from urllib.parse import quote
from zipfile import ZIP_STORED, ZipFile

from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

STAGES = {'后处理': '03-后处理', '二采': '02-二采', '一采': '01-一采'}
KINDS = {'videos': '正式版视频', 'director': '导演包', 'canvas': '画布'}


def resources(store, name, episode, data):
    selected = next((item for item in data['catalogues']['09-剧集制作']['children']
                     if item['name'] == episode), None)
    if selected is None:
        raise FileNotFoundError('剧集不存在')
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


def zip_response(files, filename):
    # Media and director packs are already compressed. Keep their original bytes.
    with ExitStack() as stack:
        archive = stack.enter_context(TemporaryFile())
        with ZipFile(archive, 'w', compression=ZIP_STORED) as bundle:
            for path, member in files:
                bundle.write(path, member)
        archive.seek(0, 2)
        size = archive.tell()
        archive.seek(0)
        cleanup = stack.pop_all()
    return StreamingResponse(iter(lambda: archive.read(1024 * 1024), b''), media_type='application/zip',
                             headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename),
                                      'Content-Length': str(size)}, background=BackgroundTask(cleanup.close))
