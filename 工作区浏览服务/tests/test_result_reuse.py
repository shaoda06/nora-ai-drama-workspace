"""The six post-completion reuse boundaries; isolated projects and fake transfers."""
import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from backend.services import comfy_tasks as t, comfy_segments as segments
from backend.services.collection_retry import saved_files
from backend.services.result_registration import closeout, register
from backend.services.result_summary import outputs, summary
from backend.parsers.project import SourceChangedError
from tests import test_result_closeout as closeout_tests


class ReuseTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = closeout_tests.CloseoutTests.asyncSetUp
    asyncTearDown = closeout_tests.CloseoutTests.asyncTearDown
    video = closeout_tests.CloseoutTests.video
    setup_video = closeout_tests.CloseoutTests.setup_video
    download = closeout_tests.CloseoutTests.download
    collect_and_notice = closeout_tests.CloseoutTests.collect_and_notice

    def test_metadata_observation_also_answers_receipt_existence(self):
        receipt, candidate = Mock(), Mock()
        receipt.stat.side_effect = FileNotFoundError()
        self.assertEqual(saved_files(receipt, candidate), (None, False))
        receipt.stat.assert_called_once(); candidate.stat.assert_not_called()
        receipt.stat.side_effect = None
        receipt.stat.return_value = Mock(st_mode=0o100644, st_size=4, st_mtime_ns=1)
        receipt.stat.reset_mock()
        candidate.stat.side_effect = FileNotFoundError()
        self.assertEqual(saved_files(receipt, candidate), (None, True))
        receipt.stat.assert_called_once(); candidate.stat.assert_called_once()

    async def test_native_receipt_never_repeats_exists_probe(self):
        self.setup_video()
        receipt = self.record / self.data.segment_plan.targets[0].response_name
        exists = Path.exists
        def observed(path):
            if path == receipt: raise AssertionError('redundant receipt exists probe')
            return exists(path)
        with patch.object(Path, 'exists', observed), patch.object(t.client, 'download', side_effect=self.download):
            await self.store.finish_collection('task', self.terminal)
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')
        with patch.object(Path, 'exists', observed), patch.object(t.client, 'download') as download:
            await self.store.finish_collection('task', self.terminal)
        download.assert_not_called()

    async def test_generic_receipt_never_repeats_exists_probe(self):
        from tests.test_comfy_tasks import TaskTests
        TaskTests.seed(self, status='running')
        result={'state':'success','files':[{'node_id':'1','output_key':'images','index':0,
                'file':{'filename':'result.png','subfolder':'','type':'output'}}]}
        receipt = self.record / self.data.outputs[0].response_name
        exists = Path.exists
        def observed(path):
            if path == receipt: raise AssertionError('redundant receipt exists probe')
            return exists(path)
        with patch.object(Path, 'exists', observed), patch.object(t.client, 'download', side_effect=self.download):
            await self.store.finish_collection('task', result)
        self.assertEqual(self.store.rows['task']['state']['status'], 'completed')

    async def test_background_handoff_initializes_collection_once(self):
        self.setup_video()
        with patch.object(self.store,'save',wraps=self.store.save) as save, \
                patch.object(t.client,'download',side_effect=self.download), patch.object(self.store,'queue_notice'):
            await self.store.reconcile_remote('task',self.terminal,background_collection=True)
            await self.store.workers['task']
        self.assertEqual(sum(call.kwargs.get('status')=='collecting' for call in save.call_args_list),1)
        self.assertEqual(self.store.rows['task']['state']['status'],'completed')

    async def test_ack_outputs_and_registration_share_fixed_entries_without_full_input(self):
        self.setup_video()
        batch=await self.collect_and_notice()
        read=Path.read_text
        def observed(path,*args,**kwargs):
            if path.name=='输入映射.json': raise AssertionError('fixed mapping must not be reread')
            return read(path,*args,**kwargs)
        self.store.acknowledge(batch,self.data.thread_id)
        self.store.rows['task'].pop('_result_outputs',None)
        converter=self.store.record_paths('task')
        with patch.object(self.store,'portable_input',side_effect=AssertionError('whole input traversal')), \
                patch.object(Path,'read_text',observed), patch.object(converter,'convert',wraps=converter.convert) as convert:
            first={'tasks':[summary(self.store,'task')]}
            stable=outputs(self.store,'task')
            again=self.store.acknowledge(batch,self.data.thread_id)
            self.assertIs(stable,outputs(self.store,'task'))
            self.assertEqual(sum(isinstance(call.args[0],list) for call in convert.call_args_list),1)
            first['tasks'][0]['outputs'][0]['identity']='external edit'
            self.assertNotEqual(again['tasks'][0]['outputs'][0]['identity'],'external edit')
            # register itself does not persist queue state or rebuild the summary.
            registered=register(self.store,'task')
            self.assertEqual(registered['status'],'registered')
            self.assertEqual(sum(isinstance(call.args[0],list) for call in convert.call_args_list),1)

    async def test_output_cache_invalidates_on_new_collected_entry(self):
        self.setup_video()
        await self.collect_and_notice()
        before=outputs(self.store,'task')
        self.store.rows['task']['state']['segments']['0']['bytes']+=1
        after=outputs(self.store,'task')
        self.assertIsNot(before,after)
        self.assertEqual(after[0]['bytes'],before[0]['bytes']+1)

    async def test_restart_rebuilds_summary_without_rechecking_fixed_mapping(self):
        self.setup_video()
        await self.collect_and_notice()
        summary(self.store,'task')
        await self.store.close()
        self.store=t.TaskStore(self.root/'runtime',self.root)
        read=Path.read_text
        def observed(path,*args,**kwargs):
            if path.name=='输入映射.json': raise AssertionError('fixed mapping reread after restart')
            return read(path,*args,**kwargs)
        with patch.object(Path,'read_text',observed):
            self.assertEqual(register(self.store,'task')['status'],'registered')

    async def test_deleted_candidate_after_ack_still_stops_registration(self):
        candidate,_=self.setup_video()
        batch=await self.collect_and_notice()
        self.store.acknowledge(batch,self.data.thread_id)
        candidate.unlink()
        with self.assertRaisesRegex(ValueError,'成果或取回凭据缺失'):
            register(self.store,'task')

    async def test_draft_reads_once_for_edit_and_once_at_final_replace(self):
        _,draft=self.setup_video()
        await self.collect_and_notice()
        read=Path.read_text
        observed=[]
        def current(path,*args,**kwargs):
            if path==draft: observed.append(path)
            return read(path,*args,**kwargs)
        with patch.object(Path,'read_text',current):
            register(self.store,'task')
        self.assertEqual(len(observed),2)

    async def test_edit_during_temporary_write_is_detected_at_final_replace(self):
        _,draft=self.setup_video()
        await self.collect_and_notice()
        read=Path.read_text
        reads=0
        def current(path,*args,**kwargs):
            nonlocal reads
            if path==draft:
                reads+=1
                if reads==2: path.write_text(read(path,'utf-8')+'\n用户刚刚修改。','utf-8')
            return read(path,*args,**kwargs)
        with patch.object(Path,'read_text',current):
            with self.assertRaisesRegex(ValueError,'源资料并发变化'):
                register(self.store,'task')
        self.assertEqual(reads,2)
        self.assertIn('用户刚刚修改。',draft.read_text('utf-8'))
        self.assertNotIn('- 决定：待审核',draft.read_text('utf-8'))
        self.assertEqual(list(draft.parent.glob('.nora-result-*')),[])

    async def test_cold_sync_uses_initial_snapshot_without_second_scan(self):
        self.setup_video()
        batch=await self.collect_and_notice()
        with patch.object(self.projects,'snapshot',wraps=self.projects.snapshot) as snapshot, \
                patch.object(self.projects,'scan',wraps=self.projects.scan) as scan:
            result=await closeout(self.store,self.projects,batch,self.data.thread_id)
        self.assertTrue(result['user_message_ready'],result)
        snapshot.assert_called_once();scan.assert_not_called()

    async def test_warm_sync_still_observes_changes_after_initial_load(self):
        self.setup_video()
        entry=self.projects.get(self.project.name)
        revision=entry['revision']
        batch=await self.collect_and_notice()
        with patch.object(self.projects,'snapshot',wraps=self.projects.snapshot) as snapshot, \
                patch.object(self.projects,'scan',wraps=self.projects.scan) as scan:
            result=await closeout(self.store,self.projects,batch,self.data.thread_id)
        self.assertTrue(result['user_message_ready'],result)
        snapshot.assert_called_once();scan.assert_called_once()
        self.assertGreater(entry['revision'],revision)

    async def test_concurrent_project_scan_returns_pending_then_resumes(self):
        self.setup_video()
        entry=self.projects.get(self.project.name)
        batch=await self.collect_and_notice()
        entry['scanning']=True
        with patch.object(self.projects,'scan',wraps=self.projects.scan) as scan:
            result=await closeout(self.store,self.projects,batch,self.data.thread_id)
        scan.assert_not_called()
        self.assertFalse(result['user_message_ready'])
        entry['scanning']=False
        result=await closeout(self.store,self.projects,batch,self.data.thread_id)
        self.assertTrue(result['user_message_ready'],result)

    async def test_source_change_during_cold_parse_is_not_approved_as_synced(self):
        self.setup_video()
        batch=await self.collect_and_notice()
        with patch('backend.services.projects.build_data',side_effect=SourceChangedError('source changed')):
            result=await closeout(self.store,self.projects,batch,self.data.thread_id)
        self.assertFalse(result['user_message_ready'])
        self.assertEqual(self.store.rows['task']['state']['closeout']['status'],'browser_pending')
        result=await closeout(self.store,self.projects,batch,self.data.thread_id)
        self.assertTrue(result['user_message_ready'],result)

    async def test_generic_video_uses_checked_report_identity_once_and_never_filename_alone(self):
        candidate,_=self.setup_video()
        await self.collect_and_notice()
        state=self.store.rows['task']['state']
        source=state['segments']['0']
        self.data.segment_plan=None
        state['result_items']=[{name:source[name] for name in ('path','receipt','bytes','remote')}]
        self.store.rows['task'].pop('_result_outputs',None)
        report=self.record/'执行检查报告.json'
        report.write_text(json.dumps({'ok':True,'prepared_input':{'mapping':{'selected_indices':[0],
            'segments':[{'segment':'EP001-C001-P001','round':'R001'}]}}}), 'utf-8')
        read=Path.read_text
        reads=[]
        def observed(path,*args,**kwargs):
            if path.name=='输入映射.json': raise AssertionError('fixed mapping must not be reread')
            if path==report: reads.append(path)
            return read(path,*args,**kwargs)
        with patch.object(Path,'read_text',observed):
            summary(self.store,'task')
            register(self.store,'task')
            self.assertEqual(len(reads),1)
            self.assertEqual(outputs(self.store,'task')[0]['identity'],candidate.stem)
            state['result_items'][0]['path']=str(candidate.with_name('EP001-C001-P999-R001-一采.mp4'))
            wrong=outputs(self.store,'task')[0]
            self.assertNotIn('review',wrong)
            self.assertEqual(len(reads),1)

    async def test_legacy_generic_video_fills_only_missing_identity_link_once(self):
        self.setup_video()
        await self.collect_and_notice()
        state=self.store.rows['task']['state']
        source=state['segments']['0']
        self.data.segment_plan=None
        state['result_items']=[{name:source[name] for name in ('path','receipt','bytes','remote')}]
        self.store.rows['task'].pop('_result_outputs',None)
        self.assertIn('review',outputs(self.store,'task')[0])
        with patch.object(Path,'read_text',side_effect=AssertionError('already recovered identity')):
            self.assertIn('review',outputs(self.store,'task')[0])
        self.store.rows['task'].pop('_review_identities',None)
        self.store.rows['task'].pop('_result_outputs',None)
        state['preparation_required']=True
        self.assertNotIn('review',outputs(self.store,'task')[0])

    async def test_missing_generic_identity_proof_can_be_repaired_without_restart(self):
        self.setup_video()
        await self.collect_and_notice()
        state=self.store.rows['task']['state']
        source=state['segments']['0']
        self.data.segment_plan=None
        state['result_items']=[{name:source[name] for name in ('path','receipt','bytes','remote')}]
        state['preparation_required']=True
        self.assertNotIn('review',outputs(self.store,'task')[0])
        report=self.record/'执行检查报告.json'
        report.write_text('[]','utf-8')
        self.assertNotIn('review',outputs(self.store,'task')[0])
        report.write_text(json.dumps({'ok':True,'prepared_input':{'mapping':{'selected_indices':[0],
            'segments':[{'segment':'EP001-C001-P001','round':'R001'}]}}}), 'utf-8')
        self.assertIn('review',outputs(self.store,'task')[0])
