#!/usr/bin/env python3
"""Read project source documents for the workspace browser service."""
import codecs
import hashlib
import html
import json
import posixpath
from pathlib import Path
import re
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit

GROUPS = ("工作稿", "历史版本", "执行附件")
LEGACY_GROUPS = ("讨论记录", "过程稿", "审阅记录")
POSITION = "00-项目定位/项目基本定位.md"
STORY = "01-主旨与简介/主旨与简介.md"
OUTLINE = "02-故事大纲/故事大纲.md"
PROGRESS = "项目进度.md"
PEOPLE = "03-人物资料"
SCENES = "04-场景资料"
PROPS = "05-道具资料"
TEXT_PREVIEW_LIMIT = 256 * 1024
INLINE_PATTERN = r"(\x60+)(.+?)\1|!?\[([^\]]*)\]\((<[^>]+>|[^)\n]+)\)|\*\*(.+?)\*\*"
STATUS_COLORS = {
    **dict.fromkeys(("已完成", "已确认", "已定稿", "通过", "批准采用", "成功", "success"), "green"),
    **dict.fromkeys(("进行中", "运行中", "running"), "blue"),
    **dict.fromkeys(("待确认", "部分确认", "待审核", "待核对", "修改后再审", "状态不明", "unknown"), "orange"),
    **dict.fromkeys(("失败", "异常", "不通过", "failed"), "red"),
    **dict.fromkeys(("未开始", "排队中", "不采用", "未记录", "不适用", "待完成", "queued"), "gray"),
}
STATUS_FIELDS = {"状态", "当前状态", "确认状态", "画风确认状态", "画幅确认状态", "适配确认状态", "执行状态", "真实执行状态", "技术检查结论", "文件核对结论",
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
    """Display record-based delivery; retain historical review formats unchanged."""
    waiting = re.match(r"^(待确认|待审核)(?=$|[。；，\s])", user_state)
    pending_label = waiting.group(1) if waiting else ""
    file_check = field(chunk, "文件核对结论")
    vision = field(chunk, "看图调用状态")
    if file_check != "未记录" or vision != "未记录":
        return {"recordBasedReview": True, "twoStageReview": False,
                "fileCheckHtml": status_markup(file_check, source),
                "visionAuthorized": bool(re.match(r"^已按授权查看(?=$|[。；，\s])", vision)),
                "visionScopeHtml": inline(field(chunk, "看图授权及限定范围"), source),
                "visionFindingsHtml": inline(field(chunk, "授权查看的发现"), source),
                "userHtml": status_markup(user_state, source),
                "pending": bool(waiting), "pendingLabel": pending_label}
    technical = field(chunk, "agent 技术审查结论")
    content = field(chunk, "agent 内容审查状态")
    findings = field(chunk, "agent 内容审查发现")
    staged = any(value != "未记录" for value in (technical, content, findings))
    return {"twoStageReview": staged,
            "technicalHtml": status_markup(technical, source),
            "contentHtml": status_markup(content, source),
            "contentFindingsHtml": inline(findings, source),
            "agentHtml": status_markup(legacy_state, source),
            "userHtml": status_markup(user_state, source),
            "pending": bool(waiting), "pendingLabel": pending_label}


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
    source = source.replace("\\", "/")
    key = posixpath.normpath(posixpath.join(posixpath.dirname(source), path)) if path else source
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
    in_header = True
    metadata_field = r"^(?:项目名称或代号|文档版本|更新日期|确认状态|确认范围|确认依据|确认说明|制作目标|阅读边界)[:：]"
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
        sample = re.fullmatch(r"\s*!\[([^\]]*)\]\(([^)]+)\)\s*", line) if source == POSITION else None
        if sample:
            href, key = safe_link(sample.group(2), source)
            if key and not key.startswith("../") and Path(key).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                url = html.escape(href, quote=True)
                label = html.escape(sample.group(1), quote=True)
                figure = ('<figure class="style-sample"><a href="' + url
                           + '" target="_blank" rel="noopener"><img src="' + url
                           + '" alt="' + label + '" loading="lazy"></a><figcaption>'
                           + label + '</figcaption></figure>')
                if out and re.match(r"<p>(女性|男性)样例", out[-1]):
                    caption = out.pop()
                    gender = "male" if caption.startswith("<p>男性") else "female"
                    out.append('<div class="style-sample-card" data-gender="' + gender + '">' + caption + figure + '</div>')
                else:
                    out.append(figure)
                i += 1
                continue
        if line.strip() == "——编制信息——":
            out.append('<details class="intro"><summary>编制信息</summary>'
                       + markdown("\n".join(lines[i + 1:]), source) + "</details>")
            break
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level, content = len(heading.group(1)), heading.group(2)
            if level >= 2:
                in_header = False
            anchor = slug(content)
            count = anchors.get(anchor, 0)
            anchors[anchor] = count + 1
            if count:
                anchor += "-" + str(count)
            out.append(f'<h{level} id="{html.escape(anchor, quote=True)}">'
                       + inline(content, source) + f"</h{level}>")
            i += 1
            continue
        separator = i + 1
        if "|" in line:
            while separator < len(lines) and not lines[separator].strip():
                separator += 1
        if separator < len(lines) and "|" in line and re.fullmatch(
                r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", lines[separator]):
            headers = cells(line)
            i = separator + 1
            rows = []
            while i < len(lines):
                if not lines[i].strip():
                    i += 1
                    continue
                if "|" not in lines[i]:
                    break
                row = cells(lines[i])
                anchor = ' id="phase-' + slug(row[0]) + '"' if headers == ["阶段名称", "对应会话入口", "当前状态", "成果入口", "待决事项", "下一步"] else ""
                rows.append("<tr" + anchor + ">" + "".join("<td>" + (
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
                note = in_header and re.match(metadata_field, item.group(1))
                css = ' class="document-note"' if note else ""
                items.append(f"<li{css}>" + field_markup(item.group(1), source) + "</li>")
                i += 1
            css = ' class="document-notes"' if all(item.startswith('<li class="document-note">') for item in items) else ""
            out.append(f"<{tag}{css}>" + "".join(items) + f"</{tag}>")
            continue
        if re.fullmatch(r"\s*(---+|\*\*\*+)\s*", line):
            out.append("<hr>")
        elif line.startswith(">"):
            out.append("<blockquote>" + inline(line.lstrip("> "), source) + "</blockquote>")
        else:
            css = ' class="document-note"' if in_header and re.match(metadata_field, line) else ""
            out.append(f"<p{css}>" + field_markup(line, source) + "</p>")
        i += 1
    rendered = "\n".join(out)
    if source == POSITION:
        # Fixed sample sections own their title, approved image and record fields.
        def sample_section(match):
            heading, content = match[1], match[3]
            resolution = re.search(r'<li>分辨率[:：]\s*(.*?)</li>', content, re.S)
            if resolution:
                heading = heading.replace('</h4>', '，' + resolution[1] + '</h4>')
                content = content[:resolution.start()] + content[resolution.end():]
            content = re.sub(r'<figcaption>.*?</figcaption>', '', content, flags=re.S)
            if '<figure class="style-sample">' not in content:
                return heading + content
            return ('<div class="style-sample-card" data-gender="'
                    + ('male' if match[2] == '男性样例' else 'female') + '">'
                    + heading + content + '</div>')
        rendered = re.sub(r'(<h4 id="[^"]+">(男性样例|女性样例)</h4>\n)(.*?)(?=\n<h[1-4]\b|\Z)',
                          sample_section,
                          rendered, flags=re.S)
        rendered = re.sub(r'(?:<div class="style-sample-card"[^>]*>.*?</div>\n?)+',
                          lambda match: '<div class="style-samples">' + match[0] + '</div>',
                          rendered, flags=re.S)
    return rendered


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
            for row in lines[i + 1:]:
                if not row.strip() or re.fullmatch(r"\s*\|[\s:|\-]+", row):
                    continue
                if not row.strip().startswith("|"):
                    break
                values = cells(row)
                if len(values) == 6:
                    result.append(dict(zip(("name", "chat", "status", "outputs", "pending", "next"), values)))
            return result
    return []


def document_header(text, source):
    """Preserve all text before the first content chapter, including extra fields."""
    title = re.match(r"^# .+\n?", text)
    body = text[title.end():] if title else text
    start = re.search(r"^## ", body, re.M)
    if not start:
        return {}
    intro, main = body[:start.start()], body[start.start():]
    if not intro.strip():
        return {}
    meta = {key: field(intro, key) for key in ("文档版本", "更新日期", "确认状态")}
    return {"headerHtml": markdown(intro, source),
            "contentHtml": markdown((title[0] if title else "") + main, source),
            "meta": meta, "confirmationHtml": status_markup(meta["确认状态"], source)}


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


def formal_record_url(version, record, record_key):
    numbers = set(re.findall(r"生成(?:记录[-－]?)?\s*(\d+)", version))
    headings = re.findall(r"^### (生成记录-\d+)\s*$", record, re.M)
    matches = [name for name in headings if name.removeprefix("生成记录-") in numbers]
    url = quote(record_key, safe="/-._~")
    return url + "#" + quote(matches[0]) if len(numbers) == len(matches) == 1 else url


def build_data(project, *, web_episode_navigation=False):
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
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
        sources[relative] = hashlib.sha256(raw).hexdigest()
        texts[relative] = text
        documents[relative] = {
            "title": next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem),
            "html": markdown(text, relative), "url": quote(relative, safe="/-._~"),
            **document_header(text, relative),
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

    def video_prompts(key):
        match = re.fullmatch(
            r"09-剧集制作/(EP\d+)/06-生成结果/(C\d+)-场次结果/(P\d+)-分段结果/"
            r"(01-一采|02-二采)/(?:候选|选定)/(.+)\.(?:mp4|webm|mov)", key)
        if match:
            episode, scene, segment, stage, stem = match.groups()
            identity = f"{episode}-{scene}-{segment}"
            take = re.fullmatch(re.escape(identity) + r"-(R\d+)-" + stage[3:], stem)
            if not take:
                return None
            stage_root = Path(key).parent.parent.as_posix()
            english_key = f"{stage_root}/执行记录/{take[1]}-{stage[3:]}/模型提示词.txt"
        else:
            adopted = re.fullmatch(
                r"09-剧集制作/(EP\d{3,})/(?:其他资料/阶段采用视频|06-生成结果)/(01-一采|02-二采)/(C\d{3,})-场次/"
                r"(.+)\.(?:mp4|webm|mov)", key)
            candidate = re.fullmatch(
                r"09-剧集制作/(EP\d{3,})/其他资料/候选视频/(.+)\.(?:mp4|webm|mov)", key)
            if not adopted and not candidate:
                return None
            episode = adopted[1] if adopted else candidate[1]
            stem = adopted[4] if adopted else candidate[2]
            take = re.fullmatch(re.escape(episode) + r"-(C\d{3,})-(P\d{3,})-(R\d{3,})-(一采|二采)", stem)
            if not take or adopted and (take[1] != adopted[3] or take[4] != adopted[2][3:]):
                return None
            scene, segment, run, stage = take.groups()
            identity = f"{episode}-{scene}-{segment}"
            english_key = f"09-剧集制作/{episode}/其他资料/执行附件/{identity}-{run}-{stage}/模型提示词.txt"
        prompts = {"english": "", "chinese": ""}
        english_path = project / english_key
        if not english_path.is_file() or not english_path.resolve().is_relative_to(project):
            return prompts
        read_plain(english_key)
        snapshot = text_previews[english_key]
        if snapshot["notice"]:
            return prompts
        prompts["english"] = snapshot["text"]
        document_key = f"09-剧集制作/{episode}/05-视频提示词/{identity}-视频提示词.md"
        document = read(document_key)
        if document:
            english = re.search(r"^## 提交给(?:模型|节点263)的完整提示词\s*\n```text\s*\n(.*?)```", document, re.M | re.S)
            chinese = re.search(r"^## 中文提示词参考版\s*\n(?:(?!^## ).)*?```text\s*\n(.*?)```", document, re.M | re.S)
            if english and chinese and english[1].strip() == prompts["english"].strip():
                prompts["chinese"] = chinese[1].strip()
        return prompts

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
        elif kind == "video":
            prompts = video_prompts(key)
            if prompts is not None:
                item["prompts"] = prompts
        return item

    progress = read(PROGRESS)
    position = read(POSITION)
    if progress is None:
        warnings.append("尚未找到项目根目录的项目进度.md，顶部信息未记录；请核对实际进度入口。")
    if position is None:
        warnings.append("尚未形成正式定位，不以草稿代替。")
    rows = phase_rows(progress or "")
    active = [dict(row, anchor="phase-" + slug(row["name"]), statusHtml=status_markup(row["status"], PROGRESS), pendingHtml=inline(row["pending"], PROGRESS),
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
        for group in (*GROUPS, *LEGACY_GROUPS):
            if group in LEGACY_GROUPS and not any(
                    (project / directory / parent / group).is_dir() for parent in ("其他资料", "")):
                continue
            files = []
            for folder in (project / directory / "其他资料" / group, project / directory / group):
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
        summary_lines = re.findall(r"^-[ \t]*确认范围[:：].*$", intro, re.M)
        for key in (*meta, "项目名称或代号", "确认范围", "阅读边界"):
            intro = re.sub(r"^-[ \t]*" + re.escape(key) + r"[:：][^\n]*\n?", "", intro, flags=re.M)
        return {"exists": text is not None, "meta": meta,
                "headerHtml": documents[source].get("headerHtml", "") if text is not None else "",
                "url": quote(source, safe="/-._~"), "confirmationHtml": status_markup(meta["确认状态"], source),
                "boundaryHtml": inline(boundary, source) if boundary != "未记录" else "",
                "summaryHtml": markdown("\n".join(summary_lines), source),
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
                or not path.is_file() or not any(path.resolve().is_relative_to((project / parent).resolve())
                           for parent in ((required_parent,) if isinstance(required_parent, str) else required_parent))
                or not path.resolve().is_relative_to(project)):
            return None
        return dict(link)

    def review_section(review, heading):
        text = texts.get(review["key"], "")
        fragment = unquote(urlsplit(review["url"]).fragment)
        if fragment:
            headings = list(re.finditer(r"^(#{1,6}) (.+?)\s*$", text, re.M))
            start = next((h for h in headings if slug(h.group(2)) == fragment), None)
            if start is None:
                return ""
            end = next((h.start() for h in headings if h.start() > start.start()
                        and len(h.group(1)) <= len(start.group(1))), len(text))
            text = text[start.end():end]
        elif review["key"].endswith("-工作稿.md"):
            # A work document can contain different decisions for different outputs.
            return ""
        match = re.search(r"^(#{2,6}) " + re.escape(heading)
                          + r"\s*\n(.*?)(?=^#{1,6} |\Z)", text, re.M | re.S)
        return match.group(2) if match else ""

    def asset_review_metadata(reviews):
        purposes, applicability, decisions = [], [], []
        for review in reviews:
            section = review_section(review, "4. 用户确认")
            decision = field(section, "结论")
            if decision == "未记录":
                decision = field(section, "决定")
            decisions.append(decision)
            section = review_section(review, "5. 采用与后续影响")
            purposes.append(field(section, "留存用途"))
            applicability.append(field(section, "当前制作适用性"))
        return {
            "retentionPurpose": "；".join(purposes) or "未记录",
            "applicability": "；".join(applicability) or "待核对（未记录）",
            "reviewRecognized": bool(decisions) and all(re.match(r"^(待确认|待审核|批准采用|修改后再审|不采用|不通过)(?:$|[。；，\s])", d) for d in decisions),
            "coverApplicable": not any(re.match(r"^(不适用|待核对)(?:$|[。；，：\s])", a) for a in applicability),
        }

    def directory_assets(record_key, number, kind, registered, folder_key):
        folder_key = Path(folder_key)
        folder = project / folder_key
        known = {Path(a["media"]["key"]) for a in registered if a["media"]}
        assets = []
        if not folder.is_dir():
            return assets
        for path in sorted(folder.iterdir()):
            key = path.relative_to(project).as_posix()
            if path.name.startswith(".") or Path(key) in known:
                continue
            media = local_media({"key": key, "url": quote(key, safe="/-._~"), "name": path.name}, str(folder_key))
            if not media:
                continue
            if kind == "prop":
                match = re.fullmatch(re.escape(number) + r"-(.+)-道具参考图", path.stem)
                state = match.group(1) if match else path.stem
                image_type = "道具参考图"
            else:
                match = re.fullmatch(re.escape(number) + r"-(EP\d{3,}-C\d{3,}(?:-V\d{3,})?)-场景参考图", path.stem)
                state = match.group(1) if match else path.stem
                image_type = "场次环境图" if match else ("平面图" if "平面" in path.stem else "场景参考图")
            assets.append({kind: True, "type": image_type, "state": state, "media": media,
                           "scope": "目录收录；实际适用范围未记录", "version": "未记录",
                           "versionHtml": "未记录", "sourceHtml": "未记录", "recordUrl": None,
                           "reviews": [], "approved": False, "directoryDiscovered": True,
                           "retentionPurpose": "未记录", "applicability": "待核对（未记录）",
                           "reviewRecognized": False, "coverApplicable": False,
                           "statusHtml": status_markup("审核结果未记录", record_key)})
        return assets

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
        formal_folder = (Path(card_key).parent / "参考图").as_posix()
        work_key = PEOPLE + "/其他资料/工作稿/" + number + "-参考图-工作稿.md"
        record_key = work_key if (project / work_key).is_file() else formal_folder + "/生成记录.md"
        record = read(record_key) or ""
        formal, candidates = [], []
        formal_section = re.search(r"^## 1\. 当前正式资产\s*\n(.*?)(?=^## |\Z)", record, re.M | re.S)
        rows_formal = table_records(formal_section.group(1) if formal_section else "",
                                   ("图片类型", "人物状态", "服装状态", "正式文件", "采用的候选版本", "审阅记录"))
        for entry in rows_formal:
            links = markdown_links(entry["正式文件"], record_key)
            media = next((m for link in links if (m := local_media(link, formal_folder))), None)
            # Never promote candidates or history through a malformed registry link.
            if media and any(p in (*GROUPS, *LEGACY_GROUPS) for p in Path(media["key"]).parts):
                media = None
            reviews = markdown_links(entry["审阅记录"], record_key)
            decisions = []
            for review in reviews:
                decisions.append(field(review_section(review, "4. 用户确认"), "结论"))
            approved = bool(decisions) and all(re.match(r"^批准采用(?:$|[。；，\s])", d) for d in decisions)
            stage = ""
            if links:
                parent = Path(links[0]["key"]).parent
                if parent.parent == Path(formal_folder) and parent.name in stage_names:
                    stage = parent.name
            formal.append({"type": entry["图片类型"], "state": entry["人物状态"],
                           "stage": stage,
                           "costume": entry["服装状态"], "version": entry["采用的候选版本"],
                           "versionHtml": inline(entry["采用的候选版本"], record_key),
                           "recordUrl": formal_record_url(entry["采用的候选版本"], record, record_key),
                           "scope": entry.get("适用范围", "未记录"), "media": media,
                           "reviews": reviews, "approved": approved, **asset_review_metadata(reviews),
                           "statusHtml": "<br>".join(status_markup(d, record_key) for d in decisions)
                           or status_markup("未记录", record_key)})
        for match in re.finditer(r"^### (生成记录-\d+)\s*\n(.*?)(?=^### |\Z)", record, re.M | re.S):
            name, chunk = match.group(1), match.group(2)
            # Code fences can contain arbitrary prompts, not management fields.
            chunk = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", chunk, flags=re.M | re.S)
            output = field(chunk, "输出候选文件")
            media = [m for link in markdown_links(output, record_key)
                     if (m := local_media(link, (PEOPLE + "/其他资料/工作稿/素材", PEOPLE + "/其他资料/过程稿", PEOPLE + "/过程稿")))]
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
        cover = next((a for a in formal if a["media"] and a["approved"] and a["coverApplicable"] and a["type"] == "人物上半身正面肖像图"),
                     next((a for a in formal if a["media"] and a["approved"] and a["coverApplicable"] and a["type"] == "角色多视角参考图"), None))
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
        formal_folder = (Path(card_key).parent / "参考图").as_posix()
        work_key = PROPS + "/其他资料/工作稿/" + number + "-参考图-工作稿.md"
        record_key = work_key if (project / work_key).is_file() else formal_folder + "/生成记录.md"
        record = read(record_key) or ""
        formal, candidates = [], []
        formal_section = re.search(r"^## 1\. 当前正式资产\s*\n(.*?)(?=^## |\Z)", record, re.M | re.S)
        rows_formal = table_records(formal_section.group(1) if formal_section else "",
                                   ("状态名", "正式文件", "采用的候选版本", "审阅记录"))
        for entry in rows_formal:
            links = markdown_links(entry["正式文件"], record_key)
            media = next((m for link in links if (m := local_media(link, formal_folder))), None)
            # Never promote candidates or history through a malformed registry link.
            if media and Path(media["key"]).parent != Path(formal_folder):
                media = None
            reviews = markdown_links(entry["审阅记录"], record_key)
            decisions = []
            for review in reviews:
                decisions.append(field(review_section(review, "4. 用户确认"), "结论"))
            approved = bool(decisions) and all(re.match(r"^批准采用(?:$|[。；，\s])", d) for d in decisions)
            formal.append({"prop": True, "type": "道具参考图", "state": entry["状态名"], "version": entry["采用的候选版本"],
                           "versionHtml": inline(entry["采用的候选版本"], record_key),
                           "recordUrl": formal_record_url(entry["采用的候选版本"], record, record_key),
                           "scope": entry.get("适用范围", "未记录"), "media": media,
                           "sourceHtml": inline(entry.get("来源参考图及版本", "未记录"), record_key),
                           "reviews": reviews, "approved": approved, **asset_review_metadata(reviews),
                           "statusHtml": "<br>".join(status_markup(d, record_key) for d in decisions)
                           or status_markup("未记录", record_key)})
        for match in re.finditer(r"^### (生成记录-\d+)\s*\n(.*?)(?=^### |\Z)", record, re.M | re.S):
            name, chunk = match.group(1), match.group(2)
            # Code fences can contain arbitrary prompts, not management fields.
            chunk = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", chunk, flags=re.M | re.S)
            output = field(chunk, "输出候选文件")
            media = [m for link in markdown_links(output, record_key)
                     if (m := local_media(link, (PROPS + "/其他资料/工作稿/素材", PROPS + "/其他资料/过程稿", PROPS + "/过程稿")))]
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
        formal.extend(directory_assets(record_key, number, "prop", formal, formal_folder))
        prop_related = [{"name": group["name"], "files": [f for f in group["files"]
                          if any(part.startswith(number + "-") for part in Path(f["key"]).parts)]}
                         for group in prop_groups]
        # The current registry determines which images are eligible as covers.
        cover = next((a for a in formal if a["media"] and a["approved"] and a["coverApplicable"] and a["state"] == "基础"),
                     next((a for a in formal if a["media"] and a["approved"] and a["coverApplicable"]), None))
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
        formal_folder = (Path(card_key).parent / "参考图").as_posix()
        work_key = SCENES + "/其他资料/工作稿/" + number + "-参考图-工作稿.md"
        record_key = work_key if (project / work_key).is_file() else formal_folder + "/生成记录.md"
        record = read(record_key) or ""
        formal, auxiliary, candidates = [], [], []
        section = re.search(r"^## (?:1[.、] )?当前正式资产[^\n]*\n(.*?)(?=^## |\Z)", record, re.M | re.S)
        registry = table_records(section.group(1) if section else "", ("正式文件", "最初制作场次", "场景状态与适用条件", "采用的候选版本", "审阅记录"))
        for entry in registry:
            links = markdown_links(entry["正式文件"], record_key)
            media = next((m for link in links if (m := local_media(link, formal_folder))), None)
            if media and (Path(media["key"]).parent != Path(formal_folder)):
                media = None
            reviews = markdown_links(entry["审阅记录"], record_key)
            decisions = []
            for review in reviews:
                decisions.append(field(review_section(review, "4. 用户确认"), "结论"))
            approved = bool(decisions) and all(re.match(r"^批准采用(?:$|[。；，\s])", d) for d in decisions)
            scope = entry["场景状态与适用条件"]
            # Only an explicit scene-origin filename qualifies as an episode environment.
            is_environment = bool(links and re.fullmatch(re.escape(number) + r"-EP\d{3,}-C\d{3,}(?:-V\d{3,})?-场景参考图\.(?:png|jpg|jpeg|webp)", Path(links[0]["key"]).name))
            if re.search(r"仅.*(?:空间|布局|结构)|不是实际|仅供.*结构|结构辅助", scope):
                is_environment = False
            asset = {"scene": True, "type": "场次环境图" if is_environment else "辅助／既有参考图",
                     "state": entry["最初制作场次"] + (" · " + entry["视图编号与名称"] if entry.get("视图编号与名称") else ""), "scope": scope, "media": media,
                     "versionHtml": inline(entry["采用的候选版本"], record_key),
                           "recordUrl": formal_record_url(entry["采用的候选版本"], record, record_key),
                     "sourceHtml": inline(entry.get("来源参考图及版本", "未记录"), record_key),
                     "reviews": reviews, "approved": approved, **asset_review_metadata(reviews),
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
                media = local_media(link, (SCENES + "/其他资料/工作稿/素材", SCENES + "/其他资料/过程稿", SCENES + "/过程稿"))
                if not media or media["key"] in seen_outputs:
                    continue
                seen_outputs.add(media["key"])
                candidates.append({"scene": True, "type": "场景候选图", "state": origin,
                                   "scope": field(chunk, "本场次需求与状态"), "media": media,
                                   "reviews": reviews, "generation": name,
                                   "recordUrl": quote(record_key, safe="/-._~") + "#" + quote(name),
                                   **image_review_fields(chunk, record_key, agent_state, user_state)})
        # Formal directory files are confirmed assets; records enrich their metadata.
        for asset in directory_assets(record_key, number, "scene", formal + auxiliary, formal_folder):
            (formal if asset["type"] == "场次环境图" else auxiliary).append(asset)
        legacy = []
        related = [{"name": group["name"], "files": [f for f in group["files"]
                   if any(part.startswith(number + "-") for part in Path(f["key"]).parts)]} for group in scene_groups]
        cover = next((a for a in formal if a["media"] and a["approved"] and a["coverApplicable"]), None)
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
                key = Path(root).joinpath(*parts[:i]).as_posix()
                if key not in branches:
                    branches[key] = {"kind": "group", "name": part, "key": key, "children": []}
                    parent["children"].append(branches[key])
                parent = branches[key]
            parent["children"].append(item)
        for branch in branches.values():
            branch["children"].sort(key=file_order)
            if re.fullmatch(r"09-剧集制作/EP\d{3,}/02-剧集剧本", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    0 if re.fullmatch(r"EP\d{3,}-本集剧本\.md", item["name"]) else 1,
                    item["name"],
                ))
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/03-分镜脚本", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    file_order(item), item["name"],
                ))
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/03-分镜脚本/C\d{3,}-场次分镜", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    0 if re.fullmatch(r"EP\d{3,}-C\d{3,}-场次分镜\.md", item["name"]) else 1,
                    item["name"],
                ))
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/04-专用素材", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    0 if re.fullmatch(r"(?:EP\d{3,}-)?素材索引\.md", item["name"]) else
                    1 if re.fullmatch(r"(?:EP\d{3,}-)?素材生成记录\.md", item["name"]) else 2,
                    item["name"],
                ))
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/05-视频提示词", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    0 if re.fullmatch(r"EP\d{3,}-生成说明\.md", item["name"]) else 1,
                    item["name"],
                ))
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/06-生成结果/(?:(?:01|04)-场次成片/C\d{3,}-场次|(?:02|05)-整集成片)", branch["key"]):
                branch["children"].sort(key=lambda item: (
                    0 if re.fullmatch(r"EP\d{3,}(?:-C\d{3,})?-成片说明\.md", item["name"]) else 1,
                    file_order(item), item["name"],
                ))
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/06-生成结果/C\d{3,}-场次结果", branch["key"]):
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
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/06-生成结果/C\d{3,}-场次结果/P\d{3,}-分段结果/(01-一采|02-二采|03-后处理)/执行记录(?:/R\d{3,}-(?:一采|二采|后处理))?", branch["key"]):
                branch["children"].sort(key=lambda item: item["name"] != "监控说明.md")
            elif re.fullmatch(r"09-剧集制作/EP\d{3,}/其他资料/执行附件/EP\d{3,}-C\d{3,}-P\d{3,}-R\d{3,}-(?:一采|二采|后处理)", branch["key"]):
                branch["children"].sort(key=lambda item: item["name"] != "监控说明.md")
        return node

    catalogues = {}
    outline_root = "06-分集大纲"
    outline_index = outline_root + "/分集索引.md"
    outline_text = read(outline_index) or ""
    outline_items, indexed, planned_episodes = [], set(), set()
    for row in table_records(outline_text, ("集号", "一句话概要", "大纲入口")):
        number = row["集号"]
        if not re.fullmatch(r"EP\d{3,}", number):
            continue
        planned_episodes.add(number)
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
        library_files = inventory(root)
        process_files = [f for f in library_files if f["key"].startswith(root + "/其他资料/")]
        leftover = [f for f in library_files if f["key"] not in referenced and f["key"] != index_key
                    and not f["key"].startswith(root + "/其他资料/")]
        catalogues[root] = {"kind": "group", "key": root, "name": label, "categories": list(categories),
            "note": "按现有索引展示用途、来源、时长及审核依据；不自动播放、不加工素材，也不将文件存在解释为已审核。",
            "indexKey": index_key if media_index_text else None, "children": media_items +
            ([dict(file_tree(leftover, root, "未登记／其他文件"), note="索引未关联的文件仅供核对，不推断用途、授权或采用状态。")] if leftover else []) +
            ([file_tree(process_files, root + "/其他资料", "其他资料")] if process_files else [])}

    production = "09-剧集制作"
    existing_episodes = {}
    episode_videos = {}
    generation_contexts = {}
    if web_episode_navigation:
        from .generation import resolve_context
    production_statuses = {match[1]: row["status"] for row in rows
                           if (match := re.fullmatch(r"(EP\d{3,})\s*制作", row["name"]))}
    folder = project / production
    for episode in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not episode.is_dir() or not re.fullmatch(r"EP\d{3,}", episode.name) or not episode.resolve().is_relative_to(project):
            continue
        root = episode.relative_to(project).as_posix()
        files = inventory(root)
        episode_videos[episode.name] = [item for item in files if item["kind"] == "video"]
        if web_episode_navigation:
            for item in files:
                if item["name"] != "输入映射.json" or "执行附件" not in Path(item["key"]).parts:
                    continue
                snapshot = text_previews[item["key"]]
                mapping_text = ((project / item["key"]).read_text("utf-8-sig")
                                if snapshot["notice"] else snapshot["text"])
                for context in json.loads(mapping_text).get("generation_contexts", []):
                    identity = context["identity"]
                    if not re.fullmatch(re.escape(episode.name) + r"-C\d{3,}-P\d{3,}-R\d{3,}-(一采|二采|后处理)", identity):
                        raise ValueError(item["key"] + "：生成资料身份格式不正确")
                    if identity in generation_contexts:
                        raise ValueError("生成资料关联重复：" + identity)
                    generation_contexts[identity] = context
        children = file_tree(files, root, episode.name)["children"]
        present = {item["name"] for item in children}
        for directory in sorted(episode.iterdir()):
            if (directory.is_dir() and not directory.name.startswith(".")
                    and directory.resolve().is_relative_to(project) and directory.name not in present):
                children.append(file_tree([], root + "/" + directory.name, directory.name))
        children.sort(key=lambda item: (file_order(item), item["name"]))
        existing_episodes[episode.name] = {"kind": "group", "name": episode.name, "key": root,
            "summary": str(len(files)) + " 份文件",
            "children": children,
        }
    episode_numbers = planned_episodes | existing_episodes.keys()
    episodes = []
    counts = {"未开始": 0, "进行中": 0, "已完成": 0}
    for number in sorted(episode_numbers, key=lambda value: int(value[2:])):
        raw_status = production_statuses.get(number)
        state = ("已完成" if raw_status == "已完成" else "进行中"
                 if raw_status in ("进行中", "待确认") or (number in existing_episodes and raw_status != "未开始")
                 else "未开始")
        counts[state] += 1
        if not web_episode_navigation and number not in existing_episodes:
            continue
        episode_node = existing_episodes.get(number) or {
            "kind": "group", "name": number, "key": production + "/" + number, "children": []}
        title_match = re.search(r"^(?:-[ \t]*)?本集题名[:：][ \t]*([^。\n]+)",
                               read(outline_root + "/" + number + "-分集大纲.md") or "", re.M)
        episode_node.update({"title": title_match[1].strip() if title_match else "",
            "statusHtml": status_markup(state if web_episode_navigation else raw_status or "未记录", PROGRESS),
            "note": "等待审阅也属于进行中；整集完成以项目进度为准。"})
        if web_episode_navigation:
            script = read(production + "/" + number + "/02-剧集剧本/" + number + "-本集剧本.md") or ""
            script_body = re.search(r"^##[ \t]+1\.[ \t]*故事剧本正文[ \t]*\n(.*?)(?=^##[ \t]|\Z)", script, re.M | re.S)
            episode_node["scenes"] = list(dict.fromkeys(re.findall(
                r"^###[ \t]+" + re.escape(number) + r"-(C\d{3,})[ \t]*$",
                script_body[1] if script_body else "", re.M)))
            episode_node["segments"] = {scene: [] for scene in episode_node["scenes"]}
            storyboard_index = production + "/" + number + "/03-分镜脚本/" + number + "-分镜索引.md"
            for row in table_records(read(storyboard_index) or "", ("场次", "分段", "分段计划时长（秒）")):
                identity = re.fullmatch(re.escape(number) + r"-(C\d{3,})-(P\d{3,})", row["分段"])
                if not identity or identity[1] not in episode_node["segments"] or row["场次"] != number + "-" + identity[1]:
                    continue
                duration = row["分段计划时长（秒）"]
                if not re.fullmatch(r"\d+(?:\.\d+)?", duration) or float(duration) <= 0:
                    raise ValueError(storyboard_index + "：" + row["分段"] + "的分段计划时长必须为正数秒")
                storyboard_source = production + "/" + number + "/03-分镜脚本/" + number + "-" + identity[1] + "-场次分镜.md"
                shots = re.search(r"^##[ \t]+1\.[ \t]*镜头正文[ \t]*\n(.*?)(?=^##[ \t]|\Z)",
                                  read(storyboard_source) or "", re.M | re.S)
                segment_script = re.search(r"^###[ \t]+分段[ \t]+" + re.escape(identity[2])
                                           + r"[ \t]*\n.*?(?=^###[ \t]|\Z)", shots[1], re.M | re.S) if shots else None
                shot_body = re.search(r"^####[ \t]+", segment_script[0], re.M) if segment_script else None
                script_text = segment_script[0][shot_body.start():] if shot_body else ""
                script_text = re.sub(r"(^####[ \t]+(EP\d+-SH\d+)[ \t]*\n)\s*\*\*镜号\*\*[：:][ \t]*\2[ \t]*(?=\n|$)",
                                     r"\1", script_text, flags=re.M)
                videos = []
                segment_identity = row["分段"]
                episode_root = production + "/" + number
                record_key = episode_root + "/其他资料/工作稿/" + segment_identity + "-视频制作-工作稿.md"
                record = read(record_key)
                if record is None:
                    record_key = episode_root + "/其他资料/执行附件/" + segment_identity + "-生成记录.md"
                    record = read(record_key) or ""
                current_results = re.search(r"^## 1\. 当前选定结果\s*\n(.*?)(?=^## |\Z)", record, re.M | re.S)
                approved_keys = set()
                for adopted in table_records(current_results[1] if current_results else "", ("处理阶段", "当前选定文件", "R编号", "人工批准依据")):
                    run_entry = re.search(r"^### " + re.escape(adopted["R编号"]) + r"(?!\d)[^\n]*\n(.*?)(?=^### |^## |\Z)", record, re.M | re.S)
                    if (run_entry and re.match(r"^批准采用(?:$|[。；，\s])", field(run_entry[1], "用户决定"))
                            and field(run_entry[1], "处理阶段").startswith(adopted["处理阶段"])):
                        approved_keys.update(link["key"] for link in markdown_links(adopted["当前选定文件"], record_key)
                            if re.fullmatch(re.escape(segment_identity + "-" + adopted["R编号"] + "-" + adopted["处理阶段"])
                                            + r"\.(?:mp4|webm|mov)", Path(link["key"]).name))
                for item in episode_videos.get(number, []):
                    take = re.fullmatch(re.escape(segment_identity) + r"-(R\d{3,})-(一采|二采|后处理)\.(?:mp4|webm|mov)", item["name"])
                    if not take:
                        continue
                    stage_folder = {"一采": "01-一采", "二采": "02-二采", "后处理": "03-后处理"}[take[2]]
                    legacy_root = episode_root + "/06-生成结果/" + identity[1] + "-场次结果/" + identity[2] + "-分段结果/" + stage_folder
                    folders = (episode_root + "/其他资料/候选视频",
                               episode_root + "/其他资料/阶段采用视频/" + stage_folder + "/" + identity[1] + "-场次",
                               episode_root + "/06-生成结果/" + stage_folder + "/" + identity[1] + "-场次",
                               legacy_root + "/候选", legacy_root + "/选定")
                    if Path(item["key"]).parent.as_posix() in folders:
                        stat = (project / item["key"]).stat()
                        revision = str(stat.st_mtime_ns) + "-" + str(stat.st_size)
                        entry = re.search(r"^### " + re.escape(take[1]) + r"(?!\d)[^\n]*\n(.*?)(?=^### |^## |\Z)", record, re.M | re.S)
                        body = entry[1] if entry else ""
                        task_body = body
                        for link in markdown_links(field(body, "共同任务证据与状态入口"), record_key):
                            anchor = unquote(urlsplit(link["url"]).fragment)
                            if (link["key"].endswith("-视频制作-工作稿.md")
                                    and re.fullmatch(r"r\d{3,}", anchor, re.I)):
                                owner = read(link["key"]) or ""
                                task_entry = re.search(r"^### " + anchor.upper() + r"(?!\d)[^\n]*\n(.*?)(?=^### |^## |\Z)", owner, re.M | re.S)
                                task_body = task_entry[1] if task_entry else ""
                                break
                        videos.append({"key": item["key"], "url": item["url"], "run": take[1], "stage": take[2],
                                       "approved": item["key"] in approved_keys, "fileRevision": revision,
                                       "deliveryStatus": field(body, "取回核对状态"),
                                       "taskStatus": field(task_body, "任务状态"),
                                       "checkedAt": field(task_body, "最近检查时间")})
                        videos[-1]["url"] += "?v=" + revision
                videos.sort(key=lambda item: (int(item["run"][1:]), item["stage"], item["key"]))
                stage_counts = {"一采": 0, "二采": 0, "后处理": 0}
                for video in videos:
                    stage_counts[video["stage"]] += 1
                    video["candidateNumber"] = stage_counts[video["stage"]]
                    video["context"] = resolve_context(segment_identity + "-" + video["run"] + "-" + video["stage"],
                        generation_contexts, project, read, read_plain, text_previews)
                episode_node["segments"][identity[1]].append({"id": identity[2], "duration": float(duration),
                    "scriptHtml": markdown(script_text, storyboard_source),
                    "videos": videos,
                    **({"scriptUrl": quote(storyboard_source, safe="/-._~")} if read(storyboard_source) is not None else {})})
        episodes.append(episode_node)
    catalogues[production] = {"kind": "group", "key": production, "name": "剧集制作", "children": episodes,
        "statistics": {"total": len(episode_numbers), "completed": counts["已完成"],
                       "notStarted": counts["未开始"], "running": counts["进行中"]},
        "note": "选择剧集查看本集内容。"}
    catalogues["历史版本"] = dict(file_tree(inventory("历史版本"), "历史版本", "历史版本"),
        note="以下是项目根目录的历史归档，仅供追溯，不代表当前设定或当前批准。各阶段自己的历史文件仍在对应标签中。")

    directories = [{"name": p.name, "label": re.sub(r"^\d+-", "", p.name),
                    "url": quote(p.name, safe="-._~") + "/"}
                   for p in sorted(project.iterdir())
                   if p.is_dir() and not p.name.startswith(".") and p.name not in ("99-综合资料", "其他资料")]
    meta = {key: field(position or "", key) for key in ("文档版本", "更新日期", "确认状态")}
    body = position or ""
    body = re.sub(r"^# .+\n?", "", body, count=1)
    for key in meta:
        body = re.sub(r"^-\s*" + re.escape(key) + r"[:：].*\n?", "", body, flags=re.M)
    body = re.sub(r"^- 项目名称(?:或代号)?[:：].*\n?", "", body, flags=re.M)
    first_section = re.search(r"^## ", body, re.M)
    intro, main = (body[:first_section.start()], body[first_section.start():]) if first_section else ("", body)
    summary_lines = re.findall(r"^-\s*确认范围[:：].*$", intro, re.M)
    intro = re.sub(r"^-\s*确认范围[:：].*\n?", "", intro, flags=re.M)
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
        "positionExists": position is not None, "positionTitle": (field(position or "", "项目名称或代号")
            if field(position or "", "项目名称或代号") != "未记录" else field(position or "", "项目名称")).rstrip("。"), "meta": meta,
        "confirmationHtml": status_markup(meta["确认状态"], POSITION),
        "headerHtml": documents[POSITION].get("headerHtml", "") if position is not None else "",
        "summaryHtml": markdown("\n".join(summary_lines), POSITION),
        "introHtml": intro_markup(intro), "positionHtml": markdown(main, POSITION),
        "warnings": warnings, "sources": sources,
    }
