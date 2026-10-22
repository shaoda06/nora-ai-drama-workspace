import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from video_revision_migrate import Migration


class RevisionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / '项目'
        self.root = self.project / '09-剧集制作/EP001'
        self.first = 'EP001-C001-P001-R010-一采'
        self.second = 'EP001-C001-P001-R010-二采'
        self.post = 'EP001-C001-P001-R011-后处理'
        self.new_second = 'EP001-C001-P001-R001-二采'
        self.new_post = 'EP001-C001-P001-R002-后处理'
        self.request = {'episode': 'EP001', 'identities': [
            {'old': self.first, 'new': self.first},
            {'old': self.second, 'new': self.new_second, 'source': self.first},
            {'old': self.post, 'new': self.new_post, 'source': self.second}]}
        self.report = self.project / '99-综合资料/其他资料/历史版本/迁移.json'

    def write(self, key, data):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
        return path

    def test_sources_notes_approval_and_sent_evidence_remain_distinct(self):
        for identity in (self.first, self.second, self.post):
            stage = identity.rsplit('-', 1)[1]
            source = self.first if identity == self.second else self.second if identity == self.post else None
            context = {'identity': identity, **({'source': source} if source else {})}
            mapping = {'phase': stage, 'segments': [{'segment': 'EP001-C001-P001', 'round': identity.split('-')[3]}],
                       'generation_contexts': [context], 'actual_submissions_this_batch': 1,
                       'output': {'filename_prefix': identity}, 'adopted': identity == self.second}
            self.write('其他资料/执行附件/' + identity + '/输入映射.json', json.dumps(mapping, ensure_ascii=False))
            self.write('其他资料/执行附件/' + identity + '/请求.json', json.dumps({'prefix': identity}))
            self.write('其他资料/执行附件/' + identity + '/任务清单.json', json.dumps({'tasks': [
                {'task_type': {'一采':'video-first-pass','二采':'video-second-pass','后处理':'video-postprocess'}[stage],
                 'record_dir': '09-剧集制作/EP001/其他资料/执行附件/' + identity}]}))
            self.write('其他资料/候选视频/' + identity + '.mp4', (identity + 'actual bytes').encode())
        draft = self.write('其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md',
                           f'| 二采 | [{self.second}](../候选视频/{self.second}.mp4) | R010 | | [批准](#审阅-r010-二采-001) |\n'
                           f'### R010-一采\n- 处理阶段：一采\n### R010-二采\n- 处理阶段：二采\n- 来源：{self.first}\n'
                           f'### R011-后处理\n- 处理阶段：后处理\n- 来源：{self.second}\n'
                           '### 审阅-R010-二采-001\n- 用户反馈原文：R010二采通过。\n- 用户决定：采用\n')
        note = {'segment': 'P001', 'stage': '后处理', 'run': 'R011', 'text': 'R011请保留此原话',
                'updatedAt': '2026-10-11T10:00:00+08:00', 'fileRevision': '123-456'}
        self.write('其他资料/工作稿/EP001-C001-视频修改意见.json',
                   json.dumps({'episode': 'EP001', 'scene': 'C001', 'notes': {'P001/后处理/R011': note}}, ensure_ascii=False))
        dbpath = self.project / 'tasks.sqlite'
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
            db.execute('INSERT INTO tasks VALUES (?,?,?)', ('real-id', json.dumps({'project': '项目',
                'record_dir': '09-剧集制作/EP001/其他资料/执行附件/' + self.post,
                'outputs': [{'path': '09-剧集制作/EP001/其他资料/候选视频/' + self.post + '.mp4'}],
                'workflow': {'prefix': self.post}}), json.dumps({'status': 'completed', 'prompt_id': 'real-prompt',
                'collected': 1, 'saved_outputs': ['09-剧集制作/EP001/其他资料/候选视频/' + self.post + '.mp4']})))
        result = Migration(self.project, self.request).apply(dbpath, self.report)
        self.assertEqual(result['tasks'], 1)
        mapping = json.loads((self.root / ('其他资料/执行附件/' + self.new_post + '/输入映射.json')).read_text('utf-8'))
        self.assertEqual(mapping['generation_contexts'][0], {'identity': self.new_post, 'source': self.new_second})
        self.assertEqual(mapping['segments'][0]['round'], 'R002')
        self.assertEqual(mapping['identity_migration']['report'], self.report.relative_to(self.project).as_posix())
        index = json.loads((self.root / ('其他资料/执行附件/' + self.new_post + '/迁移后来源清单.json')).read_text('utf-8'))
        self.assertTrue(index['tasks'][0]['record_dir'].endswith(self.new_post))
        self.assertEqual(mapping['output']['filename_prefix'], self.post)
        self.assertEqual(mapping['actual_submissions_this_batch'], 1)
        self.assertFalse(mapping['adopted'])
        self.assertEqual((self.root / ('其他资料/执行附件/' + self.new_post + '/请求.json')).read_bytes(),
                         json.dumps({'prefix': self.post}).encode())
        self.assertEqual((self.root / ('其他资料/候选视频/' + self.new_post + '.mp4')).read_bytes(), (self.post + 'actual bytes').encode())
        text = draft.read_text('utf-8')
        self.assertIn('### R001-二采', text)
        self.assertIn('| R001 |', text)
        self.assertIn('#审阅-r001-二采-001', text)
        self.assertIn('用户反馈原文：R010二采通过。', text)
        self.assertIn('原身份 `' + self.post + '`', text)
        current_note = json.loads((self.root / '其他资料/工作稿/EP001-C001-视频修改意见.json').read_text('utf-8'))['notes']['P001/后处理/R002']
        self.assertEqual(current_note, dict(note, run='R002'))
        with closing(sqlite3.connect(dbpath)) as db:
            payload, state = map(json.loads, db.execute('SELECT payload,state FROM tasks').fetchone())
        self.assertIn(self.new_post, payload['record_dir'])
        self.assertEqual(payload['workflow']['prefix'], self.post)
        self.assertEqual(state['prompt_id'], 'real-prompt')
        self.assertEqual(state['status'], 'completed')
        with self.assertRaises(ValueError):
            Migration(self.project, self.request).apply(dbpath, self.report)

    def test_overlapping_old_and_new_names_do_not_cascade_or_overwrite(self):
        old1, old2 = 'EP001-C001-P001-R000-一采', 'EP001-C001-P001-R001-一采'
        new2 = 'EP001-C001-P001-R002-一采'
        self.write('其他资料/候选视频/' + old1 + '.mp4', b'first')
        self.write('其他资料/候选视频/' + old2 + '.mp4', b'second')
        self.write('其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md',
                   f'### R000\n- 处理阶段：一采\n- 结果：{old1}\n### R001\n- 处理阶段：一采\n- 结果：{old2}\n')
        request = {'episode': 'EP001', 'identities': [{'old': old1, 'new': old2}, {'old': old2, 'new': new2}]}
        Migration(self.project, request).apply(None, self.report)
        self.assertEqual((self.root / ('其他资料/候选视频/' + old2 + '.mp4')).read_bytes(), b'first')
        self.assertEqual((self.root / ('其他资料/候选视频/' + new2 + '.mp4')).read_bytes(), b'second')
        text = (self.root / '其他资料/工作稿/EP001-C001-P001-视频制作-工作稿.md').read_text('utf-8')
        self.assertIn('### R001-一采\n', text)
        self.assertIn('- 结果：' + old2, text)
        report = json.loads(self.report.read_text('utf-8'))
        self.assertEqual({Path(before).name: Path(after).name for before, after in report['moves']},
                         {old1 + '.mp4': old2 + '.mp4', old2 + '.mp4': new2 + '.mp4'})

    def test_live_tasks_and_cross_stage_remapping_are_rejected(self):
        bad = {'episode': 'EP001', 'identities': [{'old': self.second, 'new': self.first}]}
        with self.assertRaises(ValueError):
            Migration(self.project, bad)
        dbpath = self.project / 'tasks.sqlite'
        self.project.mkdir(parents=True)
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
            db.execute('INSERT INTO tasks VALUES (?,?,?)', ('live', json.dumps({'project': '项目',
                'record_dir': '09-剧集制作/EP001/其他资料/执行附件/' + self.post}), json.dumps({'status': 'running'})))
        with self.assertRaises(ValueError):
            Migration(self.project, self.request).task_rows(dbpath)

    def test_common_documents_do_not_infer_segment_from_filename(self):
        migration = Migration(self.project, self.request)
        text = 'R010二采；' + self.second
        result = migration.markdown(self.project / '项目进度.md', text)
        self.assertEqual(result, 'R010二采；' + self.new_second)
        self.assertEqual(migration.markdown(self.root / 'EP001-生成说明.md', text), result)

    def test_mapping_stage_from_execution_directory_and_english_phase(self):
        value = {'segments': [{'segment': 'EP001-C001-P001', 'round': 'R010', 'source': self.first},
                              {'segment': 'EP001-C001-P002', 'round': None, 'selected': False}]}
        path = self.write('其他资料/执行附件/' + self.second + '/输入映射.json', json.dumps(value))
        migration = Migration(self.project, self.request)
        _, edits = migration.plan()
        self.assertEqual(json.loads(edits[path])['segments'][0]['round'], 'R001')
        english = migration.json_value(dict(value, phase='second-pass'))
        self.assertEqual(english['segments'][0]['round'], 'R001')
        self.assertIsNone(english['segments'][1]['round'])


