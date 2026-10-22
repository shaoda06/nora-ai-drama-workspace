"""Shared project-list format for initialization and workspace browsing."""
from pathlib import Path
import re


INDEX_NAME = "项目总索引.md"


def read_index(root):
    path = Path(root) / INDEX_NAME
    text = path.read_text(encoding="utf-8-sig") if path.exists() else "# 项目总索引\n\n"
    names = re.findall(r"^[ \t]*[0-9]+\.[ \t]+([^\r\n]+?)[ \t]*$", text, re.MULTILINE)
    return text, names


def register_project(project):
    project = Path(project)
    text, names = read_index(project.parent)
    if project.name in names:
        return False
    separator = "\n" if names else "\n\n"
    (project.parent / INDEX_NAME).write_text(
        text.rstrip() + separator + f"{len(names) + 1}. {project.name}\n", encoding="utf-8")
    return True
