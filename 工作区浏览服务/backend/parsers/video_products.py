"""Read explicit deliverables for one postprocessing revision."""
import json
from pathlib import Path
from urllib.parse import quote


def load_products(project, identity, read):
    episode = identity.split('-C', 1)[0]
    manifest = f'09-剧集制作/{episode}/其他资料/执行附件/{identity}/后处理产物.json'
    text = read(manifest, preview=False)
    if text is None:
        return []
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f'{manifest}：根节点必须是JSON对象')
    rows = data.get('products')
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'{manifest}：products 必须是非空数组')
    products, ids, files = [], set(), set()

    def media(key):
        if not isinstance(key, str) or not key or Path(key).is_absolute():
            raise ValueError(f'{manifest}：文件路径必须相对于项目根目录')
        path = (project / key).resolve()
        if not path.is_relative_to(project.resolve()) or not path.is_file():
            raise ValueError(f'{manifest}：产物文件不存在或越出项目：{key}')
        stat = path.stat()
        revision = f'{stat.st_mtime_ns}-{stat.st_size}'
        return {'key': key, 'url': quote(key, safe='/-._~') + '?v=' + revision, 'fileRevision': revision}

    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                            for key in ('id', 'label', 'role', 'file')):
            raise ValueError(f'{manifest}：每项须填写 id、label、role、file')
        if row['role'] not in ('最终产物', '过程产物') or row['id'] in ids or row['file'] in files:
            raise ValueError(f'{manifest}：角色须为最终产物／过程产物，id 和 file 不得重复')
        ids.add(row['id']); files.add(row['file'])
        product = {**media(row['file']), **{key: row[key] for key in ('id', 'label', 'role')}}
        if row.get('preview'):
            if not isinstance(row.get('previewNote'), str) or not row['previewNote'].strip():
                raise ValueError(f'{manifest}：使用预览代理须填写 previewNote')
            preview = media(row['preview'])
            product.update(previewUrl=preview['url'], previewRevision=preview['fileRevision'], previewNote=row['previewNote'])
        products.append(product)
    if sum(product['role'] == '最终产物' for product in products) != 1:
        raise ValueError(f'{manifest}：须且只能指定一项最终产物')
    return products


def final_product(video):
    return next((product for product in video.get('products', []) if product['role'] == '最终产物'), video)
