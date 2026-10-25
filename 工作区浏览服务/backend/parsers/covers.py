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
        items.append(dict(name=row['封面名称'], scope=row['适用范围'], layout=row['版式'],
                          setName=row.get('套组名称', ''),
                          platforms=[name.strip() for name in row.get('适用平台', '').split('、') if name.strip()],
                          targetRatio=row['目标比例'], targetSize=row['目标尺寸'], version=row['采用版本'],
                          targetFormat=row.get('目标格式', ''), specBasis=row.get('规格依据', ''),
                          media=media, original=original, review=review,
                          processing=linked(row['处理记录'], INDEX), approved=approved, ready=ready,
                          status=status, statusHtml=status_markup(status, INDEX)))
    candidates = []
    for match in re.finditer(r'^### (生成记录-\d+)\s*\n(.*?)(?=^#{1,3} |\Z)', record, re.M | re.S):
        body = match[2]
        if field(body, '真实执行状态').startswith('failed'):
            continue
        for link in markdown_links(field(body, '候选文件入口') if '候选文件入口：' in body else field(body, '输出候选文件'), RECORD):
            if not link['key'].startswith(DIRECTORY + '/') or not link['key'].lower().endswith('.png'):
                continue
            media = image(link)
            if media:
                decision = field(body, '用户决定及具体候选、批准依据').split('；')[0]
                candidates.append(dict(name=link['name'], media=media, generation=match[1], status=decision,
                                       record=dict(name='制作记录', key=RECORD, url=RECORD + '#' + match[1])))
    return dict(kind='covers', key=DIRECTORY, name='封面资料', items=items, candidates=candidates,
                index=dict(kind='document', name='封面索引', key=INDEX, url=INDEX) if index else None,
                record=dict(kind='document', name='制作记录', key=RECORD, url=RECORD) if record else None)
