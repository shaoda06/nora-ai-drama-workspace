"""A single untrimmed video track referencing sibling ZIP members.

Draft JSON: pyJianYingDraft 0.3.0 (Apache-2.0), https://github.com/GuanYixuan/pyJianYingDraft
Native path spelling: zenstory-ai/video-recap-skills, writer.py at 53916862;
verified in Windows Jianying 11.5.0.14471. The token is literal, not a draft ID.
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
    return {'draft_content.json': script.dumps(),
            'draft_meta_info.json': json.dumps(meta, ensure_ascii=False, indent=2)}
