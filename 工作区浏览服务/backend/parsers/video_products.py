"""Read explicit deliverables for one postprocessing revision."""
import json
import sys
from pathlib import Path
from urllib.parse import quote


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / '.agents/skills/nora-ai-short-drama/scripts'))
from postprocess_products import product_rows

def load_products(project, identity, read):
    episode = identity.split('-C', 1)[0]
    manifest = f'09-剧集制作/{episode}/其他资料/执行附件/{identity}/后处理产物.json'
    text = read(manifest, preview=False)
    if text is None:
        return []
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f'{manifest}：根节点必须是JSON对象')
    rows = product_rows(data)
    products = []

    def media(key):
        if not isinstance(key, str) or not key or Path(key).is_absolute():
            raise ValueError(f'{manifest}：文件路径必须相对于项目根目录')
        key = key.replace('\\', '/')
        path = (project / key).resolve()
        if not path.is_relative_to(project.resolve()) or not path.is_file():
            raise ValueError(f'{manifest}：产物文件不存在或越出项目：{key}')
        stat = path.stat()
        revision = f'{stat.st_mtime_ns}-{stat.st_size}'
        key = path.relative_to(project.resolve()).as_posix()
        return {'key': key, 'url': quote(key, safe='/-._~') + '?v=' + revision, 'fileRevision': revision}

    for row in rows:
        product = {**media(row['file']), **{key: row[key] for key in ('id', 'label', 'default')}}
        if row.get('preview'):
            if not isinstance(row.get('previewNote'), str) or not row['previewNote'].strip():
                raise ValueError(f'{manifest}：使用预览代理须填写 previewNote')
            preview = media(row['preview'])
            product.update(previewUrl=preview['url'], previewRevision=preview['fileRevision'], previewNote=row['previewNote'])
        products.append(product)
    return products


def default_product(video):
    return next((product for product in video.get('products', []) if product['default']), video)
