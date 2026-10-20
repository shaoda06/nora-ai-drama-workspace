"""Small explicit reviewed inputs for isolated preparation tests, never project data."""
import json
from pathlib import Path

from h3_prompt_checks import digest, selected_groups, REVIEW_ITEMS

ENGLISH = '''subject_definitions:
<Subject 1>陈甲 is the person in the identity reference.
summary:
<Subject 1>陈甲 waits beside the open gate.
retention_analysis:
<Subject 1>陈甲 retains the referenced face and clothes.
detailed_description:
[Shot 1] The fixed camera faces the open gate at adult eye height. <Subject 1>陈甲 stands screen right, turns toward the gate and watches the empty passage. No subtitles or title cards appear throughout the entire video.
overall_soundscape:
Wind only; no speech.
non_diegetic_music:
N/A'''
CHINESE = '''subject_definitions:
<Subject 1>陈甲是身份参考图中的人物。
summary:
<Subject 1>陈甲在敞开的门边等候。
retention_analysis:
<Subject 1>陈甲保留参考图中的面容和衣服。
detailed_description:
[Shot 1] 摄影机在成人眼高固定朝向敞开的门。<Subject 1>陈甲站在画面右侧，转向门口，注视空通道。全片没有字幕或标题卡。
overall_soundscape:
仅风声，没有人声。
non_diegetic_music:
N/A'''


def attach_review(project, record, workflow, mapping):
    project, record = Path(project), Path(record)
    chinese = record / 'review-document.md'
    chinese.write_text('## 提交给模型的完整提示词\n\n```text\n' + ENGLISH
                       + '\n```\n\n## 中文提示词参考版\n\n```text\n' + CHINESE + '\n```\n', 'utf-8')
    source = project / 'review-source.md'
    source.write_text('陈甲在门边等待，固定镜头看空通道，无人说话。', 'utf-8')
    proof = {'file': source.relative_to(project).as_posix(), 'sha256': digest(source.read_text('utf-8')),
             'quote': source.read_text('utf-8')}
    groups = []
    for node, index, prompt, signature in selected_groups(workflow):
        groups.append({'node': node, 'index': index, 'input_sha256': signature,
                       'chinese': {'file': chinese.relative_to(project).as_posix(), 'sha256': digest(CHINESE)},
                       'subjects': {'1': '陈甲'}, 'checks': {item: {
                           'status': 'passed', 'note': '已核对门边人物位置、空通道视线及无声动作，与来源一致。',
                           'prompt_quote': '<Subject 1>陈甲', 'chinese_quote': '<Subject 1>陈甲',
                           'sources': [proof.copy()]} for item in REVIEW_ITEMS}})
    mapping['content_review'] = {'version': 1, 'groups': groups}


def replace_prompts(workflow):
    for node in workflow.values():
        if node['class_type'] != 'MiniMaxH3Director':
            continue
        timeline = json.loads(node['inputs']['timeline_data'])
        timeline['global']['prompt'] = ''
        node['inputs']['global_prompt'] = ''
        for group in timeline['segments']:
            group['prompt'] = ENGLISH
        if 'batchWorkspaces' in timeline:
            timeline['batchWorkspaces']['r2v'].update(globalCommon=timeline['global'].copy(), segments=timeline['segments'])
        node['inputs']['timeline_data'] = json.dumps(timeline, ensure_ascii=False)
