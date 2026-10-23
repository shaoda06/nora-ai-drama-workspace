"""Create project or episode directories and register projects in the shared index."""
import argparse
import json
from pathlib import Path
import re
import sys

from project_paths import project_file
from project_index import INDEX_NAME, register_project


PROJECT_DIRECTORIES = (
    "00-项目定位", "01-主旨与简介", "02-故事大纲", "03-人物资料",
    "04-场景资料", "05-道具资料", "06-分集大纲", "07-参考音频",
    "08-参考视频", "09-剧集制作", "98-发布成片", "99-综合资料",
)
GENERAL_DIRECTORIES = (
    "其他资料", "其他资料/跨阶段资料", "其他资料/原稿",
    "其他资料/待分类资料", "其他资料/实验资料", "其他资料/工作稿",
    "其他资料/工作稿/素材", "其他资料/历史版本", "其他资料/执行附件",
)
EPISODE_DIRECTORIES = (
    "01-制作前检查", "02-剧集剧本", "03-分镜脚本",
    "04-专用素材", "05-视频提示词",
)


def initialize(project, episode=None, *, cover=False, intro=False, outro=False):
    if episode is not None and (cover or intro or outro):
        raise ValueError("配套选择参数只用于项目初始化，不能与--episode同时使用。")
    project = Path(project).expanduser().resolve()
    if episode is None:
        directories = (".", *PROJECT_DIRECTORIES,
                       *("99-综合资料/" + item for item in GENERAL_DIRECTORIES))
        if cover:
            directories += ("10-封面资料",)
        for unit, selected in (("片头", intro), ("片尾", outro)):
            if selected:
                root = "09-剧集制作/" + unit
                directories += (root, *(root + "/" + item for item in EPISODE_DIRECTORIES))
    else:
        if not re.fullmatch(r"(?:EP[0-9]{3}|片头|片尾)", episode) or episode == "EP000":
            raise ValueError("制作对象须为EP001至EP999、片头或片尾，不使用零集号或路径。")
        if not project.is_dir():
            raise FileNotFoundError("开始单集前须已有项目目录：" + str(project))
        root = "09-剧集制作/" + episode
        directories = ("09-剧集制作", root,
                       *(root + "/" + item for item in EPISODE_DIRECTORIES))

    targets = [(item, project_file(project, item)) for item in directories]
    # A file occupying a directory name must be reported before creating anything.
    for _, path in targets:
        if path.exists() and not path.is_dir():
            raise FileExistsError("目录位置已有文件，未覆盖：" + str(path))

    result = {"mode": "episode" if episode else "project", "project": str(project),
              "created": [], "existing": []}
    if episode:
        result["episode"] = episode
    for item, path in targets:
        if path.is_dir():
            result["existing"].append(item)
        else:
            path.mkdir(parents=True, exist_ok=True)
            result["created"].append(item)
    if episode is None:
        added = register_project(project)
        result["project_index"] = str(project.parent / INDEX_NAME)
        result["index_added"] = added
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="由Agent初始化项目或单集目录；项目模式同时追加项目总索引，不生成创作正文或连接网页服务。")
    parser.add_argument("--project", required=True,
                        help="项目根目录，例如projects/剧名；相对路径从当前工作目录解析，支持绝对路径。")
    parser.add_argument("--episode",
                        help="可选制作对象EP001至EP999、片头或片尾；只建立该对象的五个准备目录，项目根必须已存在。")
    parser.add_argument("--cover", action="store_true",
                        help="项目初始化时已确定需要封面，建立10-封面资料；默认不建。")
    parser.add_argument("--intro", action="store_true",
                        help="项目初始化时已确定需要片头，建立片头及五个准备目录；默认不建。")
    parser.add_argument("--outro", action="store_true",
                        help="项目初始化时已确定需要片尾，建立片尾及五个准备目录；默认不建。")
    args = parser.parse_args(argv)
    try:
        result = initialize(args.project, args.episode,
                            cover=args.cover, intro=args.intro, outro=args.outro)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
