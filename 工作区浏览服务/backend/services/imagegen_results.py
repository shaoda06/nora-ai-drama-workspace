"""Native Imagegen handoff and image closeout; never calls a generator or a queue."""
from datetime import datetime
import json
from pathlib import Path
import re

from project_paths import project_file
from workflow_paths import workflow_root
from backend.services import image_closeout as images
from backend.services.execution_checks import write_json
from backend.services.submission_plans import Documents, publish, reference
from backend.services.result_registration import verify_image_entries


SKILL = workflow_root().parents[1]


def now():
    return datetime.now().astimezone().isoformat()


def prepare(project, request_file):
    root = Path(project).resolve()
    request_file = project_file(root, request_file)
    spec = json.loads(request_file.read_text('utf-8-sig'))
    manifest = request_file.with_name(request_file.stem + '-Imagegen执行清单.json')
    if manifest.exists():
        job = json.loads(manifest.read_text('utf-8-sig'))
        if job['request'] != spec:
            raise ValueError('原Imagegen请求已变化；新生成须另存请求，不覆盖已有交接')
        return job
    images.validate_names(root, dict(kind=spec['kind'], image_type=spec['image_type'], formal=spec.get('formal'),
        draft=spec['draft'], images=[dict(path=spec['output'])]), required=True)
    if spec['kind'] not in images.TEMPLATES or not spec['prompt'].strip() or not spec['authorization'].strip():
        raise ValueError('Imagegen需要既定图片类型、完整提示词和实际授权')
    if not re.fullmatch(r'[1-9]\d*:[1-9]\d*', spec['ratio']):
        raise ValueError('请求比例须为正整数宽:高')
    if len(spec['formal_size']) != 2 or any(type(n) is not int or n <= 0 for n in spec['formal_size']):
        raise ValueError('正式尺寸须为两个正整数；不代表Imagegen原生像素保证')
    draft = project_file(root, spec['draft'])
    documents = Documents(root)
    cover_metadata = spec.get('fields', {})
    if spec['kind'] == '封面':
        from backend.parsers.covers import cover_fields
        cover_metadata = cover_fields(cover_metadata, documents.read)
    text = documents.read(draft)
    template = images.template_path(SKILL, spec['kind']).read_text('utf-8-sig')
    template = re.search(r'````markdown\n(.*?)\n````', template, re.S)[1]
    if text is None:
        text = '# ' + draft.stem + '\n' + template.split('\n', 1)[1]
        text = text[:text.index('### 生成记录-001')] + text[text.index('## 3. 讨论与修改'):text.index('### 审阅-生成记录-001-001')]
    if len(spec.get('references', [])) > 5:
        raise ValueError('内置Imagegen最多接收5张参考图，请先按实际用途精简输入')
    refs = [reference(root, draft, ref, documents, require_seed=False) for ref in spec.get('references', [])]
    number = max((int(n) for n in re.findall(r'^### 生成记录-(\d+)', text, re.M)), default=0) + 1
    generation = f'生成记录-{number:03d}'
    prefix = spec['object'] + '-' + generation
    record = project_file(root, spec.get('record_dir', str(draft.parent.parent / '执行附件' / prefix)))
    candidate = project_file(root, spec['output'])
    if candidate.exists():
        raise ValueError('计划候选已存在，不覆盖：' + spec['output'])
    body = images.section(template, '生成记录-001')[0].replace('生成记录-001', generation, 1)
    values = {name: '不适用' for name in re.findall(r'^- ([^：\n]+)：', body, re.M)}
    values.update(cover_metadata)
    request_link = images.link(draft, request_file, '完整生成请求')
    values.update({'创建时间': now(), '图片类型': spec['image_type'],
        '生成／修改授权与计数': spec['authorization'] + '；本条目标1张；实际调用结果见执行凭据',
        '生成方式与任务用途': ('参考图生成／编辑' if refs else '文生图') + '；' + spec.get('purpose', spec['title']),
        '本次目标': spec['title'], '本次目标、保留与变化': spec['title'],
        '模型及工作流': 'Codex内置Imagegen；执行代理gpt-6-luna／medium；生图模型版本未提供',
        '模型与工作流基准': 'Codex内置Imagegen；非ComfyUI任务；生图模型版本未提供',
        '本次工作流副本入口': request_link, '本次任务副本入口': request_link,
        '种子、步数、CFG、采样器及调度器': '未提供；不套用Qwen参数',
        '种子、步数、CFG、采样器、调度器及其他实际参数': '未提供；不套用Qwen参数',
        '种子选择与输入避重依据': '不适用；Imagegen不暴露种子',
        '目标尺寸、格式及数量': f"请求比例{spec['ratio']}；原生尺寸由工具返回；正式目标{spec['formal_size'][0]}×{spec['formal_size'][1]}；PNG、1张",
        '参考图预处理与画布设置': '使用原参考图；无预裁切或缩放；请求比例' + spec['ratio'],
        'client_id、prompt_id': '不适用；非ComfyUI任务', 'client ID／prompt ID': '不适用；非ComfyUI任务',
        '执行状态': '待子代理执行', '真实执行状态': '待子代理执行',
        '输出候选文件': '尚未生成；计划：' + images.link(draft, candidate),
        '候选文件入口': '尚未生成；计划：' + images.link(draft, candidate),
        '实际尺寸、格式及数量': '待工具返回后核对原生尺寸', '批准后超分': '待批准',
        '文件核对结论': '待核对', '审阅记录入口': '实际结果登记后建立',
        '看图调用状态': '未调用（默认）', '用户采用状态': '未送审',
        '用户决定原因与依据': '尚无本轮结果及用户决定', '正式文件入口': '尚未采用',
        '用户决定及具体候选、批准依据': '未送审；尚无本轮结果及用户决定'})
    body = images.fields(body, values)
    body = re.sub(r'```json\n\{\}\n```', lambda _: '```json\n' + json.dumps({'prompt': spec['prompt']}, ensure_ascii=False, indent=2) + '\n```', body, count=1)
    start, end = body.index('#### 2. 输入参考'), body.index('#### 3.')
    inputs = '\n'.join(f"- 输入{i}：{images.link(draft, ref['file'])}；用途：{ref['purpose']}；{ref['basis']}；未预处理" for i, ref in enumerate(refs, 1)) or '- 无输入参考图。'
    body = body[:start] + '#### 2. 输入参考\n\n' + inputs + '\n\n' + body[end:]
    marker = re.search(r'^## 3\. 讨论与修改\s*$', text, re.M)
    if not marker or not re.search(r'^## 4\. 审阅区\s*$', text, re.M):
        raise ValueError('图片工作稿缺少固定讨论／审阅区')
    documents.put(draft, text[:marker.start()] + body.rstrip() + '\n\n' + text[marker.start():])
    job = {'provider': 'imagegen', 'request': spec, 'manifest': manifest.relative_to(root).as_posix(),
        'executor': {'model': 'gpt-6-luna', 'reasoning_effort': 'medium', 'fork_turns': 'none'},
        'draft': draft.relative_to(root).as_posix(), 'kind': spec['kind'], 'generation': generation,
        'review': '审阅-' + generation + '-001', 'candidate': candidate.relative_to(root).as_posix(),
        'record': record.relative_to(root).as_posix(), 'report': (record / 'Imagegen结果报告.json').relative_to(root).as_posix(),
        'prompt_file': (record / 'Imagegen实际提示词.txt').relative_to(root).as_posix(),
        'generation_call_file': (record / 'Imagegen内置调用.js').relative_to(root).as_posix(),
        'result_store_key': 'imagegen:' + root.name + ':' + manifest.relative_to(root).as_posix()}
    if documents.read(job['prompt_file']) is not None:
        raise ValueError('Imagegen提示词附件已占用，不覆盖')
    documents.put(job['prompt_file'], spec['prompt'])
    arguments = {'prompt': spec['prompt']}
    if refs:
        arguments['referenced_image_paths'] = [str(ref['file']) for ref in refs]
    call = ('// @exec: {"yield_time_ms": 120000, "max_output_tokens": 1000}\n'
            'const imagegenResult = await tools.image_gen__imagegen(' + json.dumps(arguments, ensure_ascii=False) + ');\n'
            'store(' + json.dumps(job['result_store_key'], ensure_ascii=False) + ', imagegenResult);\n'
            'generatedImage(imagegenResult);\n')
    documents.put(job['generation_call_file'], call)
    documents.new_json(manifest, job)
    images.validate_record_updates(root, [spec['draft']], spec.get('record_updates', []),
        tokens=('{{outputs}}', '{{specs}}'), contents={draft: documents.read(draft)})
    publish(root, documents.writes())
    return job


