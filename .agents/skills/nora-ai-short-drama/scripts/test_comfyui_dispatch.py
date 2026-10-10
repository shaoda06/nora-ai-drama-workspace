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
        self.root = Path(self.temp.name)
        (self.root / 'comfyui-config.json').write_text(json.dumps({'remote-urls':['http://main.invalid:8188','http://backup.invalid:8188']}))
        self.workflow = {'1':{'class_type':'SaveImage','inputs':{'seed':9223372036854775807}}}
        self.path = self.root / 'workflow.json'
        self.path.write_text(json.dumps(self.workflow))
        self.args = argparse.Namespace(project=str(self.root), workflow=str(self.path), task_type='image',
            output_plan='targets.json', task_title='CH001 · 首次生成', uploads=None, eligible_url=None,
            timeout=30, segment_plan=None, record_dir=str(self.root/'record'), monitor='browser')

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
        with self.assertRaises(ValueError): d.dispatch(self.args)

    def test_missing_output_plan_rejected_before_handoff(self):
        self.args.output_plan=None
        with self.assertRaises(ValueError): d.dispatch(self.args)

    def test_upload_paths_are_resolved_but_missing_files_checked_by_backend(self):
        mapping=self.root/'uploads.json'
        mapping.write_text(json.dumps([{'file':'not-yet-present.png','node':'1','input':'image','subfolder':'','response-name':'upload.json'}]))
        self.args.uploads=str(mapping)
        with patch.object(d.browser_tasks,'submit',return_value={}) as handoff:
            d.dispatch(self.args)
        self.assertTrue(Path(handoff.call_args.kwargs['uploads'][0]['file']).is_absolute())

    def test_backup_cannot_be_selected(self):
        self.args.eligible_url='http://backup.invalid:8188'
        with self.assertRaises(ValueError): d.dispatch(self.args)

    def test_start_paused_is_explicit_and_keeps_primary_handoff(self):
        params = ['--project', str(self.root), '--task-type', 'image', '--workflow', str(self.path),
                  '--record-dir', str(self.root / 'record'), '--task-title', 'CH001 · 转移实测',
                  '--output-plan', 'targets.json']
        self.assertFalse(d.parser().parse_args(params).start_paused)
        args = d.parser().parse_args([*params, '--start-paused'])
        with patch.object(d.browser_tasks, 'submit', return_value={'status': 'paused'}) as handoff:
            result = d.dispatch(args)
        self.assertTrue(handoff.call_args.args[0].start_paused)
        self.assertEqual(handoff.call_args.args[2], 'http://main.invalid:8188')
        self.assertEqual(result['status'], 'paused')

    def test_nonempty_ordered_primary_and_legacy_config(self):
        self.assertEqual(d.load_config(self.root,30)['remote-urls'][0],'http://main.invalid:8188')
        (self.root/'comfyui-config.json').write_text(json.dumps({'remote-url':'http://main.invalid:8188'}))
        self.assertEqual(len(d.load_config(self.root,30)['remote-urls']),1)


if __name__=='__main__': unittest.main()
