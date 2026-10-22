"""Shared project-list format for initialization and workspace browsing."""
from pathlib import Path
import re


INDEX_NAME = "项目总索引.md"


def read_index(root):
    path = Path(root) / INDEX_NAME
    text = path.read_text(encoding="utf-8-sig") if path.exists() else "# 项目总索引\n\n| 编号 | 项目名称 |\n| --- | --- |\n"
    rows = re.findall(r"^[ \t]*\|[ \t]*[0-9]+[ \t]*\|[ \t]*([^|\r\n]+?)[ \t]*\|[ \t]*$", text, re.MULTILINE)
    names = rows or re.findall(r"^[ \t]*[0-9]+\.[ \t]+([^\r\n]+?)[ \t]*$", text, re.MULTILINE)
    return text, names


def register_project(project):
    project = Path(project)
    text, names = read_index(project.parent)
    if project.name in names:
        return False
    table = re.search(r"^[ \t]*\|[ \t]*编号[ \t]*\|[ \t]*项目名称[ \t]*\|[ \t]*$", text, re.MULTILINE)
    line = f"| {len(names) + 1:02d} | {project.name} |" if table else f"{len(names) + 1}. {project.name}"
    separator = "\n" if names or table else "\n\n"
    (project.parent / INDEX_NAME).write_text(
        text.rstrip() + separator + line + "\n", encoding="utf-8")
    return True
