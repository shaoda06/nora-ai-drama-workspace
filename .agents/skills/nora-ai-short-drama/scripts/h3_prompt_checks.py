"""Offline Ref2VA text checks and evidence binding; never uploads or generates."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from project_paths import project_file

SECTIONS = ('subject_definitions', 'summary', 'retention_analysis',
            'detailed_description', 'overall_soundscape', 'non_diegetic_music')
REVIEW_ITEMS = ('identity', 'space_action', 'continuity_sound', 'translation')
TAG = re.compile(r'<(?:Subject|Picture|Audio|Video) \d+>|\[Shot \d+\]|\(S\d+\)')
SUBJECT = re.compile(r'<Subject (\d+)>')
HAN = re.compile(r'[\u3400-\u9fff]')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sections(text):
    matches = list(re.finditer(r'^(' + '|'.join(SECTIONS) + r'):[ \t]*', text, re.M))
    if [m[1] for m in matches] != list(SECTIONS) or text[:matches[0].start()].strip():
        return None
    return {m[1]: text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
            for i, m in enumerate(matches)}


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
            signature = digest(json.dumps({'common': common, 'group': group}, ensure_ascii=False, sort_keys=True))
            yield str(node_id), index, prompt, signature


def text_findings(prompt, chinese=None, names=None):
    errors = []
    def issue(code, detail):
        errors.append({'code': code, 'detail': detail})
    english = sections(prompt)
    if english is None:
        issue('sections', '英文必须包含完整且有序的Ref2VA六节')
        return errors
    definitions = {}
    for match in SUBJECT.finditer(english['subject_definitions']):
        tail = english['subject_definitions'][match.end():]
        name = re.match(r'\s*([\u3400-\u9fff][\u3400-\u9fffA-Za-z0-9·]*)', tail)
        if name:
            definitions[match[1]] = name[1]
        else:
            issue('subject_name', f'{match[0]}定义后必须紧接准确中文名称，不能用拼音或译名')
    if names is not None and definitions != names:
        issue('subject_mapping', '正文Subject中文名称与核对记录的主体表不一致')
    for section, body in english.items():
        for match in SUBJECT.finditer(body):
            name = definitions.get(match[1])
            if name is None or not body[match.end():].lstrip().startswith(name):
                issue('subject_reference', f'{section}中{match[0]}缺少对应中文全名')
    # Only unequivocal named-role substitutions; ordinary pronouns and quoted dialogue
    # are left to the semantic review, not rejected by a broad natural-language regex.
    action = re.sub(r'<d>.*?</d>|“[^”]*”|"[^"\n]*"', '', english['detailed_description'], flags=re.S)
    role = re.search(r'\b(?:the\s+(?:(?:young|middle-aged|apron-wearing|bearded|male|female)\s+)*(?:man|woman|boy|girl|villager)|his\s+(?:wife|mother)|her\s+(?:husband|son))\b', action, re.I)
    if role:
        issue('role_alias', '动作中以角色代称替换主体：' + role[0])
    subtitle_rules = [s for s in re.split(r'(?<=[.!?])\s+|\n', prompt)
                      if re.search(r'\b(?:no|without|never|prohibit\w*|forbid\w*)\b[^.\n]{0,200}\bsubtitles?\b', s, re.I)]
    full_span = r'\b(?:(?:throughout|entire|whole|full)[^.\n]{0,40}(?:video|clip|sequence)|all frames|first frame[^.\n]{0,40}last frame|start to (?:the )?end)\b'
    if not any(re.search(full_span, s, re.I) for s in subtitle_rules):
        issue('subtitle_rule', '缺少覆盖全片的无字幕指令（语义完整性仍需内容核对）')
    if chinese is not None:
        translated = sections(chinese)
        if translated is None:
            issue('translation_sections', '中文参考版必须保留完整有序的六节英文标题')
        else:
            for section in SECTIONS:
                if Counter(TAG.findall(english[section])) != Counter(TAG.findall(translated[section])):
                    issue('translation_tags', section + '中英文标签或镜号不对应，不得用摘要替代')
                if Counter(re.findall(r'\b\d+(?:\.\d+)?\b', english[section])) != Counter(re.findall(r'\d+(?:\.\d+)?', translated[section])):
                    issue('translation_numbers', section + '中英文数字不对应')
                if not translated[section]:
                    issue('translation_empty', section + '中文正文为空')
                for match in SUBJECT.finditer(translated[section]):
                    name = definitions.get(match[1])
                    if name and not translated[section][match.end():].lstrip().startswith(name):
                        issue('translation_name', section + '中文Subject后缺少准确名称')
    return errors


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
    expected_keys = []
    for node, index, prompt, signature in selected_groups(workflow):
        key = (node, index)
        expected_keys.append(key)
        matching = [r for r in rows if (r.get('node'), r.get('index')) == key]
        errors, chinese = [], None
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
            chinese = chinese_text(path.read_text('utf-8-sig'))
            if chinese_info.get('sha256') != digest(chinese):
                issue('translation_stale', '中文核对记录与当前中文正文不一致')
        except (KeyError, OSError, ValueError, TypeError) as exc:
            issue('translation_missing', '缺少可读取的中文参考版：' + str(exc))
        names = row.get('subjects')
        if not isinstance(names, dict) or not names or any(not isinstance(n, str) or not HAN.search(n) for n in names.values()):
            issue('review_subjects', '缺少Subject编号到准确中文名称的主体表')
            names = None
        errors.extend(text_findings(prompt, chinese, names))
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
                    text = path.read_text('utf-8-sig')
                    if source.get('sha256') != digest(text):
                        issue('review_source_stale', category + '的依据已变化：' + source['file'])
                    quote = source.get('quote', '')
                    if not isinstance(quote, str) or not quote.strip() or quote not in text:
                        issue('review_evidence', category + '的依据原文不存在：' + source['file'])
                except (KeyError, OSError, ValueError) as exc:
                    issue('review_evidence', category + '依据不可读取：' + str(exc))
        results.append({'node': node, 'index': index, 'input_sha256': signature,
                        'chinese_sha256': digest(chinese) if chinese is not None else None,
                        'ok': not errors, 'issues': errors})
    if sorted((r.get('node', ''), r.get('index', -1)) for r in rows) != sorted(expected_keys):
        failures.append({'code': 'review_scope', 'detail': '核对记录必须准确覆盖本次选中原组，不含重复或未选中组'})
    return {'version': 1, 'ok': bool(results) and not failures and all(r['ok'] for r in results),
            'issues': failures, 'groups': results, 'sources': sorted(files),
            'scope': '确定性文本检查及内容核对证据绑定；不证明语义判断或生成质量正确'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='Project root; all evidence must stay within this directory')
    parser.add_argument('--workflow', required=True, help='Local API JSON; read only, no service connection')
    parser.add_argument('--mapping', required=True, help='Existing 输入映射.json with content_review; read only')
    parser.add_argument('--output', help='Optional NEW local JSON report; refuses to overwrite an existing file')
    parser.add_argument('--basis-file', action='append', default=[], help='Project-relative UTF-8 source to fingerprint for review evidence; repeatable, read only')
    args = parser.parse_args()
    try:
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