def complete(project, manifest_file, result_file, projects, *, repair=None):
    root = Path(project).resolve()
    job = json.loads(project_file(root, manifest_file).read_text('utf-8-sig'))
    images.validate_names(root, dict(kind=job['kind'], image_type=job['request'].get('image_type'), formal=job['request'].get('formal'),
        draft=job['draft'], images=[dict(path=job['candidate'])]))
    result_file = project_file(root, result_file)
    result = json.loads(result_file.read_text('utf-8-sig'))
    if result['actual_prompt'] != job['request']['prompt']:
        raise ValueError('实际Imagegen提示词与交接正文不符，不登记为本次结果')
    report_file = project_file(root, job['report'])
    if repair is not None:
        prior = json.loads(report_file.read_text('utf-8-sig')) if report_file.exists() else {}
        current = prior.get('registration_updates', job['request'].get('record_updates', []))
        updates = images.repair_record_updates(root, [job['draft']], current, repair, report_file,
                                               identity={'source': result['source'], 'manifest': job['manifest']})
        job['request']['record_updates'] = updates
    if report_file.exists():
        report = json.loads(report_file.read_text('utf-8-sig'))
        if report['source'] != result['source'] or report['manifest'] != job['manifest']:
            raise ValueError('已有收尾报告属于不同原图或执行清单')
        if report['status'] == 'completed':
            return report
    else:
        source = Path(result['source']).resolve()
        # The executor supplies the tool's actual local output; no remote receipt is invented.
        raw = source.read_bytes()
        width, height = images.png(raw)
        candidate = project_file(root, job['candidate'])
        candidate.parent.mkdir(parents=True, exist_ok=True)
        if candidate.exists():
            if candidate.read_bytes() != raw:
                raise ValueError('候选文件已有不同内容，不覆盖')
        else:
            with candidate.open('xb') as stream:
                stream.write(raw)
        draft = project_file(root, job['draft'])
        original = draft.read_text('utf-8-sig')
        generation = images.section(original, job['generation'])[0]
        evidence = images.link(draft, result_file, 'Imagegen实际调用与原生结果凭据')
        links = images.link(draft, candidate)
        specs = f'{width}×{height}、PNG、{len(raw)}字节、可解码；数量1；原生比例误差不作为失败'
        changed = images.fields(generation, {'执行状态': 'completed；原生结果已保存', '真实执行状态': 'completed；原生结果已保存',
            '输出候选文件': links, '候选文件入口': links, '实际尺寸、格式及数量': specs,
            '文件核对结论': '通过', '文件核对证据与异常': evidence,
            '请求响应与执行结果入口': evidence, '请求、上传／提交响应及执行结果入口': evidence,
            '审阅记录入口': '[审阅记录](#' + job['review'] + ')', '用户采用状态': '待确认',
            '用户决定及具体候选、批准依据': '待确认；' + links + '；尚无用户批准',
            '失败或异常说明': '无；未作画面内容判断'})
        if re.search(r'^### ' + re.escape(job['review']) + r'\s*$', original, re.M):
            raise ValueError('本次审阅编号已被占用')
        area = re.search(r'^## 4\. 审阅区\s*\n.*?(?=^## |\Z)', original, re.M | re.S)
        review = images.review_text(SKILL, job, generation, links, specs, evidence, now())
        updates = [dict(path=job['draft'], old=generation, new=changed),
            dict(path=job['draft'], old=area[0], new=area[0].rstrip() + '\n\n' + review)]
        for update in job['request'].get('record_updates', []):
            update = dict(update)
            target = project_file(root, update['path'])
            update['new'] = update['new'].replace('{{outputs}}', images.link(target, candidate)).replace('{{specs}}', specs)
            if re.search(r'\{\{[^{}]+\}\}', update['new']):
                raise ValueError('Imagegen关联更新含未知占位符')
            updates.append(update)
        report = {'provider': 'imagegen', 'manifest': job['manifest'], 'source': result['source'],
            'status': 'registering', 'recorded_at': now(), 'user_message_ready': False,
            'items': [dict(path=job['candidate'], width=width, height=height, format='PNG',
                           bytes=len(raw), decoded=True, draft=job['draft'], image=True)], 'updates': updates}
        if repair is not None:
            report.update(record_repair=repair, registration_updates=repair['updates'])
        write_json(report_file, report)
    if report['status'] != 'registered':
        images.apply_updates(root, report, report_file)
    projects.get(root.name, synchronize=True)
    status = projects.status(root.name)
    if status['updating'] or status['checking'] or status['error']:
        raise ValueError('图片已登记，网页尚未同步：' + str(status['error']))
    verify_image_entries(projects, root.name, report['items'])
    report.update(status='completed', user_message_ready=True, browser=dict(status='verified', checked_at=now()),
                  review_path='/#/projects/' + root.name)
    write_json(report_file, report)
    return report


def fail(project, manifest_file, error):
    root = Path(project).resolve()
    job = json.loads(project_file(root, manifest_file).read_text('utf-8-sig'))
    report_file = project_file(root, job['report'])
    if report_file.exists():
        raise ValueError('本次已有结果报告，不用失败状态覆盖已有收尾')
    draft = project_file(root, job['draft'])
    body = images.section(draft.read_text('utf-8-sig'), job['generation'])[0]
    changed = images.fields(body, {'执行状态': 'failed；未自动重试', '真实执行状态': 'failed；未自动重试',
        '失败或异常说明': error.replace('\n', '；'), '文件核对结论': '异常'})
    report = dict(provider='imagegen', manifest=job['manifest'], status='registering', error=error,
        user_message_ready=False, recorded_at=now(), updates=[dict(path=job['draft'], old=body, new=changed)])
    write_json(report_file, report)
    images.apply_updates(root, report, report_file)
    report['status'] = 'failed'
    write_json(report_file, report)
    return report
