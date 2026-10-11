"""Migrate explicitly approved video identities without changing generation evidence.

Dry-run by default. Apply while the browser service is stopped so its in-memory
task state cannot overwrite migrated paths. Never contacts ComfyUI.
"""
import argparse
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sqlite3
from urllib.parse import unquote


IDENTITY = re.compile(r'EP\d{3,}-C\d{3,}-P\d{3,}-R\d{3,}-(?:一采|二采|后处理)')
MUTABLE_JSON = {'输入映射.json', '成果取回映射.json', '后台任务状态.json'}
INACTIVE = {'completed', 'failed', 'cancelled', 'unknown', 'needs_attention', 'paused'}
PHASES = {'first-pass': '一采', 'second-pass': '二采', 'postprocess': '后处理',
          'video-first-pass': '一采', 'video-second-pass': '二采', 'video-postprocess': '后处理'}


def slug(title):
    return re.sub(r'[^\w\s-]', '', title.lower()).replace(' ', '-')


def record_sections(text):
    return list(re.finditer(r'^### ([^\n]+)\n(.*?)(?=^### |^## |\Z)', text, re.M | re.S))


def section_stage(title, body):
    for stage in ('后处理', '二采', '一采'):
        if stage in title:
            return stage
    field = re.search(r'^- (?:处理阶段|被审处理阶段)：([^\n]+)', body, re.M)
    if field:
        for stage in ('后处理', '二采', '一采'):
            if field[1].startswith(stage):
                return stage
    outputs = IDENTITY.findall(body)
    return outputs[0].rsplit('-', 1)[1] if outputs else '一采'


