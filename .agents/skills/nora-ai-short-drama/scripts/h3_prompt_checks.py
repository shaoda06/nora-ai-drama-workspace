"""Offline mode-aware H3 text checks and evidence binding; never generates."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from project_paths import project_file

SECTIONS = ('subject_definitions', 'summary', 'retention_analysis',
            'detailed_description', 'overall_soundscape', 'non_diegetic_music')
BASE_SECTIONS = ('integrated_multimodal_description', 'overall_soundscape', 'non_diegetic_music')
REFERENCE_MODES = ('r2v', 'v2v', 'rv2v')
REVIEW_ITEMS = ('identity', 'space_action', 'continuity_sound', 'translation')
TAG = re.compile(r'<(?:Subject|Picture|Audio|Video) \d+>|\[Shot \d+\]|\(S\d+\)')
SUBJECT = re.compile(r'<Subject (\d+)>')
HAN = re.compile(r'[\u3400-\u9fff]')
CARDINAL = re.compile(
    r'(?:东北|东南|西北|西南|[东西南北])(?:侧|方|向|面|缘|部|端|边|角|区|阵眼|阵脚|阵幕|幕|防线|冷月光)'
    r'|(?:向|往|朝|由|从)(?:东北|东南|西北|西南|[东西南北])'
    r'|[东西南北](?=在画面|\d|[一二三四五六七八九十]+米)'
    r'|东南西北|南北轴|东西轴'
    r'|\b(?:(?:north|south)(?:east|west)?|east|west)(?:ern|ward|wards)?\b', re.I)


def shot_blocks(prompt, mode='r2v'):
    parsed = sections(prompt, SECTIONS if mode in REFERENCE_MODES else BASE_SECTIONS,
                      allow_prefix=mode not in REFERENCE_MODES)
    body = parsed['detailed_description' if mode in REFERENCE_MODES else 'integrated_multimodal_description']
    return [(int(m[1]), m[2].strip()) for m in re.finditer(
        r'\[Shot (\d+)\](.*?)(?=\[Shot \d+\]|\Z)', body, re.S)]


def spatial_review_findings(prompt, check, mode='r2v'):
    blocks = shot_blocks(prompt, mode)
    rows = check.get('shots', [])
    if (not blocks or not isinstance(rows, list)
            or any(not isinstance(row, dict) or type(row.get('shot')) is not int for row in rows)
            or len({row['shot'] for row in rows}) != len(rows)
            or sorted(row['shot'] for row in rows) != sorted(shot for shot, _ in blocks)):
        return [{'code': 'review_shot_coverage', 'detail': 'space_action.shots必须逐项覆盖实际画面正文全部Shot，不重复、不遗漏'}]
    errors = []
    for row in rows:
        body = next(body for shot, body in blocks if shot == row['shot'])
        quote, note = row.get('prompt_quote'), row.get('note')
        if not isinstance(quote, str) or not quote.strip() or quote not in body:
            errors.append({'code': 'review_shot_evidence', 'detail': f"Shot {row['shot']}缺少该镜最终正文的准确片段"})
        if not isinstance(note, str) or not note.strip():
            errors.append({'code': 'review_shot_note', 'detail': f"Shot {row['shot']}缺少实际空间与动作判断"})
    return errors


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sections(text, headings=SECTIONS, allow_prefix=False):
    matches = list(re.finditer(r'^(' + '|'.join(headings) + r'):[ \t]*', text, re.M))
    if [m[1] for m in matches] != list(headings) or (not allow_prefix and text[:matches[0].start()].strip()):
        return None
    return {m[1]: text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
            for i, m in enumerate(matches)}


def group_mode(workflow, node, index):
    inputs = workflow[node]['inputs']
    timeline = json.loads(inputs['timeline_data'])
    group = timeline['segments'][index]
    raw = group.get('taskType') or group.get('task_type') or timeline['global'].get('taskType') or inputs['task_type']
    match = re.match(r'^(r2v|rv2v|v2v|t2v|i2v|fl2v)\b', raw.strip().lower())
    if not match:
        raise ValueError('无法识别H3分段模式：' + raw)
    return match[1], group


def keyframe_slots(group):
    images = {item['index']: item for item in group.get('refs', [])}
    for index, field in ((0, 'startImage'), (1, 'endImage')):
        image = group.get(field)
        if image and (image.get('imageFile') or image.get('imageB64')):
            images[index] = image
    image = group.get('genImage')
    if 0 not in images and image and (image.get('imageFile') or image.get('imageB64')):
        images[0] = image
    return {index for index, image in images.items() if image.get('imageFile') or image.get('imageB64')}


def chinese_text(text):
    """Read the existing document section, or an existing frozen plain-text copy."""
    match = re.search(r'^## 中文提示词参考版\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if match:
        block = re.search(r'^```(?:text)?\s*\n(.*?)^```\s*$', match[1], re.M | re.S)
        if not block:
            raise ValueError('中文提示词参考版章节缺少完整text围栏')
        return block[1].strip()
    return text.strip()


def selected_groups(workflow):
    for node_id, node in workflow.items():
        if node['class_type'] != 'MiniMaxH3Director':
            continue
        timeline = json.loads(node['inputs']['timeline_data'])
        common = timeline['global'] if timeline['global'].get('commonEnabled') else {}
        indices = sorted(timeline['runSelection']) if timeline.get('runSelectEnabled') else range(len(timeline['segments']))
        for index in indices:
            group = timeline['segments'][index]
            prompt = '\n\n'.join(p.strip() for p in (common.get('prompt', ''), group['prompt']) if p.strip())
            # Bind the text, duration, references and continuity settings that were reviewed.
            mode, _ = group_mode(workflow, str(node_id), index)
            reviewed = {'common': common, 'group': group}
            if mode != 'r2v':
                reviewed['mode'] = mode
            signature = digest(json.dumps(reviewed, ensure_ascii=False, sort_keys=True))
            yield str(node_id), index, prompt, signature


def text_findings(prompt, chinese=None, names=None, *, mode='r2v', images=None, duration=None):
    errors = []
    def issue(code, detail):
        errors.append({'code': code, 'detail': detail})
    reference = mode in REFERENCE_MODES
    headings = SECTIONS if reference else BASE_SECTIONS
    english = sections(prompt, headings, allow_prefix=not reference)
    if english is None:
        issue('sections', '英文必须包含完整且有序的' + ('Ref2VA六节' if reference else '基础模式三节'))
        return errors
    prefix = prompt[:prompt.index(headings[0] + ':')].strip()
    if not reference:
        slots = images if images is not None else ({0, 1} if mode == 'fl2v' else {0} if mode == 'i2v' else set())
        if mode == 'fl2v':
            if slots == {0, 1}:
                valid = prefix.startswith('How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 ')
            elif slots == {0}:
                valid = prefix == 'For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.'
            elif slots == {1}:
                valid = prefix.startswith('How the reference pictures align with the target video — <Picture 1> ')
            else:
                valid = not slots and not prefix
        elif mode == 'i2v':
            valid = slots == {0} and prefix == 'For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.'
        else:
            valid = mode == 't2v' and not prefix and not slots
        if not valid:
            issue('keyframe_alignment', '模式、首尾图槽位与首行对齐指令不对应')
        if mode == 'fl2v' and 1 in slots:
            ending = re.search(r'\(from (?:\[)?Shot (\d+)(?:\])?\) aligns with the (\d+\.\d{2})-second mark of the target video\.$', prefix)
            if not ending or int(ending[1]) != len(re.findall(r'\[Shot \d+\]', english[headings[0]])) or (duration is not None and abs(float(ending[2]) - duration) > .011):
                issue('keyframe_timing', '尾帧对齐时间或最后镜号与本段不一致')
    definitions = {}
    for match in SUBJECT.finditer(english.get('subject_definitions', '')):
        tail = english['subject_definitions'][match.end():]
        name = re.match(r'\s*([\u3400-\u9fff][\u3400-\u9fffA-Za-z0-9·]*)', tail)
        if name:
            definitions[match[1]] = name[1]
        else:
            issue('subject_name', f'{match[0]}定义后必须紧接准确中文名称，不能用拼音或译名')
    if reference and names is not None and definitions != names:
        issue('subject_mapping', '正文Subject中文名称与核对记录的主体表不一致')
    for section, body in english.items():
        for match in SUBJECT.finditer(body):
            name = definitions.get(match[1])
            if name is None or not body[match.end():].lstrip().startswith(name):
                issue('subject_reference', f'{section}中{match[0]}缺少对应中文全名')
    # Spatial descriptions only: dialogue, visible quoted text and declared names
    # are not geography instructions. Ambiguous direction words remain semantic review.
    for language, parsed in [('模型正文', english), ('中文参考', sections(chinese, headings, allow_prefix=not reference) if chinese is not None else None)]:
        if parsed is None:
            continue
        for section, body in parsed.items():
            if section in ('overall_soundscape', 'non_diegetic_music'):
                continue
            body = re.sub(r'<d>.*?</d>|“[^”]*”|「[^」]*」|"[^"\n]*"', '', body, flags=re.S)
            body = body.replace('东方幻想', '')  # Art direction, not a spatial coordinate.
            for name in sorted(definitions.values(), key=len, reverse=True):
                body = body.replace(name, '')
            found = list(dict.fromkeys(m[0] for m in CARDINAL.finditer(body)))
            if found:
                issue('spatial_coordinates', f'{language}/{section}存在未换算的地理方位：' + '、'.join(found))
    # Only unequivocal named-role substitutions; ordinary pronouns and quoted dialogue
    # are left to the semantic review, not rejected by a broad natural-language regex.
    action = re.sub(r'<d>.*?</d>|“[^”]*”|"[^"\n]*"', '', english.get('detailed_description', ''), flags=re.S)
    role = re.search(r'\b(?:the\s+(?:(?:young|middle-aged|apron-wearing|bearded|male|female)\s+)*(?:man|woman|boy|girl|villager)|his\s+(?:wife|mother)|her\s+(?:husband|son))\b', action, re.I)
    if role:
        issue('role_alias', '动作中以角色代称替换主体：' + role[0])
    subtitle_rules = [s for s in re.split(r'(?<=[.!?])\s+|\n', prompt)
                      if re.search(r'\b(?:no|without|never|prohibit\w*|forbid\w*)\b[^.\n]{0,200}\bsubtitles?\b', s, re.I)]
    full_span = r'\b(?:(?:throughout|entire|whole|full)[^.\n]{0,40}(?:video|clip|sequence)|all frames|first frame[^.\n]{0,40}last frame|start to (?:the )?end)\b'
    visual_description = english['detailed_description' if reference else 'integrated_multimodal_description']
    visual_description = re.sub(r'<d>.*?</d>', '', visual_description, flags=re.S)
    chinese_subtitle_rule = re.search(r'(?:^|[\n。！？.!?])\s*全程不要出现字幕(?=[。！？.!?\s]|$)', visual_description)
    if not chinese_subtitle_rule and not any(re.search(full_span, s, re.I) for s in subtitle_rules):
        issue('subtitle_rule', '缺少覆盖全片的无字幕指令（语义完整性仍需内容核对）')
    if chinese is not None:
        translated = sections(chinese, headings, allow_prefix=not reference)
        if translated is None:
            issue('translation_sections', '中文参考版必须保留当前模式完整有序的英文标题')
        else:
            if not reference:
                translated_prefix = chinese[:chinese.index(headings[0] + ':')]
                if Counter(re.findall(r'\d+(?:\.\d+)?', prefix)) != Counter(re.findall(r'\d+(?:\.\d+)?', translated_prefix)):
                    issue('translation_numbers', '首尾对齐说明的中英文数字不对应')
            for section in headings:
                if Counter(TAG.findall(english[section])) != Counter(TAG.findall(translated[section])):
                    issue('translation_tags', section + '中英文标签或镜号不对应，不得用摘要替代')
                english_numbers = english[section].replace('3D', '三维').replace('2D', '二维')
                chinese_numbers = translated[section].replace('3D', '三维').replace('2D', '二维')
                if Counter(re.findall(r'\d+(?:\.\d+)?', english_numbers)) != Counter(re.findall(r'\d+(?:\.\d+)?', chinese_numbers)):
                    issue('translation_numbers', section + '中英文数字不对应')
                if not translated[section]:
                    issue('translation_empty', section + '中文正文为空')
                for match in SUBJECT.finditer(translated[section]):
                    name = definitions.get(match[1])
                    if name and not translated[section][match.end():].lstrip().startswith(name):
                        issue('translation_name', section + '中文Subject后缺少准确名称')
    return errors


def bind_review(project, workflow, annotations):
    """Bind new semantic notes to actual inputs; never invent passed judgements."""
    review = deepcopy(annotations)
    signatures = {(node,index): signature for node,index,_,signature in selected_groups(workflow)}
    nodes = {node for node,_ in signatures}
    texts = {}
    def read(name):
        path = project_file(project, name)
        if path not in texts:
            text = path.read_text('utf-8-sig')
            texts[path] = text, digest(text)
        return texts[path]
    for row in review['groups']:
        if 'node' not in row and len(nodes)==1:
            row['node'] = next(iter(nodes))
        if 'input_sha256' in row or 'sha256' in row['chinese'] or any('sha256' in source for check in row['checks'].values() for source in check.get('sources',[])):
            raise ValueError('已绑定的内容核对记录应保留原映射，不自动重新绑定；新核对只传判断、原文与路径')
        row['input_sha256'] = signatures[row['node'],row['index']]
        row['chinese']['sha256'] = digest(chinese_text(read(row['chinese']['file'])[0]))
        for check in row['checks'].values():
            for source in check.get('sources', []):
                source['sha256'] = read(source['file'])[1]
    review['version'] = 1
    return review


def audit(project, workflow, mapping):
    """Validate facts and evidence presence, not the truth of a reviewer's judgement."""
    project = Path(project).resolve()
    review = mapping.get('content_review', {})
    if not isinstance(review, dict):
        review = {}  # Historical free-text reviews are evidence, not a current pass.
    rows = review.get('groups', [])
    failures, results, files = [], [], set()
    if review.get('version') != 1 or not isinstance(rows, list) or any(
            not isinstance(r, dict) or not isinstance(r.get('node'), str) or type(r.get('index')) is not int for r in rows):
        failures.append({'code': 'review_missing', 'detail': '输入映射缺少version=1的content_review及逐组核对证据'})
        rows = []
    texts = {}
    def read_once(path):
        if path not in texts:
            text = path.read_text('utf-8-sig')
            texts[path] = text, digest(text)
        return texts[path]
    chinese_versions = {}
    expected_keys = []
    for node, index, prompt, signature in selected_groups(workflow):
        mode, group = group_mode(workflow, node, index)
        key = (node, index)
        expected_keys.append(key)
        matching = [r for r in rows if (r.get('node'), r.get('index')) == key]
        errors, chinese, chinese_signature = [], None, None
        row = matching[0] if len(matching) == 1 else {}
        def issue(code, detail):
            errors.append({'code': code, 'detail': detail})
        if len(matching) != 1:
            issue('review_group', '每个选中原组必须且只能有一项内容核对记录')
        if row.get('input_sha256') != signature:
            issue('review_stale', '内容核对未绑定当前公共＋本组输入；请重新核对变化部分')
        chinese_info = row.get('chinese', {})
        if not isinstance(chinese_info, dict):
            issue('review_schema', 'chinese必须为文件与指纹对象')
            chinese_info = {}
        if not chinese_info:
            contexts = mapping.get('generation_contexts', [])
            if len(contexts) == 1:
                chinese_info = {'file': contexts[0].get('prompts', {}).get('chinese')}
        try:
            path = project_file(project, chinese_info['file'])
            files.add(str(path))
            if path not in chinese_versions:
                chinese = chinese_text(read_once(path)[0])
                chinese_versions[path] = chinese, digest(chinese)
            chinese, chinese_signature = chinese_versions[path]
            if chinese_info.get('sha256') != chinese_signature:
                issue('translation_stale', '中文核对记录与当前中文正文不一致')
        except (KeyError, OSError, ValueError, TypeError) as exc:
            issue('translation_missing', '缺少可读取的中文参考版：' + str(exc))
        names = row.get('subjects')
        if not isinstance(names, dict) or (mode in REFERENCE_MODES and not names) or any(not isinstance(n, str) or not HAN.search(n) for n in names.values()):
            issue('review_subjects', '缺少Subject编号到准确中文名称的主体表')
            names = None
        findings = text_findings(prompt, chinese, names, mode=mode,
                                 images=keyframe_slots(group), duration=group['durationSec'])
        omission = row.get('subtitle_instruction_omission_authorization')
        if omission is not None:
            if not isinstance(omission, str) or not omission.strip():
                issue('review_schema', '省略字幕指令必须记录用户对本组选中输入的明确授权')
            else:
                findings = [item for item in findings if item['code'] != 'subtitle_rule']
        errors.extend(findings)
        checks = row.get('checks', {})
        if not isinstance(checks, dict):
            issue('review_schema', 'checks必须为逐类核对对象')
            checks = {}
        for category in REVIEW_ITEMS:
            check = checks.get(category, {})
            if not isinstance(check, dict):
                issue('review_schema', category + '必须为核对对象，不能只填通过')
                continue
            if check.get('status') != 'passed' or not isinstance(check.get('note'), str) or not check['note'].strip():
                issue('review_incomplete', category + '未完成，必须记录具体判断及修正结果')
                continue
            quote = check.get('prompt_quote', '')
            if not isinstance(quote, str) or not quote.strip() or quote not in prompt:
                issue('review_evidence', category + '缺少当前英文中的准确检查片段')
            if category == 'translation':
                quote = check.get('chinese_quote', '')
                if not chinese or not isinstance(quote, str) or not quote.strip() or quote not in chinese:
                    issue('review_evidence', 'translation缺少对应中文片段')
            if category == 'space_action' and not any(e['code'] == 'sections' for e in findings):
                errors.extend(spatial_review_findings(prompt, check, mode))
            evidence = check.get('sources', [])
            if not isinstance(evidence, list) or not evidence:
                issue('review_evidence', category + '缺少上游依据原文及路径')
                continue
            for source in evidence:
                if not isinstance(source, dict):
                    issue('review_schema', category + '的sources必须包含文件、原文与指纹对象')
                    continue
                try:
                    path = project_file(project, source['file'])
                    files.add(str(path))
                    text, source_signature = read_once(path)
                    if source.get('sha256') != source_signature:
                        issue('review_source_stale', category + '的依据已变化：' + source['file'])
                    quote = source.get('quote', '')
                    if not isinstance(quote, str) or not quote.strip() or quote not in text:
                        issue('review_evidence', category + '的依据原文不存在：' + source['file'])
                except (KeyError, OSError, ValueError) as exc:
                    issue('review_evidence', category + '依据不可读取：' + str(exc))
        results.append({'node': node, 'index': index, 'input_sha256': signature,
                        'chinese_sha256': chinese_signature,
                        'subtitle_instruction_omission_authorization': omission,
                        'ok': not errors, 'issues': errors})
    if sorted((r.get('node', ''), r.get('index', -1)) for r in rows) != sorted(expected_keys):
        failures.append({'code': 'review_scope', 'detail': '核对记录必须准确覆盖本次选中原组，不含重复或未选中组'})
    return {'version': 1, 'ok': bool(results) and not failures and all(r['ok'] for r in results),
            'issues': failures, 'groups': results, 'sources': sorted(files),
            'scope': '确定性文本检查及内容核对证据绑定；不证明语义判断或生成质量正确'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', help='Project root; all evidence must stay within this directory')
    parser.add_argument('--workflow', help='Local API JSON; read only, no service connection')
    parser.add_argument('--mapping', help='Existing 输入映射.json with content_review; read only')
    parser.add_argument('--document', action='append', help='Prompt Markdown document; repeatable offline text-only check, no workflow preparation')
    parser.add_argument('--mode', default='r2v', choices=(*REFERENCE_MODES, 't2v', 'i2v', 'fl2v'), help='Document mode only; default r2v')
    parser.add_argument('--output', help='Optional NEW local JSON report; refuses to overwrite an existing file')
    parser.add_argument('--basis-file', action='append', default=[], help='Project-relative UTF-8 source to fingerprint for review evidence; repeatable, read only')
    args = parser.parse_args()
    if args.document:
        if args.project or args.workflow or args.mapping or args.basis_file:
            parser.error('--document不能与工作流或证据绑定参数混用')
    elif not all((args.project, args.workflow, args.mapping)):
        parser.error('工作流核对需要--project、--workflow、--mapping；仅检查正文请用--document')
    try:
        if args.document:
            documents = []
            for name in args.document:
                text = Path(name).read_text('utf-8-sig')
                match = re.search(r'^## 提交给模型的完整提示词\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
                block = re.search(r'^```(?:text)?\s*\n(.*?)^```\s*$', match[1], re.M | re.S) if match else None
                if not block:
                    raise ValueError(name + '缺少完整模型正文text围栏')
                prompt = block[1].strip()
                issues = text_findings(prompt, chinese_text(text), mode=args.mode)
                if len(prompt) > 7000:
                    issues.append({'code': 'prompt_length', 'detail': '完整模型正文超过7000字符'})
                documents.append({'file': name, 'characters': len(prompt), 'ok': not issues, 'issues': issues})
            result = {'ok': all(d['ok'] for d in documents), 'documents': documents,
                      'scope': '离线确定性正文检查；未检查输入绑定，不证明语义正确或已获生成授权'}
        else:
            result = audit(args.project, json.loads(Path(args.workflow).read_text('utf-8-sig')),
                       json.loads(Path(args.mapping).read_text('utf-8-sig')))
            result['evidence_basis'] = [{'file': name, 'sha256': digest(project_file(Path(args.project).resolve(), name).read_text('utf-8-sig'))}
                                    for name in args.basis_file]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {'ok': False, 'error': str(exc)}
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with Path(args.output).open('x', encoding='utf-8') as stream:
            stream.write(output + '\n')
    print(output)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
