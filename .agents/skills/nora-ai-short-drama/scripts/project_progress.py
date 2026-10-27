"""Read and replace existing project phase rows without adding execution history."""
import re


def row_pattern(name):
    label = (re.escape(name[:-2].rstrip()) + r'[ \t]*制作'
             if name.endswith('制作') else re.escape(name))
    return r'^\|[ \t]*' + label + r'[ \t]*\|[^\n]*'


def row(text, name):
    rows = list(re.finditer(row_pattern(name), text, re.M))
    if len(rows) != 1:
        raise ValueError('项目进度缺少唯一的' + name + '行')
    row = rows[0]
    cells = [cell.strip() for cell in row[0].strip().strip('|').split('|')]
    if len(cells) != 6:
        raise ValueError('项目进度阶段行须为六列：' + name)
    return row, cells


def phase_row(text, episode):
    return row(text, episode + '制作')


def update(text, episode, *, status, outputs, pending=(), next_steps=()):
    row, cells = phase_row(text, episode)
    cells[2:6] = [status, outputs,
                  '<br>'.join('- ' + item for item in pending) if pending else '- 无',
                  '<br>'.join('- ' + item for item in next_steps) if next_steps else '- 无']
    return text[:row.start()] + '| ' + ' | '.join(cells) + ' |' + text[row.end():]


def validate_update(before, after, episodes=(), *, phases=()):
    """External exact-text edits may change only the named existing phase rows."""
    if before == after:
        return
    original, updated = before, after
    changed = False
    for phase in {episode + '制作' for episode in episodes} | set(phases):
        pattern = row_pattern(phase)
        old_rows, new_rows = re.findall(pattern, before, re.M), re.findall(pattern, after, re.M)
        if old_rows == new_rows:
            continue
        row(before, phase)
        _, cells = row(after, phase)
        if cells[2] not in ('未开始', '进行中', '待确认', '已完成'):
            raise ValueError('项目进度使用了未规定的阶段状态：' + cells[2])
        original = re.sub(pattern, '', original, flags=re.M)
        updated = re.sub(pattern, '', updated, flags=re.M)
        changed = True
    if not changed or original != updated:
        raise ValueError('项目进度更新只允许修改本批对应阶段行，不得追加历史记录或修改其他内容')
