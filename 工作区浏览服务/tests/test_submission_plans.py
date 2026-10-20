"""One task list -> automatic artifacts -> all checks -> durable UUIDs, without UI queries."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from backend import main
from backend.services import comfy_tasks as t, submission_plans as plans, image_closeout as image, result_registration
from tests import test_comfy_tasks as base, test_submission_lifecycle as life
from tests.test_image_closeout import png
from tests import test_image_closeout as image_tests


class SubmissionPlanTests(unittest.IsolatedAsyncioTestCase):
    request = image_tests.ImageCloseoutTests.request
    output = image_tests.ImageCloseoutTests.output

    async def asyncSetUp(self):
        await base.TaskTests.asyncSetUp(self)
        self.session = patch.object(self.store, 'read_session_name', AsyncMock())
        self.session.start()
        self.position = self.project / '00-项目定位/项目基本定位.md'
        self.position.parent.mkdir()
        self.position.write_text('# 定位\n### 七类图片默认种子\n\n| 图片类型 | 默认种子 | 来源图片及生成记录 |\n| --- | --- | --- |\n' + ''.join(f'| {name} | {100+i} | 已确认来源 |\n' for i, name in enumerate(plans.SEEDS.values())))
        self.plan_file = self.project / '03-人物资料/其他资料/执行附件/测试批次/任务清单.json'
        self.plan_file.parent.mkdir(parents=True)
        self.payload = main.SubmissionPlanInput(project=self.project.name, plan_file=self.rel(self.plan_file),
            thread_id=self.data.thread_id, desktop=self.data.desktop)

    async def asyncTearDown(self):
        self.session.stop()
        await base.TaskTests.asyncTearDown(self)

    def rel(self, path):
        return path.relative_to(self.project).as_posix()

    def spec(self, who='CH001'):
        return dict(task_type='image', object=who, title=who + ' · 角色六视图', kind='人物', image_type='角色多视角参考图',
            state='大学', costume='首集', authorization='用户明确要求男女主各生成一张穿衣六视图',
            draft=f'03-人物资料/其他资料/工作稿/{who}-参考图-工作稿.md',
            prompt=dict(rewritten_prompt='风格要求：真人摄影感。\n画面要求：同一人物六视图。\n人物描述：按当前确认的衣装。', wh_ratio='1:1', ratio_follow=''))

    def write_plan(self, *tasks):
        self.plan_file.write_text(json.dumps(dict(tasks=tasks), ensure_ascii=False))

    async def test_batch_builds_both_pairs_and_records_before_one_queue_handoff(self):
        self.write_plan(self.spec(), self.spec('CH002'))
        events = []
        prepare, enqueue = self.store.prepare_only, self.store.enqueue
        async def checked(data):
            events.append('prepare:' + data.title)
            return await prepare(data)
        async def accepted(data):
            events.append('enqueue:' + data.title)
            return await enqueue(data)
        with patch.object(self.store, 'prepare_only', side_effect=checked), patch.object(self.store, 'enqueue', side_effect=accepted), \
                patch.object(t.client.Client, 'json', side_effect=AssertionError('no remote request')), \
                patch('backend.services.projects.ProjectStore.get', side_effect=AssertionError('no web scan')):
            result = await plans.execute(self.store, self.payload)
        self.assertEqual([e.split(':')[0] for e in events], ['prepare','prepare','enqueue','enqueue'])
        self.assertEqual(result['next_action'], 'end-turn')
        self.assertEqual(len(result['tasks']), 2)
        for row in self.store.rows.values():
            data = row['input']
            self.assertEqual(data.image_batch_id, self.rel(self.plan_file))
            self.assertEqual(data.image_batch_size, 2)
            self.assertEqual(data.workflow['514']['inputs']['width'], 2048)
            self.assertEqual(data.workflow['515']['inputs']['seed'], 103)
            record = Path(data.record_dir)
            self.assertFalse((record / (record.name+'.workflow.json')).exists())
            body = (self.project / data.image_plan['draft']).read_text()
            self.assertIn('### 生成记录-001', body)
            self.assertIn('- 用户采用状态：未送审', body)
            self.assertIn('后台任务状态.json', body)
            self.assertNotIn('### 审阅-生成记录-001-001', body)

    async def test_repeat_plan_reuses_uuid_without_rebuilding_or_rechecking(self):
        self.write_plan(self.spec())
        first = await plans.execute(self.store, self.payload)
        with patch.object(plans, 'build_image', side_effect=AssertionError('no rebuild')), \
                patch.object(self.store, 'prepare_only', side_effect=AssertionError('no recheck')):
            again = await plans.execute(self.store, self.payload)
        self.assertTrue(again['reused'])
        self.assertEqual(first['tasks'], again['tasks'])
        self.assertEqual(len(self.store.rows), 1)

    async def test_prepare_only_never_enqueues_or_queries_remote(self):
        self.write_plan(self.spec())
        self.payload.prepare_only = True
        with patch.object(self.store, 'enqueue', side_effect=AssertionError('must not enqueue')):
            result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'prepared')
        self.assertFalse(self.store.rows)
        self.payload.prepare_only = False
        result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'enqueued')
        self.assertEqual(len(self.store.rows), 1)

    def test_text_to_image_uses_api_without_reading_or_rewriting_canvas(self):
        source = plans.workflow_file('Qwen2.1-文生图-普通版')
        original = source.read_bytes()
        for width, height, ratio in [(1024, 1024, '1:1'), (1152, 864, '4:3'),
                                     (1376, 768, '43:24'), (1536, 864, '16:9'), (1536, 1024, '3:2')]:
            with self.subTest(size=(width, height)), patch.object(plans.pairs, 'Canvas', side_effect=AssertionError('文生图不读取画布')):
                spec = dict(task_type='image', prompt=dict(rewritten_prompt='已确认的完整正文', wh_ratio=ratio))
                canvas, api, uploads, output = plans.image_workflow(t.SKILL, spec, [], width, height, 2**53-1,
                    'CH001-生成记录-001', '测试项目/图片生成/人物/CH001/CH001-肖像-生成记录-001')
            self.assertIsNone(canvas)
            self.assertEqual(uploads, [])
            self.assertEqual(output, '508')
            self.assertEqual((api['514']['inputs']['width'], api['514']['inputs']['height']), (width, height))
            self.assertEqual(api['515']['inputs']['seed'], 2**53-1)
            self.assertEqual(api['515']['inputs']['steps'], 40)
            self.assertEqual(api['672']['inputs']['value'], '已确认的完整正文')
            self.assertEqual(api['653']['inputs']['step_cache'], 'te_predictor')
            self.assertFalse({'512', '524', '583', '663'} & set(api))
        self.assertEqual(source.read_bytes(), original)

    async def test_remote_image_folder_does_not_change_local_evidence_names(self):
        self.write_plan(self.spec())
        self.payload.prepare_only = True
        await plans.execute(self.store, self.payload)
        api_file = next(self.project.rglob('CH001-生成记录-001.api.json'))
        workflow = json.loads(api_file.read_text())
        self.assertEqual(workflow['508']['inputs']['filename_prefix'],
            '测试项目/图片生成/人物/CH001/CH001-角色多视角参考图-生成记录-001')
        self.assertEqual(api_file.parent.name, 'CH001-生成记录-001')
        self.assertFalse(api_file.with_name('CH001-生成记录-001.workflow.json').exists())

    def test_remote_video_outputs_leave_director_segment_export_and_cache_unchanged(self):
        life.LifecycleTests.video(self)
        source = self.record / 'task.workflow.json'
        raw = source.read_bytes()
        original = plans.pairs.Canvas(json.loads(raw)).api(['403', '504', '506'])
        mapping = json.loads((self.record / '输入映射.json').read_text())
        task = dict(task_type='video-first-pass', title='目录测试', record_dir=self.rel(self.record / '新任务'),
            canvas=self.rel(source), mapping=mapping, output_nodes=['403', '504', '506'], segment_plan={})
        with patch('backend.services.video_records.prepare_records'):
            result = plans.build_video(self.project, task, plans.Documents(self.project))
        api = result['workflow']
        for key in ('504', '506'):
            self.assertTrue(api[key]['inputs']['filename_prefix'].startswith('测试项目/视频生成/EP001/C001/辅助预览/'))
        for field in ('cache_name', 'timeline_data'):
            self.assertEqual(api['502']['inputs'][field], original['502']['inputs'][field])
        self.assertEqual(source.read_bytes(), raw)

    def test_remote_video_postprocess_folder_uses_existing_segment_and_round(self):
        source = self.project / 'post.workflow.json'
        source.write_bytes(plans.workflow_file('Nora-RTX-RIFE-自动切镜保护超分插帧').read_bytes())
        mapping = dict(scene='EP001-C001', selected_indices=[0],
            segments=[dict(segment='EP001-C001-P002', round='R003')])
        task = dict(task_type='video-postprocess', title='后处理', record_dir='执行附件/后处理测试',
            canvas='post.workflow.json', mapping=mapping, output_nodes=['16'])
        with patch('backend.services.video_records.prepare_records'):
            result = plans.build_video(self.project, task, plans.Documents(self.project))
        self.assertEqual(result['workflow']['16']['inputs']['filename_prefix'],
            '测试项目/视频生成/EP001/C001/后处理/EP001-C001-P002-R003-后处理')

    async def test_missing_authorization_stops_before_writes_or_queue(self):
        task = self.spec()
        task.pop('authorization')
        self.write_plan(task)
        with self.assertRaisesRegex(ValueError, '授权'):
            await plans.execute(self.store, self.payload)
        self.assertFalse(self.store.rows)
        self.assertFalse((self.project / task['draft']).exists())

    async def test_second_preparation_failure_never_enqueues_first(self):
        self.write_plan(self.spec(), self.spec('CH002'))
        original, calls = self.store.prepare_only, []
        async def checked(data):
            calls.append(1)
            if len(calls) == 2:
                raise ValueError('second task invalid')
            return await original(data)
        with patch.object(self.store, 'prepare_only', side_effect=checked), self.assertRaisesRegex(ValueError, 'second task'):
            await plans.execute(self.store, self.payload)
        self.assertFalse(self.store.rows)

    async def test_partial_registration_returns_existing_ids_and_resume_does_not_duplicate(self):
        self.write_plan(self.spec(), self.spec('CH002'))
        enqueue, calls = self.store.enqueue, []
        async def fail(data):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('disk temporarily unavailable')
            return await enqueue(data)
        with patch.object(self.store, 'enqueue', side_effect=fail):
            result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['tasks']), 1)
        first = result['tasks'][0]['local_task_id']
        result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'enqueued')
        self.assertEqual(result['tasks'][0]['local_task_id'], first)
        self.assertEqual(len(self.store.rows), 2)

    async def test_concurrent_source_edit_is_preserved(self):
        self.write_plan(self.spec())
        publish = plans.publish
        def conflicting(root, writes):
            target = next(w for w in writes if w['path'].endswith('参考图-工作稿.md'))
            path = root / target['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('用户正在修改的正文')
            return publish(root, writes)
        with patch.object(plans, 'publish', side_effect=conflicting), self.assertRaisesRegex(ValueError, '不覆盖'):
            await plans.execute(self.store, self.payload)
        self.assertFalse(self.store.rows)
        self.assertEqual((self.project / self.spec()['draft']).read_text(), '用户正在修改的正文')

    async def test_approved_reference_automatically_builds_upload_and_input_record(self):
        source = self.project / 'source.png'
        source.write_bytes(png())
        refdraft = self.project / '批准工作稿.md'
        refdraft.write_text('### 生成记录-001\n- 种子、步数、CFG、采样器及调度器：987、25、1\n'
            '### 审阅-生成记录-001-001\n#### 4. 用户确认\n- 结论：批准采用\n- 批准的具体候选：[原图](source.png)\n#### 5. 采用\n')
        task = self.spec()
        task['references'] = [dict(file='source.png', purpose='人物本体身份', approval='批准工作稿.md#审阅-生成记录-001-001')]
        self.write_plan(task)
        result = await plans.execute(self.store, self.payload)
        data = self.store.rows[result['tasks'][0]['local_task_id']]['input']
        self.assertEqual(data.uploads[0]['node'], '475')
        self.assertEqual(data.workflow['497']['inputs']['images.image_1'], ['532',0])
        self.assertEqual(data.workflow['481']['inputs']['seed'], 103)
        self.assertFalse(list(Path(data.record_dir).glob('*.workflow.json')))
        self.assertNotIn('images.image_2', data.workflow['497']['inputs'])
        text = (self.project / task['draft']).read_text()
        self.assertIn('原始种子：987', text)
        self.assertIn('人物本体身份', text)

    async def test_unknown_input_seed_requires_existing_user_decision(self):
        source = self.project / '用户参考.png'
        source.write_bytes(png())
        task = self.spec()
        task['references'] = [dict(file='用户参考.png', user_reference=True, purpose='用户指定衣装', basis='本次用户指定')]
        self.write_plan(task)
        with self.assertRaisesRegex(ValueError, '来源种子未知'):
            await plans.execute(self.store, self.payload)
        task['references'][0]['unknown_seed_basis'] = '用户已明确按未知记录继续'
        self.write_plan(task)
        result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'enqueued')

    async def test_new_category_seed_registered_once_for_same_batch(self):
        self.position.write_text(self.position.read_text().replace('| 角色六视图 | 103 |','| 角色六视图 | 首次生成时确定 |'))
        self.write_plan(self.spec(), self.spec('CH002'))
        await plans.execute(self.store, self.payload)
        seeds = [row['input'].workflow['515']['inputs']['seed'] for row in self.store.rows.values()]
        self.assertEqual(seeds[0], seeds[1])
        self.assertIn(str(seeds[0]), self.position.read_text())

    def test_image_edit_dimensions_seeds_and_order_use_api_only(self):
        for width, height, ratio in [(1024, 1024, '1:1'), (2048, 2048, '1:1'),
                                     (1152, 864, '4:3'), (1376, 768, '43:24'),
                                     (1536, 864, '16:9'), (1536, 1024, '3:2')]:
            for count in (1, 3, 10):
                with self.subTest(size=(width, height), references=count), patch.object(plans.pairs, 'Canvas', side_effect=AssertionError('图生图不读取画布')):
                    refs = [dict(file=Path(str(n)+'.png')) for n in range(count)]
                    spec = self.spec()
                    spec['prompt']['wh_ratio'] = ratio
                    canvas, api, uploads, output = plans.image_workflow(t.SKILL, spec, refs,
                        width, height, 2**53-1, 'many', '测试项目/图片生成/人物/CH001/本次候选')
                self.assertIsNone(canvas)
                self.assertEqual(output, '487')
                self.assertEqual(len(uploads), count)
                self.assertEqual((api['479']['inputs']['width'], api['479']['inputs']['height']), (width, height))
                self.assertEqual(api['481']['inputs']['seed'], 2**53-1)
                self.assertEqual(api['481']['inputs']['steps'], 40)
                self.assertEqual(api['680']['inputs']['value'], spec['prompt']['rewritten_prompt'])
                self.assertEqual(api['487']['inputs']['images'], ['480', 0])
                self.assertEqual(api['487']['inputs']['filename_prefix'], '测试项目/图片生成/人物/CH001/本次候选')
                self.assertEqual(len([k for k in api['497']['inputs'] if k.startswith('images.image_')]), count)
                for index, upload in enumerate(uploads):
                    scale = api[api['497']['inputs'][f'images.image_{index+1}'][0]]['inputs']
                    self.assertEqual(scale['image'], [upload['node'], 0])
                    self.assertEqual((scale['megapixels'], scale['resolution_steps']), (1.5, 32))
                    self.assertEqual(api[upload['node']]['inputs']['image'], refs[index]['file'].name)
                self.assertFalse({'13', '502', '530', '565', '569', '661', '671', '672', '673', '674'} & set(api))

    def test_image_edit_rejects_fixed_parameter_override_and_excess_references(self):
        refs = [dict(file=Path('input.png'))]
        for field in ('steps', 'seed', 'resolution', 'megapixels', 'batch_size'):
            spec = self.spec()
            spec['parameters'] = {field: 1}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '固定配置'):
                plans.image_workflow(t.SKILL, spec, refs, 2048, 2048, 103, 'one')
        with self.assertRaisesRegex(ValueError, '10图'):
            plans.image_workflow(t.SKILL, self.spec(), refs * 11, 2048, 2048, 103, 'many')

    async def test_video_uses_preconfigured_canvas_and_same_one_call_checks(self):
        # Reuse the canonical isolated H3 fixture, including content review and scene-round dependencies.
        life.LifecycleTests.video(self)
        canvas = self.record / 'task.workflow.json'
        task = dict(task_type='video-first-pass', title='EP001-C001 · 一采', authorization='用户已授权一采',
            record_dir=self.rel(self.record), canvas=self.rel(canvas), output_nodes=['403'],
            mapping=json.loads((self.record/'输入映射.json').read_text()), report_node='403', output_root='E:/Comfy/output',
            references=[dict(file='reference.png', placeholder='planned/ref.png')])
        task['mapping'].pop('uploads')
        self.write_plan(task)
        result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'enqueued')
        data = next(iter(self.store.rows.values()))['input']
        self.assertEqual(data.segment_plan.targets[0].index, 0)
        self.assertEqual(data.uploads[0]['json-path'], ['global','refs',0,'imageFile'])
        mapping = json.loads((self.record/'输入映射.json').read_text())
        self.assertEqual(mapping['uploads'], [dict(input_path='planned/ref.png', file='reference.png')])
        timeline = json.loads(data.workflow['502']['inputs']['timeline_data'])
        self.assertEqual(timeline['global']['refs'][0]['imageFile'], 'planned/ref.png')

    def test_shared_reference_binds_each_slot_once(self):
        life.LifecycleTests.video(self)
        canvas_file = self.record/'task.workflow.json'
        canvas = json.loads(canvas_file.read_text())
        director = next(node for node in canvas['nodes'] if node['type'] == 'MiniMaxH3Director')
        timeline = json.loads(director['widgets_values_named']['timeline_data'])
        timeline['segments'][0]['refs'] = deepcopy(timeline['global']['refs'])
        timeline['batchWorkspaces']['r2v']['segments'] = deepcopy(timeline['segments'])
        plans.widget(canvas, director, timeline_data=json.dumps(timeline))
        canvas_file.write_text(json.dumps(canvas))
        task = dict(task_type='video-first-pass', title='测试', authorization='仅离线测试', record_dir=self.rel(self.record), canvas=self.rel(canvas_file),
            mapping=json.loads((self.record/'输入映射.json').read_text()), output_nodes=['403'],
            report_node='403', output_root='E:/Comfy/output',
            references=[dict(file='reference.png', placeholder='planned/ref.png')]*2)
        documents = plans.Documents(self.project.resolve())
        data = plans.build_video(self.project.resolve(), task, documents)
        self.assertEqual(len(data['uploads']), 2)
        self.assertEqual({tuple(item['json-path']) for item in data['uploads']},
            {('global','refs',0,'imageFile'), ('segments',0,'refs',0,'imageFile')})
        self.assertEqual(json.loads(documents.read(self.record/'输入映射.json'))['uploads'],
            [dict(input_path='planned/ref.png', file='reference.png')])

    def test_video_rejects_conflicting_reference_sources_before_writes(self):
        life.LifecycleTests.video(self)
        mapping = json.loads((self.record/'输入映射.json').read_text())
        mapping['uploads'] = [dict(input_path='planned/ref.png', file='different.png')]
        documents = plans.Documents(self.project)
        task = dict(record_dir=self.rel(self.record), canvas=self.rel(self.record/'task.workflow.json'),
            mapping=mapping, references=[dict(file='reference.png', placeholder='planned/ref.png')])
        with self.assertRaisesRegex(ValueError, '不同源文件'):
            plans.build_video(self.project, task, documents)
        self.assertEqual(documents.writes(), [])

    def test_widget_updates_object_and_list_storage_without_losing_preview(self):
        for stored in ({'filename_prefix': 'old', 'videopreview': {'hidden': True}}, ['old']):
            node = dict(id=264, type='VHS_VideoCombine', inputs=[],
                widgets_values_named={'filename_prefix': 'old'}, widgets_values=deepcopy(stored))
            canvas = dict(nodes=[node], links=[])
            plans.widget(canvas, node, filename_prefix='new-test')
            self.assertEqual(node['widgets_values_named']['filename_prefix'], 'new-test')
            if isinstance(stored, dict):
                self.assertEqual(node['widgets_values']['filename_prefix'], 'new-test')
                self.assertEqual(node['widgets_values']['videopreview'], {'hidden': True})
            else:
                self.assertEqual(node['widgets_values'], ['new-test'])
            plans.pairs.Canvas(canvas)

    async def test_reprepare_corrects_failed_plan_in_place_and_preserves_failure(self):
        task = self.spec()
        self.write_plan(task)
        self.payload.prepare_only = True
        with patch.object(self.store, 'prepare_only', side_effect=ValueError('实际准备失败')):
            with self.assertRaisesRegex(ValueError, '实际准备失败'):
                await plans.execute(self.store, self.payload)
        journal_file = self.plan_file.with_name('任务清单-装配结果.json')
        original = json.loads(journal_file.read_text())
        task['prompt']['rewritten_prompt'] += '\n衣装的银色刺绣清晰可见。'
        self.write_plan(task)
        with self.assertRaisesRegex(ValueError, '--reprepare'):
            await plans.execute(self.store, self.payload)
        self.payload.reprepare = True
        with patch.object(self.store, 'enqueue', side_effect=AssertionError('no enqueue')), \
                patch.object(t.client.Client, 'json', side_effect=AssertionError('no remote')):
            result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'prepared')
        saved = json.loads(journal_file.read_text())
        self.assertEqual(saved['tasks'][0]['record_dir'], original['tasks'][0]['record_dir'])
        archive = json.loads(self.plan_file.with_name('任务清单-装配结果-准备归档-001.json').read_text())
        self.assertEqual(archive['source'], original['source'])
        draft = (self.project/task['draft']).read_text()
        self.assertIn('银色刺绣', draft)
        self.assertNotIn('### 生成记录-002', draft)
        task['prompt']['rewritten_prompt'] += '\n衣领完整。'
        self.write_plan(task)
        await plans.execute(self.store, self.payload)
        draft = (self.project/task['draft']).read_text()
        self.assertIn('衣领完整', draft)
        self.assertNotIn('### 生成记录-002', draft)
        self.payload.reprepare = self.payload.prepare_only = False
        result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'enqueued')
        self.assertEqual(len(self.store.rows), 1)

    async def test_reprepare_rejects_registered_tasks_even_if_journal_id_is_missing(self):
        self.write_plan(self.spec())
        await plans.execute(self.store, self.payload)
        journal_file = self.plan_file.with_name('任务清单-装配结果.json')
        journal = json.loads(journal_file.read_text())
        journal['accepted'] = []
        journal_file.write_text(json.dumps(journal))
        self.payload.reprepare = self.payload.prepare_only = True
        with self.assertRaisesRegex(ValueError, '已登记'):
            await plans.execute(self.store, self.payload)
        self.assertEqual(len(self.store.rows), 1)
        self.assertFalse(list(self.plan_file.parent.glob('*准备归档*')))

    async def test_reprepare_build_failure_preserves_original_and_archives_report(self):
        task = self.spec()
        self.write_plan(task)
        self.payload.prepare_only = True
        await plans.execute(self.store, self.payload)
        journal_file = self.plan_file.with_name('任务清单-装配结果.json')
        original = journal_file.read_bytes()
        record = Path(json.loads(original)['tasks'][0]['record_dir'])
        report = json.loads((record/'执行检查报告.json').read_text())
        draft = (self.project/task['draft']).read_bytes()
        task['prompt']['rewritten_prompt'] += '\n银色刺绣。'
        self.write_plan(task)
        self.payload.reprepare = True
        with patch.object(plans, 'build_image', side_effect=ValueError('装配未完成')):
            with self.assertRaisesRegex(ValueError, '装配未完成'):
                await plans.execute(self.store, self.payload)
        self.assertEqual(journal_file.read_bytes(), original)
        self.assertEqual((self.project/task['draft']).read_bytes(), draft)
        archive = json.loads(self.plan_file.with_name('任务清单-装配结果-准备归档-001.json').read_text())
        self.assertEqual(archive['preparation_reports'][0]['report'], report)
        self.assertFalse(self.store.rows)
        result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'prepared')
        self.assertNotIn('### 生成记录-002', (self.project/task['draft']).read_text())

    async def test_reprepare_preserves_concurrent_edits(self):
        task = self.spec()
        self.write_plan(task)
        self.payload.prepare_only = True
        await plans.execute(self.store, self.payload)
        draft = self.project/task['draft']
        draft.write_text('其他会话正在修改')
        self.payload.reprepare = True
        with self.assertRaisesRegex(ValueError, '资料已变化'):
            await plans.execute(self.store, self.payload)
        self.assertEqual(draft.read_text(), '其他会话正在修改')

    async def test_reprepare_cannot_enqueue(self):
        self.write_plan(self.spec())
        self.payload.reprepare = True
        with self.assertRaisesRegex(ValueError, '仅用于--prepare-only'):
            await plans.execute(self.store, self.payload)
        self.assertFalse(self.store.rows)

    async def test_prepare_then_add_only_authorization_and_enqueue(self):
        task = self.spec()
        task.pop('authorization')
        self.write_plan(task)
        self.payload.prepare_only = True
        await plans.execute(self.store, self.payload)
        task['authorization'] = '准备结果展示后用户批准生成'
        self.write_plan(task)
        self.payload.prepare_only = False
        result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['status'], 'enqueued')
        self.assertIn(task['authorization'], (self.project/task['draft']).read_text())
        self.assertNotIn('仅准备，尚未执行授权', (self.project/task['draft']).read_text())

    async def test_accepted_uuid_recovers_if_journal_write_was_interrupted(self):
        self.write_plan(self.spec())
        first = await plans.execute(self.store, self.payload)
        journal = self.plan_file.with_name('任务清单-装配结果.json')
        saved = json.loads(journal.read_text())
        saved['accepted'] = []
        journal.write_text(json.dumps(saved))
        with patch.object(self.store, 'prepare_only', side_effect=AssertionError('accepted task must not be rechecked')):
            result = await plans.execute(self.store, self.payload)
        self.assertEqual(result['tasks'], first['tasks'])
        self.assertEqual(len(self.store.rows), 1)

    async def test_upscale_builds_formal_adoption_and_closes_bound_upload(self):
        source = image_tests.ImageCloseoutTests.setup_image(self)
        result_registration.register(self.store, 'task')
        text = self.draft.read_text()
        review = image.section(text, '审阅-生成记录-001-001')[0]
        approved = image.fields(review, {'结论': '批准采用', '批准的具体候选': image.link(self.draft, source), '确认时间与依据': '用户同意这版'})
        self.draft.write_text(text.replace(review, approved))
        formal = self.project / '03-人物资料/CH001-男主/参考图/CH001-日常-服装参考图.png'
        task = dict(task_type='image-upscale', object='CH001', title='CH001 · 服装批准后2倍超分', kind='人物',
            draft=self.rel(self.draft), authorization='原图已批准，按固定流程2倍超分', formal=self.rel(formal),
            adoption_fields={'适用范围': '第一集'}, references=[dict(file=self.rel(source), purpose='获批原图',
            approval=self.rel(self.draft)+'#审阅-生成记录-001-001')])
        self.write_plan(task)
        result = await plans.execute(self.store, self.payload)
        key = result['tasks'][0]['local_task_id']
        data = self.store.rows[key]['input']
        self.assertEqual(data.image_plan['upscale']['record_updates'][0]['path'], self.rel(self.draft))
        self.assertIn('| 服装参考图 | 大学 | 日常 | {{file}} | v01／超分-001 | 第一集 |',
                      data.image_plan['upscale']['record_updates'][0]['new'])
        # Actual upload binds the saved API and canvas; input TaskInput retains its planned placeholder.
        import hashlib
        record = Path(data.record_dir)
        uploaded = 'actual/source.png'
        receipt = {'data': {'input_path': uploaded, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}}
        (record/data.uploads[0]['response-name']).write_text(json.dumps(receipt))
        workflow = deepcopy(data.workflow)
        workflow['2']['inputs']['image'] = uploaded
        from backend.services.director_uploads import save_uploaded_workflow
        save_uploaded_workflow(data.project, record, data.workflow, workflow, {}, [(data.uploads[0], receipt['data'])])
        self.assertEqual(json.loads(next(record.glob('*.api.json')).read_text())['2']['inputs']['image'], uploaded)
        saved_canvas = json.loads(next(record.glob('*.workflow.json')).read_text())
        image_loader = next(node for node in saved_canvas['nodes'] if node['id'] == 2)
        self.assertEqual(image_loader['widgets_values_named']['image'], uploaded)
        (record/data.request_name).write_text(json.dumps({'prompt': workflow, 'client_id': 'listener-id'}))
        self.store.save(key, status='completed', prompt_id='upscale-prompt', client_id='listener-id', collected=1)
        self.data, self.record = data, record
        out = Path(data.outputs[0].path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png(8, 6))
        remote = dict(filename='result.png', subfolder='batch', type='output')
        receiptfile = record / data.outputs[0].response_name
        receiptfile.write_text(json.dumps({'data': dict(path=self.rel(out), bytes=out.stat().st_size,
            sha256=hashlib.sha256(out.read_bytes()).hexdigest(), remote=remote)}))
        self.store.save(key, result_items=[dict(path=str(out), receipt=str(receiptfile), bytes=out.stat().st_size, remote=remote)])
        report = await self.store.prepare_report([key])
        self.assertTrue(report['user_message_ready'], report)
        self.assertEqual(formal.read_bytes(), out.read_bytes())
        self.assertIn('### 超分-001', self.draft.read_text())

    async def test_http_route_returns_ids_and_rejects_browser_or_bad_token(self):
        from fastapi import FastAPI
        import httpx
        app = FastAPI()
        app.state.comfy_tasks = self.store
        app.add_api_route('/submit-plan', main.agent_submit_plan, methods=['POST'])
        self.write_plan(self.spec(), self.spec('CH002'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as http:
            body = self.payload.model_dump()
            self.assertEqual((await http.post('/submit-plan', json=body)).status_code, 403)
            browser = await http.post('/submit-plan', json=body,
                headers={'x-nora-task-token': self.store.token, 'origin': 'http://localhost'})
            self.assertEqual(browser.status_code, 403)
            result = await http.post('/submit-plan', json=body, headers={'x-nora-task-token': self.store.token})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['next_action'], 'end-turn')
        self.assertEqual(len(result.json()['tasks']), 2)

    async def test_pending_same_asset_versions_are_reserved_before_generation_returns(self):
        self.write_plan(self.spec(), self.spec())
        result = await plans.execute(self.store, self.payload)
        paths = [self.store.rows[item['local_task_id']]['input'].outputs[0].path for item in result['tasks']]
        self.assertTrue(paths[0].endswith('-v01.png'), paths)
        self.assertTrue(paths[1].endswith('-v02.png'), paths)
        self.assertEqual(len(self.store.rows), 2)

    async def test_actual_api_parameters_and_shared_input_metadata_are_tool_owned(self):
        source = self.project / '用户参考.png'
        source.write_bytes(png())
        task = self.spec()
        task['parameters'] = {'negative_prompt': '本次明确的反向条件'}
        task['references'] = [dict(file='用户参考.png', user_reference=True, source_kind='非生成', purpose='已指定衣装', basis='用户指定非生成素材')]
        other = deepcopy(task)
        other.update(object='CH002', title='CH002 · 首集角色六视图', draft=self.spec('CH002')['draft'])
        self.write_plan(task, other)
        with patch.object(image, 'png', wraps=image.png) as decoded, patch.object(plans.pairs, 'validate_rtx_inputs', wraps=plans.pairs.validate_rtx_inputs) as rtx:
            result = await plans.execute(self.store, self.payload)
        self.assertEqual(decoded.call_count, 1)  # Same input in this batch, not two decodes.
        self.assertEqual(rtx.call_count, 2)  # One common preparation check per task, none in assembly.
        for entry in result['tasks']:
            data = self.store.rows[entry['local_task_id']]['input']
            text = (self.project/data.image_plan['draft']).read_text()
            self.assertIn('103、40、1、euler、simple', text)
            self.assertIn('- 实际反向提示词：本次明确的反向条件', text)
            self.assertIn('每张参考图lanczos缩放至1.5MP', text)
            self.assertIn('原始图生图画布仅保存在技能工作流目录', text)
            self.assertIn('qwen_image_2.1_int8_convrot.safetensors', text)
            self.assertIn('缓存device=auto、dtype=default', text)
            self.assertNotIn('- 模型及工作流：不适用', text)

    async def test_common_preparation_rejects_bad_rtx_before_any_enqueue(self):
        self.data.workflow = {'1': {'class_type':'RTXVideoSuperResolution', 'inputs':{}}}
        with self.assertRaisesRegex(ValueError, 'strength'):
            await self.store.prepare_only(self.data)
        self.assertFalse(self.store.rows)
