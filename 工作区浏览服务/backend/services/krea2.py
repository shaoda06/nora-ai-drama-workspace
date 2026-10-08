import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'Krea2风格库'
spec = importlib.util.spec_from_file_location('workspace_krea_updater', ROOT / 'Krea2_更新工具/updater.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def state(can_manage: bool):
    data = updater.catalog()
    versions = updater.versions()
    result = {'app': 'nora-workspace-browser', 'canManage': can_manage,
              'job': updater.JOB.copy(), 'sources': {s: {
                  'status': updater.JOB.copy() if updater.JOB['source'] == s else updater.SOURCE_STATUS[s].copy(),
                  'local': versions.get(s), 'count': sum(x['library'] == lib for x in data['styles']),
                  'remote': updater.REMOTE.get(s),
                  'plan': {k: v for k, v in updater.PLANS.get(s, {}).items() if k != 'stage'},
                  'restore': (updater.WORK / ('previous-' + s)).exists(),
              } for s, lib in updater.SOURCES.items()}}
    if can_manage:
        result['token'] = updater.TOKEN
    return result
