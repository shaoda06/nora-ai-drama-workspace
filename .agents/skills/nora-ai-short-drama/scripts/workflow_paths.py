"""Shared locations for bundled workflows; project task copies keep their own paths."""
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_GROUPS = (
    ('Qwen-image-2-1', 'formal'),
    ('Minimax-H3', 'formal'),
    ('后处理综合', 'formal'),
    ('非正式工作流', 'backup'),
)


def workflow_root(skill=SKILL_ROOT):
    return Path(skill) / 'references/comfyui-workflow'


def workflow_directories(root):
    return [(Path(root) / name, group) for name, group in WORKFLOW_GROUPS]


def workflow_file(name, kind='workflow', *, root=None):
    """Locate one formal baseline by name, without coupling callers to its category."""
    root = workflow_root() if root is None else Path(root)
    matches = [directory / f'{name}.{kind}.json'
               for directory, group in workflow_directories(root)
               if group == 'formal' and (directory / f'{name}.{kind}.json').is_file()]
    if len(matches) != 1:
        raise ValueError(f'正式工作流应有唯一文件，实际找到{len(matches)}份：{name}.{kind}.json')
    return matches[0]
