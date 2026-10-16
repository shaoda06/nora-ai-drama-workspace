"""Resolve a video's explicitly recorded generation inputs, never current defaults."""
import mimetypes
import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from .project import field, markdown


def segment_body(text, segment):
    current = re.search(r"^##[ \t]+1\.[ \t]*当前内容[ \t]*\n(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)
    if current:
        text = re.sub(r"^#{3,6}(?= )", lambda match: match[0][2:], current[1].strip(), flags=re.M)
    shots = re.search(r"^##[ \t]+1\.[ \t]*镜头正文[ \t]*\n(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)
    section = re.search(r"^###[ \t]+分段[ \t]+" + re.escape(segment)
                        + r"[ \t]*\n.*?(?=^###[ \t]|\Z)", shots[1], re.M | re.S) if shots else None
    start = re.search(r"^####[ \t]+", section[0], re.M) if section else None
    body = section[0][start.start():] if start else ""
    body = re.sub(r"(^####[ \t]+(EP\d+(?:-C\d+)?-SH\d+)[ \t]*\n)\s*(?:-[ \t]+)?\*\*镜号\*\*[：:][ \t]*\2[ \t]*(?=\n|$)",
                  r"\1", body, flags=re.M)
    # Historical files retain their bytes; display the existing duration after time.
    shots = re.split(r"(?=^####[ \t])", body, flags=re.M)
    for index, shot in enumerate(shots):
        duration = re.search(r"^(?:-[ \t]+)?\*\*时长\*\*[：:][^\n]*\n?", shot, re.M)
        time = re.search(r"^(?:-[ \t]+)?\*\*时间\*\*[：:][^\n]*\n?", shot, re.M)
        if duration and time and duration.start() > time.end():
            without_duration = shot[:duration.start()] + shot[duration.end():]
            shots[index] = without_duration[:time.end()] + "\n" + duration[0].rstrip() + "\n" + without_duration[time.end():]
    return "".join(shots)


def resolve_context(identity, contexts, project, read, read_plain, previews, trail=(), dependencies=None):
    empty = {"scriptHtml": "", "shots": [], "prompts": {"english": "", "chinese": ""},
             "references": {"common": [], "segment": []}, "issues": []}
    if identity not in contexts:
        return dict(empty, issues=["该次生成的资料关联尚未记录。"])
    if identity in trail:
        raise ValueError("视频来源循环：" + identity)
    context = contexts[identity]
    if "source" in context and "storyboard" not in context and "prompts" not in context:
        result = resolve_context(context["source"], contexts, project, read, read_plain, previews, (*trail, identity), dependencies)
        return dict(result, source=context["source"])
    result = empty
    if "source" in context:
        result["source"] = context["source"]

    def local_file(key):
        path = project / key
        if Path(key).is_absolute() or not path.resolve().is_relative_to(project):
            raise ValueError("生成资料越出项目：" + key)
        if dependencies is not None:
            dependencies.add(key)
        return path if path.is_file() else None

    storyboard = context.get("storyboard")
    if storyboard and local_file(storyboard["file"]):
        text = read(storyboard["file"])
        if field(text, "文档版本").rstrip("。") != storyboard["version"]:
            result["issues"].append("该次分镜的文件版本与记录不一致。")
        else:
            body = segment_body(text, identity.split("-")[2])
            result.update(scriptHtml=markdown(body, storyboard["file"]),
                          scriptUrl=quote(storyboard["file"], safe="/-._~"))
            for shot in re.finditer(r"^####[ \t]+(EP\d+(?:-C\d+)?-SH\d+)[ \t]*\n.*?(?=^####[ \t]|\Z)", body, re.M | re.S):
                duration = re.search(r"^(?:-[ \t]+)?\*\*时长\*\*[：:][ \t]*(\d+(?:\.\d+)?)[ \t]*秒[。.]?[ \t]*$", shot[0], re.M)
                seconds = float(duration[1]) if duration else 0
                result["shots"].append({"id": shot[1], "duration": seconds if seconds > 0 else None,
                                        "html": markdown(shot[0], storyboard["file"])})
            if any(shot["duration"] is None for shot in result["shots"]):
                result["issues"].append("该次分镜存在缺失或无效的镜头时长，无法跟视频对齐。")
            if not body:
                result["issues"].append("该次分镜中未找到对应分段的镜头正文。")
    else:
        result["issues"].append("该次分镜原文件尚未关联或已缺失。")

    for language in ("english", "chinese"):
        key = context.get("prompts", {}).get(language)
        if not key or not local_file(key):
            continue
        if key.endswith(".md"):
            text = read(key)
            english = re.search(r"^## 提交给(?:模型|节点263)的完整提示词\s*\n```text\s*\n(.*?)```", text, re.M | re.S)
            chinese = re.search(r"^## 中文提示词参考版\s*\n(?:(?!^## ).)*?```text\s*\n(.*?)```", text, re.M | re.S)
            if language == "chinese" and english and chinese and english[1].strip() == result["prompts"]["english"].replace("\r\n", "\n").strip():
                result["prompts"][language] = chinese[1].strip()
        else:
            read_plain(key)
            if not previews[key]["notice"]:
                result["prompts"][language] = previews[key]["text"]
        if result["prompts"][language]:
            result["prompts"][language + "Url"] = quote(key, safe="/-._~")
    if not result["prompts"]["english"]:
        result["issues"].append("该次实际提交的提示词快照尚未关联或已缺失。")
    if "references" not in context:
        result["issues"].append("该次参考素材关联尚未记录。")
    for group in ("common", "segment"):
        for item in context.get("references", {}).get(group, []):
            path = local_file(item["file"])
            kind = (mimetypes.guess_type(item["file"])[0] or '').split('/')[0]
            if kind not in ('image', 'video', 'audio'):
                raise ValueError("该次参考素材类型无法识别：" + item["file"])
            material = {"name": Path(item["file"]).name, "label": item["label"], "kind": kind}
            if path:
                material["url"] = quote(item["file"], safe="/-._~")
            else:
                material["missing"] = True
                result["issues"].append("该次输入原素材缺失：" + material["name"])
            result["references"][group].append(material)
        result["references"][group].sort(key=lambda item: ('image', 'video', 'audio').index(item['kind']))
    return result


def load_context(project, identity, contexts):
    """Read only the selected revision's frozen inputs, with existing integrity checks."""
    from .project import plain_text_preview, SourceChangedError
    texts, previews, sources, dependencies = {}, {}, {}, set()

    def read(key):
        if key not in texts:
            path = project / key
            if not path.resolve().is_relative_to(project):
                raise ValueError('生成资料越出项目：' + key)
            if not path.is_file():
                return None
            raw = path.read_bytes()
            sources[key] = hashlib.sha256(raw).hexdigest()
            texts[key] = raw.decode('utf-8-sig').replace('\r\n', '\n')
        return texts[key]

    def read_plain(key):
        if key not in previews:
            path = project / key
            if not path.resolve().is_relative_to(project):
                raise ValueError('生成资料越出项目：' + key)
            previews[key], sources[key] = plain_text_preview(path)

    context = resolve_context(identity, contexts, project, read, read_plain, previews, dependencies=dependencies)
    for key, digest in sources.items():
        if hashlib.sha256((project / key).read_bytes()).hexdigest() != digest:
            raise SourceChangedError('Source changed while reading; rerun: ' + key)
    return {'context': context, 'sources': sources, 'dependencies': sorted(dependencies)}
