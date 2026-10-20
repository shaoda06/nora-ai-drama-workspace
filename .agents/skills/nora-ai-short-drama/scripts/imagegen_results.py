"""Fixed native Imagegen preparation/closeout CLI. Does not generate or upscale images."""
import argparse
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(WORKSPACE / '工作区浏览服务'))

from project_paths import project_file
from backend.services import imagegen_results as native
from backend.services.execution_checks import write_json
from backend.services.projects import ProjectStore


def main():
    parser = argparse.ArgumentParser(description='主控准备Imagegen交接；子代理运行固定收尾；不调用生图或超分，不登记自动批准')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'complete', 'report', 'fail'):
        item = commands.add_parser(command)
        item.add_argument('--project', required=True, help='本机项目绝对目录；也可为独立测试项目')
        if command == 'prepare':
            item.add_argument('--request', required=True, help='项目内JSON请求，路径相对项目根；含完整prompt和实际授权')
        else:
            item.add_argument('--manifest', required=True, help='prepare返回的项目内Imagegen执行清单路径')
        if command == 'complete':
            item.add_argument('--source', required=True, help='内置Imagegen实际返回的本机原生PNG绝对路径；只复制，不改原图')
            item.add_argument('--actual-prompt-file', required=True, help='本次实际逐字提交的UTF-8提示词文件；与交接正文核对')
        if command == 'fail':
            item.add_argument('--error-file', required=True, help='实际错误的UTF-8文件；不自动重试或改换模型／能力')
    args = parser.parse_args()
    root = Path(args.project).resolve()
    if args.command == 'prepare':
        job = native.prepare(root, args.request)
        result = {name: job[name] for name in ('manifest', 'executor', 'generation', 'candidate', 'prompt_file', 'report')}
    else:
        job = json.loads(project_file(root, args.manifest).read_text('utf-8-sig'))
        if args.command == 'complete':
            actual = Path(args.actual_prompt_file).read_text('utf-8-sig')
            if actual != job['request']['prompt']:
                raise ValueError('实际提示词与交接不符，未保存或登记候选')
            receipt = project_file(root, str(Path(job['record']) / 'Imagegen实际调用结果.json'))
            content = dict(source=str(Path(args.source).resolve()), actual_prompt=actual,
                executor=job['executor'], provider='imagegen')
            if receipt.exists():
                if json.loads(receipt.read_text('utf-8-sig')) != content:
                    raise ValueError('实际调用凭据已存在不同内容，不覆盖')
            else:
                write_json(receipt, content)
            result = native.complete(root, args.manifest, receipt, ProjectStore(root.parent))
        elif args.command == 'fail':
            result = native.fail(root, args.manifest, Path(args.error_file).read_text('utf-8-sig'))
        else:
            result = json.loads(project_file(root, job['report']).read_text('utf-8-sig'))
        result = {name: result[name] for name in ('provider', 'status', 'user_message_ready', 'items', 'review_path', 'browser', 'error') if name in result}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
