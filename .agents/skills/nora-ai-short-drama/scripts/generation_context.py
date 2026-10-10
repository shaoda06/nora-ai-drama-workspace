"""Save the submitted video's inputs in the existing project mapping, before POST."""
from datetime import datetime
import json
from pathlib import Path
import re

STAGES = {'video-first-pass': '一采', 'video-second-pass': '二采', 'video-postprocess': '后处理'}


def prepare_generation_context(project, record, workflow, task_type, uploaded_materials=None):
    project, record = Path(project).resolve(), Path(record).resolve()
    mapping_file = record / '输入映射.json'
    mapping = json.loads(mapping_file.read_text(encoding='utf-8-sig'))
    stage = STAGES[task_type]
    scene = mapping['scene']
    if not re.fullmatch(r'EP\d{3,}-C\d{3,}', scene):
        raise ValueError('输入映射的场次编号不正确')
    payloads = {}

    def inside(path):
        path = (project / path).resolve()
        if not path.is_relative_to(project):
            raise ValueError('生成资料越出项目：' + str(path))
        return path

    def snapshot(target, data):
        target = inside(target)
        if target in payloads and payloads[target] != data or target.exists() and target.read_bytes() != data:
            raise ValueError('当次资料已冻结，不可覆盖：' + str(target))
        payloads[target] = data
        return target.relative_to(project).as_posix()

    if stage != '后处理':
        directors = [node for node in workflow.values() if node['class_type'] == 'MiniMaxH3Director']
        if len(directors) != 1:
            raise ValueError('资料保存需要一个正式MiniMaxH3Director节点')
        inputs = directors[0]['inputs']
        timeline = json.loads(inputs['timeline_data'])
        groups = timeline['segments']
        indices = sorted(timeline['runSelection']) if timeline.get('runSelectEnabled', False) else list(range(len(groups)))
        if len(mapping['segments']) != len(groups) or mapping['selected_indices'] != indices or not indices:
            raise ValueError('输入映射的原组序或执行范围与实际API不一致')
        storyboard = inside(mapping.get('storyboard_file') or f"09-剧集制作/{scene.split('-')[0]}/03-分镜脚本/{scene}-场次分镜.md")
        text = storyboard.read_text(encoding='utf-8-sig')
        version = re.search(r'^- 文档版本[：:][ \t]*(.+)$', text, re.M)
        if not version or version[1].strip().rstrip('。') != mapping['scene_storyboard_version'].rstrip('。'):
            raise ValueError('当次分镜版本与输入映射不一致')
        uploads = {item['input_path']: item for item in mapping['uploads']}
        uploads.update(uploaded_materials or {})
        common = timeline['global']
        if not common['taskType'].startswith('r2v') or timeline['editMode'] != 'segment' or 'r2v_groups' in inputs or 'i2v_groups' in inputs:
            raise ValueError('自动资料保存仅用于现行原生r2v导演台分组，不可按原生组记录外部输入')
        common_enabled = common['commonEnabled']
        if inputs['global_prompt'] != common['prompt']:
            raise ValueError('实际节点的公共提示词与时间线不一致')

        def references(group, reused):
            result = {'common': [], 'segment': []}
            for field, file_field, label in (('refs', 'imageFile', 'Picture'), ('refVideos', 'videoFile', 'Video'), ('refAudios', 'audioFile', 'Audio')):
                public = list(common.get(field, [])) if common_enabled else []
                local = list(group.get(field, []))
                if field == 'refVideos':
                    for data, items in ((common, public), (group, local)):
                        legacy = data.get('referenceVideo')
                        if legacy and (legacy.get('videoFile') or legacy.get('fileName')) and not any(item['index'] == 0 for item in items):
                            if data is not common or common_enabled:
                                items.insert(0, {**legacy, 'index': 0, 'videoFile': legacy.get('videoFile') or legacy['fileName']})
                local_slots = {item['index'] for item in local}
                for scope, items in (('common', [item for item in public if item['index'] not in local_slots]), ('segment', local)):
                    for item in sorted(items, key=lambda item: item['index']):
                        original = inside(uploads[item[file_field]]['file'])
                        slot = f"<{label} {item['index'] + 1}>"
                        prior = next((ref for ref in reused.get(scope, []) if ref['label'] == slot), None)
                        target = inside(prior['file']) if prior else record / '输入素材' / original.name
                        result[scope].append({'file': snapshot(target, original.read_bytes()),
                                              'label': slot,
                                              'original_file': prior.get('original_file', original.relative_to(project).as_posix()) if prior else original.relative_to(project).as_posix()})
            return result
    else:
        indices = mapping['selected_indices']

    contexts = []
    for index in indices:
        segment = mapping['segments'][index]
        identity = f"{segment['segment']}-{segment['round']}-{stage}"
        if not re.fullmatch(re.escape(scene) + r'-P\d{3,}-R\d{3,}-' + stage, identity):
            raise ValueError('生成资料身份与场次不一致：' + identity)
        context = {'identity': identity}
        if stage in ('二采', '后处理'):
            context['source'] = segment['source']
            if not re.fullmatch(re.escape(segment['segment']) + r'-R\d{3,}-(一采|二采|后处理)', context['source']) or context['source'] == identity:
                raise ValueError('接续来源必须是同一分段的已有其他执行身份')
        if stage != '后处理':
            group = groups[index]
            directory = inside(segment['local_execution_dir'])
            if directory.name != identity and not (directory.parent.name == identity and re.fullmatch(r'执行-\d{8}-\d{6}', directory.name)):
                raise ValueError('本段执行附件目录与执行身份不一致')
            prompt = '\n\n'.join(part.strip() for part in
                                  ([common['prompt'], group['prompt']] if common_enabled else [group['prompt']]) if part.strip())
            reused = None
            if segment.get('materials_from'):
                origin = segment['materials_from']
                if not re.fullmatch(re.escape(segment['segment']) + r'-R\d{3,}-(一采|二采)', origin['identity']):
                    raise ValueError('复用资料必须来自同一分段的明确版本')
                old = json.loads(inside(origin['mapping']).read_text(encoding='utf-8-sig'))
                reused = next(item for item in old['generation_contexts'] if item['identity'] == origin['identity'])
            english_file = inside(reused['prompts']['english']) if reused else directory / '模型提示词.txt'
            if english_file.exists() and english_file.read_text(encoding='utf-8-sig').strip() != prompt:
                raise ValueError('已有冻结英文与本次实际API提示词不一致')
            english = snapshot(english_file, english_file.read_bytes() if english_file.exists() else prompt.encode('utf-8'))
            prompts = {'english': english}
            chinese = inside(reused['prompts']['chinese']) if reused and 'chinese' in reused['prompts'] else directory / '中文提示词参考版.txt'
            if chinese.is_file():
                prompts['chinese'] = chinese.relative_to(project).as_posix()
            script_file = snapshot(inside(reused['storyboard']['file']) if reused else record / '分镜脚本.md', storyboard.read_bytes())
            refs = references(group, reused['references'] if reused else {})
            if reused and {scope: [item['label'] for item in refs[scope]] for scope in refs} != {scope: [item['label'] for item in reused['references'][scope]] for scope in refs}:
                raise ValueError('复用资料的实际素材槽位与来源不一致')
            context.update(storyboard={'file': script_file, 'version': mapping['scene_storyboard_version'].rstrip('。')},
                           prompts=prompts, references=refs)
        contexts.append(context)
    if 'generation_contexts' in mapping and mapping['generation_contexts'] != contexts:
        raise ValueError('已有当次资料关联与本次API不一致，不能改写同一执行身份')
    for path, data in payloads.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
    if 'generation_contexts' not in mapping:
        mapping.update(generation_contexts=contexts,
                       generation_contexts_recorded_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                       generation_contexts_basis='统一提交入口在POST前按实际API自动保存当次资料。')
        mapping_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