class Migration:
    def __init__(self, project, request):
        self.project = Path(project).resolve()
        self.episode = request['episode']
        if not re.fullmatch(r'EP\d{3,}', self.episode):
            raise ValueError('episode 须为完整EP编号')
        self.root = self.project / '09-剧集制作' / self.episode
        self.rows = request['identities']
        self.identities = {}
        targets = set()
        for row in self.rows:
            old, new = row['old'], row['new']
            if not IDENTITY.fullmatch(old) or not IDENTITY.fullmatch(new):
                raise ValueError('身份格式不正确')
            if old.split('-')[:3] != new.split('-')[:3] or old.rsplit('-', 1)[1] != new.rsplit('-', 1)[1]:
                raise ValueError('迁移不能改变片段或处理阶段')
            if not old.startswith(self.episode + '-') or old in self.identities or new in targets:
                raise ValueError('重复身份或越出本集范围')
            self.identities[old] = new
            targets.add(new)
        self.anchors = {}
        for path in (self.root / '其他资料/工作稿').glob('*视频制作-工作稿.md'):
            segment = path.name.removesuffix('-视频制作-工作稿.md')
            for match in record_sections(path.read_text('utf-8-sig')):
                title, body = match[1], match[2]
                run = re.search(r'R\d{3,}', title)
                if not run or not (title.startswith('R') or title.startswith('审阅-R')):
                    continue
                stage = section_stage(title, body)
                old = segment + '-' + run[0] + '-' + stage
                if old not in self.identities:
                    raise ValueError('修订条目未包含在迁移请求中：' + old)
                new_run = self.identities[old].split('-')[3]
                if title.startswith('R'):
                    new_title = new_run + '-' + stage
                else:
                    tail = title[run.end():]
                    tail = re.sub(r'^-(一采|二采|后处理)', '', tail)
                    new_title = '审阅-' + new_run + '-' + stage + tail
                self.anchors[(path.name, slug(title))] = (slug(new_title), new_title)

    def replace(self, value):
        return IDENTITY.sub(lambda m: self.identities.get(m[0], m[0]), value)

    def run(self, segment, run, stage):
        mapped = self.identities.get(segment + '-' + run + '-' + stage)
        return mapped.split('-')[3] if mapped else run

    def json_value(self, value, stage=None):
        if isinstance(value, str):
            return self.replace(value)
        if isinstance(value, list):
            return [self.json_value(item, stage) for item in value]
        if isinstance(value, dict):
            phase = value.get('phase', stage)
            stage = PHASES.get(phase, phase)
            raw = {'filename_prefix', 'remote', 'remote_output', 'remote_output_path',
                   'request', 'response', 'workflow', 'workflow_api', 'notices',
                   'user_feedback', 'approval_basis', 'authority', 'source_approval',
                   'adoption_basis', 'file_flow'}
            result = {self.replace(key): item if key in raw else self.json_value(item, stage)
                      for key, item in value.items()}
            if 'segment' in value and value.get('round') is not None and stage in ('一采', '二采', '后处理'):
                old = value['segment'] + '-' + value['round'] + '-' + stage
                if old in self.identities:
                    result['round'] = self.identities[old].split('-')[3]
            return result
        return value

    def markdown(self, path, text):
        # Links use their target document's anchors, including common-task owners.
        def link(match):
            target = match[2]
            label = match[1]
            if '#' in target:
                file, fragment = target.split('#', 1)
                name = unquote(file).rsplit('/', 1)[-1] if file else path.name
                mapped = self.anchors.get((name, unquote(fragment)))
                if mapped:
                    target = file + '#' + mapped[0]
                    old_run = re.search(r'r\d{3,}', unquote(fragment), re.I)
                    new_run = re.search(r'r\d{3,}', mapped[0], re.I)
                    if old_run and new_run:
                        label = re.sub(old_run[0], new_run[0].upper(), label, flags=re.I)
            return '[' + label + '](' + target + ')'
        text = re.sub(r'\[([^\]]*)\]\(([^)]+)\)', link, text)
        segment = path.name.removesuffix('-视频制作-工作稿.md')
        # Keep the user's quoted feedback verbatim, including historical R names.
        originals = []
        def protect(match):
            originals.append(match[0])
            return f'@@USER_FEEDBACK_{len(originals)-1}@@'
        text = re.sub(r'^- (?:用户反馈原文|用户反馈|用户原话|人工批准原文)：[^\n]*', protect, text, flags=re.M)
        legacy = []
        chunks, cursor = [], 0
        for match in record_sections(text):
            title, body = match[1], match[2]
            mapped = self.anchors.get((path.name, slug(title)))
            chunks.append(text[cursor:match.start()])
            if mapped:
                stage = section_stage(title, body)
                old_run = re.search(r'R\d{3,}', title)[0]
                new_run = self.identities[segment + '-' + old_run + '-' + stage].split('-')[3]
                # Full identities and explicitly staged shorthand are unambiguous.
                if new_run != old_run:
                    # Bare R references in a stage's record refer to that record.
                    body = re.sub(r'(?<![A-Za-z0-9-])' + old_run + r'(?!\d|[- ]?(?:一采|二采|后处理))', new_run, body)
                if title.startswith('R'):
                    row = next(row for row in self.rows if row['old'] == segment + '-' + old_run + '-' + stage)
                    origin = self.identities.get(row.get('source'), row.get('source', '无上游视频阶段'))
                    legacy.append('- 阶段编号整理：原身份 `' + row['old'] + '`；当前身份 `' + row['new'] + '`；来源 `' + origin + '`。原提交证据与批准事实保留。')
                    body = f'@@MIGRATION_{len(legacy)-1}@@\n' + body
                legacy.append('### ' + mapped[1])
                chunks.append(f'@@MIGRATION_{len(legacy)-1}@@\n' + body)
            else:
                chunks.append(match[0])
            cursor = match.end()
        chunks.append(text[cursor:])
        result = self.replace(''.join(chunks))
        result = re.sub(r'(?<![A-Za-z0-9-])(R\d{3,})([- ]?)(一采|二采|后处理)',
                        lambda m: self.run(segment, m[1], m[3]) + m[2] + m[3], result)
        # Approved table has a bare R column, and each row supplies its stage.
        def adopted_row(match):
            stage = match[1]
            return re.sub(r'\| (R\d{3,}) \|', lambda m: '| ' + self.run(segment, m[1], stage) + ' |', match[0])
        if path.name.endswith('-视频制作-工作稿.md'):
            result = re.sub(r'^\| (一采|二采|后处理) \|[^\n]+', adopted_row, result, flags=re.M)
        for index, original in enumerate(originals):
            result = result.replace(f'@@USER_FEEDBACK_{index}@@', original)
        for index, original in enumerate(legacy):
            result = result.replace(f'@@MIGRATION_{index}@@', original)
        return result

    def plan(self):
        moves, edits = [], {}
        for path in sorted(self.root.rglob('*')):
            if '历史版本' in path.relative_to(self.root).parts:
                continue
            target = path.with_name(self.replace(path.name))
            if target != path:
                moves.append((path, target))
            if not path.is_file():
                continue
            if path.suffix == '.md' and '执行附件' not in path.relative_to(self.root).parts:
                original = path.read_text('utf-8-sig')
                updated = self.markdown(path, original)
            elif path.name in MUTABLE_JSON:
                original = path.read_text('utf-8-sig')
                data = json.loads(original)
                identity = IDENTITY.findall(str(path))
                stage = identity[-1].rsplit('-', 1)[1] if identity else None
                updated = json.dumps(self.json_value(data, stage), ensure_ascii=False, indent=2) + '\n'
            elif path.name.endswith('-视频修改意见.json'):
                original = path.read_text('utf-8-sig')
                data = json.loads(original)
                scene = data['scene']
                notes = {}
                for key, item in data['notes'].items():
                    old = f"{self.episode}-{scene}-{item['segment']}-{item['run']}-{item['stage']}"
                    new = self.identities.get(old, old).split('-')[3]
                    new_key = f"{item['segment']}/{item['stage']}/{new}"
                    if new_key in notes:
                        raise ValueError('备注身份冲突：' + new_key)
                    notes[new_key] = dict(item, run=new)
                data['notes'] = notes
                updated = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
            else:
                continue  # Requests, workflows, replies, receipts and media retain bytes.
            if updated != original:
                edits[path] = updated
        sources = {old for old, _ in moves}
        for old, new in moves:
            if new.exists() and new not in sources:
                raise ValueError('目标已存在，不覆盖：' + str(new))
        return moves, edits

    def task_rows(self, database):
        result = []
        with closing(sqlite3.connect(database)) as db:
            for task_id, payload, state in db.execute('SELECT id,payload,state FROM tasks'):
                data, status = json.loads(payload), json.loads(state)
                if data.get('project') != self.project.name or f'09-剧集制作/{self.episode}/' not in data.get('record_dir', '').replace('\\', '/'):
                    continue
                if status['status'] not in INACTIVE:
                    raise ValueError('仍有活动任务，先完成或暂停原任务：' + task_id)
                # Keep sent requests/workflow, remote evidence and notices intact.
                current_data = dict(data)
                stage = PHASES.get(data.get('task_type'))
                for field in ('title', 'record_dir', 'outputs', 'segment_plan'):
                    if field in data:
                        current_data[field] = self.json_value(data[field], stage)
                current_state = dict(status)
                for field in ('title', 'segments', 'saved_outputs'):
                    if field in status:
                        current_state[field] = self.json_value(status[field], stage)
                result.append((task_id, payload, state, json.dumps(current_data, ensure_ascii=False), json.dumps(current_state, ensure_ascii=False)))
        return result

    def apply(self, database, report):
        report = Path(report).resolve()
        if not report.is_relative_to(self.project / '99-综合资料/其他资料/历史版本'):
            raise ValueError('迁移记录须位于项目99-综合资料/其他资料/历史版本，避免被当作现行生成映射')
        if report.exists():
            raise ValueError('该迁移已经执行；按原报告核对，不重复执行')
        moves, edits = self.plan()
        rows = self.task_rows(database) if database else []
        report.parent.mkdir(parents=True, exist_ok=True)
        backup = report.parent / (report.stem + '-原记录')
        backup.mkdir()
        for path in edits:
            destination = backup / path.relative_to(self.project)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        ledger = {'episode': self.episode, 'at': datetime.now().astimezone().isoformat(),
                  'identities': self.rows, 'moves': [[str(a), self.replace(str(a))] for a, _ in moves],
                  'edited_files': [str(p) for p in edits],
                  'task_rows_before': [list(row[:3]) for row in rows], 'state': 'prepared'}
        report.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
        for path, text in edits.items():
            path.write_text(text, encoding='utf-8')
        # Children move first; simultaneous substitutions never cascade R001/R002.
        for depth in sorted({len(old.parts) for old, _ in moves}, reverse=True):
            group = [(old, new) for old, new in moves if len(old.parts) == depth]
            staged = []
            for old, new in group:
                temporary = old.with_name('.' + old.name + '.stage-numbering')
                if temporary.exists():
                    raise ValueError('上次迁移暂存仍在，按原报告恢复：' + str(temporary))
                old.rename(temporary)
                staged.append((temporary, new))
            for temporary, new in staged:
                temporary.rename(new)
        if database:
            with closing(sqlite3.connect(database)) as db, db:
                db.executemany('UPDATE tasks SET payload=?,state=? WHERE id=?',
                               [(row[3], row[4], row[0]) for row in rows])
        ledger['state'] = 'completed'
        report.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'state': 'completed', 'moves': len(moves), 'records': len(edits), 'tasks': len(rows), 'report': str(report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='项目根目录')
    parser.add_argument('--request', required=True, help='UTF-8 JSON：episode、identities[{old,new,source可选}]，须已获迁移授权')
    parser.add_argument('--database', help='停止服务后的comfy-tasks.sqlite；仅迁移本集非活动任务当前入口')
    parser.add_argument('--apply', action='store_true', help='执行迁移；默认只读预览')
    parser.add_argument('--report', help='执行时必填；项目99-综合资料/其他资料/历史版本下的JSON，附原记录备份')
    args = parser.parse_args()
    migration = Migration(args.project, json.loads(Path(args.request).read_text('utf-8-sig')))
    if args.apply:
        if not args.report:
            parser.error('--apply 需要 --report')
        result = migration.apply(args.database, args.report)
    else:
        moves, edits = migration.plan()
        rows = migration.task_rows(args.database) if args.database else []
        result = {'state': 'preview', 'moves': len(moves), 'records': len(edits), 'tasks': len(rows), 'identities': migration.rows}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
