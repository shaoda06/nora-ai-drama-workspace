"""A single untrimmed video track referencing sibling ZIP members.

Draft JSON: pyJianYingDraft 0.3.0 (Apache-2.0), https://github.com/GuanYixuan/pyJianYingDraft
Native path spelling: zenstory-ai/video-recap-skills, writer.py at 53916862;
verified in Windows Jianying 11.5.0.14471 and Mac Jianying 11.6.0.
Windows reads draft_content.json; Mac reads the identical draft_info.json.
The token is literal, not a draft ID.
"""
import json
from pathlib import Path
import time
import uuid

import pyJianYingDraft as draft
from pyJianYingDraft import assets
from pymediainfo import MediaInfo


DRAFT_PATH = '##_draftpath_placeholder_0E685133-18CE-45ED-8CB8-2904A212EC80_##/'


def draft_files(files, name):
    """Use the caller's script order, original video duration and embedded audio."""
    materials = []
    for source, member in files:
        material = draft.VideoMaterial(str(source), material_name=member)
        material.path = DRAFT_PATH + member
        materials.append(material)
    first = materials[0]
    info = MediaInfo.parse(str(files[0][0]))
    fps = float(info.video_tracks[0].frame_rate)
    script = draft.ScriptFile(first.width, first.height, fps, True)
    track = script.append_track(draft.TrackSpec(draft.TrackType.video))
    start = 0
    for material in materials:
        script.add_segment(draft.VideoSegment(
            material, draft.trange(start, material.duration),
            source_timerange=draft.trange(0, material.duration), speed=1.0, volume=1.0), track)
        start += material.duration
    identifier = str(uuid.uuid4()).upper()
    script.content.update(id=identifier, name=name)
    meta = json.loads(Path(assets.get_asset_path('DRAFT_META_TEMPLATE')).read_text(encoding='utf-8'))
    now = time.time_ns() // 1000
    meta.update(draft_id=identifier, draft_name=name, tm_duration=start,
                tm_draft_create=now, tm_draft_modified=now)
    # The import bin is indexed separately from timeline materials. Its paths
    # use ./ relative to the draft folder (writer.py _meta_value), not source paths.
    imported = next(group for group in meta['draft_materials'] if group['type'] == 0)
    imported['value'] = [{
        'id': str(uuid.uuid4()).upper(), 'md5': '', 'metetype': 'video', 'type': 0,
        'extra_info': member, 'file_Path': './' + member,
        'width': material.width, 'height': material.height, 'duration': material.duration,
        'create_time': now // 1000000, 'import_time': now // 1000000,
        'import_time_ms': now // 1000, 'item_source': 1,
        'roughcut_time_range': {'start': 0, 'duration': material.duration},
        'sub_time_range': {'start': -1, 'duration': -1},
    } for material, (_, member) in zip(materials, files)]
    content = script.dumps()
    return {'draft_content.json': content, 'draft_info.json': content,
            'draft_meta_info.json': json.dumps(meta, ensure_ascii=False, indent=2)}
