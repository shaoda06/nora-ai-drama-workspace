"""Local size adaptation for approved images; never uploads or submits a ComfyUI job."""
import json
from pathlib import Path
import re

from PIL import Image, ImageOps, __version__

from project_paths import project_file
from backend.services import execution_checks as checks, image_closeout as images
from backend.services.result_registration import verify_image_entries


def prepare(store, data):
    # Existing results resume their journal; placeholder source rows may already be applied.
    images.validate_plan(data, check_records=not (Path(data.record_dir) / '结果收尾报告.json').exists())
    plan, root = data.image_plan, Path(data.project)
    source = project_file(root, plan['upscale']['source'])
    report = dict(ok=True, new_task_ready=True, checked_at=store.client.now(),
                  prepared_input=checks.basis(store, data), sources=checks.sources(data, [source]))
    previous = checks.read_report(data)
    if previous and (previous['prepared_input'] != report['prepared_input'] or previous['sources'] != report['sources']):
        raise ValueError('本地处理准备资料已变化；请重新准备，不能沿用原处理计划')
    formal = project_file(root, plan['upscale']['formal'])
    if formal.exists() and not plan['upscale'].get('archive') and not (Path(data.record_dir) / '结果收尾报告.json').exists():
        raise ValueError('正式文件已存在，缺少替换归档入口')
    checks.write_report(data, report)
    return dict(prepared=True, report=checks.REPORT)


def repair(store, data, request):
    root, plan = Path(data.project), data.image_plan
    report_file = Path(data.record_dir) / '结果收尾报告.json'
    report = json.loads(report_file.read_text('utf-8-sig'))
    if report.get('provider') != 'local':
        raise ValueError('没有可接续的本地图片结果')
    current = report.get('registration_updates', images.record_updates(plan))
    images.repair_record_updates(root, [plan['draft']], current, request, report_file)
    return complete(store, data)


def complete(store, data):
    root, record, plan = Path(data.project), Path(data.record_dir), data.image_plan
    report_file = record / '结果收尾报告.json'
    previous = json.loads(report_file.read_text('utf-8')) if report_file.exists() else None
    if previous is None:
        checks.check_prepared(store, data)
        draft, original, planned = images.validate_plan(data)
        up, processing = plan['upscale'], plan['local_processing']
        source = project_file(root, up['source'])
        candidate = next(iter(planned))
        target = (plan['images'][0]['width'], plan['images'][0]['height'])
        if candidate.exists():
            raise ValueError('本地处理输出已存在，不能覆盖：' + str(candidate))
        with Image.open(source) as image:
            image.load()
            width, height = image.size
            scale = max(target[0] / width, target[1] / height)
            crop_width, crop_height = target[0] / scale, target[1] / scale
            left = (width - crop_width) * processing['crop_anchor'][0]
            top = (height - crop_height) * processing['crop_anchor'][1]
            box = [left, top, left + crop_width, top + crop_height]
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with candidate.open('xb') as stream:
                if image.size == target:
                    stream.write(source.read_bytes())
                else:
                    result = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS, centering=tuple(processing['crop_anchor']))
                    result.save(stream, format='PNG')
        raw = candidate.read_bytes()
        assert images.png(raw) == target
        receipt = record / data.outputs[0].response_name
        proof = dict(provider='local', tool='Pillow ' + __version__, method='LANCZOS / equal-aspect fit',
                     source=up['source'], source_size=[width, height], crop_box=box,
                     crop_anchor=processing['crop_anchor'], path=plan['images'][0]['path'], size=list(target),
                     bytes=len(raw), format='PNG', decoded=True, recorded_at=store.client.now())
        checks.write_json(receipt, proof)
        evidence = images.link(draft, receipt, '本地处理凭据')
        specs = f'{target[0]}×{target[1]}、PNG、{len(raw)}字节、可解码；数量1'
        formal = project_file(root, up['formal'])
        body = images.section(original, plan['generation'])[0]
        changed = images.fields(body, {'批准后超分': '本地规格处理成功；未调用RTX',
            '超分输出文件及实际规格': images.link(draft, candidate) + '；' + specs,
            '超分请求响应与执行结果入口': evidence,
            '超分工作流、参数与任务ID': '本地Pillow等比缩放与裁切；远端任务ID不适用',
            '正式文件入口': images.link(draft, formal), '用户采用状态': '已采用'})
        subrecord = ('##### ' + up['number'] + '\n\n- 本地处理方式：Pillow／LANCZOS等比缩放与裁切；未调用RTX。'
                     + '\n- 原批准输入：' + images.link(draft, source) + '；[批准](#' + plan['review'] + ')'
                     + f'\n- 实际源图与输出尺寸：{width}×{height} → {target[0]}×{target[1]}'
                     + '\n- 原图裁切坐标：' + json.dumps(box) + '\n- 处理凭据：' + evidence + '\n\n')
        changed = changed.replace('#### 5. 检查与采用', subrecord + '#### 5. 检查与采用', 1)
        updates = [dict(path=plan['draft'], old=body, new=changed)]
        for update in [*plan.get('record_updates', []), *up['record_updates']]:
            update = dict(update)
            target_file = project_file(root, update['path'])
            for token, value in {'{{file}}': images.link(target_file, formal), '{{outputs}}': images.link(target_file, candidate),
                                 '{{specs}}': specs, '{{time}}': store.client.now(),
                                 '{{evidence}}': images.link(target_file, receipt, '本地处理凭据')}.items():
                update['new'] = update['new'].replace(token, value)
            if re.search(r'\{\{[^{}]+\}\}', update['new']):
                raise ValueError('图片关联更新有未知占位符')
            updates.append(update)
        review = images.section(original, plan['review'])[0]
        confirmation = re.search(r'^#### 4\. 用户确认\s*\n(.*?)(?=^#### |\Z)', review, re.M | re.S)[0]
        prior = formal.stat() if formal.exists() else None
        previous = dict(status='registering', provider='local', items=[dict(path=plan['images'][0]['path'],
            display_path=up['formal'], draft=plan['draft'], image=True, width=target[0], height=target[1],
            format='PNG', decoded=True, bytes=len(raw), receipt=receipt.relative_to(root).as_posix())], updates=updates,
            publication=dict(source=plan['images'][0]['path'], formal=up['formal'], archive=up.get('archive'),
                             prior=[prior.st_size, prior.st_mtime_ns] if prior else None),
            approval=dict(path=plan['draft'], heading=plan['review'], text=confirmation))
        checks.write_json(report_file, previous)
    if previous['status'] == 'registering':
        images.apply_updates(root, previous, report_file)
    if previous['status'] != 'completed':
        store.projects.get(root.name, synchronize=True)
        status = store.projects.status(root.name)
        if status['updating'] or status['checking'] or status['error']:
            raise ValueError('本地成品已保存，网页尚未同步：' + str(status['error']))
        verify_image_entries(store.projects, root.name, previous['items'])
        previous.update(status='completed', browser=dict(status='verified', revision=status['revision']))
        checks.write_json(report_file, previous)
    return dict(status='completed', provider='local', local_task_id=None, report=report_file.relative_to(root).as_posix())
