"""One revision owns all its deliverables; default only selects presentation."""
from copy import deepcopy


def product_rows(data):
    rows = deepcopy(data.get('products'))
    if not isinstance(rows, list) or not rows:
        raise ValueError('products 必须是非空数组')
    legacy = all('default' not in row for row in rows if isinstance(row, dict))
    ids, files = set(), set()
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip()
                                           for k in ('id', 'label', 'file')):
            raise ValueError('每项须填写 id、label、file')
        if row['id'] in ids or row['file'] in files:
            raise ValueError('id 和 file 不得重复')
        ids.add(row['id']); files.add(row['file'])
        if legacy:
            if row.get('role') not in ('最终产物', '过程产物'):
                raise ValueError('旧清单角色无效')
            row['default'] = row['role'] == '最终产物'
        if not isinstance(row.get('default', False), bool):
            raise ValueError('default 必须是布尔值')
        row.setdefault('default', False)
        row.pop('role', None)
        if row.get('preview') and not str(row.get('previewNote', '')).strip():
            raise ValueError('使用播放关联须填写 previewNote')
    if sum(row['default'] for row in rows) != 1:
        raise ValueError('须且只能指定一项默认展示产物')
    # Older manifests kept browser-playable media only in a pointer. They are
    # ordinary deliverables too, included in adoption and archive exports.
    for row in list(rows):
        if row.get('preview') and row['preview'] not in files:
            if not legacy:
                raise ValueError('preview 必须指向本轮 products 中已列出的文件')
            identifier = row['id'] + '-preview'
            if identifier in ids:
                raise ValueError('兼容产物 id 不得重复')
            rows.append({'id': identifier, 'label': row['label'] + '（网页播放）',
                         'file': row['preview'], 'default': False})
            ids.add(identifier); files.add(row['preview'])
    return rows
