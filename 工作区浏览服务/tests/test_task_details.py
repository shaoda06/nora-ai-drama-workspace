"""Read-only details, evidence-based outputs and safe project file links."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from backend import main
from backend.services.comfy_segments import SegmentPlan
from backend.services.task_details import task_detail
from tests import test_comfy_tasks as task_tests


class DetailTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = task_tests.TaskTests.asyncSetUp
    asyncTearDown = task_tests.TaskTests.asyncTearDown
    seed = task_tests.TaskTests.seed

    async def test_completed_transfer_times_outputs_and_merged_notification_are_read_only(self):
        self.seed('completed', 'acknowledged')
        output = Path(self.data.outputs[0].path)
        output.parent.mkdir()
        output.write_bytes(b'test media')
        self.store.save('task', enqueued_url='http://primary.invalid', ended_at='2026-10-11T00:00:00+08:00',
                        collected=1, notices=[{'desktop': 'private desktop'}])
        self.store.record('task', 'transfer', 'accepted', source_url='http://primary.invalid', target_url=self.data.url)
        self.store.record('task', 'director', 'progress', segment=1)
        self.store.record('task', 'download', 'success', path=str(output))
        self.store.record('task', 'collection', 'completed')
        self.store.record('task', 'notification', 'sent', notification_id='batch', message='private notification')
        self.store.db.execute('INSERT INTO notification_batches VALUES (?,?,?,?,?)',
                              ('batch', 'thread', json.dumps(['task', 'other']), 'private payload', 'acknowledged'))
        self.store.db.commit()
        before = self.store.db.total_changes
        with patch.object(self.store.client, 'download') as download, patch.object(self.store.client, 'submit') as submit:
            result = await task_detail(self.store, 'task')
        download.assert_not_called()
        submit.assert_not_called()
        self.assertEqual(before, self.store.db.total_changes)
        self.assertEqual(result['summary']['enqueued_url'], 'http://primary.invalid')
        self.assertEqual(result['summary']['ended_at'], '2026-10-11T00:00:00+08:00')
        self.assertEqual(result['summary']['collected_at'], result['events'][2]['time'])
        self.assertEqual([event['stage'] for event in result['events']], ['transfer', 'download', 'collection', 'notification'])
        self.assertEqual(result['outputs'][0]['status'], 'saved')
        self.assertEqual(result['outputs'][0]['bytes'], 10)
        self.assertIn('/files/', result['outputs'][0]['url'])
        self.assertEqual(result['notification_batches'][0]['task_count'], 2)
        serialized = json.dumps(result)
        for private in ('private-pipe', 'listener-id', 'private desktop', 'private payload', 'private notification', 'workflow'):
            self.assertNotIn(private, serialized)

    async def test_file_existence_does_not_prove_collection_and_missing_saved_output_is_explicit(self):
        self.seed('collection_failed')
        output = Path(self.data.outputs[0].path)
        output.parent.mkdir()
        output.write_bytes(b'unconfirmed')
        self.assertEqual((await task_detail(self.store, 'task'))['outputs'][0]['status'], 'pending')
        self.store.record('task', 'download', 'failed', path=str(output), error='HTTP 503')
        failed = (await task_detail(self.store, 'task'))['outputs'][0]
        self.assertEqual((failed['status'], failed['error']), ('failed', 'HTTP 503'))
        self.store.record('task', 'download', 'success', path=str(output))
        output.unlink()
        missing = (await task_detail(self.store, 'task'))['outputs'][0]
        self.assertEqual(missing['status'], 'missing')
        self.assertIsNone(missing['url'])

    async def test_director_success_and_missing_report_output_remain_separate(self):
        self.seed('collection_failed')
        self.data.task_type = 'video-first-pass'
        self.data.outputs = []
        self.data.segment_plan = SegmentPlan(director_node='1', report_node='2', output_root='/output', targets=[
            dict(index=index, path=str(self.project / f'{index}.mp4'), response_name=f'{index}.json') for index in (0, 1)])
        (self.record / '输入映射.json').write_text(json.dumps({'selected_indices': [0, 1], 'segments': [
            {'segment': f'EP001-C001-P00{index + 1}', 'round': 'R001', 'local_execution_dir': '执行附件'} for index in (0, 1)]}))
        first = self.project / '0.mp4'
        first.write_bytes(b'video')
        self.store.record('task', 'download', 'success', path=str(first))
        self.store.record('task', 'download', 'failed', identity='EP001-C001-P002-R001-一采', error='最终报告缺少该段的保存路径')
        outputs = (await task_detail(self.store, 'task'))['outputs']
        self.assertEqual([item['status'] for item in outputs], ['saved', 'failed'])
        self.assertEqual(outputs[1]['error'], '最终报告缺少该段的保存路径')
        # Older rows may retain only per-output state, without the event log or mapping file.
        self.store.db.execute('DELETE FROM task_events WHERE task_id=?', ('task',))
        (self.record / '输入映射.json').unlink()
        self.store.rows['task']['state']['segments'] = {
            '0': {'identity': 'EP001-C001-P001-R001-一采', 'path': str(first), 'check': '已取回'},
            '1': {'identity': 'EP001-C001-P002-R001-一采', 'check': '取回失败', 'error': '最终报告缺少该段的保存路径'}}
        outputs = (await task_detail(self.store, 'task'))['outputs']
        self.assertEqual([item['status'] for item in outputs], ['saved', 'failed'])
        self.assertEqual(outputs[1]['error'], '最终报告缺少该段的保存路径')

    async def test_outside_project_and_hidden_files_have_no_links(self):
        self.seed()
        for path in (self.root / 'outside.png', self.project / '.private.png'):
            path.write_bytes(b'private')
            self.data.outputs[0].path = str(path)
            self.store.record('task', 'download', 'success', path=str(path))
            result = (await task_detail(self.store, 'task'))['outputs'][0]
            self.assertIsNone(result['url'])
            self.assertIsNone(result['bytes'])

    async def test_legacy_without_events_does_not_invent_times_or_saved_evidence(self):
        self.seed('cancelled')
        result = await task_detail(self.store, 'task')
        self.assertEqual(result['events'], [])
        self.assertIsNone(result['summary']['collected_at'])
        self.assertIsNone(result['summary']['started_at'])
        self.assertEqual(result['outputs'][0]['status'], 'pending')

    async def test_http_missing_task_and_corrupt_mapping_are_distinct(self):
        api = FastAPI()
        api.add_api_route('/tasks/{key}', main.comfy_task_detail, methods=['GET'])
        api.state.comfy_tasks = self.store
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url='http://test') as client:
            self.assertEqual((await client.get('/tasks/missing')).status_code, 404)
            self.seed()
            self.data.segment_plan = SegmentPlan(director_node='1', report_node='2', output_root='/output')
            (self.record / '输入映射.json').write_text('{broken')
            response = await client.get('/tasks/task')
            self.assertEqual(response.status_code, 503)
            self.assertIn('任务详情读取失败', response.json()['detail'])


if __name__ == '__main__':
    unittest.main()