class ExecutionMigrationTests(unittest.TestCase):
    def test_split_repeat_preserves_original_approval_and_sent_evidence(self):
        from video_revision_migrate import ExecutionMigration
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / '项目'
            base = project / '09-剧集制作/片尾'
            old, new = '片尾-C001-P001-R003-一采', '片尾-C001-P001-R005-一采'
            record = base / '其他资料/执行附件' / old / '执行-20261023-061024'
            target = record.parent.parent / new
            record.mkdir(parents=True)
            original = record.parent / '输入映射.json'
            original.write_text(json.dumps({'adoptions': [{'identity': old}]}))
            video = base / '其他资料/候选视频' / (old + '.mp4')
            video.parent.mkdir(parents=True)
            video.write_bytes(b'original video bytes')
            new_video = video.with_name(new + '.mp4')
            frozen = b'{"identity":"old sent request"}'
            (record / '请求.json').write_bytes(frozen)
            (record / '最终取回-000.json').write_bytes(frozen)
            mapping = {'segments': [{'segment':'片尾-C001-P001','round':'R003','local_execution_dir':str(record.relative_to(project)),
                'materials_from':{'identity':old,'mapping':str(original.relative_to(project))}}], 'scene_modification_round':4,
                'generation_contexts':[{'identity':old,'prompts':{'english':str(record.parent.relative_to(project) / '模型提示词.txt')}}]}
            (record / '输入映射.json').write_text(json.dumps(mapping))
            payload = {'project':'项目','task_type':'video-first-pass','record_dir':str(record),'workflow':{'unchanged':'R003'},
                'segment_plan':{'targets':[{'index':0,'path':str(video)}]}}
            (record/'任务清单.json').write_text(json.dumps({'tasks':[payload]}))
            state = {'status':'completed','segments':{'0':{'identity':old,'path':str(video)}}}
            database = Path(temp) / 'tasks.sqlite'
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
                for key in ('repeat','unrelated'):
                    db.execute('INSERT INTO tasks VALUES(?,?,?)',(key,json.dumps(payload),json.dumps(state)))
            request = {'episode':'片尾','identities':[{'old':old,'new':new}], 'execution':{
                'record_dir':str(record.relative_to(project)),'new_record_dir':str(target.relative_to(project)),
                'source_output':str(video.relative_to(project)),'target_output':str(new_video.relative_to(project)),
                'task_id':'repeat','scene_modification_round':6}}
            migration = ExecutionMigration(project, request)
            report = project / '99-综合资料/其他资料/历史版本/重建重编号.json'
            migration.apply(database, report)
            self.assertEqual(new_video.read_bytes(), b'original video bytes')
            self.assertEqual((target/'请求.json').read_bytes(), frozen)
            self.assertEqual((target/'最终取回-000.json').read_bytes(), frozen)
            current=json.loads((target/'输入映射.json').read_text())
            self.assertEqual(current['segments'][0]['round'],'R005')
            self.assertEqual(current['generation_contexts'][0]['identity'],new)
            self.assertEqual(current['identity_migration']['report'],str(report.relative_to(project)))
            index=json.loads((target/'迁移后来源清单.json').read_text())
            self.assertEqual(index['tasks'][0]['record_dir'],str(target.relative_to(project)))
            self.assertEqual(current['segments'][0]['materials_from']['identity'],old)
            self.assertEqual(json.loads(original.read_text())['adoptions'][0]['identity'],old)
            with closing(sqlite3.connect(database)) as db:
                migrated=json.loads(db.execute('SELECT payload FROM tasks WHERE id="repeat"').fetchone()[0])
                untouched=json.loads(db.execute('SELECT payload FROM tasks WHERE id="unrelated"').fetchone()[0])
            self.assertEqual(migrated['record_dir'],str(target))
            self.assertEqual(migrated['workflow'],payload['workflow'])
            self.assertEqual(untouched,payload)
            with self.assertRaisesRegex(ValueError,'目标已存在|目录或实际视频缺失'):
                migration.plan()


if __name__ == '__main__':
    unittest.main()
