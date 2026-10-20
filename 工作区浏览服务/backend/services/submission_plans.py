"""Build submission artifacts from one project task list; prepare all before queueing any."""
from copy import deepcopy
import json
from pathlib import Path
import re
import secrets
import tempfile
from urllib.parse import unquote

from project_paths import project_file
from workflow_paths import workflow_file, workflow_root
from backend.services.director_uploads import pairs
from backend.services.execution_checks import write_json
from backend.services import image_closeout as images

SEEDS = {'人物上半身正面肖像图': '人物上半身正面肖像', '人物多视角参考图': '人物六视图',
         '服装参考图': '服装正背面图', '角色多视角参考图': '角色六视图', '道具三视图': '道具三视图',
         '场景参考图': '场景参考图', '首帧参考图': '首帧参考图'}
SIZES = {'人物上半身正面肖像图': (1024, 1024), '人物多视角参考图': (2048, 2048),
         '服装参考图': (1152, 864), '角色多视角参考图': (2048, 2048)}


class Documents:
    def __init__(self, root, previous_writes=()):
        self.root, self.edits, self.image_sizes = root, {}, {}
        self.previous = {project_file(root, item['path']): item for item in previous_writes}
        for path, item in self.previous.items():
            current = path.read_text('utf-8-sig') if path.exists() else None
            if current not in (item['old'], item['new']):
                raise ValueError('准备资料已变化，不覆盖：' + item['path'])

    def read(self, name):
        path = project_file(self.root, name)
        if path not in self.edits:
            text = path.read_text('utf-8-sig') if path.exists() else None
            # Rebuild from the original inputs, while publishing against the current files.
            previous = self.previous.get(path)
            self.edits[path] = [text, previous.get('original', previous['old']) if previous else text]
        return self.edits[path][1]

    def put(self, name, text):
        self.read(name)
        self.edits[project_file(self.root, name)][1] = text

    def new_json(self, name, value):
        old = self.read(name)
        if old is not None:
            if json.loads(old) != value:
                raise ValueError('执行文件已被占用：' + str(name))
            return
        self.put(name, json.dumps(value, ensure_ascii=False, indent=2))

    def writes(self):
        return [dict(path=p.relative_to(self.root).as_posix(), old=old, new=new,
                     **({'original': self.previous[p].get('original', self.previous[p]['old'])} if p in self.previous else {}))
                for p, (old, new) in self.edits.items() if old != new or p in self.previous]


