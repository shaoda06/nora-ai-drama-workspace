"""Bind episode image files to their existing generation and review records."""
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit


def material_review_states(files, record, source):
    from backend.parsers.project import field, markdown_links, status_markup, table_records

    record = re.sub(r'^```[^\n]*\n.*?^```[^\n]*$', '', record, flags=re.M | re.S)
    generations, dispositions, reviews, formal = {}, {}, {}, {}
    for match in re.finditer(r'^### (生成记录-\d+|审阅-生成记录-\d+-\d+)\s*\n(.*?)(?=^#{1,3} |\Z)', record, re.M | re.S):
        name, body = match[1], match[2]
        if name.startswith('生成记录-'):
            outputs = []
            for label in ('候选文件入口', '输出候选文件', '超分输出文件及实际规格', '超分成果与文件核对'):
                outputs.extend(markdown_links(field(body, label), source))
            generations[name] = {link['key'] for link in outputs}
            dispositions[name] = field(body, '用户决定及具体候选、批准依据').split('；', 1)[0]
        else:
            reviews[name] = body
    for row in table_records(record, ('正式文件', '审阅记录')):
        for link in markdown_links(row['审阅记录'], source):
            if link['key'] == source:
                for image in markdown_links(row['正式文件'], source):
                    formal[image['key']] = (unquote(urlsplit(link['url']).fragment), row.get('采用候选版本', row.get('采用的候选版本', '')))
    bound = {}
    for name, body in reviews.items():
        targets = markdown_links(field(body, '对应具体候选'), source)
        if not targets:
            targets = markdown_links(field(body, '具体候选文件及版本'), source)
        keys = {link['key'] for link in targets}
        generation = re.fullmatch(r'审阅-(生成记录-\d+)-\d+', name)[1]
        outputs = generations.get(generation, set())
        # Processing inherits the original decision only when its input is bound.
        if keys & outputs:
            keys |= outputs
        saved = {link['key'] for label in ('正式文件入口', '正式保存位置')
                 for link in markdown_links(field(body, label), source)}
        for key, (review, version) in formal.items():
            if review != name:
                continue
            adopted = re.search(r'v\d+(?:\.\d+)*', version)
            matching = [target for target in targets if re.sub(r'-(?:候选|草稿)-v\d+(?:\.\d+)*(?:-超分-\d+)?$', '', PurePosixPath(target['key']).stem) == PurePosixPath(key).stem]
            if adopted:
                matching = [target for target in matching if re.search(r'-(?:候选|草稿)-' + re.escape(adopted[0]) + r'(?:-超分-\d+)?$', PurePosixPath(target['key']).stem)]
            if targets and (matching or key in saved):
                keys.add(key)
        for key in keys:
            bound[key] = (name, body, dispositions.get(generation, ''))
    result = []
    for file in files:
        entry = dict(file)
        name, body, disposition = bound.get(file['key'], ('', '', ''))
        decision = field(body, '决定')
        if decision == '未记录':
            decision = field(body, '结论')
        applicable = field(body, '当前制作适用性')
        retention = field(body, '留存用途')
        approved = bool(re.match(r'^(批准采用|已批准)(?:$|[；。\s])', decision))
        obsolete = applicable.startswith('不适用') or retention.startswith(('旧版留档', '历史留档'))
        if disposition in ('已结束未采用', '已被替换／归档'):
            group, label = 'history', disposition
        elif approved:
            group = 'history' if obsolete or file['key'] not in formal else 'adopted'
            label = '旧版留档（曾获批准）' if obsolete else '当前采用' if group == 'adopted' else '已采用源图／处理副本'
            if group == 'adopted' and (applicable == '未记录' or applicable.startswith('待核对')):
                group, label = 'unknown', '已批准／适用性待核对'
        elif decision.startswith('修改后再审'):
            group = 'history' if retention.startswith(('旧版留档', '历史留档')) else 'revision'
            label = '旧版留档（曾要求返修）' if group == 'history' else '待修改'
        elif decision.startswith(('不采用', '不通过')):
            group, label = 'history', '未采用'
        elif decision.startswith(('待确认', '待审核')):
            group, label = 'pending', '待审核'
        else:
            group, label = 'unknown', '状态待核对'
        entry.update(materialGroup=group, materialStatus=label,
                     approvalHtml=status_markup(decision, source),
                     materialNote=applicable if applicable != '未记录' else '当前制作适用性未登记。')
        if name:
            entry['materialReview'] = dict(kind='markdown', name='审阅记录', key=source + '#' + name)
        result.append(entry)
    return result
