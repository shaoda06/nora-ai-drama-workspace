"""Video tasks own technical assembly, stream facts and ready-to-report delivery."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from backend import main
from backend.services import comfy_tasks as tasks, submission_plans, result_registration, video_records
from tests import test_submission_plans as plan_tests, test_submission_lifecycle as lifecycle, test_result_closeout as closeout
from tests.test_queue_recovery import serving
import h3_prompt_checks


class VideoExecutionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=plan_tests.SubmissionPlanTests.asyncSetUp
    asyncTearDown=plan_tests.SubmissionPlanTests.asyncTearDown
    rel=plan_tests.SubmissionPlanTests.rel
    write_plan=plan_tests.SubmissionPlanTests.write_plan
    video=lifecycle.LifecycleTests.video
    download=closeout.CloseoutTests.download

    def new_task(self,timing=False):
        self.video()
        mapping=json.loads((self.record/'输入映射.json').read_text())
        task=dict(task_type='video-first-pass',title='EP001-C001 · 一采',authorization='用户已批准本场正文并授权一采',
            record_dir=self.rel(self.record),canvas=self.rel(self.record/'task.workflow.json'),output_nodes=['403'],
            report_node='403',output_root='E:/Comfy/output',mapping=mapping,
            references=[dict(file='reference.png',placeholder='planned/ref.png')])
        if timing:
            review=mapping.pop('content_review')
            for row in review['groups']:
                row.pop('input_sha256');row.pop('node');row['chinese'].pop('sha256')
                for check in row['checks'].values():
                    for source in check['sources']:source.pop('sha256',None)
            self.record = self.record/'执行-20261020-000000'
            self.record.mkdir()
            for entry in mapping['segments']:
                entry['local_execution_dir'] = str(self.record)
            task.update(sync_timing=True,content_review=review,record_dir=self.rel(self.record))
            (self.record/'输入映射.json').write_text(json.dumps(mapping))
        return task

    async def test_new_video_builds_records_timing_and_evidence_without_manual_json_work(self):
        task=self.new_task(timing=True)
        source=(self.project/task['canvas']).read_bytes()
        self.write_plan(task);self.payload.prepare_only=True
        with patch.object(self.store,'enqueue',side_effect=AssertionError('pure preparation')),patch.object(video_records,'probe',side_effect=AssertionError('no output yet')):
            result=await submission_plans.execute(self.store,self.payload)
        self.assertEqual(result['status'],'prepared');self.assertFalse(self.store.rows)
        self.assertEqual((self.project/task['canvas']).read_bytes(),source)
        api=json.loads((self.record/'任务.api.json').read_text())
        timeline=json.loads(api['502']['inputs']['timeline_data'])
        self.assertEqual(timeline['segments'][0]['frameCount'],73)
        self.assertEqual(timeline['segments'][0]['length'],73)
        self.assertEqual(api['502']['inputs']['total_frames'],73)
        self.assertEqual(timeline['batchWorkspaces']['r2v']['segments'],timeline['segments'])
        mapping=json.loads((self.record/'输入映射.json').read_text())
        self.assertTrue(h3_prompt_checks.audit(self.project,api,mapping)['ok'])
        text=(self.project/'09-剧集制作/EP001/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md').read_text()
        self.assertIn('- 计算帧数：73',text);self.assertIn('- 请求秒数：3',text)
        self.assertIn('后台共同状态及任务ID',text)
        self.assertIn('- 实测时长及数值来源：待后台读取实际输出',text)
        self.assertNotIn('### 审阅-R001-一采-001',text)

    async def test_second_pass_never_recalculates_historical_timing(self):
        task=self.new_task();task.update(task_type='video-second-pass',sync_timing=True)
        self.write_plan(task);source=(self.project/task['canvas']).read_bytes()
        with self.assertRaisesRegex(ValueError,'保留原画布'):
            await submission_plans.execute(self.store,self.payload)
        self.assertEqual((self.project/task['canvas']).read_bytes(),source);self.assertFalse(self.store.rows)

    async def test_shared_evidence_read_once_and_stale_review_not_rebound(self):
        task=self.new_task();mapping=task['mapping']
        counts={self.project/'review-source.md':0,self.record/'review-document.md':0}
        read=Path.read_text
        def observed(path,*args,**kwargs):
            if path in counts:counts[path]+=1
            return read(path,*args,**kwargs)
        with patch.object(Path,'read_text',observed):
            result=h3_prompt_checks.audit(self.project,self.data.workflow,mapping)
        self.assertTrue(result['ok']);self.assertEqual(list(counts.values()),[1,1])
        with self.assertRaisesRegex(ValueError,'不自动重新绑定'):
            h3_prompt_checks.bind_review(self.project,self.data.workflow,mapping['content_review'])

    def setup_completed(self):
        result=closeout.CloseoutTests.setup_video(self)
        self.data.video_plan={'metadata':'ffprobe'}
        return result

    def measurement(self,path):
        state=path.stat()
        return dict(stamp=[state.st_size,state.st_mtime_ns],width=1536,height=864,frame_rate=24.,duration=3.,frames=72,
            codec='h264',video_mbps=3.,total_mbps=3.1,audio=[{'codec_type':'audio','codec_name':'aac'}],source='isolated ffprobe result')

    async def test_video_report_fields_ready_before_notice_and_cli_only_reports(self):
        from fastapi import FastAPI
        out,draft=self.setup_completed()
        with patch.object(video_records,'probe',side_effect=self.measurement) as measured:
            batch=await closeout.CloseoutTests.collect_and_notice(self,automatic=True)
            self.assertIn('- 实际尺寸及数值来源：1536×864',draft.read_text())
            self.assertIn('视频轨3.0Mbps；文件总3.1Mbps',draft.read_text())
            app=FastAPI();app.state.comfy_tasks=self.store
            app.add_api_route('/api/internal/comfy/notifications/{batch_id}/report',main.agent_result_report,methods=['POST'])
            cli=self.root/'.agents/skills/nora-ai-short-drama/scripts/browser_tasks.py'
            cli.parent.mkdir(parents=True);shutil.copyfile(tasks.SKILL/'scripts/browser_tasks.py',cli)
            async with serving(app) as url:
                config=self.root/'工作区浏览服务/runtime/task-service.json'
                config.parent.mkdir(parents=True,exist_ok=True);config.write_text(json.dumps({'url':url,'token':self.store.token}))
                with patch.object(result_registration,'register',side_effect=AssertionError('read must not register')):
                    process=await asyncio.create_subprocess_exec(sys.executable,'-B',str(cli),'report','--notification-id',batch,
                        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
                        env={**os.environ,'CODEX_THREAD_ID':self.data.thread_id})
                    stdout,stderr=await asyncio.wait_for(process.communicate(),15)
                    self.assertEqual(process.returncode,0,stderr.decode())
            measured.assert_called_once()
        report=json.loads(stdout);self.assertNotIn('tasks',report)
        self.assertEqual(report['delivery']['video_count'],1)
        entry=report['delivery']['tasks'][0]
        self.assertEqual(entry['videos'][0]['file'],str(out))
        self.assertEqual(entry['review_url'],url+self.store.read_report(batch,self.data.thread_id)['tasks'][0]['review_path'])
        self.assertEqual(entry['videos'][0]['metadata']['width'],1536)

    async def test_bad_media_fails_closeout_without_retrying_generation(self):
        self.setup_completed()
        with patch.object(tasks.client,'download',side_effect=self.download):
            await self.store.finish_collection('task',self.terminal)
        with patch.object(video_records,'probe',side_effect=ValueError('容器信息不可读取')),patch.object(tasks.client,'submit',side_effect=AssertionError('no generation')):
            report=await self.store.prepare_report(['task'])
        self.assertFalse(report['user_message_ready']);self.assertIn('容器信息不可读取',report['results'][0]['error'])
        self.assertEqual(self.store.rows['task']['state']['status'],'completed')

    async def test_ffprobe_reads_real_container_without_quality_analysis(self):
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):self.skipTest('ffmpeg/ffprobe not installed')
        output=self.project/'probe.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=64x48:r=24:d=0.5',
            '-c:v','libx264','-pix_fmt','yuv420p','-y',str(output)],check=True,capture_output=True)
        result=video_records.probe(output)
        self.assertEqual((result['width'],result['height']),(64,48));self.assertEqual(result['frame_rate'],24)
        self.assertAlmostEqual(result['duration'],.5,places=3);self.assertEqual(result['audio'],[])
        with patch.object(video_records.shutil,'which',return_value=None),self.assertRaisesRegex(FileNotFoundError,'ffprobe'):
            video_records.probe(output)


    async def test_measured_facts_survive_browser_retry_and_changed_file_stops_reuse(self):
        out,_=self.setup_completed()
        with patch.object(tasks.client,'download',side_effect=self.download):
            await self.store.finish_collection('task',self.terminal)
        with patch.object(video_records,'probe',side_effect=self.measurement) as measured:
            first=result_registration.register(self.store,'task')
            again=result_registration.register(self.store,'task')
            self.assertEqual(first['probes'],again['probes']);measured.assert_called_once()
            out.write_bytes(out.read_bytes()+b' changed')
            with self.assertRaisesRegex(ValueError,'不复用旧测量'):
                result_registration.register(self.store,'task')
            measured.assert_called_once()

    async def test_new_binding_does_not_invent_a_semantic_review_pass(self):
        task=self.new_task(timing=True)
        task['content_review']['groups'][0]['checks'].pop('identity')
        self.write_plan(task)
        with self.assertRaisesRegex(ValueError,'identity'):
            await submission_plans.execute(self.store,self.payload)
        self.assertFalse(self.store.rows)

    async def test_existing_stage_notes_are_not_overwritten_by_technical_assembly(self):
        task=self.new_task()
        draft=self.project/'09-剧集制作/EP001/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md'
        draft.parent.mkdir(parents=True,exist_ok=True)
        draft.write_text('# 分段\n## 2. 执行记录\n### R001-一采\n- 修订内容及依据：用户保留的说明\n- 实际种子：历史文字保持\n## 3. 讨论与修改\n')
        self.write_plan(task);await submission_plans.execute(self.store,self.payload)
        self.assertIn('用户保留的说明',draft.read_text());self.assertIn('历史文字保持',draft.read_text())

    async def test_standard_postprocess_derives_output_and_execution_fields(self):
        task=self.new_task()
        canvas=self.project/'后处理输入.workflow.json'
        canvas.write_bytes((tasks.SKILL/'references/comfyui-workflow/Nora-RTX-RIFE-自动切镜保护超分插帧.workflow.json').read_bytes())
        task.update(task_type='video-postprocess',canvas=self.rel(canvas),output_nodes=['16'],
            record_dir=self.rel(self.record.with_name('EP001-C001-P001-R001-后处理')))
        task.pop('references')
        task['mapping']['segments'][0]['source']='EP001-C001-P001-R001-二采'
        documents=submission_plans.Documents(self.project)
        result=submission_plans.build_video(self.project,task,documents)
        output=result['outputs'][0]
        self.assertEqual((output['node_id'],output['output_key']),('16','gifs'))
        self.assertTrue(output['path'].endswith('EP001-C001-P001-R001-后处理.mp4'))
        text=documents.read(self.project/'09-剧集制作/EP001/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md')
        self.assertIn('### R001-后处理',text)
        self.assertIn('后处理无采样种子',text)
        self.assertIn('来源身份：EP001-C001-P001-R001-二采',text)

    async def test_prepare_then_authorize_video_uses_one_authorization_source(self):
        task=self.new_task();task.pop('authorization')
        self.write_plan(task);self.payload.prepare_only=True
        await submission_plans.execute(self.store,self.payload)
        task['authorization']='用户看过准备结果后明确授权本次一采'
        self.write_plan(task);self.payload.prepare_only=False
        result=await submission_plans.execute(self.store,self.payload)
        self.assertEqual(result['status'],'enqueued')
        text=(self.project/'09-剧集制作/EP001/其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md').read_text()
        self.assertIn('原任务清单',text)
        self.assertNotIn('仅准备，尚未执行授权',text)
        self.assertEqual(json.loads(self.plan_file.read_text())['tasks'][0]['authorization'],task['authorization'])
