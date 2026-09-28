"""Local fixture tests. Never opens a browser, calls ComfyUI, or mutates real projects."""
import json
from pathlib import Path
import re
import tempfile
import unittest

import build_project_portal as portal


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_video_prompts_match_execution_identity_and_translation(self):
        episode = "09-剧集制作/EP001"
        segment = episode + "/06-生成结果/C001-场次结果/P001-分段结果"
        document = episode + "/05-视频提示词/EP001-C001-P001-视频提示词.md"
        english = "Actual <Subject 1> & dialogue"
        self.put(document, "## 提交给节点263的完整提示词\n\n```text\n" + english +
                 "\n```\n\n## 中文提示词参考版\n\n说明\n\n```text\n中文参考正文\n```\n")
        expected = {}
        for stage, run, location, text in [("01-一采", "R001", "选定", english),
                                           ("02-二采", "R002", "候选", english),
                                           ("01-一采", "R003", "候选", "Different historical prompt")]:
            self.put(f"{segment}/{stage}/执行记录/{run}-{stage[3:]}/模型提示词.txt", text)
            video = f"{segment}/{stage}/{location}/EP001-C001-P001-{run}-{stage[3:]}.mp4"
            self.put(video, "video fixture")
            expected[video] = {"english": text, "chinese": "中文参考正文" if text == english else ""}
        missing = segment + "/01-一采/候选/EP001-C001-P001-R004-一采.mp4"
        self.put(missing, "video fixture")
        expected[missing] = {"english": "", "chinese": ""}
        excluded = [segment + "/03-后处理/选定/EP001-C001-P001-R005-后处理.mp4",
                    episode + "/06-生成结果/C001-场次结果/场次成片/候选/EP001-C001-一采合并.mp4",
                    segment + "/01-一采/候选/EP001-C001-P002-R001-一采.mp4"]
        for path in excluded:
            self.put(path, "video fixture")
        portal.build(self.root)
        videos = {}
        def visit(node):
            if node["kind"] == "video":
                videos[node["key"]] = node
            for child in node.get("children", []):
                visit(child)
        visit(self.extract()["catalogues"]["09-剧集制作"])
        for key, prompts in expected.items():
            self.assertEqual(videos[key]["prompts"], prompts)
        for key in excluded:
            self.assertNotIn("prompts", videos[key])

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def extract(self):
        output = (self.root / "项目总览.html").read_text("utf-8")
        return json.loads(re.search(r'id="portal-data">(.*?)</script>', output, re.S).group(1))

    def test_episode_materials_index_record_then_images_by_filename(self):
        for episode, prefix in (("EP001", ""), ("EP002", "EP002-")):
            root = f"09-剧集制作/{episode}/04-专用素材"
            for name in [prefix + "C002-P001-首帧参考图.png", prefix + "素材生成记录.md",
                         prefix + "C001-P002-首帧参考图.png", prefix + "素材索引.md",
                         prefix + "C001-P001-首帧参考图.png"]:
                self.put(root + "/" + name, "fixture")
        portal.build(self.root)
        episodes = self.extract()["catalogues"]["09-剧集制作"]["children"]
        for episode, prefix in zip(episodes, ("", "EP002-")):
            entries = episode["children"][0]["children"]
            self.assertEqual([e["name"] for e in entries], [prefix + name for name in
                             ["素材索引.md", "素材生成记录.md", "C001-P001-首帧参考图.png",
                              "C001-P002-首帧参考图.png", "C002-P001-首帧参考图.png"]])

    def test_indexes_then_files_then_folders_at_each_level(self):
        root = "09-剧集制作/EP001"
        paths = ["EP001-制作索引.md", "03-分镜/EP001-分镜索引.md",
                 "03-分镜/C001-场次分镜/EP001-C001-分镜.md",
                 "03-分镜/A-说明.md", "03-分镜/EP001-分镜索引-草稿-v01.md",
                 "02-剧本/EP001-故事剧本.md", "02-剧本/分场剧本/EP001-C001-分场剧本.md"]
        for path in paths:
            self.put(root + "/" + path, "# 正文")
        self.put("00-项目定位/过程稿/A-说明.md", "# 说明")
        self.put("00-项目定位/过程稿/Z-资料索引.md", "# 索引")
        portal.build(self.root)
        data = self.extract()
        children = data["catalogues"]["09-剧集制作"]["children"][0]["children"]
        self.assertEqual([c["name"] for c in children], ["EP001-制作索引.md", "02-剧本", "03-分镜"])
        self.assertEqual([c["name"] for c in children[2]["children"]],
                         ["EP001-分镜索引.md", "A-说明.md", "EP001-分镜索引-草稿-v01.md", "C001-场次分镜"])
        self.assertEqual([c["name"] for c in children[1]["children"]],
                         ["EP001-故事剧本.md", "分场剧本"])
        self.assertEqual(data["groups"][1]["files"][0]["name"], "Z-资料索引.md")
        self.assertTrue(all(root + "/" + path in data["documents"] for path in paths))

    def test_folder_previews_cover_documents_text_media_and_unknown_files(self):
        base = "00-项目定位/过程稿/"
        expected = {"md": "document", "json": "text", "txt": "text", "log": "text",
                    "png": "image", "mp4": "video", "wav": "audio", "zip": "file"}
        payload = '</script><img src=x onerror="alert(1)">'
        for extension in expected:
            self.put(base + "附件." + extension, payload)
        portal.build(self.root)
        data = self.extract()
        files = data["groups"][1]["files"]
        self.assertEqual({Path(f["key"]).suffix[1:]: f["kind"] for f in files}, expected)
        self.assertEqual(data["textPreviews"][base + "附件.json"]["text"], payload)
        self.assertNotIn(base + "附件.png", data["textPreviews"])
        self.assertIn(base + "附件.json", data["sources"])
        self.assertNotIn(payload, (self.root / "项目总览.html").read_text())

    def test_plain_text_preview_is_bounded_and_invalid_utf8_does_not_break_page(self):
        base = "00-项目定位/过程稿/"
        self.put(base + "大.json", "中" * 100000)
        bad = self.put(base + "错误.log", "")
        bad.write_bytes(b"\xff\xfe")
        portal.build(self.root)
        previews = self.extract()["textPreviews"]
        self.assertLessEqual(len(previews[base + "大.json"]["text"].encode()), 256 * 1024)
        self.assertIn("截取", previews[base + "大.json"]["notice"])
        self.assertIn("UTF-8", previews[base + "错误.log"]["notice"])
        self.assertEqual(previews[base + "错误.log"]["text"], "")

    def test_catalogue_and_folders_share_preview_types(self):
        self.put("历史版本/批次/工作流.json", '{"value": 1}')
        portal.build(self.root)
        data = self.extract()
        item = data["catalogues"]["历史版本"]["children"][0]["children"][0]
        self.assertEqual(item["kind"], "text")
        self.assertEqual(data["textPreviews"][item["key"]]["text"], '{"value": 1}')

    def test_formal_generation_links_use_explicit_generation_not_candidate_version(self):
        from urllib.parse import unquote
        record = "### 生成记录-009\n正文\n### 生成记录-026\n正文\n"
        for version in ("v08／生成026", "v08 / 生成记录-026", "v13／生成026（测试001转正式）"):
            self.assertEqual(unquote(portal.formal_record_url(version, record, "参考图/生成记录.md")),
                             "参考图/生成记录.md#生成记录-026")
        for version in ("v26", "v08／生成099", "生成009／生成026"):
            self.assertEqual(unquote(portal.formal_record_url(version, record, "参考图/生成记录.md")),
                             "参考图/生成记录.md")

    def test_all_formal_asset_kinds_link_to_existing_generation_sections(self):
        from urllib.parse import unquote
        records = [self.person_fixture()[1], self.prop_fixture(), self.scene_fixture()[1]]
        for record in records:
            record.write_text(record.read_text().replace("| v01 |", "| v01／生成001 |"))
        data = portal.build_data(self.root.resolve())
        for kind in ("people", "props", "scenes"):
            owner = data[kind][0]
            asset = next(a for a in owner["formal"] if "v01" in a["versionHtml"])
            self.assertEqual(unquote(asset["recordUrl"]), owner["recordKey"] + "#生成记录-001")

    def person_fixture(self, decision="批准采用。"):
        base = "03-人物资料"
        self.put(base + "/人物索引.md", "# 人物索引\n| 人物编号 | 姓名 | 人物定位 | 资料卡入口 |\n"
                 "| --- | --- | --- | --- |\n| CH001 | 小林 | 主角 | [卡](CH001-小林/CH001-小林-人物资料卡.md) |\n")
        card = self.put(base + "/CH001-小林/CH001-小林-人物资料卡.md",
                        "# 人物资料卡\n- 确认状态：已确认；仅文字。\n## 基本信息\n原文\n")
        self.put(base + "/CH001-小林/参考图/正式.png", "fixture image")
        self.put(base + "/过程稿/CH001-肖像-草稿-v01.png", "fixture candidate")
        self.put(base + "/审阅记录/CH001-审阅-001.md", "# 审阅\n## 4. 用户确认\n- 结论：" + decision)
        record = self.put(base + "/CH001-小林/参考图/生成记录.md",
                 "# 记录\n## 1. 当前正式资产\n"
                 "| 图片类型 | 人物状态 | 服装状态 | 正式文件 | 采用的候选版本 | 审阅记录 |\n"
                 "| --- | --- | --- | --- | --- | --- |\n\n"
                 "| 人物上半身正面肖像图 | 少年 | 基础服 | [图](正式.png) | v01 | [审阅](../../审阅记录/CH001-审阅-001.md) |\n"
                 "\n## 2. 逐次生成记录\n### 生成记录-001\n"
                 "- 图片类型：人物上半身正面肖像图。\n- 人物状态：少年。\n- 服装状态：基础服。\n"
                 "- 输出候选文件：[v01](../../过程稿/CH001-肖像-草稿-v01.png)\n"
                 "- agent 画面初审结论：通过；不等于用户批准。\n- 用户采用状态：待确认。\n"
                 "- 审阅记录：[审阅](../../审阅记录/CH001-审阅-001.md)\n")
        return card, record

    def test_auxiliary_directories_preserve_asset_reviews_and_exclude_execution_images(self):
        records = [("people", "03-人物资料", self.person_fixture()[1]),
                   ("props", "05-道具资料", self.prop_fixture()),
                   ("scenes", "04-场景资料", self.scene_fixture()[1])]
        before = portal.build_data(self.root.resolve())
        for kind, stage, record in records:
            for group in ("过程稿", "审阅记录"):
                source = self.root / stage / group
                target = self.root / stage / "其他资料" / group
                target.parent.mkdir(exist_ok=True)
                source.rename(target)
            record.write_text(record.read_text().replace("../../过程稿/", "../../其他资料/过程稿/")
                              .replace("../../审阅记录/", "../../其他资料/审阅记录/"))
            number = before[kind][0]["id"]
            self.put(stage + "/其他资料/执行附件/" + number + "-请求.json", '{"prompt": {}}')
            self.put(stage + "/其他资料/执行附件/" + number + "-技术检查.png", "fixture")
        after = portal.build_data(self.root.resolve())
        for kind, stage, record in records:
            person = after[kind][0]
            self.assertEqual(len(person["candidates"]), len(before[kind][0]["candidates"]))
            self.assertEqual([x["approved"] for x in person["formal"]],
                             [x["approved"] for x in before[kind][0]["formal"]])
            self.assertTrue(all("/其他资料/过程稿/" in c["media"]["key"] for c in person["candidates"]))
            groups = {g["name"]: g["files"] for g in person["groups"]}
            self.assertEqual(len(groups["执行附件"]), 2)
            self.assertTrue(all("/执行附件/" not in c["media"]["key"] for c in person["candidates"]))

    def test_auxiliary_groups_include_new_and_unmigrated_files_once(self):
        for name in ("其他资料/讨论记录/新.md", "讨论记录/旧.md", "其他资料/执行附件/请求.json"):
            self.put("00-项目定位/" + name, "fixture")
        data = portal.build_data(self.root.resolve())
        groups = {g["name"]: g["files"] for g in data["groups"]}
        self.assertEqual(len(groups["讨论记录"]), 2)
        self.assertEqual(len(groups["执行附件"]), 1)
        keys = [f["key"] for g in data["groups"] for f in g["files"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_candidate_stage_order_does_not_depend_on_formal_assets(self):
        card, record = self.person_fixture()
        card.write_text(card.read_text() + "\n## 3. 外貌与基础造型\n### 3.1 成年\n成年外貌\n### 3.2 少年\n少年外貌\n")
        data = portal.build_data(self.root.resolve())
        self.assertEqual(data["people"][0]["stages"], [])
        self.assertEqual(data["people"][0]["candidateStages"], ["成年", "少年"])
        self.assertEqual(len(data["people"][0]["candidates"]), 1)

    def test_two_stage_review_content_deviation_does_not_block_user_review(self):
        records = [("people", self.person_fixture()[1]),
                   ("props", self.prop_fixture()), ("scenes", self.scene_fixture()[1])]
        for group, record in records:
            record.write_text(re.sub(r"- agent 画面初审结论：[^\n]*",
                "- agent 技术审查结论：通过\n- agent 内容审查状态：已完成\n"
                "- agent 内容审查发现：有偏差；肩部裁切 <script>bad</script>", record.read_text()))
        before = {str(r): r.read_bytes() for _, r in records}
        portal.build(self.root)
        data = self.extract()
        for group, record in records:
            candidate = data[group][0]["candidates"][0]
            self.assertTrue(candidate["twoStageReview"])
            self.assertTrue(candidate["pending"])
            self.assertIn("通过", candidate["technicalHtml"])
            self.assertIn("有偏差", candidate["contentFindingsHtml"])
            self.assertNotIn("<script>", candidate["contentFindingsHtml"])
            self.assertEqual(record.read_bytes(), before[str(record)])
            self.assertIn("待确认", candidate["userHtml"])

    def test_technical_failure_or_unfinished_review_is_not_pending_approval(self):
        _, record = self.person_fixture()
        original = record.read_text()
        for technical, content in [("不通过", "未进行"), ("待确认", "未进行"),
                                   ("通过", "未进行"), ("未记录", "已完成")]:
            with self.subTest(technical=technical, content=content):
                record.write_text(re.sub(r"- agent 画面初审结论：[^\n]*",
                    f"- agent 技术审查结论：{technical}\n- agent 内容审查状态：{content}\n"
                    "- agent 内容审查发现：技术审查未通过，未进行内容审查", original))
                portal.build(self.root)
                person = self.extract()["people"][0]
                self.assertFalse(person["candidates"][0]["pending"])
                self.assertEqual(person["pendingCount"], 0)
                self.assertTrue(person["formal"][0]["approved"])
        record.write_text(original)
        portal.build(self.root)
        candidate = self.extract()["people"][0]["candidates"][0]
        self.assertFalse(candidate["twoStageReview"])
        self.assertTrue(candidate["pending"])
        self.assertIn("通过", candidate["agentHtml"])

    def test_scene_assets_survive_multiple_production_episodes(self):
        self.scene_fixture()
        portal.build(self.root)
        expected = self.extract()["scenes"]
        for episode, scene in (("EP001", "C001"), ("EP002", "C002")):
            self.put(f"09-剧集制作/{episode}/03-分镜/{scene}-场次分镜/{episode}-{scene}-场次分镜.md", "# 分镜")
        portal.build(self.root)
        data = self.extract()
        self.assertEqual(data["scenes"], expected)
        episodes = data["catalogues"]["09-剧集制作"]["children"]
        self.assertEqual(len(episodes), 2)
        for episode, scene in zip(episodes, ("C001", "C002")):
            self.assertEqual(episode["children"][0]["name"], "03-分镜")
            self.assertEqual(episode["children"][0]["children"][0]["name"], scene + "-场次分镜")

    def test_people_index_survives_empty_media_libraries(self):
        self.person_fixture()
        portal.build(self.root)
        data = self.extract()
        self.assertEqual(data["peopleIndex"], "03-人物资料/人物索引.md")
        self.assertIn(data["peopleIndex"], data["documents"])

    def test_media_index_does_not_create_missing_people_index(self):
        self.put("08-参考视频/参考视频索引.md", "# 参考视频索引")
        portal.build(self.root)
        data = self.extract()
        self.assertIsNone(data["peopleIndex"])
        self.assertEqual(data["catalogues"]["08-参考视频"]["indexKey"], "08-参考视频/参考视频索引.md")

    def test_catalogue_outlines_follow_index_not_production_status(self):
        self.put("06-分集大纲/分集索引.md", "# 索引\n| 集号 | 所属故事阶段 | 一句话概要 | 大纲入口 |\n| --- | --- | --- | --- |\n| EP001 | 第一阶段 | 原概要 | [文档](EP001-分集大纲.md) |\n| EP002 | 第二阶段 | 缺文件 | [文档](EP002-分集大纲.md) |")
        source = self.put("06-分集大纲/EP001-分集大纲.md", "# EP001\n- 确认状态：已确认\n## 剧情\n原剧情")
        portal.build(self.root)
        items = self.extract()["catalogues"]["06-分集大纲"]["children"]
        self.assertEqual([i["name"] for i in items], ["EP001", "EP002"])
        self.assertEqual(items[0]["category"], "第一阶段")
        self.assertFalse(items[1]["doc"]["exists"])
        self.assertEqual(source.read_text("utf-8"), "# EP001\n- 确认状态：已确认\n## 剧情\n原剧情")
        self.assertEqual(self.extract()["catalogues"]["09-剧集制作"]["children"], [])

    def test_outline_without_stage_column_remains_readable(self):
        self.put("06-分集大纲/分集索引.md", "# 索引\n| 集号 | 一句话概要 | 大纲入口 |\n| --- | --- | --- |\n| EP001 | 原概要 | [文档](EP001-分集大纲.md) |")
        self.put("06-分集大纲/EP001-分集大纲.md", "# EP001\n## 本集剧情\n正文")
        portal.build(self.root)
        item = self.extract()["catalogues"]["06-分集大纲"]["children"][0]
        self.assertEqual(item["name"], "EP001")
        self.assertEqual(item["category"], "")
        self.assertTrue(item["doc"]["exists"])
        self.assertIn("正文", item["doc"]["bodyHtml"])

    def test_catalogue_media_uses_recorded_metadata_and_missing_file(self):
        self.put("07-参考音频/参考音频索引.md", "# 索引\n| 编号 | 名称 | 分类 | 文件入口 | 参考用途与适用范围 | 来源及使用授权说明 | 实测时长 | 审核／采用状态及版本依据 |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| RA001 | 声音 | 人物声音 | [音频](人物声音/RA001.wav) | 音色 | 用户自制 | 未测 | 待确认 |\n| RA002 | 缺失 | 环境声音 | [音频](环境声音/RA002.wav) | 风 | 未记录 | 未测 | 未记录 |")
        self.put("07-参考音频/人物声音/RA001.wav", "fixture audio")
        self.put("07-参考音频/环境声音/未登记.mp3", "loose file")
        portal.build(self.root)
        audio = self.extract()["catalogues"]["07-参考音频"]
        self.assertEqual(audio["children"][0]["media"]["kind"], "audio")
        self.assertEqual(audio["children"][0]["duration"], "未测")
        self.assertIn("status-orange", audio["children"][0]["statusHtml"])
        self.assertIsNone(audio["children"][1]["media"])
        self.assertEqual(audio["children"][2]["name"], "未登记／其他文件")

    def test_catalogue_empty_libraries_do_not_create_directories(self):
        portal.build(self.root)
        for root in ("07-参考音频", "08-参考视频"):
            self.assertEqual(self.extract()["catalogues"][root]["children"], [])
            self.assertFalse((self.root / root).exists())

    def test_scene_results_show_finished_scene_before_numeric_segments(self):
        root = "09-剧集制作/EP001/06-生成结果/C001-场次结果"
        names = ["P1000-分段结果", "P010-分段结果", "P002-分段结果", "P001-分段结果", "场次成片", "其他资料"]
        for name in names:
            self.put(root + "/" + name + "/记录.md", "# 记录")
        self.put(root + "/说明.md", "# 说明")
        self.put(root + "/场次索引.md", "# 索引")
        other = "09-剧集制作/EP001/05-视频提示词/C001-场次生成资料"
        for name in ("P001-分段结果", "场次成片"):
            self.put(other + "/" + name + "/记录.md", "# 其他层级不受影响")
        portal.build(self.root)
        ep = self.extract()["catalogues"]["09-剧集制作"]["children"][0]
        results = next(n for n in ep["children"] if n["name"] == "06-生成结果")["children"][0]
        self.assertEqual([n["name"] for n in results["children"]],
                         ["场次索引.md", "说明.md", "场次成片", "P001-分段结果", "P002-分段结果", "P010-分段结果", "P1000-分段结果", "其他资料"])
        preparation = next(n for n in ep["children"] if n["name"] == "05-视频提示词")["children"][0]
        self.assertEqual([n["name"] for n in preparation["children"]], ["P001-分段结果", "场次成片"])
        self.assertTrue((self.root / root / "P001-分段结果/记录.md").is_file())

    def test_segment_stage_folders_follow_review_order(self):
        root = "09-剧集制作/EP001/06-生成结果/C001-场次结果/P001-分段结果"
        stages = ("01-一采", "02-二采", "03-后处理")
        for stage in stages:
            for name in ("执行记录", "候选", "其他附件", "选定", "审阅记录"):
                self.put(root + "/" + stage + "/" + name + "/记录.md", "# 记录")
            self.put(root + "/" + stage + "/说明.md", "# 说明")
        self.put(root + "/04-其他/选定/记录.md", "# 记录")
        self.put(root + "/04-其他/执行记录/记录.md", "# 记录")
        portal.build(self.root)
        ep = self.extract()["catalogues"]["09-剧集制作"]["children"][0]
        segment = ep["children"][0]["children"][0]["children"][0]
        self.assertEqual(segment["name"], "P001-分段结果")
        for stage in segment["children"][:3]:
            self.assertEqual([n["name"] for n in stage["children"]],
                             ["说明.md", "选定", "候选", "审阅记录", "执行记录", "其他附件"])
        self.assertEqual([n["name"] for n in segment["children"][3]["children"]], ["执行记录", "选定"])

    def test_scene_film_keeps_documents_before_ordered_review_folders(self):
        root = "09-剧集制作/EP001/06-生成结果/C001-场次结果/场次成片"
        for name in ("执行记录", "其他附件", "选定", "审阅记录", "候选"):
            self.put(root + "/" + name + "/记录.md", "# 记录")
        self.put(root + "/EP001-C001-成片说明.md", "# 成片说明")
        self.put(root + "/成片索引.md", "# 索引")
        portal.build(self.root)
        ep = self.extract()["catalogues"]["09-剧集制作"]["children"][0]
        film = ep["children"][0]["children"][0]["children"][0]
        self.assertEqual(film["name"], "场次成片")
        self.assertEqual([n["name"] for n in film["children"]],
                         ["成片索引.md", "EP001-C001-成片说明.md", "选定", "候选", "审阅记录", "执行记录", "其他附件"])

    def test_production_navigation_retains_segments_stages_and_candidate_selection(self):
        root = "09-剧集制作/EP001"
        self.put(root + "/03-分镜/C001-场次分镜/分段分镜/EP001-C001-P001-分段分镜.md", "# 分镜1")
        self.put(root + "/03-分镜/C001-场次分镜/分段分镜/EP001-C001-P002-分段分镜.md", "# 分镜2")
        self.put(root + "/05-视频提示词/C001-场次生成资料/P001-分段生成资料/EP001-C001-P001-视频提示词.md", "# 准备")
        self.put(root + "/06-生成结果/C001-场次结果/P001-分段结果/01-一采/选定/EP001-C001-P001-R001-一采.mp4", "fixture")
        self.put(root + "/06-生成结果/C001-场次结果/P001-分段结果/02-二采/候选/EP001-C001-P001-R002-二采.mp4", "fixture")
        self.put(root + "/其他资料/过程稿/EP001-C002-草稿.md", "# 非正式")
        for category in ("讨论记录", "审阅记录", "历史版本"):
            self.put(root + "/其他资料/" + category + "/EP001-记录.md", "# 记录")
        self.put(root + "/说明.md", "# 根目录文件")
        (self.root / root / "01-制作前检查").mkdir()
        portal.build(self.root)
        ep = self.extract()["catalogues"]["09-剧集制作"]["children"][0]
        self.assertEqual([s["name"] for s in ep["children"]],
                         ["说明.md", "01-制作前检查", "03-分镜", "05-视频提示词", "06-生成结果", "其他资料"])
        self.assertEqual(ep["children"][1]["children"], [])
        def leaves(node):
            if node["kind"] != "group":
                return [node["key"]]
            return [key for child in node["children"] for key in leaves(child)]
        keys = leaves(ep)
        self.assertEqual(len(keys), 10)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn(root + "/其他资料/过程稿/EP001-C002-草稿.md", keys)
        other = next(node for node in ep["children"] if node["name"] == "其他资料")
        self.assertEqual({node["name"] for node in other["children"]},
                         {"讨论记录", "过程稿", "审阅记录", "历史版本"})
        encoded = json.dumps(ep, ensure_ascii=False)
        self.assertNotIn("按场次与分段浏览", encoded)
        self.assertNotIn("按原目录浏览", encoded)
        self.assertNotIn("#scenes", encoded)
        self.assertIn("01-一采/选定", encoded)
        self.assertIn("02-二采/候选", encoded)
        self.assertIn("status-gray", ep["statusHtml"])
        self.assertNotIn("批准采用", encoded)

    def test_history_is_separate_and_inventory_skips_outside_symlinks(self):
        self.put("历史版本/旧批次/定位.md", "# 旧定位\n旧事实")
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "private.md"
            external.write_text("private", encoding="utf-8")
            (self.root / "历史版本/越界.md").symlink_to(external)
            portal.build(self.root)
        data = self.extract()
        self.assertFalse(data["positionExists"])
        self.assertNotIn("历史版本/越界.md", data["documents"])
        self.assertIn("历史版本/旧批次/定位.md", data["documents"])
        self.assertEqual(data["catalogues"]["历史版本"]["children"][0]["name"], "旧批次")

    def prop_fixture(self, decision="批准采用。"):
        base = "05-道具资料"
        self.put(base + "/道具索引.md", "# 道具索引\n| 道具编号 | 名称 | 道具类别 | 资料卡入口 |\n"
                 "| --- | --- | --- | --- |\n| PR001 | 盒子 | 容器 | [卡](PR001-盒子/PR001-盒子-资料卡.md) |\n")
        self.put(base + "/PR001-盒子/PR001-盒子-资料卡.md", "# 资料卡\n- 确认状态：已确认\n## 状态\n基础与破损并存。")
        for state in ("基础", "破损"):
            self.put(base + "/PR001-盒子/参考图/PR001-" + state + "-道具参考图.png", "fixture image")
            self.put(base + "/审阅记录/PR001-" + state + "-审阅.md", "# 审阅\n## 4. 用户确认\n- 结论：" + (decision if state == "基础" else "批准采用。"))
        self.put(base + "/过程稿/PR001-基础-道具参考图-草稿-v01.png", "fixture candidate")
        record = self.put(base + "/PR001-盒子/参考图/生成记录.md", "# 生成记录\n## 1. 当前正式资产\n"
                 "| 状态名 | 正式文件 | 采用的候选版本 | 适用范围 | 来源参考图及版本 | 审阅记录 |\n"
                 "| --- | --- | --- | --- | --- | --- |\n"
                 "| 破损 | [图](PR001-破损-道具参考图.png) | v02 | 损坏后 | 基础v01 | [审阅](../../审阅记录/PR001-破损-审阅.md) |\n"
                 "| 基础 | [图](PR001-基础-道具参考图.png) | v01 | 完整关闭 | 无 | [审阅](../../审阅记录/PR001-基础-审阅.md) |\n"
                 "## 2. 逐次生成记录\n### 生成记录-001\n- 状态名及实际含义：基础；完整关闭。\n- 本次目标、保留与变化：确定结构\n"
                 "- 输出候选文件：[v01](../../过程稿/PR001-基础-道具参考图-草稿-v01.png)\n"
                 "- agent 画面初审结论：通过\n- 用户采用状态：待确认\n")
        return record

    def test_prop_states_coexist_and_base_cover_preferred(self):
        record = self.prop_fixture()
        before = record.read_bytes()
        portal.build(self.root)
        prop = self.extract()["props"][0]
        self.assertEqual([a["state"] for a in prop["formal"]], ["破损", "基础"])
        self.assertEqual(prop["cover"]["state"], "基础")
        self.assertIn("status-green", prop["formal"][0]["statusHtml"])
        self.assertEqual(prop["candidates"][0]["state"], "基础；完整关闭")
        self.assertIn("status-orange", prop["candidates"][0]["userHtml"])
        self.assertEqual(prop["pendingCount"], 1)
        self.assertEqual(before, record.read_bytes())

    def test_prop_unapproved_base_falls_back_to_approved_state(self):
        self.prop_fixture("待确认。")
        portal.build(self.root)
        prop = self.extract()["props"][0]
        self.assertEqual(prop["cover"]["state"], "破损")
        self.assertFalse(prop["formal"][1]["approved"])

    def test_prop_card_or_loose_file_does_not_approve_image(self):
        record = self.prop_fixture()
        record.unlink()
        portal.build(self.root)
        prop = self.extract()["props"][0]
        self.assertIsNone(prop["cover"])
        self.assertEqual(prop["formal"], [])
        self.assertIn("status-green", prop["card"]["confirmationHtml"])
        self.assertFalse((self.root / "05-道具资料/讨论记录").exists())

    def test_prop_template_enumeration_is_not_approval(self):
        self.prop_fixture("批准采用／修改后再审／不采用")
        portal.build(self.root)
        self.assertFalse(self.extract()["props"][0]["formal"][1]["approved"])

    def test_prop_missing_media_and_other_prop_records(self):
        self.prop_fixture()
        (self.root / "05-道具资料/PR001-盒子/参考图/PR001-基础-道具参考图.png").unlink()
        self.put("05-道具资料/审阅记录/PR002-其他.md", "# 其他道具")
        portal.build(self.root)
        prop = self.extract()["props"][0]
        self.assertIsNone(prop["formal"][1]["media"])
        self.assertEqual(prop["cover"]["state"], "破损")
        self.assertFalse(any("PR002" in f["key"] for g in prop["groups"] for f in g["files"]))

    def test_prop_template_document_and_panel_targets(self):
        template = (Path(portal.__file__).resolve().parent.parent / "references/模板/项目总览模板.html").read_text("utf-8")
        opened = template.split("function openProp(", 1)[1].split("function returnToProps", 1)[0]
        self.assertIn('renderLongDocument("prop",', opened)
        self.assertNotIn('renderLongDocument("person",', opened)
        self.assertIn('"05-道具资料":"props-panel"', template)

    def scene_fixture(self, decision="批准采用。"):
        base = "04-场景资料"
        self.put(base + "/场景索引.md", "# 场景索引\n| 场景编号 | 名称 | 场景类型 | 资料卡入口 |\n"
                 "| --- | --- | --- | --- |\n| SC001 | 药庐 | 室内 | [卡](SC001-药庐/SC001-药庐-资料卡.md) |\n")
        card = self.put(base + "/SC001-药庐/SC001-药庐-资料卡.md", "# 药庐\n- 确认状态：已确认\n## 空间\n原正文")
        self.put(base + "/SC001-药庐/参考图/SC001-布局.png", "aux")
        self.put(base + "/SC001-药庐/参考图/SC001-EP001-C001-场景参考图.png", "environment")
        self.put(base + "/过程稿/SC001-草稿-v01.png", "candidate")
        self.put(base + "/审阅记录/SC001-审阅-001.md", "# 审阅\n## 4. 用户确认\n- 结论：" + decision)
        record = self.put(base + "/SC001-药庐/参考图/生成记录.md",
                 "# 生成记录\n## 1. 当前正式资产（历史保留）\n"
                 "| 正式文件 | 最初制作场次 | 场景状态与适用条件 | 采用的候选版本 | 审阅记录 |\n"
                 "| --- | --- | --- | --- | --- |\n"
                 "| [结构](SC001-布局.png) | 旧图 | 仅供空间结构参考 | v02 | [审阅](../../审阅记录/SC001-审阅-001.md) |\n\n"
                 "| [环境](SC001-EP001-C001-场景参考图.png) | EP001-C001 | 晨；可供C002复用 | v01 | [审阅](../../审阅记录/SC001-审阅-001.md) |\n"
                 "## 2. 逐次生成记录\n### 生成记录-001\n- 最初制作场次：EP001-C001。\n- 本场次需求与状态：晨间\n"
                 "- 输出候选文件：[图](../../过程稿/SC001-草稿-v01.png)\n- agent 画面初审结论：通过\n- 用户采用状态：待确认\n")
        return card, record

    def test_scene_environment_auxiliary_and_candidate_separate(self):
        card, record = self.scene_fixture()
        before = card.read_bytes(), record.read_bytes()
        portal.build(self.root)
        scene = self.extract()["scenes"][0]
        self.assertEqual(len(scene["formal"]), 1)
        self.assertEqual(len(scene["auxiliary"]), 1)
        self.assertEqual(scene["cover"]["type"], "场次环境图")
        self.assertEqual(scene["cover"]["state"], "EP001-C001")
        self.assertIn("可供C002复用", scene["cover"]["scope"])
        self.assertEqual(scene["candidates"][0]["state"], "EP001-C001")
        self.assertIn("status-green", scene["candidates"][0]["agentHtml"])
        self.assertIn("status-orange", scene["candidates"][0]["userHtml"])
        self.assertEqual(scene["pendingCount"], 1)
        self.assertEqual(before, (card.read_bytes(), record.read_bytes()))

    def test_scene_confirmed_card_does_not_approve_cover(self):
        self.scene_fixture("修改后再审。")
        portal.build(self.root)
        scene = self.extract()["scenes"][0]
        self.assertIsNone(scene["cover"])
        self.assertIn("status-green", scene["card"]["confirmationHtml"])

    def test_scene_legacy_file_is_accessible_without_inferred_approval(self):
        self.scene_fixture()
        self.put("04-场景资料/SC001-药庐/参考图/旧环境.png", "old")
        self.put("04-场景资料/SC001-药庐/参考图/生成记录.md", "# 旧记录\n用户曾批准，范围见旧记录。")
        portal.build(self.root)
        scene = self.extract()["scenes"][0]
        self.assertIsNone(scene["cover"])
        self.assertEqual(scene["formal"], [])
        self.assertEqual(len(scene["legacy"]), 3)
        self.assertNotIn("approved", scene["legacy"][0])

    def test_scene_records_isolated_and_external_images_not_loaded(self):
        self.scene_fixture()
        self.put("04-场景资料/审阅记录/SC002-别处.md", "# 另一场景")
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "outside.png"
            external.write_bytes(b"outside")
            (self.root / "04-场景资料/SC001-药庐/参考图/外部.png").symlink_to(external)
            portal.build(self.root)
        scene = self.extract()["scenes"][0]
        self.assertFalse(any(m["name"] == "外部.png" for m in scene["legacy"]))
        self.assertFalse(any("SC002" in f["key"] for g in scene["groups"] for f in g["files"]))
        self.assertFalse((self.root / "04-场景资料/讨论记录").exists())

    def test_scene_alternate_fields_use_output_section_not_input(self):
        _, record = self.scene_fixture()
        self.put("04-场景资料/过程稿/SC001-输入.png", "input")
        record.write_text(record.read_text("utf-8") + "\n### 生成记录-002\n#### 1. 任务信息\n- SC001／EP001-C002，晨。\n"
                          "#### 2. 输入参考\n- 唯一输入：[输入](../../过程稿/SC001-输入.png)\n"
                          "#### 4. 执行结果\n- [v01](../../过程稿/SC001-草稿-v01.png)\n"
                          "#### 5. 检查与采用\n- agent初审：不通过；[审阅](../../审阅记录/SC001-审阅-001.md)\n"
                          "- 用户采用：待确认，非正式审批。", encoding="utf-8")
        portal.build(self.root)
        candidates = self.extract()["scenes"][0]["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[-1]["state"], "EP001-C002")
        self.assertIn("status-red", candidates[-1]["agentHtml"])
        self.assertTrue(candidates[-1]["reviews"])
        self.assertNotIn("输入", candidates[-1]["media"]["key"])

    def test_scene_template_ids_and_document_target(self):
        template = (Path(portal.__file__).resolve().parent.parent / "references/模板/项目总览模板.html").read_text("utf-8")
        ids = re.findall(r'\bid="([^"]+)"', template)
        self.assertEqual(len(ids), len(set(ids)))
        open_scene = template.split("function openScene(", 1)[1].split("function returnToScenes", 1)[0]
        self.assertIn('renderLongDocument("scene",', open_scene)
        self.assertNotIn('renderLongDocument("person",', open_scene)
        self.assertIn('"04-场景资料":"scenes-panel"', template)

    def test_people_stage_directories_follow_card_order_and_preserve_assets(self):
        card, record = self.person_fixture()
        card.write_text(card.read_text() + "\n## 3. 外貌与基础造型\n### 3.1 成年\n### 3.2 少年\n### 3.3 暂无图片\n## 4. 性格\n")
        original = record.parent / "正式.png"
        (record.parent / "少年").mkdir()
        original.rename(record.parent / "少年/正式.png")
        self.put("03-人物资料/CH001-小林/参考图/成年/成年.png", "adult")
        self.put("03-人物资料/CH001-小林/参考图/未归属.png", "unassigned")
        text = record.read_text().replace("[图](正式.png)", "[图](少年/正式.png)")
        text = text.replace("\n## 2. 逐次生成记录", "\n| 人物多视角参考图 | 成年 | 无 | [图](成年/成年.png) | v02 | [审阅](../../审阅记录/CH001-审阅-001.md) |\n"
                            "| 服装参考图 | 巡防 | 制服 | [图](未归属.png) | v01 | [审阅](../../审阅记录/CH001-审阅-001.md) |\n\n## 2. 逐次生成记录")
        record.write_text(text)
        portal.build(self.root)
        person = self.extract()["people"][0]
        self.assertEqual(person["stages"], ["成年", "少年"])
        self.assertEqual([a["stage"] for a in person["formal"]], ["少年", "成年", ""])
        self.assertTrue(all(a["media"] and a["approved"] for a in person["formal"]))
        self.assertEqual(person["cover"]["media"]["key"], "03-人物资料/CH001-小林/参考图/少年/正式.png")
        self.assertEqual(person["pendingCount"], 1)
        self.assertEqual(record.read_text(), text)

    def test_people_flat_registry_does_not_invent_stage_tabs(self):
        card, _ = self.person_fixture()
        card.write_text(card.read_text() + "\n## 3. 外貌与基础造型\n### 3.1 少年\n### 3.2 成年\n")
        portal.build(self.root)
        person = self.extract()["people"][0]
        self.assertEqual(person["stages"], [])
        self.assertEqual(person["formal"][0]["stage"], "")
        self.assertIsNotNone(person["cover"])

    def test_people_formal_candidate_and_approval_are_separate(self):
        card, record = self.person_fixture()
        original = (card.read_bytes(), record.read_bytes())
        portal.build(self.root)
        person = self.extract()["people"][0]
        self.assertEqual(person["id"], "CH001")
        self.assertEqual(len(person["formal"]), 1)
        self.assertEqual(person["cover"]["version"], "v01")
        self.assertEqual(person["candidates"][0]["type"], "人物上半身正面肖像图")
        self.assertIn("status-orange", person["candidates"][0]["userHtml"])
        self.assertEqual(person["pendingCount"], 1)
        self.assertEqual(original, (card.read_bytes(), record.read_bytes()))

    def test_people_unapproved_registry_image_is_not_cover(self):
        self.person_fixture("修改后再审。")
        portal.build(self.root)
        person = self.extract()["people"][0]
        self.assertIsNone(person["cover"])
        self.assertFalse(person["formal"][0]["approved"])
        self.assertIn("修改后再审", person["formal"][0]["statusHtml"])

    def test_people_history_or_loose_files_are_not_current_assets(self):
        _, record = self.person_fixture()
        record.write_text("# 记录\n## 1. 当前正式资产\n暂无\n", encoding="utf-8")
        self.put("03-人物资料/人物参考图采用总表.md", "# 旧表\n全部已采用")
        self.put("03-人物资料/历史版本/CH001-小林/旧正式.png", "old")
        portal.build(self.root)
        person = self.extract()["people"][0]
        self.assertEqual(person["formal"], [])
        self.assertIsNone(person["cover"])
        self.assertEqual(len(person["groups"][3]["files"]), 1)

    def test_people_missing_or_external_media_not_previewed(self):
        _, record = self.person_fixture()
        self.put("03-人物资料/历史版本/历史.png", "old")
        text = record.read_text("utf-8").replace("(正式.png)", "(../../历史版本/历史.png)")
        text = text.replace("(../../过程稿/CH001-肖像-草稿-v01.png)", "(https://example.test/image.png)")
        record.write_text(text, encoding="utf-8")
        portal.build(self.root)
        person = self.extract()["people"][0]
        self.assertIsNone(person["formal"][0]["media"])
        self.assertIsNone(person["cover"])
        self.assertEqual(person["candidates"], [])

    def test_people_process_groups_do_not_mix_character_ids(self):
        self.person_fixture()
        self.put("03-人物资料/审阅记录/CH002-审阅-001.md", "# 别人")
        self.put("03-人物资料/审阅记录/人物索引-审阅记录-001.md", "# 跨人物")
        portal.build(self.root)
        data = self.extract()
        self.assertEqual(len(data["people"][0]["groups"][2]["files"]), 1)
        self.assertEqual(len(data["peopleGroups"][2]["files"]), 3)

    def test_people_prompt_code_cannot_supply_approval_fields(self):
        _, record = self.person_fixture()
        record.write_text(record.read_text("utf-8").replace("- 图片类型：", "```text\n- 用户采用状态：批准采用\n```\n- 图片类型："), encoding="utf-8")
        portal.build(self.root)
        self.assertIn("待确认", self.extract()["people"][0]["candidates"][0]["userHtml"])

    def test_empty_project_has_no_invented_status_and_creates_no_folders(self):
        portal.build(self.root)
        data = self.extract()
        self.assertFalse(data["positionExists"])
        self.assertEqual(data["active"], [])
        self.assertEqual(data["meta"]["确认状态"], "未记录")
        self.assertEqual([p.name for p in self.root.iterdir()], ["项目总览.html"])

    def test_missing_formal_does_not_promote_draft(self):
        self.put("00-项目定位/过程稿/项目基本定位-草稿-v01.md", "# 草稿\n候选内容")
        portal.build(self.root)
        data = self.extract()
        self.assertFalse(data["positionExists"])
        self.assertEqual(len(data["groups"][1]["files"]), 1)
        self.assertNotIn("候选内容", data["positionHtml"])

    def test_real_metadata_extra_sections_and_source_bytes_are_preserved(self):
        content = "# 项目\n\n- 文档版本：v1.0\n- 更新日期：2026-09-26\n- 确认状态：待确认\n\n## 受众定位\n原词\n\n## 其他备注\n既有补充"
        path = self.put(portal.POSITION, content)
        portal.build(self.root)
        data = self.extract()
        self.assertEqual(path.read_text("utf-8"), content)
        self.assertEqual(data["meta"]["确认状态"], "待确认")
        self.assertIn("既有补充", data["positionHtml"])
        self.assertIn("原词", data["positionHtml"])

    def test_multiple_active_phases_use_exact_recorded_states(self):
        self.put(portal.PROGRESS, "# 项目进度\n- 项目名称：测试剧\n\n"
                 "| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n"
                 "| --- | --- | --- | --- | --- | --- |\n"
                 "| 定位 | 无 | 已完成 | 文件 | 无 | 完成 |\n"
                 "| 图片 | 无 | 待确认 | 文件 | 等待 | 审阅 |\n"
                 "| EP001 | 无 | 进行中 | 文件 | 无 | 准备 |\n")
        portal.build(self.root)
        data = self.extract()
        self.assertEqual([r["name"] for r in data["active"]], ["图片", "EP001"])
        self.assertEqual(data["project"], "测试剧")

    def test_relative_links_resolve_from_original_document(self):
        href, key = portal.safe_link("../项目基本定位.md", "00-项目定位/审阅记录/记录.md")
        self.assertEqual(key, portal.POSITION)
        self.assertTrue(href.endswith(".md"))
        href, key = portal.safe_link("../01-主旨与简介/主旨与简介.md#2-世界观与核心规则", portal.POSITION)
        self.assertEqual(key, "01-主旨与简介/主旨与简介.md")
        self.assertIn("#2-", href)

    def test_unsafe_links_and_raw_html_are_not_executed(self):
        for target in ("javascript:alert", "data:text/html,abc", "//evil.test", "file:///etc/passwd"):
            self.assertEqual(portal.safe_link(target, portal.POSITION), (None, None))
        rendered = portal.markdown("<script>alert(1)</script>\n[x](javascript:alert)\n![x](https://example.test/x.png)", portal.POSITION)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn('href="javascript:', rendered)

    def test_script_closing_text_is_safe_in_json(self):
        self.put(portal.POSITION, "# 文档\n\n## 内容\n</script><script>bad()</script>")
        portal.build(self.root)
        output = (self.root / "项目总览.html").read_text("utf-8")
        self.assertNotIn("</script><script>bad()", output)
        self.assertIn("&lt;script&gt;", self.extract()["positionHtml"])

    def test_foreign_html_is_not_overwritten(self):
        path = self.put("项目总览.html", "用户手写文件")
        with self.assertRaises(ValueError):
            portal.build(self.root)
        self.assertEqual(path.read_text("utf-8"), "用户手写文件")

    def test_outside_source_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "private.md"
            target.write_text("do not read", encoding="utf-8")
            (self.root / "项目进度.md").symlink_to(target)
            with self.assertRaises(ValueError):
                portal.build(self.root)

    def test_empty_field_does_not_capture_next_line(self):
        self.assertEqual(portal.field("- 文档版本：\n- 更新日期：今天", "文档版本"), "")

    def test_approval_clauses_are_separate_and_source_is_unchanged(self):
        value = "2026-09-23定位确认继续有效；2026-09-25用户明确暂定80集、不强制80集，随后批准单集时长采用新默认值，并批准剩余迁移与修改。"
        content = "# 定位\n\n- 确认依据：" + value + "\n- 适用范围：甲；乙。\n\n## 内容\n正文"
        path = self.put(portal.POSITION, content)
        portal.build(self.root)
        rendered = self.extract()["introHtml"]
        items = re.search(r'<ul class="approval-items">(.*?)</ul>', rendered, re.S).group(1)
        parts = re.findall(r"<li>(.*?)</li>", items)
        self.assertEqual(len(parts), 2)
        self.assertIn("，随后批准", parts[1])
        self.assertIn("，并批准", parts[1])
        self.assertEqual("".join(parts), value)
        self.assertIn("适用范围：甲；乙。", rendered)
        self.assertEqual(path.read_text("utf-8"), content)

    def test_approval_links_and_code_are_not_split_at_semicolons(self):
        rendered = portal.intro_markup("- 确认依据：[审阅；记录](https://example.test/a;b)；`甲；乙`。")
        self.assertIn('href="https://example.test/a;b"', rendered)
        self.assertIn("<code>甲；乙</code>", rendered)
        items = re.search(r'<ul class="approval-items">(.*?)</ul>', rendered, re.S).group(1)
        self.assertEqual(items.count("<li>"), 2)

    def test_statuses_share_five_colors_and_keep_exact_labels(self):
        self.assertEqual(set(portal.STATUS_COLORS.values()), {"green", "blue", "orange", "red", "gray"})
        for label, color in portal.STATUS_COLORS.items():
            rendered = portal.status_markup(label, portal.POSITION)
            self.assertIn('status-' + color + '"', rendered)
            self.assertIn('>' + label + '</span>', rendered)
        self.assertIn('status-green', portal.status_markup("已确认；定位阶段修订已完成。", portal.POSITION))
        self.assertIn('</span>；定位阶段修订已完成。', portal.status_markup("已确认；定位阶段修订已完成。", portal.POSITION))

    def test_status_styling_is_scoped_not_substring_based(self):
        for value in ("尚未通过", "已完成部分，待审核", "未批准", "通过／不通过／待确认", "<script>失败</script>"):
            rendered = portal.status_markup(value, portal.POSITION)
            self.assertIn("status-gray", rendered)
            self.assertNotIn("<script>", rendered)
        self.assertNotIn("status-badge", portal.markdown("正文说已完成。\n- 故事结束时的状态：失败", portal.POSITION))
        self.assertIn("status-red", portal.markdown("- agent 初审结论：不通过", portal.POSITION))
        self.assertIn("status-blue", portal.markdown("| 阶段 | 当前状态 | 说明 |\n| --- | --- | --- |\n| 测试 | 进行中 | 已完成第一步 |", portal.PROGRESS))
        self.assertNotIn("status-green", portal.markdown("| 阶段 | 当前状态 | 说明 |\n| --- | --- | --- |\n| 测试 | 进行中 | 已完成第一步 |", portal.PROGRESS))

    def test_approval_sentences_in_same_record_stay_together(self):
        rendered = portal.intro_markup("- 确认依据：第一日确认。补充条件仍有效；第二日确认，随后批准后续工作。")
        items = re.search(r'<ul class="approval-items">(.*?)</ul>', rendered, re.S).group(1)
        self.assertEqual(items.count("<li>"), 2)
        self.assertIn("第一日确认。补充条件仍有效；</li>", items)

    def test_story_formal_body_metadata_boundary_and_relative_links(self):
        content = "# 主旨与简介\n- 文档版本：v2\n- 确认状态：待确认\n- 阅读边界：第六章用于观众。\n- 采用与来源：[审阅](审阅记录/审阅.md)\n\n## 1. 故事主旨\n原文不可改\n## 2. 世界观\n### 规则甲\n规则正文\n### 规则甲\n另一规则\n## 7. 结局方向\n结局原文"
        source = self.put(portal.STORY, content)
        self.put("01-主旨与简介/审阅记录/审阅.md", "# 审阅\n待确认")
        portal.build(self.root)
        story = self.extract()["story"]
        self.assertTrue(story["exists"])
        self.assertEqual(story["meta"]["文档版本"], "v2")
        self.assertIn("status-orange", story["confirmationHtml"])
        self.assertEqual(story["boundaryHtml"], "第六章用于观众。")
        self.assertNotIn("阅读边界", story["introHtml"])
        self.assertIn('data-doc="01-主旨与简介/审阅记录/审阅.md"', story["introHtml"])
        self.assertIn("结局原文", story["bodyHtml"])
        self.assertIn('id="规则甲-1"', story["bodyHtml"])
        self.assertEqual(source.read_text("utf-8"), content)

    def test_story_history_and_drafts_never_replace_missing_formal(self):
        self.put("01-主旨与简介/过程稿/草稿.md", "# 故事\n候选内容")
        self.put("01-主旨与简介/历史版本/世界观旧稿.md", "# 世界观\n旧规则")
        portal.build(self.root)
        data = self.extract()
        self.assertFalse(data["story"]["exists"])
        self.assertEqual(data["story"]["bodyHtml"], "")
        self.assertEqual(data["story"]["boundaryHtml"], "")
        self.assertEqual([len(g["files"]) for g in data["story"]["groups"]], [0, 1, 0, 1, 0])
        self.assertEqual([len(g["files"]) for g in data["groups"]], [0, 0, 0, 0, 0])
        self.assertFalse((self.root / "01-主旨与简介/讨论记录").exists())

    def test_story_outside_source_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "private.md"
            target.write_text("private", encoding="utf-8")
            folder = self.root / "01-主旨与简介"
            folder.mkdir()
            (folder / "主旨与简介.md").symlink_to(target)
            with self.assertRaises(ValueError):
                portal.build(self.root)

    def test_outline_preserves_five_chapters_tables_links_and_source(self):
        chapters = ["全剧故事主线", "故事阶段与重大转折", "主要人物作用与变化", "重要人物关系发展", "关键秘密与伏笔安排"]
        content = "# 故事大纲\n- 文档版本：v0.7\n- 更新日期：2026-09-25\n- 确认状态：已确认；原始依据。\n- 规则依据：[世界观](../01-主旨与简介/主旨与简介.md#2-世界观与核心规则)\n- 制作规格：原规格\n\n"
        content += "\n".join("## " + str(i) + ". " + name + "\n原始正文" for i, name in enumerate(chapters, 1))
        content += "\n| 秘密 | 回收 |\n| --- | --- |\n| 原秘密 | 原结局 |\n"
        source = self.put(portal.OUTLINE, content)
        self.put("02-故事大纲/审阅记录/记录.md", "# 审阅\n真实决定")
        portal.build(self.root)
        data = self.extract()
        outline = data["outline"]
        self.assertEqual(outline["meta"]["文档版本"], "v0.7")
        self.assertEqual(outline["bodyHtml"].count("<h2 "), 5)
        self.assertNotIn("<h3 ", outline["bodyHtml"])
        self.assertIn("<table>", outline["bodyHtml"])
        self.assertIn("原秘密", outline["bodyHtml"])
        self.assertIn('data-doc="01-主旨与简介/主旨与简介.md"', outline["introHtml"])
        self.assertEqual(outline["boundaryHtml"], "")
        self.assertEqual([len(g["files"]) for g in outline["groups"]], [0, 0, 1, 0, 0])
        self.assertEqual([len(g["files"]) for g in data["story"]["groups"]], [0, 0, 0, 0, 0])
        self.assertEqual(source.read_text("utf-8"), content)

    def test_outline_draft_is_not_formal_and_no_extra_folders_created(self):
        self.put("02-故事大纲/过程稿/草稿.md", "# 草稿\n候选大纲")
        self.put("02-故事大纲/历史版本/旧大纲.md", "# 旧大纲\n旧结局")
        portal.build(self.root)
        outline = self.extract()["outline"]
        self.assertFalse(outline["exists"])
        self.assertEqual(outline["bodyHtml"], "")
        self.assertEqual([len(g["files"]) for g in outline["groups"]], [0, 1, 0, 1, 0])
        self.assertFalse((self.root / "02-故事大纲/讨论记录").exists())

    def test_rebuild_updates_view_not_source_files(self):
        source = self.put(portal.POSITION, "# 定位\n\n## 受众\n第一版")
        portal.build(self.root)
        source.write_text("# 定位\n\n## 受众\n第二版", encoding="utf-8")
        portal.build(self.root)
        self.assertIn("第二版", self.extract()["positionHtml"])
        self.assertEqual(source.read_text("utf-8"), "# 定位\n\n## 受众\n第二版")

    def test_tables_lists_and_code_are_readable(self):
        source = "# 标题\n\n- **重点**\n\n| 项目 | 值 |\n| --- | --- |\n| 数量 | 1 |\n\n~~~\n<b>原文</b>\n~~~"
        rendered = portal.markdown(source, portal.POSITION)
        self.assertIn("<table>", rendered)
        self.assertIn("<strong>重点</strong>", rendered)
        self.assertIn("&lt;b&gt;原文&lt;/b&gt;", rendered)


if __name__ == "__main__":
    unittest.main()
