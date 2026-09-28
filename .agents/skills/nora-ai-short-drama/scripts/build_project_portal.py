#!/usr/bin/env python3
"""Build the local, read-only project portal. Python 3.9+, standard library only."""
import argparse
import codecs
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit

MARKER = "<!-- nora-project-portal:generated-v1 -->"
GROUPS = ("讨论记录", "过程稿", "审阅记录", "历史版本")
POSITION = "00-项目定位/项目基本定位.md"
STORY = "01-故事主旨与简介/故事主旨与简介.md"
OUTLINE = "02-全局故事大纲/全局故事大纲.md"
PROGRESS = "项目进度.md"
PEOPLE = "03-人物资料"
SCENES = "04-场景资料"
PROPS = "05-道具资料"
TEXT_PREVIEW_LIMIT = 256 * 1024
INLINE_PATTERN = r"(\x60+)(.+?)\1|!?\[([^\]]*)\]\((<[^>]+>|[^)\n]+)\)|\*\*(.+?)\*\*"
STATUS_COLORS = {
    **dict.fromkeys(("已完成", "已确认", "已定稿", "通过", "批准采用", "成功", "success"), "green"),
    **dict.fromkeys(("进行中", "运行中", "running"), "blue"),
    **dict.fromkeys(("待确认", "待审核", "修改后再审", "状态不明", "unknown"), "orange"),
    **dict.fromkeys(("失败", "不通过", "failed"), "red"),
    **dict.fromkeys(("未开始", "排队中", "不采用", "未记录", "不适用", "待完成", "queued"), "gray"),
}
STATUS_FIELDS = {"状态", "当前状态", "确认状态", "执行状态", "真实执行状态", "技术检查结论",
                 "agent 技术审查结论", "agent 内容审查状态", "agent 初审结论", "agent初审结论", "agent 画面初审结论", "用户采用状态", "用户决定"}


def status_markup(value, source):
    """Style a declared status only; retain qualifiers and never infer approval."""
    names = "|".join(re.escape(s) for s in sorted(STATUS_COLORS, key=len, reverse=True))
    match = re.match(r"^(" + names + r")(?=$|[\s；;，,。：（(])", value)
    label = match.group(1) if match else value
    suffix = value[len(label):]
    color = STATUS_COLORS.get(label, "gray")
    return '<span class="status-badge status-' + color + '">' + inline(label, source) + '</span>' + inline(suffix, source)



def image_review_fields(chunk, source, legacy_state, user_state):
    """Keep new review stages separate; legacy decisions remain historical facts."""
    technical = field(chunk, "agent 技术审查结论")
    content = field(chunk, "agent 内容审查状态")
    findings = field(chunk, "agent 内容审查发现")
    staged = any(value != "未记录" for value in (technical, content, findings))
    waiting = bool(re.match(r"^(待确认|待审核)(?=$|[。；，\s])", user_state))
    eligible = (bool(re.match(r"^通过(?=$|[。；，\s])", technical))
                and bool(re.match(r"^已完成(?=$|[。；，\s])", content)))
    return {"twoStageReview": staged,
            "technicalHtml": status_markup(technical, source),
            "contentHtml": status_markup(content, source),
            "contentFindingsHtml": inline(findings, source),
            "agentHtml": status_markup(legacy_state, source),
            "userHtml": status_markup(user_state, source),
            "pending": waiting and (eligible if staged else True)}


def field_markup(text, source):
    match = re.match(r"^([^：:]+)([：:][ \t]*)(.*)$", text)
    if match and match.group(1).strip() in STATUS_FIELDS:
        return inline(match.group(1) + match.group(2), source) + status_markup(match.group(3), source)
    return inline(text, source)


def safe_link(target, source):
    """Resolve a Markdown link relative to its source, not relative to the HTML."""
    target = target.strip().strip("<>")
    if any(ord(c) < 32 for c in target) or "\\" in target:
        return None, None
    parsed = urlsplit(target)
    if parsed.scheme:
        if parsed.scheme.lower() not in ("https", "http", "thread", "mailto"):
            return None, None
        return target, None
    if target.startswith("//"):
        return None, None
    path = unquote(parsed.path)
    if path.startswith("/"):
        return None, None
    key = os.path.normpath(os.path.join(os.path.dirname(source), path)) if path else source
    href = quote(key, safe="/-._~") + ("?" + parsed.query if parsed.query else "")
    if parsed.fragment:
        href += "#" + quote(unquote(parsed.fragment), safe="-._~")
    return href, key


def inline(text, source):
    output, offset = [], 0
    for match in re.finditer(INLINE_PATTERN, text):
        output.append(html.escape(text[offset:match.start()]))
        if match.group(1):
            output.append("<code>" + html.escape(match.group(2)) + "</code>")
        elif match.group(3) is not None:
            href, key = safe_link(match.group(4), source)
            label = html.escape(match.group(3))
            if href is None:
                output.append(label + "（不支持的链接）")
            else:
                attrs = (' data-doc="' + html.escape(key, quote=True) + '"') if key else ""
                output.append('<a href="' + html.escape(href, quote=True) + '"' + attrs
                              + '>' + label + "</a>")
        else:
            output.append("<strong>" + html.escape(match.group(5)) + "</strong>")
        offset = match.end()
    output.append(html.escape(text[offset:]))
    return "".join(output)


