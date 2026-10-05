#!/usr/bin/env python3
"""Offline export entry; parsing is shared with the workspace browser service."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / '工作区浏览服务'))
from backend.parsers.project import *

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='Existing project root; writes only 项目总览.html')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.project), ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')
