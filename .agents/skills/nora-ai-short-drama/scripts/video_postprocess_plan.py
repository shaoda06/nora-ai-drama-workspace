#!/usr/bin/env python3
"""Build one postprocessing submission list from completed second-pass approval reports; no queueing."""
import argparse
import copy
import json
from pathlib import Path

import video_approve
from episode_rounds import episode_manifest_key, validate_episode_manifest
from project_paths import project_file
from workflow_paths import workflow_file

PROFILES = {'crop': 'RIFE-自动切镜保护裁切', 'upscale': 'RTX-RIFE-自动切镜保护超分插帧'}


def build(project, request, output):
    root = Path(project).resolve(strict=True)
    output = project_file(root, output)
    episode = request['episode']
    manifest = validate_episode_manifest(video_approve.adopt.load(root / episode_manifest_key(episode)), episode)
    composition = next((r for r in manifest['rounds'] if r['number'] == request['round']), None)
    if composition is None:
        raise ValueError('指定后处理轮次不存在：' + str(request['round']))
    if not request['authorization'].strip():
        raise ValueError('后处理执行授权不能为空')
    profile, orientation = request['profile'], request['orientation']
    if profile not in PROFILES or orientation not in ('landscape', 'portrait'):
        raise ValueError('profile应为crop/upscale，orientation应为landscape/portrait')
    sources = {}
    for name in request['approval_reports']:
        report_path = project_file(root, name)
        report = video_approve.adopt.load(report_path)
        finalization = report['finalization']
        batches = finalization['batches'] if 'batches' in finalization else [finalization]
        if report['state'] != 'completed' or any(batch['stage'] != '二采' for batch in batches):
            raise ValueError('来源二采采用与定稿尚未完成：' + name)
        for batch in batches:
            for source in batch['sources']:
                identity = source['identity']
                if identity in sources:
                    raise ValueError('重复来源二采身份：' + identity)
                sources[identity] = (source, report_path.relative_to(root).as_posix())
    baseline = workflow_file(PROFILES[profile])
    template = video_approve.adopt.load(baseline)
    width, height = (1920, 1080) if orientation == 'landscape' else (1080, 1920)
    tasks, canvases = [], {}
    for scene, data in composition['scenes'].items():
        for segment in data['segments']:
            if segment['stage'] != '后处理':
                raise ValueError('本轮须明确全部后处理对象；先用scene_rounds登记范围')
            part = f'{episode}-{scene}-{segment["id"]}'
            identity = f'{part}-{segment["run"]}-后处理'
            chosen = video_approve.selected(root, part, '二采')
            if chosen not in sources:
                raise ValueError('缺少当前采用二采的完成报告：' + part)
            source, approval = sources[chosen]
            video = project_file(root, source['selected_path'], recorded=True)
            if not video.is_file():
                raise ValueError('来源二采文件缺失：' + chosen)
            directory = Path(f'09-剧集制作/{episode}/其他资料/执行附件/{identity}')
            canvas_path = directory / '内容画布.workflow.json'
            canvas = copy.deepcopy(template)
            placeholder = 'planned/' + video.name
            for node in canvas['nodes']:
                if node['type'] == 'LoadVideo':
                    node['widgets_values_named']['file'] = placeholder
                    node['widgets_values'] = list(node['widgets_values_named'].values())
                elif node['id'] == 1:
                    values = node['widgets_values_named']
                    if profile == 'crop':
                        values.update(width=width, height=height, x=0 if orientation == 'landscape' else 4,
                                      y=4 if orientation == 'landscape' else 0)
                    else:
                        values.update({'resize_type.width': width, 'resize_type.height': height})
                    node['widgets_values'] = list(values.values())
                elif node['type'] == 'VHS_VideoCombine':
                    node['widgets_values_named']['filename_prefix'] = identity
                    node['widgets_values']['filename_prefix'] = identity
            canvases[project_file(root, canvas_path)] = canvas
            tasks.append({'task_type': 'video-postprocess', 'title': part + ' · 后处理',
                          'authorization': request['authorization'],
                          'description': '已采用二采逐段后处理；保留原音轨、播放速度和完整原片，自动切镜保护插帧30fps。',
                          'delivery_basis': f'{PROFILES[profile]}；{width}×{height}、30fps、H.264/yuv420p/CRF19。',
                          'canvas': canvas_path.as_posix(), 'record_dir': directory.as_posix(),
                          'output_nodes': ['16'], 'output_root': request['output_root'],
                          'references': [{'file': video.relative_to(root).as_posix(), 'placeholder': placeholder,
                                          'purpose': '当前采用二采原片，批准与阶段留档见approval_basis'}],
                          'mapping': {'scene': episode + '-' + scene,
                                      'screenplay_version': composition['script']['version'],
                                      'scene_storyboard_version': data['storyboard']['version'],
                                      'scene_modification_round': composition['number'], 'selected_indices': [0],
                                      'segments': [{'segment': part, 'round': segment['run'], 'source': chosen,
                                                    'duration_seconds': segment['duration'],
                                                    'local_execution_dir': directory.as_posix()}],
                                      'source_video': video.relative_to(root).as_posix(),
                                      'baseline': str(baseline), 'approval_basis': approval}})
    plan = {'business_scope': {'episode': episode, 'episode_round': composition['number'],
                              'expected_video_count': len(tasks), 'scenes': list(composition['scenes']),
                              'delivery': '整轮全部成果齐备并按后处理自动采用规则收尾后统一交付，正常部分成功静默。'},
            'tasks': tasks}
    # Refuse all collisions before creating anything; existing accepted plans remain immutable.
    for path in [output, *canvases]:
        if path.exists():
            raise ValueError('目标已存在，沿原清单接续，不覆盖：' + str(path))
    for path, value in [*canvases.items(), (output, plan)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'state': 'planned', 'task_count': len(tasks), 'plan': output.relative_to(root).as_posix(),
            'next_action': 'comfyui_dispatch --plan；未上传、未入队'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='项目根目录，绝对路径或相对当前工作目录')
    parser.add_argument('--request', required=True, help='项目内JSON：episode、round、profile、orientation、authorization、approval_reports、output_root')
    parser.add_argument('--output', required=True, help='新任务清单的项目相对路径；已有文件拒绝覆盖')
    args = parser.parse_args()
    try:
        request = video_approve.adopt.load(project_file(args.project, args.request))
        result = build(args.project, request, args.output)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'state': 'needs_attention', 'error': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
