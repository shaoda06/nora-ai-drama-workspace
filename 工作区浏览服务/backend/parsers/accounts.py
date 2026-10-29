"""Read adopted account visuals from their index and linked review records."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from PIL import Image


DIRECTORY = '10-社交媒体资料/个人页资料'
INDEX = DIRECTORY + '/账号视觉索引.md'


def build_accounts(project, read):
    from backend.parsers.project import field, markdown_links, status_markup, table_records

    index = read(INDEX) or ''
    items, issues = [], []
    for row in table_records(index, ('平台／账号代号', '用途', '正式文件', '采用版本', '采用依据', '处理记录')):
        name = row['平台／账号代号'] + ' · ' + row['用途']
        media_links = markdown_links(row['正式文件'], INDEX)
        if not media_links:
            continue
        media = media_links[0]
        formal_directory = {'头像': '头像', '背景图': '背景图', '主页背景图': '背景图'}.get(row['用途'])
        parts = Path(media['key']).parts
        if formal_directory is None or len(parts) != 4 or parts[:3] != (*Path(DIRECTORY).parts, formal_directory):
            issues.append(name + '：正式目录与用途不符，请核对索引。')
            continue
        path = (project / media['key']).resolve()
        if not path.is_relative_to(project):
            raise ValueError('账号图片路径越出项目：' + media['key'])
        reviews = markdown_links(row['采用依据'], INDEX)
        block = ''
        if reviews:
            review = reviews[0]
            body = read(review['key']) or ''
            heading = unquote(urlsplit(review['url']).fragment)
            match = re.search(r'^(#{1,6}) ' + re.escape(heading) + r'[ \t]*\n', body, re.M) if heading else None
            if match:
                block = re.split(r'^#{1,' + str(len(match[1])) + r'} ', body[match.end():], maxsplit=1, flags=re.M)[0]
        confirmation = next((field(block, key) for key in ('用户确认', '用户决定、采用范围与依据', '决定', '结论')
                             if field(block, key) != '未记录'), '')
        disposed = any(field(block, key).startswith(('已被', '已结束', '不采用', '修改后再审'))
                       for key in ('当前处置', '当前状态', '用户采用状态'))
        candidates = markdown_links(' '.join(field(block, key) for key in
                                    ('候选', '审阅的具体文件及候选版本', '对应具体候选')), reviews[0]['key']) if reviews else []
        version = re.search(r'v\d+(?:\.\d+)*', row['采用版本'])
        selected = bool(version and any(version[0] in re.findall(r'v\d+(?:\.\d+)*', Path(link['key']).name)
                                       for link in candidates))
        documented = bool(reviews and any(link['key'] == media['key'] for link in markdown_links(block, reviews[0]['key'])))
        approved = confirmation.startswith('批准采用') and selected and documented and not disposed
        if not approved:
            issues.append(name + '：采用记录或候选版本待核对。')
            continue
        if not path.is_file():
            issues.append(name + '：已登记的正式图片文件缺失。')
            continue
        with Image.open(path) as image:
            width, height = image.size
        items.append(dict(name=name, platform=row['平台／账号代号'], purpose=row['用途'],
                          version=row['采用版本'], media=dict(media, kind='image', name=name,
                          width=width, height=height), statusHtml=status_markup('已采用', INDEX)))
    return dict(kind='accounts', key=DIRECTORY, name='账号资料', items=items, issues=issues,
                index=dict(kind='document', name='账号视觉索引', key=INDEX, url=INDEX) if index else None)
