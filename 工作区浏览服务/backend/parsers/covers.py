"""Read project cover index and image records without inferring approval from files."""
from math import gcd
import re
import struct
from urllib.parse import unquote, urlsplit



DIRECTORY = '10-封面资料'
INDEX = DIRECTORY + '/封面索引.md'
RECORD = DIRECTORY + '/其他资料/工作稿/封面制作-工作稿.md'


def build_covers(project, read):
    from backend.parsers.project import field, markdown_links, status_markup, table_records

    def image(link):
        path = (project / link['key']).resolve()
        if not path.is_relative_to(project):
            raise ValueError('封面路径越出项目：' + link['key'])
        if not path.is_file():
            return None
        with path.open('rb') as stream:
            header = stream.read(24)
        if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('封面不是完整的PNG图片：' + link['key'])
        width, height = struct.unpack('>II', header[16:24])
        divisor = gcd(width, height)
        return dict(link, width=width, height=height, ratio=f'{width // divisor}:{height // divisor}')

    def linked(text, source):
        links = markdown_links(text, source)
        return links[0] if links else None

    index = read(INDEX) or ''
    record = read(RECORD) or ''
    items = []
    for row in table_records(index, ('封面名称', '成品文件', '采用原图', '审阅记录')):
        media_link = linked(row['成品文件'], INDEX)
        original_link = linked(row['采用原图'], INDEX)
        review = linked(row['审阅记录'], INDEX)
        approved = False
        if review and original_link:
            body = read(review['key']) or ''
            heading = unquote(urlsplit(review['url']).fragment)
            match = re.search(r'^### ' + re.escape(heading) + r'\s*\n(.*?)(?=^#{1,3} |\Z)', body, re.M | re.S)
            if match:
                confirmation = re.search(r'^#### 4\. 用户确认\s*\n(.*?)(?=^#### |\Z)', match[1], re.M | re.S)
                if confirmation:
                    candidates = markdown_links(field(confirmation[1], '对应具体候选'), review['key'])
                    approved = field(confirmation[1], '决定') == '批准采用' and any(
                        item['key'] == original_link['key'] for item in candidates)
        media = image(media_link) if media_link else None
        original = image(original_link) if original_link else None
        target = re.fullmatch(r'(\d+)[×xX](\d+)', row['目标尺寸'])
        if not target:
            raise ValueError('封面索引目标尺寸须填写宽×高：' + row['封面名称'])
        ratio = re.fullmatch(r'(\d+):(\d+)', row['目标比例'])
        if not ratio or int(ratio[1]) <= 0 or int(ratio[2]) <= 0:
            raise ValueError('封面索引目标比例须填写正整数宽:高：' + row['封面名称'])
        ready = bool(approved and media and (media['width'], media['height']) == (int(target[1]), int(target[2]))
                     and media['width'] * int(ratio[2]) == media['height'] * int(ratio[1]))
        status = '已采用' if ready else ('待规格处理' if approved else '未确认')
        items.append(dict(coverId=row.get('封面编号', ''), name=row['封面名称'], scope=row['适用范围'], layout=row['版式'],
                          sourceKey=original_link['key'] if original_link else '',
                          setName=row.get('套组名称', ''),
                          platforms=[name.strip() for name in row.get('适用平台', '').split('、') if name.strip()],
                          targetRatio=row['目标比例'], targetSize=row['目标尺寸'], version=row['采用版本'],
                          targetFormat=row.get('目标格式', ''), specBasis=row.get('规格依据', ''),
                          media=media, original=original, review=review,
                          processing=linked(row['处理记录'], INDEX), approved=approved, ready=ready,
                          status=status, statusHtml=status_markup(status, INDEX)))
    adopted_sources = {item['original']['key'] for item in items if item['ready'] and item['original']}
    assets = {}
    for item in items:
        identity = item['coverId'] or 'legacy:' + item['name']
        if identity in assets:
            raise ValueError('封面编号重复：' + identity)
        assets[identity] = dict(id=identity, name=item['layout'] + '封面', scope=item['scope'],
                               platforms=item['platforms'], current=item, rounds=[])
    historical = {}
    for row in table_records(index, ('生成记录', '封面编号', '修订轮次')):
        generation = row['生成记录']
        if generation in historical:
            raise ValueError('封面历史归属重复：' + generation)
        historical[generation] = row
    candidates, unassigned = [], []
    rounds = {}
    for match in re.finditer(r'^### (生成记录-\d+)\s*\n(.*?)(?=^#{1,3} |\Z)', record, re.M | re.S):
        generation, body = match[1], match[2]
        association = historical.get(generation, {})
        cover_id = field(body, '封面编号')
        round_id = field(body, '修订轮次')
        label = field(body, '轮次名称')
        cover_id = association.get('封面编号', '') if cover_id in ('未记录', '不适用', '') else cover_id
        round_id = association.get('修订轮次', '') if round_id in ('未记录', '不适用', '') else round_id
        label = association.get('轮次名称', round_id) if label in ('未记录', '不适用', '') else label
        record_link = dict(name=generation, key=RECORD, url=RECORD + '#' + generation)
        links = markdown_links(field(body, '候选文件入口') if '候选文件入口：' in body else field(body, '输出候选文件'), RECORD)
        # The index already explicitly links an adopted source; unrelated loose files are never inferred.
        if not cover_id:
            owners = [asset for asset in assets.values() if any(link['key'] == asset['current']['sourceKey'] for link in links)]
            if len(owners) == 1:
                cover_id, round_id, label = owners[0]['id'], generation, '原采用记录'
        if cover_id and cover_id not in assets:
            raise ValueError('生成记录引用了未登记的封面编号：' + cover_id)
        if cover_id and not round_id:
            raise ValueError('封面生成记录缺少修订轮次：' + generation)
        entry = None
        if cover_id:
            key = (cover_id, round_id)
            if key not in rounds:
                entry = dict(id=round_id, name=label or round_id, order=0, candidates=[], records=[], current=False)
                rounds[key] = entry
                assets[cover_id]['rounds'].append(entry)
            entry = rounds[key]
            entry['order'] = max(entry['order'], int(generation.rsplit('-', 1)[1]))
            entry['records'].append(dict(**record_link, state=field(body, '真实执行状态')))
        if field(body, '真实执行状态').startswith('failed'):
            continue
        processing = linked(field(body, '超分输出文件及实际规格'), RECORD)
        if association.get('历史成品'):
            processing = linked(association['历史成品'], INDEX) or processing
        formal = image(processing) if processing else None
        review = linked(field(body, '审阅记录入口'), RECORD)
        for link in links:
            if not link['key'].startswith(DIRECTORY + '/') or not link['key'].lower().endswith('.png'):
                continue
            media = image(link)
            if not media:
                continue
            decision = field(body, '用户决定及具体候选、批准依据').split('；')[0]
            platform = field(body, '适用平台')
            candidate = dict(name=link['name'], media=media, generation=generation, status=decision,
                             setName=field(body, '套组名称'), coverId=cover_id, roundId=round_id,
                             platforms=[] if platform == '未记录' else [name.strip() for name in platform.split('、') if name.strip()],
                             record=record_link, review=review, formal=formal)
            if link['key'] not in adopted_sources:
                candidates.append(candidate)
            if entry is None:
                unassigned.append(candidate)
            else:
                current = assets[cover_id]['current']
                is_current = current['ready'] and current['sourceKey'] == link['key']
                candidate = dict(candidate, current=is_current)
                if is_current:
                    candidate.update(formal=current['media'], review=current['review'], processing=current['processing'])
                    entry['current'] = True
                entry['candidates'].append(candidate)
    for asset in assets.values():
        asset['rounds'].sort(key=lambda entry: entry['order'], reverse=True)
        all_candidates = [candidate for entry in asset['rounds'] for candidate in entry['candidates']]
        all_candidates.sort(key=lambda candidate: int(candidate['generation'].rsplit('-', 1)[1]), reverse=True)
        current = next((candidate for candidate in all_candidates if candidate['current']), None)
        latest = all_candidates[0] if all_candidates else None
        asset['latest'] = latest
        asset['hasUpdate'] = bool(asset['current']['ready'] and latest and not latest['current']
            and (current is None or int(latest['generation'].rsplit('-', 1)[1]) > int(current['generation'].rsplit('-', 1)[1]))
            and latest['status'] not in ('已结束未采用', '不采用', '已被替换／归档'))
    candidates.sort(key=lambda item: int(item['generation'].rsplit('-', 1)[1]), reverse=True)
    unassigned.sort(key=lambda item: int(item['generation'].rsplit('-', 1)[1]), reverse=True)
    return dict(kind='covers', key=DIRECTORY, name='封面资料', items=items, candidates=candidates,
                assets=list(assets.values()), unassigned=unassigned,
                index=dict(kind='document', name='封面索引', key=INDEX, url=INDEX) if index else None,
                record=dict(kind='document', name='制作记录', key=RECORD, url=RECORD) if record else None)


def cover_fields(fields, read):
    """Require a declared cover and revision for new generation; legacy execution recovery stays unchanged."""
    from backend.parsers.project import table_records
    identity, revision = fields.get('封面编号', ''), fields.get('修订轮次', '')
    if not re.fullmatch(r'COV[0-9]{3,}', identity) or not re.fullmatch(r'R[0-9]{3,}', revision):
        raise ValueError('新封面生成须填写固定封面编号COV001及修订轮次R001，先在封面索引登记对象')
    rows = [row for row in table_records(read(INDEX) or '', ('封面编号', '版式', '适用平台')) if row['封面编号'] == identity]
    if len(rows) != 1:
        raise ValueError('封面编号未登记或重复：' + identity)
    row = rows[0]
    for key in ('套组名称', '版式', '适用平台'):
        if fields.get(key) and fields[key] != row[key]:
            raise ValueError('封面编号的' + key + '与索引不一致：' + identity)
    return {**fields, **{key: row[key] for key in ('套组名称', '版式', '适用平台')}}