def cells(line):
    return [part.strip().replace(r"\|", "|") for part in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def slug(text):
    return re.sub(r"[^\w\u3400-\u9fff -]", "", text.lower()).replace(" ", "-")


def markdown(text, source):
    """Render headings, paragraphs, lists, tables, quotes and code.
    Raw HTML is escaped; unknown Markdown stays readable as source text.
    """
    lines, out, i, anchors = text.splitlines(), [], 0, {}
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = re.match(r"^\s*(\x60{3,}|~{3,})", line)
        if fence:
            marker, chunk = fence.group(1), []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith(marker):
                chunk.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(chunk)) + "</code></pre>")
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level, content = len(heading.group(1)), heading.group(2)
            anchor = slug(content)
            count = anchors.get(anchor, 0)
            anchors[anchor] = count + 1
            if count:
                anchor += "-" + str(count)
            out.append(f'<h{level} id="{html.escape(anchor, quote=True)}">'
                       + inline(content, source) + f"</h{level}>")
            i += 1
            continue
        if i + 1 < len(lines) and "|" in line and re.fullmatch(
                r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", lines[i + 1]):
            headers = cells(line)
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                row = cells(lines[i])
                rows.append("<tr>" + "".join("<td>" + (
                    status_markup(c, source) if j < len(headers) and headers[j] in STATUS_FIELDS
                    else inline(c, source)) + "</td>" for j, c in enumerate(row)) + "</tr>")
                i += 1
            out.append('<div class="table-scroll"><table><thead><tr>'
                       + "".join("<th>" + inline(c, source) + "</th>" for c in headers)
                       + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
            continue
        bullet = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if bullet:
            ordered = bool(re.match(r"^\s*\d", line))
            tag, items = ("ol" if ordered else "ul"), []
            while i < len(lines):
                item = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$", lines[i])
                if not item or bool(re.match(r"^\s*\d", lines[i])) != ordered:
                    break
                items.append("<li>" + field_markup(item.group(1), source) + "</li>")
                i += 1
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        if re.fullmatch(r"\s*(---+|\*\*\*+)\s*", line):
            out.append("<hr>")
        elif line.startswith(">"):
            out.append("<blockquote>" + inline(line.lstrip("> "), source) + "</blockquote>")
        else:
            out.append("<p>" + field_markup(line, source) + "</p>")
        i += 1
    return "\n".join(out)


def field(text, name):
    match = re.search(r"^-[ \t]*" + re.escape(name) + r"[:：][ \t]*([^\n]*)$", text, re.M)
    return match.group(1).strip() if match else "未记录"


def intro_markup(text):
    """List approval clauses without editing source words, punctuation, or links."""
    rendered = markdown(text, POSITION)
    match = re.search(r"^-[ \t]*确认依据[:：][ \t]*([^\n]*)$", text, re.M)
    if not match:
        return rendered
    value = match.group(1)
    protected = list(re.finditer(INLINE_PATTERN, value))
    cuts = [m.end() for m in re.finditer(r"[；;]", value)
            if not any(p.start() <= m.start() < p.end() for p in protected)]
    boundaries = [0] + cuts + [len(value)]
    items = [value[a:b].strip() for a, b in zip(boundaries, boundaries[1:]) if value[a:b].strip()]
    replacement = '确认依据：<ul class="approval-items">' + "".join(
        "<li>" + inline(item, POSITION) + "</li>" for item in items) + "</ul>"
    return rendered.replace(inline("确认依据：" + value, POSITION), replacement, 1)


def phase_rows(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and cells(line) == [
                "阶段名称", "对应会话入口", "当前状态", "成果入口", "待决事项", "下一步"]:
            result = []
            for row in lines[i + 2:]:
                if not row.strip().startswith("|"):
                    break
                values = cells(row)
                if len(values) == 6:
                    result.append(dict(zip(("name", "chat", "status", "outputs", "pending", "next"), values)))
            return result
    return []


def table_records(text, required):
    """Read only a table with the explicit expected columns."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        headers = cells(line)
        if not set(required).issubset(headers) or not re.match(r"^\s*\|?[ :\-]+\|", lines[i + 1]):
            continue
        result = []
        for row in lines[i + 2:]:
            if not row.strip():
                continue
            if not row.strip().startswith("|"):
                break
            values = cells(row)
            if len(values) == len(headers):
                result.append(dict(zip(headers, values)))
        return result
    return []


def markdown_links(text, source):
    result = []
    for match in re.finditer(r"!?\[([^\]]*)\]\((<[^>]+>|[^)\n]+)\)", text):
        url, key = safe_link(match.group(2), source)
        if key and url:
            result.append({"name": match.group(1), "key": key, "url": url})
    return result


def build_data(project):
    documents, sources, texts = {}, {}, {}
    text_previews = {}
    warnings = []

    def read(relative):
        if relative in texts:
            return texts[relative]
        path = project / relative
        if not path.is_file():
            return None
        if not path.resolve().is_relative_to(project):
            raise ValueError("Refusing source outside project: " + relative)
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        sources[relative] = hashlib.sha256(raw).hexdigest()
        texts[relative] = text
        documents[relative] = {
            "title": next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem),
            "html": markdown(text, relative), "url": quote(relative, safe="/-._~"),
        }
        return text

    def read_plain(relative):
        if relative in text_previews:
            return
        digest, prefix, total = hashlib.sha256(), bytearray(), 0
        with (project / relative).open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
                total += len(chunk)
                prefix.extend(chunk[:max(0, TEXT_PREVIEW_LIMIT - len(prefix))])
        sources[relative] = digest.hexdigest()
        truncated = total > TEXT_PREVIEW_LIMIT
        notice = "仅截取前256 KiB供预览；完整内容请打开原文件。" if truncated else ""
        try:
            text = codecs.getincrementaldecoder("utf-8-sig")().decode(bytes(prefix), final=not truncated)
        except UnicodeDecodeError:
            text, notice = "", "文件不是有效的UTF-8文本，无法页内预览；请打开原文件。"
        text_previews[relative] = {"text": text, "notice": notice}

    def file_entry(path):
        if not path.is_file() or not path.resolve().is_relative_to(project):
            return None
        key = path.relative_to(project).as_posix()
        kind = {".md": "document", ".json": "text", ".txt": "text", ".log": "text",
                ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
                ".wav": "audio", ".mp3": "audio", ".m4a": "audio", ".ogg": "audio",
                ".flac": "audio", ".mp4": "video", ".webm": "video", ".mov": "video"
                }.get(path.suffix.lower(), "file")
        item = {"kind": kind, "name": path.name, "key": key, "url": quote(key, safe="/-._~")}
        if kind == "document":
            text = read(key)
            item["statusHtml"] = status_markup(field(text, "确认状态"), key)
        elif kind == "text":
            read_plain(key)
        return item

    progress = read(PROGRESS)
    position = read(POSITION)
    if progress is None:
        warnings.append("尚未找到项目根目录的项目进度.md，顶部信息未记录；请核对实际进度入口。")
    if position is None:
        warnings.append("尚未形成正式定位，不以草稿代替。")
    rows = phase_rows(progress or "")
    active = [dict(row, statusHtml=status_markup(row["status"], PROGRESS), pendingHtml=inline(row["pending"], PROGRESS),
                   nextHtml=inline(row["next"], PROGRESS))
              for row in rows if row["status"] in ("进行中", "待确认")]
    if progress and not rows:
        warnings.append("项目进度表格式未识别，请打开原记录核对；不推断当前阶段。")
    def file_order(item):
        if item["kind"] == "group":
            return 2
        return 0 if item["kind"] == "document" and Path(item["key"]).name.endswith("索引.md") else 1

    def collect_groups(directory):
        result = []
        for group in GROUPS:
            folder = project / directory / group
            files = []
            if folder.is_dir():
                for path in sorted(folder.rglob("*")):
                    if not path.is_file() or any(p.startswith(".") for p in path.relative_to(folder).parts):
                        continue
                    if not path.resolve().is_relative_to(project):
                        continue
                    item = file_entry(path)
                    if item:
                        item["name"] = path.relative_to(folder).as_posix()
                        item["preview"] = item["key"] in documents
                        files.append(item)
            files.sort(key=file_order)
            result.append({"name": group, "files": files})
        return result

    groups = collect_groups("00-项目定位")
    def long_document(source, with_groups=True):
        text = read(source)
        meta = {key: field(text or "", key) for key in ("文档版本", "更新日期", "确认状态")}
        body = re.sub(r"^# .+\n?", "", text or "", count=1)
        start = re.search(r"^## ", body, re.M)
        intro, main = (body[:start.start()], body[start.start():]) if start else ("", body)
        boundary = field(intro, "阅读边界")
        for key in (*meta, "阅读边界"):
            intro = re.sub(r"^-[ \t]*" + re.escape(key) + r"[:：][^\n]*\n?", "", intro, flags=re.M)
        return {"exists": text is not None, "meta": meta,
                "url": quote(source, safe="/-._~"), "confirmationHtml": status_markup(meta["确认状态"], source),
                "boundaryHtml": inline(boundary, source) if boundary != "未记录" else "",
                "introHtml": markdown(intro, source), "bodyHtml": markdown(main, source),
                "groups": collect_groups(str(Path(source).parent)) if with_groups else []}

    story = long_document(STORY)
    outline = long_document(OUTLINE)
    people_groups = collect_groups(PEOPLE)
    people_index = PEOPLE + "/人物索引.md"
    index_text = read(people_index) or ""
    index_rows = table_records(index_text, ("人物编号", "姓名", "人物定位", "资料卡入口"))
    people = []

    def local_media(link, required_parent):
        key = link["key"]
        path = project / key
        if (Path(key).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")
                or not path.is_file() or not path.resolve().is_relative_to((project / required_parent).resolve())
                or not path.resolve().is_relative_to(project)):
            return None
        return dict(link)

    # Registry is identity authority. A loose image or old adoption summary is not one.
    for row in index_rows:
        number = row["人物编号"]
        if not re.fullmatch(r"CH\d{3,}", number):
            continue
        card_links = markdown_links(row["资料卡入口"], people_index)
        card_key = next((link["key"] for link in card_links
                         if Path(link["key"]).parent.parent.as_posix() == PEOPLE
                         and Path(link["key"]).parent.name.startswith(number + "-")
                         and link["key"].endswith("-人物资料卡.md")), None)
        if not card_key:
            warnings.append(number + "资料卡入口未识别，请核对人物索引。")
            continue
        card = long_document(card_key, False)
        appearance = re.search(r"^## 3\. 外貌与基础造型\s*\n(.*?)(?=^## |\Z)",
                               texts.get(card_key, ""), re.M | re.S)
        stage_names = re.findall(r"^### 3\.\d+ (.+?)\s*$", appearance.group(1), re.M) if appearance else []
        record_key = str(Path(card_key).parent / "参考图/生成记录.md")
        record = read(record_key) or ""
        formal, candidates = [], []
        formal_section = re.search(r"^## 1\. 当前正式资产\s*\n(.*?)(?=^## |\Z)", record, re.M | re.S)
        rows_formal = table_records(formal_section.group(1) if formal_section else "",
                                   ("图片类型", "人物状态", "服装状态", "正式文件", "采用的候选版本", "审阅记录"))
        for entry in rows_formal:
            links = markdown_links(entry["正式文件"], record_key)
            media = next((m for link in links if (m := local_media(link, str(Path(record_key).parent)))), None)
            # Never promote candidates or history through a malformed registry link.
            if media and any(p in GROUPS for p in Path(media["key"]).parts):
                media = None
            reviews = markdown_links(entry["审阅记录"], record_key)
            decisions = []
            for review in reviews:
                review_text = texts.get(review["key"], "")
                section = re.search(r"^## 4\. 用户确认\s*\n(.*?)(?=^## |\Z)", review_text, re.M | re.S)
                decisions.append(field(section.group(1) if section else "", "结论"))
            approved = bool(decisions) and all(d.startswith("批准采用") for d in decisions)
            stage = ""
            if links:
                parent = Path(links[0]["key"]).parent
                if parent.parent == Path(record_key).parent and parent.name in stage_names:
                    stage = parent.name
            formal.append({"type": entry["图片类型"], "state": entry["人物状态"],
                           "stage": stage,
                           "costume": entry["服装状态"], "version": entry["采用的候选版本"],
                           "versionHtml": inline(entry["采用的候选版本"], record_key),
                           "scope": entry.get("适用范围", "未记录"), "media": media,
                           "reviews": reviews, "approved": approved,
                           "statusHtml": "<br>".join(status_markup(d, record_key) for d in decisions)
                           or status_markup("未记录", record_key)})
        for match in re.finditer(r"^### (生成记录-\d+)\s*\n(.*?)(?=^### |\Z)", record, re.M | re.S):
            name, chunk = match.group(1), match.group(2)
            # Code fences can contain arbitrary prompts, not management fields.
            chunk = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", chunk, flags=re.M | re.S)
            output = field(chunk, "输出候选文件")
            media = [m for link in markdown_links(output, record_key)
                     if (m := local_media(link, PEOPLE + "/过程稿"))]
            if not media:
                continue
            review_line = next((line for line in chunk.splitlines() if re.match(r"^- 审阅记录[^：]*：", line)), "")
            reviews = markdown_links(review_line, record_key)
            agent_state = field(chunk, "agent 画面初审结论")
            user_state = field(chunk, "用户采用状态")
            for image in media:
                candidates.append({"type": field(chunk, "图片类型").rstrip("。"),
                                   "state": field(chunk, "人物状态").rstrip("。"),
                                   "costume": field(chunk, "服装状态").rstrip("。"),
                                   "media": image, "reviews": reviews, "generation": name,
                                   "recordUrl": quote(record_key, safe="/-._~") + "#" + quote(name),
                                   **image_review_fields(chunk, record_key, agent_state, user_state)})
        person_groups = [{"name": group["name"], "files": [f for f in group["files"]
                          if any(part.startswith(number + "-") for part in Path(f["key"]).parts)]}
                         for group in people_groups]
        # The current registry determines which images are eligible as covers.
        cover = next((a for a in formal if a["media"] and a["approved"] and a["type"] == "人物上半身正面肖像图"),
                     next((a for a in formal if a["media"] and a["approved"] and a["type"] == "角色多视角参考图"), None))
        people.append({"id": number, "name": row["姓名"], "role": row["人物定位"],
                       "stages": [name for name in stage_names if any(a["stage"] == name for a in formal)],
                       "candidateStages": stage_names if len(stage_names) > 1 else [],
                       "card": card, "cardKey": card_key, "formal": formal, "candidates": candidates,
                       "cover": cover, "recordKey": record_key if record else None,
                       "pendingCount": sum(c["pending"] for c in candidates), "groups": person_groups})
    prop_groups = collect_groups(PROPS)
    prop_index = PROPS + "/道具索引.md"
    prop_index_text = read(prop_index) or ""
    props = []
    # Registry is identity authority. A loose image or old adoption summary is not one.
    for row in table_records(prop_index_text, ("道具编号", "名称", "道具类别", "资料卡入口")):
        number = row["道具编号"]
        if not re.fullmatch(r"PR\d{3,}", number):
            continue
        card_links = markdown_links(row["资料卡入口"], prop_index)
        card_key = next((link["key"] for link in card_links
                         if Path(link["key"]).parent.parent.as_posix() == PROPS
                         and Path(link["key"]).parent.name.startswith(number + "-")
                         and link["key"].endswith("-资料卡.md")), None)
        if not card_key:
            warnings.append(number + "资料卡入口未识别，请核对道具索引。")
            continue
        card = long_document(card_key, False)
        record_key = str(Path(card_key).parent / "参考图/生成记录.md")
        record = read(record_key) or ""
        formal, candidates = [], []
        formal_section = re.search(r"^## 1\. 当前正式资产\s*\n(.*?)(?=^## |\Z)", record, re.M | re.S)
        rows_formal = table_records(formal_section.group(1) if formal_section else "",
                                   ("状态名", "正式文件", "采用的候选版本", "审阅记录"))
        for entry in rows_formal:
            links = markdown_links(entry["正式文件"], record_key)
            media = next((m for link in links if (m := local_media(link, str(Path(record_key).parent)))), None)
            # Never promote candidates or history through a malformed registry link.
            if media and Path(media["key"]).parent != Path(record_key).parent:
                media = None
            reviews = markdown_links(entry["审阅记录"], record_key)
            decisions = []
            for review in reviews:
                review_text = texts.get(review["key"], "")
                section = re.search(r"^## 4\. 用户确认\s*\n(.*?)(?=^## |\Z)", review_text, re.M | re.S)
                decisions.append(field(section.group(1) if section else "", "结论"))
            approved = bool(decisions) and all(re.match(r"^批准采用(?:$|[。；，\s])", d) for d in decisions)
            formal.append({"prop": True, "type": "道具参考图", "state": entry["状态名"], "version": entry["采用的候选版本"],
                           "versionHtml": inline(entry["采用的候选版本"], record_key),
                           "scope": entry.get("适用范围", "未记录"), "media": media,
                           "sourceHtml": inline(entry.get("来源参考图及版本", "未记录"), record_key),
                           "reviews": reviews, "approved": approved,
                           "statusHtml": "<br>".join(status_markup(d, record_key) for d in decisions)
                           or status_markup("未记录", record_key)})
        for match in re.finditer(r"^### (生成记录-\d+)\s*\n(.*?)(?=^### |\Z)", record, re.M | re.S):
            name, chunk = match.group(1), match.group(2)
            # Code fences can contain arbitrary prompts, not management fields.
            chunk = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", chunk, flags=re.M | re.S)
            output = field(chunk, "输出候选文件")
            media = [m for link in markdown_links(output, record_key)
                     if (m := local_media(link, PROPS + "/过程稿"))]
            if not media:
                continue
            review_line = next((line for line in chunk.splitlines() if re.match(r"^- 审阅记录[^：]*：", line)), "")
            reviews = markdown_links(review_line, record_key)
            agent_state = field(chunk, "agent 画面初审结论")
            user_state = field(chunk, "用户采用状态")
            for image in media:
                candidates.append({"prop": True, "type": "道具候选图",
                                   "state": field(chunk, "状态名及实际含义").rstrip("。"),
                                   "scope": field(chunk, "本次目标、保留与变化"),
                                   "media": image, "reviews": reviews, "generation": name,
                                   "recordUrl": quote(record_key, safe="/-._~") + "#" + quote(name),
                                   **image_review_fields(chunk, record_key, agent_state, user_state)})
        prop_related = [{"name": group["name"], "files": [f for f in group["files"]
                          if any(part.startswith(number + "-") for part in Path(f["key"]).parts)]}
                         for group in prop_groups]
        # The current registry determines which images are eligible as covers.
        cover = next((a for a in formal if a["media"] and a["approved"] and a["state"] == "基础"),
                     next((a for a in formal if a["media"] and a["approved"]), None))
        props.append({"id": number, "name": row["名称"], "role": row["道具类别"],
                       "card": card, "cardKey": card_key, "formal": formal, "candidates": candidates,
                       "cover": cover, "recordKey": record_key if record else None,
                       "pendingCount": sum(c["pending"] for c in candidates), "groups": prop_related})
    scene_groups = collect_groups(SCENES)
    scene_index = SCENES + "/场景索引.md"
    scene_index_text = read(scene_index) or ""
    scenes = []
    for row in table_records(scene_index_text, ("场景编号", "名称", "场景类型", "资料卡入口")):
        number = row["场景编号"]
        if not re.fullmatch(r"SC\d{3,}", number):
            continue
        card_key = next((link["key"] for link in markdown_links(row["资料卡入口"], scene_index)
                         if Path(link["key"]).parent.parent.as_posix() == SCENES
                         and Path(link["key"]).parent.name.startswith(number + "-")
                         and link["key"].endswith("资料卡.md")), None)
        if not card_key:
            warnings.append(number + "资料卡入口未识别，请核对场景索引。")
            continue
        card = long_document(card_key, False)
        record_key = str(Path(card_key).parent / "参考图/生成记录.md")
        record = read(record_key) or ""
        formal, auxiliary, candidates = [], [], []
        section = re.search(r"^## (?:1[.、] )?当前正式资产[^\n]*\n(.*?)(?=^## |\Z)", record, re.M | re.S)
        registry = table_records(section.group(1) if section else "", ("正式文件", "最初制作场次", "场景状态与适用条件", "采用的候选版本", "审阅记录"))
        for entry in registry:
            links = markdown_links(entry["正式文件"], record_key)
            media = next((m for link in links if (m := local_media(link, str(Path(record_key).parent)))), None)
            if media and (Path(media["key"]).parent != Path(record_key).parent):
                media = None
            reviews = markdown_links(entry["审阅记录"], record_key)
            decisions = []
            for review in reviews:
                review_text = texts.get(review["key"], "")
                confirm = re.search(r"^## 4\. 用户确认\s*\n(.*?)(?=^## |\Z)", review_text, re.M | re.S)
                decisions.append(field(confirm.group(1) if confirm else "", "结论"))
            approved = bool(decisions) and all(d.startswith("批准采用") for d in decisions)
            scope = entry["场景状态与适用条件"]
            # Only an explicit scene-origin filename qualifies as an episode environment.
            is_environment = bool(links and re.fullmatch(re.escape(number) + r"-EP\d{3,}-C\d{3,}-场景参考图\.png", Path(links[0]["key"]).name))
            if re.search(r"仅.*(?:空间|布局|结构)|不是实际|仅供.*结构|结构辅助", scope):
                is_environment = False
            asset = {"scene": True, "type": "场次环境图" if is_environment else "辅助／既有参考图",
                     "state": entry["最初制作场次"], "scope": scope, "media": media,
                     "versionHtml": inline(entry["采用的候选版本"], record_key),
                     "sourceHtml": inline(entry.get("来源参考图及版本", "未记录"), record_key),
                     "reviews": reviews, "approved": approved,
                     "statusHtml": "<br>".join(status_markup(d, record_key) for d in decisions) or status_markup("未记录", record_key)}
            (formal if is_environment else auxiliary).append(asset)
        for match in re.finditer(r"^### (生成记录-\d+)\s*\n(.*?)(?=^### |\Z)", record, re.M | re.S):
            name, chunk = match.group(1), match.group(2)
            chunk = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", chunk, flags=re.M | re.S)
            result_section = re.search(r"^#### 4\. [^\n]*\n(.*?)(?=^#### |\Z)", chunk, re.M | re.S)
            output_text = field(chunk, "输出候选文件")
            if output_text == "未记录":
                output_text = field(chunk, "输出候选")
            if output_text == "未记录" and result_section:
                output_text = result_section.group(1)
            outputs = markdown_links(output_text, record_key)
            review_line = next((line for line in chunk.splitlines() if re.match(r"^- 审阅记录[^：]*：", line)), "")
            user_state = field(chunk, "用户采用状态")
            if user_state == "未记录":
                user_state = field(chunk, "用户采用")
            agent_state = field(chunk, "agent 画面初审结论")
            if agent_state == "未记录":
                agent_state = field(chunk, "agent初审结论")
            if agent_state == "未记录":
                agent_state = field(chunk, "agent初审")
            inspection = re.search(r"^#### 5\. [^\n]*\n(.*?)(?=^#### |\Z)", chunk, re.M | re.S)
            reviews = markdown_links(review_line, record_key)
            if not reviews and inspection:
                reviews = [link for link in markdown_links(inspection.group(1), record_key)
                           if Path(link["key"]).parent.as_posix() == SCENES + "/审阅记录"]
            origin = field(chunk, "最初制作场次").rstrip("。")
            if origin == "未记录":
                task_info = re.search(r"^#### 1\. [^\n]*\n(.*?)(?=^#### |\Z)", chunk, re.M | re.S)
                origins = set(re.findall(r"EP\d{3,}-C\d{3,}", task_info.group(1) if task_info else ""))
                if len(origins) == 1:
                    origin = origins.pop()
            seen_outputs = set()
            for link in outputs:
                media = local_media(link, SCENES + "/过程稿")
                if not media or media["key"] in seen_outputs:
                    continue
                seen_outputs.add(media["key"])
                candidates.append({"scene": True, "type": "场景候选图", "state": origin,
                                   "scope": field(chunk, "本场次需求与状态"), "media": media,
                                   "reviews": reviews, "generation": name,
                                   "recordUrl": quote(record_key, safe="/-._~") + "#" + quote(name),
                                   **image_review_fields(chunk, record_key, agent_state, user_state)})
        # Expose legacy originals without treating file presence as approval or a scene assignment.
        known = {link["key"] for entry in registry for link in markdown_links(entry["正式文件"], record_key)}
        legacy = []
        folder = project / Path(record_key).parent
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                key = path.relative_to(project).as_posix()
                if key in known:
                    continue
                media = local_media({"key": key, "url": quote(key, safe="/-._~"), "name": path.name}, str(Path(record_key).parent))
                if media:
                    legacy.append(media)
        related = [{"name": group["name"], "files": [f for f in group["files"]
                   if any(part.startswith(number + "-") for part in Path(f["key"]).parts)]} for group in scene_groups]
        cover = next((a for a in formal if a["media"] and a["approved"]), None)
        scenes.append({"id": number, "name": row["名称"], "role": row["场景类型"], "cardKey": card_key,
                       "card": card, "formal": formal, "auxiliary": auxiliary, "legacy": legacy,
                       "candidates": candidates, "cover": cover, "recordKey": record_key if record else None,
                       "pendingCount": sum(c["pending"] for c in candidates), "groups": related})
    # Remaining tabs use a read-only catalogue. Text is embedded once in documents;
    # media stays on disk and is never decoded, transformed or judged here.
    def inventory(relative):
        folder = project / relative
        if not folder.is_dir() or not folder.resolve().is_relative_to(project):
            return []
        return [item for path in sorted(folder.rglob("*"))
                if not any(p.startswith(".") for p in path.relative_to(folder).parts)
                and (item := file_entry(path))]

    def file_tree(items, root, name):
        node = {"kind": "group", "name": name, "key": root, "children": []}
        branches = {root: node}
        for item in items:
            parts = Path(item["key"]).relative_to(root).parts
            parent = node
            for i, part in enumerate(parts[:-1], 1):
                key = str(Path(root).joinpath(*parts[:i]))
                if key not in branches:
                    branches[key] = {"kind": "group", "name": part, "key": key, "children": []}
                    parent["children"].append(branches[key])
                parent = branches[key]
            parent["children"].append(item)
        for branch in branches.values():
            branch["children"].sort(key=file_order)
            if re.fullmatch(r"09-剧集制作/EP\d{3,}/06-生成结果/C\d{3,}-场次结果", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    file_order(item),
                    0 if item["name"] == "场次成片" else 1 if re.fullmatch(r"P\d+-分段结果", item["name"]) else 2,
                    int(match.group(1)) if (match := re.fullmatch(r"P(\d+)-分段结果", item["name"])) else 0,
                ))
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/06-生成结果/C\d{3,}-场次结果/(场次成片|P\d{3,}-分段结果/(01-一采|02-二采|03-后处理))", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    file_order(item),
                    {"选定": 0, "候选": 1, "审阅记录": 2, "执行记录": 3}.get(item["name"], 4),
                ))
        return node

    catalogues = {}
    outline_root = "06-分集大纲"
    outline_index = outline_root + "/分集索引.md"
    outline_text = read(outline_index) or ""
    outline_items, indexed = [], set()
    for row in table_records(outline_text, ("集号", "一句话概要", "大纲入口")):
        number = row["集号"]
        if not re.fullmatch(r"EP\d{3,}", number):
            continue
        key = next((link["key"] for link in markdown_links(row["大纲入口"], outline_index)
                    if link["key"] == outline_root + "/" + number + "-分集大纲.md"), None)
        if not key:
            warnings.append(number + "大纲入口未识别，请核对分集索引。")
            continue
        indexed.add(key)
        doc = long_document(key, False)
        outline_items.append({"kind": "outline", "name": number, "key": key, "doc": doc,
                              "category": row.get("所属故事阶段", ""), "summary": row["一句话概要"],
                              "statusHtml": doc["confirmationHtml"]})
    outline_files = inventory(outline_root)
    extra = [f for f in outline_files if f["key"] not in indexed and f["key"] != outline_index]
    catalogues[outline_root] = {"kind": "group", "key": outline_root, "name": "分集大纲",
        "note": "概要与故事阶段来自分集索引；文档确认状态不代表该集视频已制作完成。",
        "indexKey": outline_index if outline_text else None,
        "children": outline_items + ([file_tree(extra, outline_root, "过程资料与其他文件")] if extra else [])}

    for root, prefix, media_kind, categories in (
            ("07-参考音频", "RA", "audio", ("人物声音", "环境声音", "动作与物件声音")),
            ("08-参考视频", "RV", "video", ("人物表演与动作", "运镜与构图", "场景与物件动态"))):
        label = root.split("-", 1)[1]
        index_key = root + "/" + label + "索引.md"
        media_index_text = read(index_key) or ""
        media_items, referenced = [], set()
        columns = ("编号", "名称", "分类", "文件入口", "参考用途与适用范围", "来源及使用授权说明", "实测时长", "审核／采用状态及版本依据")
        for row in table_records(media_index_text, columns):
            if not re.fullmatch(prefix + r"\d{3,}", row["编号"]):
                continue
            key = next((l["key"] for l in markdown_links(row["文件入口"], index_key)
                        if l["key"].startswith(root + "/")), None)
            item = file_entry(project / key) if key else None
            if item and item["kind"] != media_kind:
                item = None
            if key:
                referenced.add(key)
            media_items.append({"kind": "reference", "name": row["编号"] + " · " + row["名称"],
                "key": key or index_key + "#" + row["编号"], "category": row["分类"],
                "summary": row["参考用途与适用范围"], "media": item,
                "sourceHtml": inline(row["来源及使用授权说明"], index_key), "duration": row["实测时长"],
                "statusHtml": status_markup(row["审核／采用状态及版本依据"], index_key)})
        leftover = [f for f in inventory(root) if f["key"] not in referenced and f["key"] != index_key]
        catalogues[root] = {"kind": "group", "key": root, "name": label, "categories": list(categories),
            "note": "按现有索引展示用途、来源、时长及审核依据；不自动播放、不加工素材，也不将文件存在解释为已审核。",
            "indexKey": index_key if media_index_text else None, "children": media_items +
            ([dict(file_tree(leftover, root, "未登记／其他文件"), note="索引未关联的文件仅供核对，不推断用途、授权或采用状态。")] if leftover else [])}

    production = "09-剧集制作"
    episodes = []
    folder = project / production
    for episode in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not episode.is_dir() or not re.fullmatch(r"EP\d{3,}", episode.name) or not episode.resolve().is_relative_to(project):
            continue
        root = episode.relative_to(project).as_posix()
        files = inventory(root)
        children = file_tree(files, root, episode.name)["children"]
        present = {item["name"] for item in children}
        for directory in sorted(episode.iterdir()):
            if (directory.is_dir() and not directory.name.startswith(".")
                    and directory.resolve().is_relative_to(project) and directory.name not in present):
                children.append(file_tree([], root + "/" + directory.name, directory.name))
        children.sort(key=lambda item: (file_order(item), item["name"]))
        phase = [r for r in rows if re.search(r"\b" + re.escape(episode.name) + r"\b", r["name"])]
        episode_node = {"kind": "group", "name": episode.name, "key": root,
            "summary": str(len(files)) + " 份文件",
            "statusHtml": "<br>".join(status_markup(r["status"], PROGRESS) for r in phase) or status_markup("未记录", PROGRESS),
            "note": "展开目录查看子目录和文件。制作状态仅引用项目进度；文件存在、分段获批均不代表整集完成。",
            "children": children,
        }
        episodes.append(episode_node)
    catalogues[production] = {"kind": "group", "key": production, "name": "剧集制作", "children": episodes,
        "note": "只列实际已有的剧集目录，不按大纲预建制作任务。选择剧集后通过可折叠列表查看本集目录与文件。视频结果仅供用户人工审核。"}
    catalogues["历史版本"] = dict(file_tree(inventory("历史版本"), "历史版本", "历史版本"),
        note="以下是项目根目录的历史归档，仅供追溯，不代表当前设定或当前批准。各阶段自己的历史文件仍在对应标签中。")

    directories = [{"name": p.name, "label": re.sub(r"^\d+-", "", p.name),
                    "url": quote(p.name, safe="-._~") + "/"}
                   for p in sorted(project.iterdir()) if p.is_dir() and not p.name.startswith(".")]
    meta = {key: field(position or "", key) for key in ("文档版本", "更新日期", "确认状态")}
    body = position or ""
    body = re.sub(r"^# .+\n?", "", body, count=1)
    for key in meta:
        body = re.sub(r"^-\s*" + re.escape(key) + r"[:：].*\n?", "", body, flags=re.M)
    first_section = re.search(r"^## ", body, re.M)
    intro, main = (body[:first_section.start()], body[first_section.start():]) if first_section else ("", body)
    for key, digest in sources.items():
        if hashlib.sha256((project / key).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Source changed while reading; rerun: " + key)
    return {
        "project": field(progress or "", "项目名称") if field(progress or "", "项目名称") != "未记录" else project.name,
        "builtAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "progressUpdated": field(progress or "", "更新时间"), "active": active,
        "directories": directories, "documents": documents, "groups": groups, "story": story, "outline": outline,
        "people": people, "peopleIndex": people_index if index_text else None, "peopleGroups": people_groups,
        "props": props, "propIndex": prop_index if prop_index_text else None, "propGroups": prop_groups,
        "catalogues": catalogues, "textPreviews": text_previews,
        "scenes": scenes, "sceneIndex": scene_index if scene_index_text else None, "sceneGroups": scene_groups,
        "positionExists": position is not None, "meta": meta,
        "confirmationHtml": status_markup(meta["确认状态"], POSITION),
        "introHtml": intro_markup(intro), "positionHtml": markdown(main, POSITION),
        "warnings": warnings, "sources": sources,
    }


def build(project):
    project = project.resolve(strict=True)
    if not project.is_dir():
        raise ValueError("Project must be a directory")
    target = project / "项目总览.html"
    if target.is_symlink():
        raise ValueError("Refusing symlink output")
    previous = target.read_bytes() if target.exists() else None
    if previous is not None and MARKER.encode() not in previous:
        raise ValueError("Existing HTML is not generated by this tool; refusing overwrite")
    data = build_data(project)
    template = (Path(__file__).resolve().parent.parent / "references/模板/项目总览模板.html").read_text("utf-8")
    encoded = json.dumps(data, ensure_ascii=False).replace("&", r"\u0026").replace("<", r"\u003c").replace(">", r"\u003e")
    output = template.replace("__PROJECT_TITLE__", html.escape(data["project"])).replace("__PORTAL_DATA__", encoded)
    if (target.read_bytes() if target.exists() else None) != previous:
        raise RuntimeError("Portal changed concurrently; rerun")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=project,
                                         prefix=".项目总览-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(output)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {"output": str(target), "documents": len(data["documents"]),
            "tabs": len(data["directories"]), "warnings": data["warnings"], "updated": data["builtAt"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Existing project root; writes only 项目总览.html")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.project), ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")
