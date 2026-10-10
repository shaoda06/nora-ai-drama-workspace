#!/usr/bin/env python3
"""Apply an explicit human video approval to files and existing project records, offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'references' / 'comfyui-scripts'))
import comfyui_client as client

IDENTITY = re.compile(r'(EP\d{3})-(C\d{3})-(P\d{3})-(R\d{3})-(一采|二采|后处理)')
STAGES = {'一采': '01-一采', '二采': '02-二采', '后处理': '03-后处理'}


def local_path(root, value):
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'路径越出项目：{path}')
    return path


def link(base, path):
    return os.path.relpath(path, base.parent).replace('\\', '/').replace(' ', '%20')


def load(path):
    return client.strict_json(path.read_bytes())


def check_file(path, receipt):
    if not path.is_file() or path.stat().st_size != receipt['bytes']:
        raise ValueError(f'文件缺失或长度不符合取回凭据：{path}')
    # Reuse the download's existing digest; do not create a new approval hash scheme.
    with path.open('rb') as video:
        digest = hashlib.file_digest(video, 'sha256').hexdigest()
    if digest != receipt['sha256']:
        raise ValueError(f'文件字节与取回凭据不符，不能继承批准：{path}')


def section(text, heading):
    matches = list(re.finditer(r'^### ' + re.escape(heading) + r'\s*$', text, re.M))
    if len(matches) != 1:
        raise ValueError(f'执行章节必须唯一：{heading}')
    start = matches[0].end()
    end = re.search(r'^#{1,3} ', text[start:], re.M)
    return start, start + end.start() if end else len(text)


def field(text, name, value):
    pattern = r'^- ' + re.escape(name) + r'：[^\n]*'
    matches = list(re.finditer(pattern, text, re.M))
    if len(matches) > 1:
        raise ValueError(f'字段重复：{name}')
    replacement = f'- {name}：{value}'
    if matches:
        return re.sub(pattern, lambda _: replacement, text, count=1, flags=re.M)
    return text.rstrip() + '\n' + replacement + '\n\n'


def selected_row(text, stage):
    area = re.search(r'^## 1\. 当前选定结果\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not area:
        raise ValueError('缺少模板的“## 1. 当前选定结果”')
    rows = list(re.finditer(r'^\| ' + re.escape(stage) + r' \|[^\n]*', area[1], re.M))
    if len(rows) != 1:
        raise ValueError(f'当前选定表的{stage}行必须唯一')
    row = rows[0]
    return area.start(1) + row.start(), area.start(1) + row.end(), row[0]


def approved_row(text, row, filename):
    if filename not in row:
        return False
    anchors = re.findall(r'\]\(#([^)]*)\)', row)
    if len(anchors) != 1:
        return False
    headings = re.findall(r'^### (.+)$', text, re.M)
    matching = [h for h in headings if h.startswith('审阅-') and h.lower() == anchors[0].lower()]
    if len(matching) != 1:
        return False
    start, end = section(text, matching[0])
    body = text[start:end]
    outputs = '\n'.join(re.findall(r'^- (?:对应具体输出|被审具体输出文件及R编号／版本|具体输出|被审具体输出|采用文件)：([^\n]*)', body, re.M))
    return bool(re.search(r'^- 决定：(?:批准采用(?:\s|[；。，]|$)|通过并采用(?:\s|[；。，]|本轮|P\d|$))', body, re.M)
                and filename in outputs)


def adoption(args):
    root = Path(args.project).resolve(strict=True)
    plan_path = Path(args.plan)
    plan = load(plan_path if plan_path.is_absolute() else root / plan_path)
    if not isinstance(plan, dict):
        raise ValueError('采用计划必须是 JSON 对象')
    if not isinstance(plan.get('approval_text'), str) or not plan['approval_text'].strip():
        raise ValueError('必须提供用户实际批准原话 approval_text')
    if 'approval_time' in plan and datetime.fromisoformat(plan['approval_time']).utcoffset() is None:
        raise ValueError('approval_time 必须包含时区偏移')
    items = plan['items']
    if not isinstance(items, list) or not items or any(not isinstance(item, dict) for item in items):
        raise ValueError('items 必须是非空对象数组')
    identities = [item['identity'] for item in items]
    if len(identities) != len(set(identities)):
        raise ValueError('批准对象重复')
    stamp = client.now()
    basis = plan['approval_text'].strip().replace('\n', '<br>')
    texts, original, maps, moves, results, episodes = {}, {}, {}, [], [], set()

    def read_text(path):
        if path not in texts:
            texts[path] = path.read_text(encoding='utf-8-sig')
            original[path] = texts[path]
        return texts[path]

    def sync_related(item, mapping, prompt, record):
        for related_value in item.get('related_mappings', []):
            related_path = local_path(root, related_value)
            related = maps.setdefault(related_path, load(related_path))
            current = related.get('current_execution', {})
            current_mapping = current.get('mapping')
            if not current_mapping or local_path(root, current_mapping) != mapping or current.get('prompt_id') != prompt:
                raise ValueError('父映射 current_execution 未指向本次实际执行，不能代填')
            for container in (related, current):
                container['adoptions'] = [a for a in container.get('adoptions', []) if a.get('identity') != record['identity']] + [record]
            if len(items) == 1:
                current['adoption'] = record
            related['adoption_updated_at'] = record['recorded_at']

    for item in items:
        identity = item['identity']
        match = IDENTITY.fullmatch(identity)
        if not match:
            raise ValueError(f'无效视频身份：{identity}')
        ep, scene, part, revision, stage = match.groups()
        episodes.add(ep)
        extra = root / '09-剧集制作' / ep / '其他资料'
        draft = local_path(root, extra / '工作稿' / f'{ep}-{scene}-{part}-视频制作-工作稿.md')
        mapping = local_path(root, item['mapping'])
        mapped = maps.setdefault(mapping, load(mapping))
        contexts = mapped.get('generation_contexts', [])
        if identity not in [context['identity'] for context in contexts]:
            raise ValueError(f'输入映射未关联本次批准对象：{identity}')
        prompt = mapped.get('prompt_id')
        if not prompt:
            raise ValueError(f'请指定实际执行的输入映射，不用父级旧请求代替：{mapping}')
        receipt_path = local_path(root, item['receipt'])
        receipt_document = load(receipt_path)
        receipt = receipt_document.get('data', receipt_document)
        if not isinstance(receipt.get('bytes'), int) or not re.fullmatch(r'[0-9a-f]{64}', receipt.get('sha256', '')):
            raise ValueError(f'缺少固定下载工具的完整字节凭据：{receipt_path}')
        # The agent specifies the actual receipt; mapping and receipt must belong to this execution.
        if not receipt_path.is_relative_to(mapping.parent):
            if str(receipt_path) not in json.dumps(mapped, ensure_ascii=False):
                raise ValueError('共同任务外的取回凭据须已在输入映射中明确关联')
        outputs = mapped.get('outputs', []) + mapped.get('runtime_retrieved', [])
        matching_outputs = [output for output in outputs if output.get('identity') == identity]
        if not matching_outputs and len(contexts) == 1 and mapped.get('output'):
            matching_outputs = [mapped['output']]
        if len(matching_outputs) != 1:
            raise ValueError('输入映射须明确关联本段已取回的唯一输出，不凭同目录猜归属')
        output = matching_outputs[0]
        if output.get('remote') and output['remote'] != receipt.get('remote'):
            raise ValueError('取回凭据的远端文件不符合映射中的本段输出')
        if output.get('bytes') is not None and output['bytes'] != receipt['bytes']:
            raise ValueError('取回凭据长度不符合本段输出记录')
        filename = identity + '.mp4'
        source = local_path(root, item.get('source', extra / '候选视频' / filename))
        if source.name != filename:
            raise ValueError('采用源文件须已按具体 EP/C/P/R/阶段命名')
        target = local_path(root, extra / '阶段采用视频' / STAGES[stage] / f'{scene}-场次' / filename)
        data = read_text(draft)
        start, end, row = selected_row(data, stage)
        if target.exists():
            check_file(target, receipt)
            if source != target and source.exists():
                raise ValueError('候选和采用目录同时存在本次文件，请先核对来源')
        else:
            check_file(source, receipt)
            moves.append((source, target))
        already = approved_row(data, row, filename) and link(draft, target) in row
        adoptions = mapped.get('adoptions', [])
        existing = [a for a in adoptions if a.get('identity') == identity and a.get('selected_path')
                    and local_path(root, a['selected_path']) == target]
        if already and existing:
            sync_related(item, mapping, prompt, existing[0])
            results.append({'identity': identity, 'state': 'already_adopted', 'selected_path': str(target)})
            continue
        old_links = re.findall(r'\]\(([^)#]+\.mp4)\)', row)
        if old_links:
            old = local_path(root, draft.parent / old_links[0].replace('%20', ' '))
            if old != target:
                # Changing an upstream selection must not silently invalidate approved downstream video.
                later = list(STAGES)[list(STAGES).index(stage) + 1:]
                for later_stage in later:
                    _, _, downstream = selected_row(data, later_stage)
                    if '.mp4)' in downstream:
                        raise ValueError(f'{identity}更换采用会影响已选定{later_stage}，须先明确下游处置')
                previous = local_path(root, extra / '候选视频' / old.name)
                if not old.is_file() or previous.exists():
                    raise ValueError(f'旧采用文件缺失或退回候选时冲突：{old}')
                moves.append((old, previous))
                data = data.replace(link(draft, old), link(draft, previous))
        heading = item.get('execution_heading', revision + '-' + stage)
        a, b = section(data, heading)
        body = data[a:b]
        if not heading.startswith(revision) or not re.search(r'^- 处理阶段：' + re.escape(stage) + r'(?:\s|[；。，]|$)', body, re.M):
            raise ValueError('执行章节的 R 和处理阶段不符合批准对象')
        review_base = f'审阅-{revision}-{stage}-采用-'
        numbers = re.findall(r'^### ' + re.escape(review_base) + r'(\d+)\s*$', data, re.M)
        review = review_base + f'{max(map(int, numbers), default=0) + 1:03d}'
        reference = f'[本阶段人工审核决定](#{review.lower()})'
        body = field(body, '人工审阅记录入口', reference)
        body = field(body, '用户决定', '见' + reference + '。')
        body = field(body, '输出当前入口及取回／展示情况', f'[已采用文件]({link(draft, target)})；文件身份按[取回凭据]({link(draft, receipt_path)})核对。')
        body = field(body, '用户采用的具体输出、批准范围、时间与依据', '见' + reference + '。')
        body += (f'\n#### 位置变化及替代关系（{stamp}）\n\n'
                 '| 原位置 | 新位置 | 时间 | 用户决定／移动依据 | 替代关系及需同步的下游入口 |\n'
                 '| --- | --- | --- | --- | --- |\n')
        for old, new in moves:
            if old.name.endswith(f'-{stage}.mp4') and (old == source or old_links and old.name in row):
                body += f'| {link(draft, old)} | [文件]({link(draft, new)}) | {stamp} | {reference} | 原批准历史保留；当前关联见选定表 |\n'
        data = data[:a] + body + '\n' + data[b:]
        start, end, _ = selected_row(data, stage)
        new_row = f'| {stage} | [当前采用文件]({link(draft, target)}) | {revision} | {prompt} | {reference} |'
        data = data[:start] + new_row + data[end:]
        data = data.replace(link(draft, source), link(draft, target))
        # Insert into the existing review area without adding a parallel approval ledger.
        review_text = (f'\n### {review}\n\n#### 1. 审阅对象\n\n'
                       f'- 所属分段／场次／整集：{ep}-{scene}-{part}\n- 处理阶段或成片类型：{stage}\n'
                       f'- 被审具体输出文件及R编号／版本：[{filename}]({link(draft, target)})；{revision}\n'
                       f'- 来源任务、执行记录或成片说明入口：[{identity}]({link(draft, mapping)})；prompt {prompt}\n'
                       f'- agent取回及展示入口：[取回凭据]({link(draft, receipt_path)})\n\n'
                       '#### 2. 用户反馈\n\n'
                       f'- 用户原话：{basis}\n\n#### 3. 人工审核决定\n\n'
                       f'- 决定：批准采用\n- 对应具体输出：[{filename}]({link(draft, target)})\n'
                       f'- 批准或要求修改的范围：本次明确指定的 {identity} 视频文件\n'
                       f'- 决定时间与依据：{plan.get("approval_time", stamp)}；用户原话：{basis}\n'
                       f'- 记录更新时间：{stamp}\n\n#### 4. 采用与后续处理\n\n'
                       f'- 当前候选／选定入口：[当前采用文件]({link(draft, target)})\n'
                       f'- 移动或替代关系及对应记录入口：[执行章节](#{heading.lower()})\n'
                       '- 用户要求的后续处理及授权范围：本工具只落实上述采用；后续执行沿用已有明确授权。\n')
        area = re.search(r'^## \d+\. 审阅区\s*$', data, re.M)
        if not area:
            raise ValueError('工作稿缺少审阅区，请先按现有模板规范化')
        next_area = re.search(r'^## ', data[area.end():], re.M)
        position = area.end() + next_area.start() if next_area else len(data)
        data = data[:position].rstrip() + '\n' + review_text + '\n' + data[position:]
        data = re.sub(r'^- 最近更新：[^\n]*', lambda _: '- 最近更新：' + stamp, data, count=1, flags=re.M)
        data = re.sub(r'^- 当前状态及待办：[^\n]*', lambda _: f'- 当前状态及待办：{revision}{stage}已批准采用；其他阶段及下游状态见选定表和执行记录。', data, count=1, flags=re.M)
        texts[draft] = data
        record = {'identity': identity, 'recorded_at': stamp, 'source_path': str(source),
                  'selected_path': str(target), 'basis': plan['approval_text'],
                  'segment_review': draft.name + '#' + review.lower(), 'prompt_id': prompt,
                  'bytes': receipt['bytes'], 'receipt': str(receipt_path)}
        mapped['adoptions'] = [a for a in adoptions if a.get('identity') != identity] + [record]
        mapped['adoption_updated_at'] = stamp
        sync_related(item, mapping, prompt, record)
        results.append({'identity': identity, 'state': 'adopt', 'selected_path': str(target), 'review': review})

    changed = any(item['state'] == 'adopt' for item in results)
    record_updates = plan.get('record_updates', [])
    if not isinstance(record_updates, list) or any(not isinstance(update, dict) for update in record_updates):
        raise ValueError('record_updates 必须是对象数组')
    required = {root / '项目进度.md'} | {root / '09-剧集制作' / ep / '其他资料' / '工作稿' / f'{ep}-生成说明-工作稿.md' for ep in episodes}
    covered = set()
    for update in record_updates:
        path = local_path(root, update['path'])
        if path not in required:
            raise ValueError('record_updates 只允许本集生成说明和项目进度，不改其他文件')
        before, after = update['old'], update['new']
        if not before.strip() or not after.strip():
            raise ValueError('记录替换不能使用空字符串或删除记录')
        data = read_text(path)
        if data.count(before) == 1:
            texts[path] = data.replace(before, after, 1)
        elif data.count(before) != 0 or data.count(after) != 1:
            raise ValueError(f'记录原文已变化或匹配不唯一：{path}')
        covered.add(path)
    missing = sorted(str(p) for p in required - covered) if changed else []
    if args.apply and missing:
        raise ValueError('正式采用须提供生成说明和项目进度的定点更新（无变化可 old=new）：' + ', '.join(missing))
    destinations = [new for _, new in moves]
    if len(destinations) != len(set(destinations)):
        raise ValueError('移动目标重复')
    counts = {stage: 0 for stage in STAGES}
    for ep in episodes:
        for draft in (root / '09-剧集制作' / ep / '其他资料' / '工作稿').glob('*-视频制作-工作稿.md'):
            text = texts.get(draft, draft.read_text(encoding='utf-8-sig'))
            for stage in STAGES:
                _, _, row = selected_row(text, stage)
                name = re.search(r'(EP\d{3}-C\d{3}-P\d{3}-R\d{3}-' + stage + r'\.mp4)', row)
                if name and approved_row(text, row, name[0]):
                    counts[stage] += 1
    changed_maps = [str(path) for path, value in maps.items() if load(path) != value]
    if args.apply:
        # All input, identity, byte, record and conflict checks finish before any mutation.
        for old, new in moves:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
        for path, value in maps.items():
            serialized = client.encoded(value).decode('utf-8')
            if load(path) != value:
                texts[path] = serialized
                original[path] = path.read_text(encoding='utf-8-sig')
        for path, value in texts.items():
            if value != original[path]:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent,
                                                 delete=False, prefix='.' + path.name + '-', suffix='.tmp') as output:
                    output.write(value)
                    temporary = Path(output.name)
                try:
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
    return {'mode': 'apply' if args.apply else 'dry_run', 'items': results,
            'moves': [{'from': str(a), 'to': str(b)} for a, b in moves],
            'record_files': sorted(str(path) for path in texts if texts[path] != original[path]),
            'mapping_files': changed_maps,
            'selected_approved_counts': counts, 'required_record_updates': missing,
            'browser_sync': 'not_checked'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='短剧项目根目录；所有计划路径相对本目录解析，或用目录内绝对路径')
    parser.add_argument('--plan', required=True, help='采用计划 JSON（项目内）；列明身份、实际映射、取回凭据、用户原话和记录定点更新')
    parser.add_argument('--apply', action='store_true', help='执行移动和记录更新；省略时只读预览，不联网，不提交生成')
    args = parser.parse_args()
    try:
        result = adoption(args)
    except (ValueError, KeyError, OSError, client.ClientError) as error:
        print(json.dumps({'ok': False, 'error': str(error), 'note': '若为写入/移动 I/O 错误，核对已执行位置后沿用同计划收尾，不重新生成。'}, ensure_ascii=False))
        return 1
    print(json.dumps({'ok': True, 'data': result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
