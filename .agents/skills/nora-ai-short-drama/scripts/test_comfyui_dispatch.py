"""Agent enqueue preparation: no uploads or remote POST."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import comfyui_dispatch as d


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / "projects/test"
        self.root.mkdir(parents=True)
        (self.workspace / 'comfyui-config.json').write_text(json.dumps({'remote-urls':['http://main.invalid:8188','http://backup.invalid:8188']}))
        self.workflow = {'1':{'class_type':'SaveImage','inputs':{'seed':9223372036854775807}}}
        self.path = self.root / 'workflow.json'
        self.path.write_text(json.dumps(self.workflow))
        self.args = argparse.Namespace(project=str(self.root), workflow=str(self.path), task_type='image',
            output_plan='targets.json', task_title='CH001 · 首次生成', uploads=None, eligible_url=None,
            timeout=30, segment_plan=None, record_dir=str(self.root/'record'), monitor='browser', image_plan='image-plan.json')

    def test_only_backend_handoff_no_remote_upload_or_post(self):
        with patch.object(d.browser_tasks,'submit',return_value={'local_task_id':'uuid'}) as handoff, \
                patch.object(d.client,'submit') as post, patch.object(d.client,'upload') as upload:
            result=d.dispatch(self.args)
        self.assertEqual(result['dispatch_state'],'enqueued')
        handoff.assert_called_once_with(self.args,self.workflow,'http://main.invalid:8188',uploads=[])
        post.assert_not_called()
        upload.assert_not_called()

    def test_missing_title_is_not_replaced_by_directory_name(self):
        self.args.task_title=' '
        with patch.object(d.browser_tasks, 'submit', return_value={}) as handoff:
            d.dispatch(self.args)
        self.assertEqual(handoff.call_args.args[0].task_title, ' ')

    def test_h3_relationship_checks_are_delegated_to_preparation_not_repeated_in_cli(self):
        self.workflow['1']['class_type'] = 'MiniMaxH3ReferenceToVideo'
        self.path.write_text(json.dumps(self.workflow))
        for preparing in (True, False):
            self.args.prepare_only = preparing
            with self.subTest(preparing=preparing), \
                    patch.object(d.browser_tasks, 'submit', return_value={}) as handoff, \
                    patch.object(d.client, 'validate_workflow') as check:
                d.dispatch(self.args)
                handoff.assert_called_once()
                check.assert_not_called()

    def test_prepare_only_routes_to_tool_without_agent_validation_or_generation(self):
        self.args.prepare_only = True
        with patch.object(d.browser_tasks, 'submit', return_value={'prepared': True, 'report': '执行检查报告.json'}) as handoff, \
                patch.object(d.client, 'validate_workflow') as check, patch.object(d.client, 'submit') as post:
            result = d.dispatch(self.args)
        self.assertEqual(result['dispatch_state'], 'prepared')
        self.assertTrue(handoff.call_args.args[0].prepare_only)
        check.assert_not_called()
        post.assert_not_called()

    def test_prepare_rejects_missing_rtx_inputs_before_backend_handoff(self):
        self.args.prepare_only = True
        for field in ('strength', 'image_encoding'):
            with self.subTest(field=field):
                inputs = {'strength': 1.0, 'image_encoding': '8-bit RGB'}
                del inputs[field]
                self.path.write_text(json.dumps({'1': {'class_type': 'RTXVideoSuperResolution',
                                                       'inputs': inputs}}))
                with patch.object(d.browser_tasks, 'submit') as handoff, \
                        self.assertRaisesRegex(ValueError, field):
                    d.dispatch(self.args)
                handoff.assert_not_called()

    def test_prepared_enqueue_does_not_repeat_rtx_checks(self):
        self.args.prepare_only = False
        with patch.object(d, 'validate_rtx_inputs', side_effect=AssertionError('repeated check')), \
                patch.object(d.browser_tasks, 'submit', return_value={}) as handoff:
            d.dispatch(self.args)
        handoff.assert_called_once()

    def test_path_validation_is_owned_by_backend_boundary(self):
        self.args.record_dir = 'projects/' + self.root.name + '/执行附件/任务'
        with patch.object(d.browser_tasks, 'submit', return_value={}) as handoff:
            d.dispatch(self.args)
        self.assertEqual(handoff.call_args.args[0].record_dir, self.args.record_dir)

    def test_missing_output_plan_rejected_before_handoff(self):
        self.args.output_plan=None
        with self.assertRaises(ValueError): d.dispatch(self.args)

    def test_upload_mapping_is_passed_without_repeating_backend_checks(self):
        mapping=self.root/'uploads.json'
        mapping.write_text(json.dumps([{'file':'not-yet-present.png','node':'1','input':'image','subfolder':'','response-name':'upload.json'}]))
        self.args.uploads=str(mapping)
        with patch.object(d.browser_tasks,'submit',return_value={}) as handoff:
            d.dispatch(self.args)
        self.assertEqual(handoff.call_args.kwargs['uploads'][0]['file'], 'not-yet-present.png')

    def test_backup_cannot_be_selected(self):
        self.args.eligible_url='http://backup.invalid:8188'
        with self.assertRaises(ValueError): d.dispatch(self.args)

    def test_start_paused_is_explicit_and_keeps_primary_handoff(self):
        params = ['--project', str(self.root), '--task-type', 'image', '--workflow', str(self.path),
                  '--record-dir', str(self.root / 'record'), '--task-title', 'CH001 · 转移实测',
                  '--output-plan', 'targets.json', '--image-plan', 'image-plan.json']
        self.assertFalse(d.parser().parse_args(params).start_paused)
        args = d.parser().parse_args([*params, '--start-paused'])
        with patch.object(d.browser_tasks, 'submit', return_value={'status': 'paused'}) as handoff:
            result = d.dispatch(args)
        self.assertTrue(handoff.call_args.args[0].start_paused)
        self.assertEqual(handoff.call_args.args[2], 'http://main.invalid:8188')
        self.assertEqual(result['status'], 'paused')

    def test_nonempty_ordered_primary_and_legacy_config(self):
        self.assertEqual(d.load_config(self.root,30)['remote-urls'][0],'http://main.invalid:8188')
        (self.workspace/'comfyui-config.json').write_text(json.dumps({'remote-url':'http://main.invalid:8188'}))
        self.assertEqual(len(d.load_config(self.root,30)['remote-urls']),1)

    def test_task_list_is_one_handoff_without_manual_legacy_artifacts(self):
        args = d.parser().parse_args(['--project', str(self.root), '--plan', '任务清单.json'])
        with patch.object(d.browser_tasks, 'submit_plan', return_value={'status': 'enqueued', 'next_action': 'end-turn'}) as call, \
                patch.object(d.browser_tasks, 'submit', side_effect=AssertionError('no legacy handoff')), \
                patch.object(d.client, 'submit', side_effect=AssertionError('no remote')):
            result = d.dispatch(args)
        call.assert_called_once_with(args)
        self.assertEqual(result['next_action'], 'end-turn')

    def test_task_list_prepare_only_and_paused_flags_survive_handoff(self):
        args = d.parser().parse_args(['--project', str(self.root), '--plan', '任务清单.json', '--prepare-only', '--start-paused'])
        with patch.object(d.browser_tasks, 'submit_plan', return_value={'status': 'prepared'}) as call:
            d.dispatch(args)
        self.assertTrue(call.call_args.args[0].prepare_only)
        self.assertTrue(call.call_args.args[0].start_paused)


if __name__=='__main__': unittest.main()