def publish(root, updates):
    """Replay exact planned writes, without overwriting concurrent edits or historical outputs."""
    for update in updates:
        path = project_file(root, update['path'])
        current = path.read_text('utf-8-sig') if path.exists() else None
        if current == update['new']:
            continue
        if current != update['old']:
            raise ValueError('准备资料已变化，不覆盖：' + update['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(update['new'])
            actual = path.read_text('utf-8-sig') if path.exists() else None
            if actual != current:
                raise ValueError('准备资料并发变化，不覆盖：' + update['path'])
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def widget(graph, node, **values):
    named = node['widgets_values_named']
    for key, content in values.items():
        if key not in named:
            raise ValueError('基准不存在控件：' + key)
        slot = next((i for i in node.get('inputs', []) if i['name'] == key), None)
        if slot and slot.get('link') is not None:
            disconnect(graph, slot)
        named[key] = content
    if isinstance(node['widgets_values'], dict):
        node['widgets_values'].update(values)
    else:
        node['widgets_values'] = list(named.values())


def disconnect(graph, slot):
    key = slot['link']
    if key is None:
        return
    link = next(pairs.link_tuple(link) for link in graph['links'] if pairs.link_tuple(link)[0] == key)
    origin = next(n for n in graph['nodes'] if n['id'] == link[1])
    origin['outputs'][link[2]]['links'].remove(key)
    graph['links'] = [item for item in graph['links'] if pairs.link_tuple(item)[0] != key]
    slot['link'] = None


def remote_prefix(root, *parts):
    """Build output-relative paths; each supplied identity is one path component."""
    names = (root.name, *parts)
    if any(not name or name in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith(('.', ' ')) for name in names):
        raise ValueError('远端输出名称须为合法的单个目录名或文件前缀')
    return '/'.join(names)


def image_workflow(skill, spec, refs, width, height, seed, prefix, remote_output=None):
    upscale = spec['task_type'] == 'image-upscale'
    base = 'RTX-图片2倍超分' if upscale else 'Qwen2.1-' + ('图生图' if refs else '文生图') + '-普通版'
    remote_output = prefix if remote_output is None else remote_output
    if upscale:
        canvas = json.loads(workflow_file(base, root=workflow_root(skill)).read_text('utf-8-sig'))
        nodes = {n['id']: n for n in canvas['nodes']}
        widget(canvas, nodes[2], image=refs[0]['file'].name)
        widget(canvas, nodes[3], filename_prefix=remote_output)
        uploads = [dict(file=str(refs[0]['file']), node='2', input='image', subfolder=prefix,
                        **{'response-name': prefix + '-上传响应.json'})]
        return canvas, pairs.Canvas(canvas).api(3), uploads, '3'

    prompt = spec['prompt']
    from fractions import Fraction
    if set(prompt) not in ({'rewritten_prompt', 'wh_ratio'}, {'rewritten_prompt', 'wh_ratio', 'ratio_follow'}) or not prompt['rewritten_prompt'] or not prompt['wh_ratio'] or prompt.get('ratio_follow'):
        raise ValueError('任务清单须提供最终正文和明确画幅，不能同时跟随输入画幅')
    if Fraction(prompt['wh_ratio'].replace(':', '/')) != Fraction(width, height):
        raise ValueError('提示词画幅元数据与目标宽高不一致')
    api = json.loads(workflow_file(base, 'api', root=workflow_root(skill)).read_text('utf-8-sig'))
    text, latent, sampler, encoder, output = ('680', '479', '481', '497', '487') if refs else ('672', '514', '515', '522', '508')
    api[text]['inputs']['value'] = prompt['rewritten_prompt']
    api[latent]['inputs'].update(width=width, height=height)
    api[sampler]['inputs']['seed'] = seed
    for name, content in spec.get('parameters', {}).items():
        if name == 'negative_prompt':
            api[encoder]['inputs'][name] = content
        else:
            raise ValueError('图片任务不能覆盖固定配置：' + name)
    api[output]['inputs']['filename_prefix'] = remote_output
    uploads = []
    if len(refs) > 10:
        raise ValueError('参考图数量超过现行10图入口')
    for index, ref in enumerate(refs):
        loader = '475' if index == 0 else str(700 + (index - 1) * 2)
        scale = '532' if index == 0 else str(701 + (index - 1) * 2)
        if index:
            api[loader] = deepcopy(api['475'])
            api[scale] = deepcopy(api['532'])
        api[loader]['inputs']['image'] = ref['file'].name
        api[scale]['inputs']['image'] = [loader, 0]
        api[encoder]['inputs'][f'images.image_{index + 1}'] = [scale, 0]
        uploads.append(dict(file=str(ref['file']), node=loader, input='image', subfolder=prefix,
                            **{'response-name': prefix + f'-上传响应-{index + 1:03d}.json'}))
    return None, api, uploads, output


def reference(root, draft, ref, documents, *, require_seed=True):
    file = project_file(root, ref['file'])
    if file not in documents.image_sizes:
        documents.image_sizes[file] = images.png(file.read_bytes())
    size = documents.image_sizes[file]
    if ref.get('user_reference'):
        if not ref.get('basis'):
            raise ValueError('用户参考图须写明本次指定依据与用途')
        source_seed = ref.get('source_seed')
        if require_seed and source_seed is None and not (ref.get('source_kind') == '非生成' or ref.get('unknown_seed_basis')):
            raise ValueError('来源种子未知，须记录用户对未知来源的处理决定')
        basis = ref['basis']
    else:
        approval_file, heading = ref['approval'].split('#', 1)
        approval_path = project_file(root, approval_file)
        text = documents.read(approval_file)
        review = images.section(text, heading)[0]
        confirmation = re.search(r'^#### 4\. 用户确认\s*\n(.*?)(?=^#### |\Z)', review, re.M | re.S)
        if not confirmation or (images.value(confirmation[1], '结论') or images.value(confirmation[1], '决定')) != '批准采用':
            raise ValueError('输入参考图未批准：' + ref['file'])
        candidate_links = re.findall(r'\[[^\]]*\]\(([^)]+)\)', images.value(confirmation[1], '批准的具体候选') or images.value(confirmation[1], '对应具体候选'))
        candidates = [project_file(root, approval_path.parent / unquote(link)) for link in candidate_links]
        formal = False
        for line in text.splitlines():
            if not line.startswith('|'):
                continue
            links = [unquote(link) for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', line)]
            if ('#' + heading) in links and any('#' not in link and project_file(root, approval_path.parent / link) == file for link in links):
                formal = True
        if file not in candidates and not formal:
            raise ValueError('输入不是该批准的具体候选或已登记正式文件：' + ref['file'])
        generation = re.search(r'生成记录-\d+', heading)[0]
        body = images.section(text, generation)[0]
        token = images.value(body, '种子、步数、CFG、采样器及调度器') or images.value(body, '种子、步数、CFG、采样器、调度器及其他实际参数')
        matched = re.match(r'(\d+)\b', token)
        source_seed = int(matched[1]) if matched else None
        if require_seed and source_seed is None and not ref.get('unknown_seed_basis'):
            raise ValueError('批准输入缺少原始种子依据：' + ref['file'])
        basis = images.link(draft, approval_path, '批准记录')[:-1] + '#' + heading + ')'
    return dict(file=file, size=size, seed=source_seed, purpose=ref['purpose'], basis=basis,
                unknown_seed_basis=ref.get('unknown_seed_basis', ''), non_generated=ref.get('source_kind') == '非生成')


def choose_seed(root, spec, refs, documents, generation_link):
    kind = SEEDS.get(spec['image_type']) if not spec.get('supplementary') else None
    position = root / '00-项目定位/项目基本定位.md'
    text = documents.read(position)
    rows = list(re.finditer(r'^\| ([^|\n]+) \| (\d+|首次生成时确定) \|[^\n]*', text or '', re.M))
    values = {row[1]: int(row[2]) for row in rows if row[2].isdigit()}
    if len(values.values()) != len(set(values.values())):
        raise ValueError('项目类别种子存在重复，请先解决原登记冲突')
    prior = set()
    if spec.get('supplementary'):
        previous = documents.read(spec['draft']) or ''
        prior = {int(n) for n in re.findall(r'^- 种子、[^：\n]*：([0-9]+)\b', previous, re.M)}
    selected = spec.get('seed', values.get(kind))
    if kind and kind not in [row[1] for row in rows]:
        raise ValueError('缺少项目七类种子表的目标类别：' + kind)
    if selected is None:
        selected = secrets.randbelow(2**53)
        while selected in values.values() or selected in prior or selected in [ref['seed'] for ref in refs]:
            selected = secrets.randbelow(2**53)
    if type(selected) is not int or selected < 0 or selected >= 2**64:
        raise ValueError('种子必须为有效非负整数')
    if selected in prior:
        raise ValueError('补充图须使用未在该工作稿历史使用过的新种子')
    if kind in values and selected != values[kind]:
        raise ValueError('任务种子与已登记类别不同；变更须先按原规则确认并更新登记')
    if any(value == selected for name, value in values.items() if name != kind) or any(ref['seed'] == selected for ref in refs):
        raise ValueError('种子与其他类别或实际输入冲突，不自动换值')
    if kind and kind not in values:
        row = next(row for row in rows if row[1] == kind)
        replacement = f'| {kind} | {selected} | {generation_link}；首次生成所选值，实际提交状态见后台记录 |'
        documents.put(position, text[:row.start()] + replacement + text[row.end():])
    return selected


def generation_record(skill, spec, generation, refs, seed, width, height, record, draft, candidate, api):
    template = (skill / 'references/模板' / images.TEMPLATES[spec['kind']]).read_text('utf-8-sig')
    template = re.search(r'````markdown\n(.*?)\n````', template, re.S)[1]
    body = images.section(template, '生成记录-001')[0].replace('### 生成记录-001', '### ' + generation, 1)
    names = re.findall(r'^- ([^：\n]+)：', body, re.M)
    values = {name: '不适用' for name in names}
    values.update(spec.get('fields', {}))
    native = spec['image_type'] in ('人物多视角参考图', '角色多视角参考图')
    sampler = next(node['inputs'] for node in api.values() if node['class_type'] == 'KSampler')
    encoder = next(node['inputs'] for node in api.values() if node['class_type'] == 'TextEncodeQwenImage21')
    model_names = [node['inputs'][field] for node in api.values() for field in ('unet_name', 'clip_name', 'vae_name') if field in node['inputs']]
    parameters = '、'.join(str(sampler[name]) for name in ('seed', 'steps', 'cfg', 'sampler_name', 'scheduler'))
    caches = [node['inputs'] for node in api.values() if node['class_type'] == 'QwenImage21Cache']
    cache_text = '；'.join(f"缓存device={cache['device']}、dtype={cache['dtype']}" for cache in caches) or '无缓存节点'
    acceleration = [node['inputs'] for node in api.values() if node['class_type'] == 'TESpeedQwenImage21']
    if acceleration:
        cache_text += '；TE加速：' + json.dumps({key: value for key, value in acceleration[0].items() if key != 'model'}, ensure_ascii=False)
    api_link = images.link(draft, record / (record.name + '.api.json'), '实际API副本')
    workflow_entry = images.link(draft, record / (record.name + '.api.json'), 'API')
    workflow_entry += '；原始' + ('图生图' if refs else '文生图') + '画布仅保存在技能工作流目录'
    values.update({'创建时间': spec['created_at'], '生成／修改授权与计数': spec['authorization'] + '；本次目标1张；实际提交次数及状态见后台记录',
        '图片类型': spec['image_type'], '生成方式与任务用途': ('图生图' if refs else '文生图') + '；' + spec.get('purpose', '基础参考图'),
        '人物状态': spec.get('state', '不适用'), '服装状态': spec.get('costume', '不适用'),
        '本次目标': spec.get('description', spec['title']), '本次目标、保留与变化': spec.get('description', spec['title']),
        '依据的资料卡及版本': spec.get('basis', '任务清单所列当前需求及已批准输入'),
        '本次工作流副本入口': workflow_entry,
        '本次任务副本入口': workflow_entry,
        '目标尺寸、格式及数量': f'{width}×{height}、PNG、1张',
        '实际反向提示词': encoder['negative_prompt'] or '空',
        '模型及工作流': '；'.join(model_names) + '；' + api_link,
        '模型与工作流基准': '；'.join(model_names) + '；' + api_link,
        '种子、步数、CFG、采样器及调度器': parameters,
        '种子、步数、CFG、采样器、调度器及其他实际参数': parameters + '；denoise=' + str(sampler['denoise']) + '；' + api_link,
        '其他实际参数（如降噪、缓存设置）': f"denoise={sampler['denoise']}；" + cache_text,
        '参考图预处理与画布设置': f"明确{width}×{height}；" + (f"每张参考图lanczos缩放至1.5MP、32对齐；编码器resolution={encoder['resolution']}；API节点479直接设置宽高；输入顺序见第2节" if refs else '无输入参考；API节点514直接设置宽高'),
        '请求响应与执行结果入口': '实际通信证据与状态见' + images.link(draft, record / '后台任务状态.json', '后台状态'),
        '请求、上传／提交响应及执行结果入口': '实际通信证据与状态见' + images.link(draft, record / '后台任务状态.json', '后台状态'),
        '种子选择与输入避重依据': '按项目类别登记；' + '；'.join(f'输入{i+1}原始种子：{r["seed"] if r["seed"] is not None else ("不适用" if r["non_generated"] else "未知；" + r["unknown_seed_basis"])}' for i, r in enumerate(refs)),
        '执行状态': '技术状态见' + images.link(draft, record / '后台任务状态.json', '后台状态'),
        '真实执行状态': '技术状态见' + images.link(draft, record / '后台任务状态.json', '后台状态'),
        '输出候选文件': '尚未取得实际输出；计划保存：' + images.link(draft, candidate, '计划候选'),
        '候选文件入口': '尚未取得实际输出；计划保存：' + images.link(draft, candidate, '计划候选'),
        '实际尺寸、格式及数量': '待核对', '失败或异常说明': '具体状态及问题见后台记录',
        '批准后超分': '不适用，原生图直接保存' if native else '待批准',
        '文件核对结论': '待核对', '文件核对证据与异常': '结果由后台收尾；尚无实际输出',
        '看图调用状态': '未调用（默认）', '审阅记录入口': '实际候选取回后由后台登记',
        '用户采用状态': '未送审', '用户决定原因与依据': '尚无本轮候选与采用决定', '正式文件入口': '尚未采用',
        '用户决定及具体候选、批准依据': '未送审；尚无本轮候选与采用决定',
        'client_id、prompt_id': '见' + images.link(draft, record / '后台任务状态.json', '后台任务状态')})
    body = images.fields(body, values)
    body = re.sub(r'```json\n\{\}\n```', lambda _: '```json\n' + json.dumps(spec['prompt'], ensure_ascii=False, indent=2) + '\n```', body, count=1)
    start = body.index('#### 2. 输入参考')
    end = body.index('#### 3.', start)
    inputs = '\n'.join(f'- 输入{i+1}：{images.link(draft,r["file"])}；用途：{r["purpose"]}；{r["size"][0]}×{r["size"][1]}；来源／批准：{r["basis"]}；原始种子：{r["seed"] if r["seed"] is not None else "未知或不适用，见来源依据"}' for i, r in enumerate(refs)) or '- 无输入参考图。'
    return body[:start] + '#### 2. 输入参考\n\n' + inputs + '\n\n' + body[end:]


def adoption_updates(root, draft, text, generation, heading, source, spec):
    """Fill the existing formal-assets table; optional extra associations remain explicit."""
    area = re.search(r'^## 1\. 当前正式资产\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)[1]
    rows = [line for line in area.splitlines() if line.startswith('|')]
    columns = [name.strip() for name in rows[0].strip('|').split('|')]
    body = images.section(text, generation)[0]
    version = re.search(r'-v(\d+)', source.stem)
    values = {name: images.value(body, name) for name in columns}
    values.update({'正式文件': '{{file}}', '审阅记录': '[批准](#' + heading + ')',
        '采用的候选版本': ('v' + version[1] if version else source.stem) + '／' + spec['upscale_number'],
        '采用候选版本': ('v' + version[1] if version else source.stem) + '／' + spec['upscale_number']})
    values.update(spec.get('adoption_fields', {}))
    missing = [name for name in columns if not values.get(name) or values[name] == '不适用']
    # 不适用 is a valid explicit state for portraits/base bodies, but not a missing scope or view.
    missing = [name for name in missing if name not in ('人物状态', '服装状态')]
    if missing:
        raise ValueError('正式资产表缺少已确认内容，请在adoption_fields填写：' + '、'.join(missing))
    replacement = '| ' + ' | '.join(values[name] for name in columns) + ' |'
    formal = project_file(root, spec['formal'])
    previous = []
    for row in rows[2:]:
        links = re.findall(r'\]\(([^)]+)\)', row)
        if any('#' not in link and project_file(root, draft.parent / unquote(link)) == formal for link in links):
            previous.append(row)
    if len(previous) > 1:
        raise ValueError('正式资产表中同一正式文件重复')
    old = previous[0] if previous else '\n'.join(rows[:2])
    new = replacement if previous else old + '\n' + replacement
    return [dict(path=draft.relative_to(root).as_posix(), old=old, new=new), *spec.get('adoption_updates', [])]


def build_image(root, skill, spec, documents, now):
    draft = project_file(root, spec['draft'])
    text = documents.read(draft)
    if text is None:
        template = (skill / 'references/模板' / images.TEMPLATES[spec['kind']]).read_text('utf-8-sig')
        text = re.search(r'````markdown\n(.*?)\n````', template, re.S)[1]
        text = '# ' + draft.stem + '\n' + text.split('\n', 1)[1]
        text = text[:text.index('### 生成记录-001')] + text[text.index('## 3. 讨论与修改'):text.index('### 审阅-生成记录-001-001')]
    refs = [reference(root, draft, ref, documents, require_seed=spec['task_type'] != 'image-upscale') for ref in spec.get('references', [])]
    if spec['task_type'] == 'image-upscale':
        if len(refs) != 1:
            raise ValueError('超分必须选择一个获批输入')
        approval = spec['references'][0]['approval']
        approval_file, heading = approval.split('#', 1)
        if project_file(root, approval_file) != draft:
            raise ValueError('超分必须在原生成工作稿留档')
        generation = re.search(r'生成记录-\d+', heading)[0]
        numbers = [int(n) for n in re.findall(r'超分-(\d+)', images.section(text, generation)[0])]
        number = spec.get('upscale_number', f'超分-{max(numbers, default=0)+1:03d}')
        prefix = spec['object'] + '-' + generation + '-' + number
        width, height = (n * 2 for n in refs[0]['size'])
        candidate = project_file(root, spec.get('output', str(refs[0]['file'].with_name(refs[0]['file'].stem + '-' + number + '.png'))))
        record = project_file(root, spec.get('record_dir', str(draft.parent.parent / '执行附件' / prefix)))
        plan = dict(draft=draft.relative_to(root).as_posix(), kind=spec['kind'], generation=generation, review=heading,
            images=[dict(path=candidate.relative_to(root).as_posix(), width=width, height=height)],
            upscale=dict(number=number, source=refs[0]['file'].relative_to(root).as_posix(), approval=approval,
                         formal=spec['formal'], record_updates=adoption_updates(root, draft, text, generation, heading, refs[0]['file'], {**spec, 'upscale_number': number})))
        if spec.get('archive'):
            plan['upscale']['archive'] = spec['archive']
        body = images.section(text, generation)[0]
        changed = images.fields(body, {'批准后超分': '已批准待超分；进度见后台状态',
            '超分编号及批准输入': number + '；' + images.link(draft, refs[0]['file']) + '；[原批准](#' + heading + ')',
            '超分工作流、参数与任务ID': '固定RTX2倍；任务状态见' + images.link(draft, record / '后台任务状态.json', '后台状态')})
        text = text.replace(body, changed, 1)
        seed = None
    else:
        number = max((int(n) for n in re.findall(r'^### 生成记录-(\d+)', text, re.M)), default=0) + 1
        generation = spec.get('generation', f'生成记录-{number:03d}')
        prefix = spec['object'] + '-' + generation
        if re.search(r'^### ' + re.escape(generation) + r'\s*$', text, re.M):
            raise ValueError('新生成编号已存在，不能覆盖：' + generation)
        width, height = spec.get('size', SIZES.get(spec['image_type'], (None, None)))
        if not width or not height or width % 32 or height % 32:
            raise ValueError('明确图片尺寸须为有效32倍数；其他类型请在size指定既定尺寸')
        stem = '-'.join(str(x) for x in (spec['object'], spec.get('state'), spec.get('costume'), spec['image_type']) if x)
        versions = []
        for area in re.finditer(r'^### 生成记录-\d+\s*\n.*?(?=^#{1,3} |\Z)', text, re.M | re.S):
            if images.value(area[0], '图片类型') != spec['image_type'] or images.value(area[0], '人物状态') != spec.get('state', '不适用') or images.value(area[0], '服装状态') != spec.get('costume', '不适用'):
                continue
            for path in re.findall(r'\]\(([^)]+\.png)\)', images.value(area[0], '输出候选文件') or images.value(area[0], '候选文件入口')):
                version = re.search(r'-v(\d+)\.png$', path)
                if version: versions.append(int(version[1]))
        candidate = project_file(root, spec.get('output', str(draft.parent / '素材' / f'{stem}-候选-v{max(versions, default=0)+1:02d}.png')))
        record = project_file(root, spec.get('record_dir', str(draft.parent.parent / '执行附件' / prefix)))
        seed = choose_seed(root, spec, refs, documents, images.link(root / '00-项目定位/项目基本定位.md', draft, generation)[:-1] + '#' + generation + ')')
        plan = dict(draft=draft.relative_to(root).as_posix(), kind=spec['kind'], generation=generation,
                    review='审阅-' + generation + '-001', images=[dict(path=candidate.relative_to(root).as_posix(), width=width, height=height)])
    if candidate.exists():
        raise ValueError('候选文件已存在，不能覆盖：' + str(candidate))
    image_type = spec.get('image_type') or images.value(images.section(text, generation)[0], '图片类型')
    remote_name = spec['object'] + '-' + image_type + '-' + prefix[len(spec['object']) + 1:]
    category = '剧集专用' if spec['kind'] == '剧集素材' else spec['kind']
    if image_type == '画风样例':
        remote_output = remote_prefix(root, '图片生成', '画风样例', prefix)
    elif category == '剧集专用':
        episode = re.search(r'EP\d+', spec['object'])[0]
        remote_output = remote_prefix(root, '图片生成', category, episode, remote_name)
    else:
        remote_output = remote_prefix(root, '图片生成', category, spec['object'], remote_name)
    canvas, api, uploads, output_node = image_workflow(skill, spec, refs, width, height, seed, prefix, remote_output)
    if spec['task_type'] == 'image':
        body = generation_record(skill, {**spec, 'created_at': now}, generation, refs, seed, width, height, record, draft, candidate, api)
        marker = re.search(r'^## 3\. 讨论与修改\s*$', text, re.M)
        if not marker:
            raise ValueError('图片工作稿不符合既有模板：' + spec['draft'])
        text = text[:marker.start()] + body.rstrip() + '\n\n' + text[marker.start():]
    for suffix, content in [('.workflow.json', canvas), ('.api.json', api), ('-上传映射.json', uploads), ('-成果取回映射.json', [dict(node_id=output_node, output_key='images', index=0, path=candidate.relative_to(root).as_posix(), response_name=prefix+'-取回响应.json')]), ('-图片收尾计划.json', plan)]:
        if content is not None:
            documents.new_json(record / (prefix + suffix), content)
    documents.put(draft, text)
    return dict(project=str(root), task_type=spec['task_type'], title=spec['title'], workflow=api, uploads=uploads, image_plan=plan,
        record_dir=str(record), outputs=[dict(node_id=output_node, output_key='images', index=0, path=str(candidate), response_name=prefix+'-取回响应.json')],
        attempt_name=prefix+'-提交尝试.json', request_name=prefix+'-请求.json', response_name=prefix+'-提交响应.json', history_name=prefix+'-执行结果.json')


def build_video(root, spec, documents):
    record = project_file(root, spec['record_dir'])
    canvas = json.loads(project_file(root, spec['canvas']).read_text('utf-8-sig'))
    mapping = deepcopy(spec.get('mapping'))
    if mapping is None:
        mapping = json.loads(documents.read(record / '输入映射.json'))
    unbound_mapping = deepcopy(mapping)
    unbound_mapping.setdefault('uploads', [])
    source_index = mapping.setdefault('uploads', [])
    for ref in spec.get('references', []):
        file = project_file(root, ref['file']).relative_to(root.resolve()).as_posix()
        matches = [item for item in source_index if item['input_path'] == ref['placeholder']]
        if any(project_file(root, item['file']) != project_file(root, file) for item in matches):
            raise ValueError('视频参考占位值对应不同源文件：' + ref['placeholder'])
        if not matches:
            source_index.append(dict(input_path=ref['placeholder'], file=file))
    if spec.get('sync_timing'):
        from backend.services.video_records import sync_timing
        sync_timing(canvas, mapping, spec['task_type'])
    stage = {'video-first-pass': '一采', 'video-second-pass': '二采', 'video-postprocess': '后处理'}[spec['task_type']]
    episode, scene = mapping['scene'].split('-')
    native = any(node['type'] == 'MiniMaxH3Director' for node in canvas['nodes'])
    selected = [mapping['segments'][index] for index in mapping['selected_indices']]
    for node in canvas['nodes']:
        if node['type'] not in ('SaveVideo', 'VHS_VideoCombine', 'SaveImage') or node.get('mode', 0) in (2, 4):
            continue
        if native:
            saved_stage = {504: '一采', 506: '二采'}.get(node['id'], stage)
            folder = '辅助预览'
            identity = f"{mapping['scene']}-{record.name}-{saved_stage}-辅助预览-节点{node['id']}"
        else:
            folder = stage
            identity = (selected[0]['segment'] + '-' + selected[0]['round'] if len(selected) == 1 else mapping['scene'] + '-' + record.name) + '-' + stage
        widget(canvas, node, filename_prefix=remote_prefix(root, '视频生成', episode, scene, folder, identity))
    api = pairs.Canvas(canvas).api(spec['output_nodes'])
    if spec.get('content_review'):
        if mapping.get('content_review'):
            raise ValueError('已有内容核对映射不自动覆盖；新核对请明确使用本次无绑定映射及注释')
        from h3_prompt_checks import bind_review
        mapping['content_review'] = bind_review(root, api, spec['content_review'])
    documents.new_json(record / '任务.workflow.json', canvas)
    documents.new_json(record / '任务.api.json', api)
    mapping_file = record / '输入映射.json'
    existing_mapping = documents.read(mapping_file)
    existing_unbound = json.loads(existing_mapping) if existing_mapping is not None else None
    if existing_unbound is not None:
        existing_unbound.setdefault('uploads', [])
    if existing_unbound == unbound_mapping:
        documents.put(mapping_file, json.dumps(mapping, ensure_ascii=False, indent=2))
    else:
        documents.new_json(mapping_file, mapping)
    outputs = spec.get('outputs', [])
    segment_plan = spec.get('segment_plan')
    if spec['task_type'] in ('video-first-pass', 'video-second-pass') and segment_plan is None:
        director = next(key for key, node in api.items() if node['class_type'] == 'MiniMaxH3Director')
        targets = []
        stage = {'video-first-pass': '一采', 'video-second-pass': '二采'}[spec['task_type']]
        for index in mapping['selected_indices']:
            entry = mapping['segments'][index]
            identity = f"{entry['segment']}-{entry['round']}-{stage}"
            targets.append(dict(index=index, path=f"09-剧集制作/{identity.split('-')[0]}/其他资料/候选视频/{identity}.mp4", response_name=f'最终取回-{index:03d}.json'))
        segment_plan = dict(director_node=director, report_node=str(spec['report_node']), output_root=spec['output_root'], targets=targets)
    if spec['task_type'] == 'video-postprocess' and not outputs:
        savers = [key for key,node in api.items() if node['class_type']=='VHS_VideoCombine' and node['inputs'].get('format')=='video/h264-mp4']
        if len(mapping['selected_indices']) != 1 or len(savers) != 1:
            raise ValueError('非标准单段MP4后处理须显式提供outputs，不猜测保存节点')
        entry = mapping['segments'][mapping['selected_indices'][0]]
        identity = entry['segment']+'-'+entry['round']+'-后处理'
        outputs = [dict(node_id=savers[0], output_key='gifs', index=0,
            path=f"09-剧集制作/{identity.split('-')[0]}/其他资料/候选视频/{identity}.mp4", response_name='最终取回-000.json')]
    uploads = list(spec.get('uploads', []))
    timelines = {key: json.loads(node['inputs']['timeline_data']) for key,node in api.items() if node['class_type']=='MiniMaxH3Director'}
    for ref in {item['placeholder']: item for item in spec.get('references', [])}.values():
        file = project_file(root, ref['file'])
        placeholder, matched = ref['placeholder'], False
        for key, node in api.items():
            for name, content in node['inputs'].items():
                slots = []
                if content == placeholder:
                    slots.append(None)
                elif node['class_type'] == 'MiniMaxH3Director' and name == 'timeline_data':
                    timeline = timelines[key]
                    for area, block in [(['global'], timeline['global']), *[(['segments', i], item) for i, item in enumerate(timeline['segments'])]]:
                        for array, field in [('refs', 'imageFile'), ('refVideos', 'videoFile'), ('refAudios', 'audioFile')]:
                            for index, item in enumerate(block.get(array, [])):
                                if item.get(field) == placeholder:
                                    slots.append(area + [array, index, field])
                for path in slots:
                    upload = dict(file=str(file), node=key, input=name, subfolder=record.name,
                                  **{'response-name': f'上传响应-{len(uploads)+1:03d}.json'})
                    if path is not None:
                        upload['json-path'] = path
                    uploads.append(upload)
                    matched = True
        if not matched:
            raise ValueError('视频参考未对应实际画布槽位：' + placeholder)
    from backend.services.comfy_tasks import SKILL
    from backend.services.video_records import prepare_records
    prepare_records(root, SKILL, spec, api, mapping, record, documents)
    return dict(project=str(root), task_type=spec['task_type'], title=spec['title'], workflow=api, record_dir=str(record),
        video_plan={'metadata': 'ffprobe'}, uploads=uploads, outputs=outputs, segment_plan=segment_plan, attempt_name='提交尝试.json',
        request_name='请求.json', response_name='提交响应.json', history_name='执行结果.json')


async def execute(store, payload):
    from backend.services.comfy_tasks import TaskInput, SKILL
    root = project_file(store.workspace / 'projects', payload.project)
    if root.parent != store.workspace / 'projects':
        raise ValueError('任务清单必须属于projects中的单个项目')
    plan_file = project_file(root, payload.plan_file)
    source = json.loads(plan_file.read_text('utf-8-sig'))
    if not source['tasks']:
        raise ValueError('任务清单不能为空')
    if payload.reprepare and not payload.prepare_only:
        raise ValueError('重新装配仅用于--prepare-only，不会直接入队')
    journal_file = plan_file.with_name(plan_file.stem + '-装配结果.json')
    journal = None
    documents = None
    if journal_file.exists():
        journal = json.loads(journal_file.read_text('utf-8-sig'))
        if journal['thread_id'] != payload.thread_id:
            raise ValueError('任务清单来源已改变，不能覆盖原装配记录')
        if payload.reprepare:
            if journal.get('accepted') or any(
                    row['input'].record_dir == str(project_file(root, task['record_dir']))
                    for row in store.rows.values() for task in [*journal['tasks'], *source['tasks']]):
                raise ValueError('任务已登记，不能重装原清单；请使用原任务ID接续')
            documents = Documents(root, journal['writes'])
            archive = deepcopy(journal)
            archive['preparation_reports'] = []
            for task in journal['tasks']:
                report = project_file(root, task['record_dir']) / '执行检查报告.json'
                if report.exists():
                    archive['preparation_reports'].append(dict(record_dir=task['record_dir'],
                        report=json.loads(report.read_text('utf-8-sig'))))
            index = 1
            while journal_file.with_name(f'{journal_file.stem}-准备归档-{index:03d}.json').exists():
                index += 1
            with journal_file.with_name(f'{journal_file.stem}-准备归档-{index:03d}.json').open('x', encoding='utf-8') as stream:
                json.dump(archive, stream, ensure_ascii=False, indent=2)
            journal = None
    elif payload.reprepare:
        raise ValueError('没有原装配记录，请先按常规入口准备')
    if journal is not None:
        if journal['source'] != source:
            before, after = deepcopy(journal['source']), deepcopy(source)
            for item in [*before['tasks'], *after['tasks']]:
                item.pop('authorization', None)
            if journal.get('accepted') or any(
                    row['input'].record_dir == str(project_file(root, task['record_dir']))
                    for row in store.rows.values() for task in journal['tasks']):
                raise ValueError('任务清单内容已改变，不能覆盖原装配记录')
            if before != after:
                raise ValueError('尚未登记的任务清单内容已改变；修正后使用--prepare-only --reprepare原地重新准备')
            replacements = [(old.get('draft'), old.get('authorization', '仅准备，尚未执行授权'), new.get('authorization', '仅准备，尚未执行授权'))
                            for old, new in zip(journal['source']['tasks'], source['tasks'])]
            for update in journal['writes']:
                revised = update['new']
                for draft, old, new in replacements:
                    if update['path'] == draft:
                        revised = revised.replace('- 生成／修改授权与计数：' + old + '；', '- 生成／修改授权与计数：' + new + '；')
                if revised != update['new']:
                    update['old'], update['new'] = update['new'], revised
            journal['source'] = source
            write_json(journal_file, journal)
        if len(journal.get('accepted', [])) == len(journal['tasks']):
            return dict(status='enqueued', tasks=journal['accepted'], reused=True, next_action='end-turn')
    else:
        documents = documents or Documents(root)
        tasks = []
        for entry in source['tasks']:
            if not payload.prepare_only and not entry.get('authorization'):
                raise ValueError('生成任务必须写明本次执行授权依据')
            spec = {**entry, 'authorization': entry.get('authorization', '仅准备，尚未执行授权'), 'submission_plan': str(plan_file)}
            task = build_image(root, SKILL, spec, documents, store.client.now()) if spec['task_type'].startswith('image') else build_video(root, spec, documents)
            tasks.append(task)
        image_count = sum(task['task_type'] == 'image' for task in tasks)
        for task in tasks:
            if task['task_type'] == 'image':
                task.update(image_batch_id=plan_file.relative_to(root).as_posix(), image_batch_size=image_count)
        journal = dict(source=source, thread_id=payload.thread_id, tasks=tasks, writes=documents.writes())
        write_json(journal_file, journal)
    if not payload.prepare_only and any(not entry.get('authorization') for entry in source['tasks']):
        raise ValueError('此清单仅准备，尚缺实际执行授权依据')
    accepted = journal.setdefault('accepted', [])
    while len(accepted) < len(journal['tasks']):
        task = journal['tasks'][len(accepted)]
        data = TaskInput(**task, url=store.remote_urls()[0], thread_id=payload.thread_id, desktop=payload.desktop,
                         start_paused=payload.start_paused, timeout=payload.timeout)
        store.resolve_input(data)
        if not any(row['input'].record_dir == data.record_dir for row in store.rows.values()):
            break
        result = await store.enqueue(data)
        accepted.append(dict(title=data.title, task_type=data.task_type, local_task_id=result['local_task_id'],
                             status=result['status'], record_dir=data.record_dir))
        write_json(journal_file, journal)
    if not journal.get('accepted'):
        publish(root, journal['writes'])
    prepared = []
    inputs = []
    for index, task in enumerate(journal['tasks']):
        data = TaskInput(**task, url=store.remote_urls()[0], thread_id=payload.thread_id, desktop=payload.desktop,
                         start_paused=payload.start_paused, timeout=payload.timeout)
        if index < len(accepted):
            continue
        store.resolve_input(data)
        if any(row['input'].record_dir == data.record_dir for row in store.rows.values()):
            raise ValueError('清单后项已被其他登记占用，请核对原任务，不自动补提')
        report = await store.prepare_only(data)
        prepared.append(dict(title=data.title, report=report['report']))
        inputs.append(data)
    if payload.prepare_only:
        return dict(status='prepared', tasks=prepared, next_action='review-content')
    for data in inputs:
        try:
            result = await store.enqueue(data)
        except (ValueError, OSError, store.client.ClientError) as error:
            return dict(status='partial' if accepted else 'failed', tasks=accepted, error=str(error), next_action='inspect-failure')
        accepted.append(dict(title=data.title, task_type=data.task_type, local_task_id=result['local_task_id'],
                             status=result['status'], record_dir=data.record_dir))
        write_json(journal_file, journal)
    return dict(status='enqueued', tasks=accepted, next_action='end-turn')
