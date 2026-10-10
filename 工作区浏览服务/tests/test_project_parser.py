"""Local fixture tests. Never opens a browser, calls ComfyUI, or mutates real projects."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from backend.parsers import project as portal


class ProjectParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_process_file_status_only_shows_recorded_confirmation(self):
        self.put("00-项目定位/其他资料/工作稿/参考图-工作稿.md", "# 工作稿\n- 当前稿版本：v01\n- 当前状态及待办：等待本批审核\n\n## 生成记录\n原记录")
        self.put("00-项目定位/其他资料/工作稿/已确认稿.md", "# 工作稿\n- 确认状态：已确认\n\n原记录")
        files = portal.build_data(self.root)["groups"][0]["files"]
        by_name = {item["name"]: item for item in files}
        self.assertEqual(by_name["参考图-工作稿.md"]["statusHtml"], "")
        self.assertIn("已确认", by_name["已确认稿.md"]["statusHtml"])

    def test_record_document_preview_has_no_invented_confirmation(self):
        source = "00-项目定位/其他资料/工作稿/参考图-工作稿.md"
        text = "# 工作稿\n- 当前稿版本：v01\n- 当前状态及待办：等待本批审核\n\n## 生成记录\n原记录"
        self.put(source, text)
        doc = portal.build_data(self.root)["documents"][source]
        self.assertEqual(doc["confirmationHtml"], "")
        self.assertEqual(doc["meta"], {})
        self.assertIn("等待本批审核", doc["headerHtml"])
        self.assertIn("原记录", doc["contentHtml"])
        self.assertNotIn("未记录", doc["headerHtml"])

    def test_work_draft_categories_do_not_create_legacy_groups(self):
        self.put("00-项目定位/其他资料/工作稿/项目基本定位-工作稿.md", "# 工作稿\n草稿")
        self.put("00-项目定位/其他资料/工作稿/素材/样例.png", "image")
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertEqual([g["name"] for g in data["groups"]], ["工作稿", "历史版本", "执行附件"])
        self.assertEqual(len(data["groups"][0]["files"]), 2)
        self.assertFalse((self.root / portal.POSITION).exists())

    def test_image_work_draft_uses_scoped_approval_and_original_asset_folder(self):
        _, person_record = self.person_fixture()
        prop_record = self.prop_fixture()
        _, scene_record = self.scene_fixture()
        for stage, number, old_record, collection in (
                (portal.PEOPLE, "CH001", person_record, "people"),
                (portal.PROPS, "PR001", prop_record, "props"),
                (portal.SCENES, "SC001", scene_record, "scenes")):
            old_key = old_record.relative_to(self.root).as_posix()
            new_key = f"{stage}/其他资料/工作稿/{number}-参考图-工作稿.md"
            blocks, review_targets = [], {}
            record = old_record.read_text()
            for link in portal.markdown_links(record, old_key):
                if "审阅记录/" in link["key"] and link["key"] not in review_targets:
                    anchor = f"审阅-生成记录-001-{len(blocks)+1:03}"
                    review_targets[link["key"]] = "#" + anchor
                    text = (self.root / link["key"]).read_text()
                    text = re.sub(r"^# .*\n", f"### {anchor}\n", text, count=1)
                    text = re.sub(r"^## ", "#### ", text, flags=re.M)
                    blocks.append(text)
            def relocate(match):
                target = match.group(2)
                _, key = portal.safe_link(target, old_key)
                if key in review_targets:
                    return f"[{match.group(1)}]({review_targets[key]})"
                if "过程稿/" in key:
                    new_media = f"{stage}/其他资料/工作稿/素材/{Path(key).name}"
                    self.put(new_media, (self.root / key).read_text())
                    key = new_media
                target = Path(os.path.relpath(self.root / key, (self.root / new_key).parent)).as_posix()
                return f"[{match.group(1)}]({target})"
            record = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", relocate, record)
            work = self.put(new_key, record + "\n## 4. 审阅区\n" + "\n".join(blocks))
            # An unrelated rejected output must not change approval of the selected one.
            work.write_text(work.read_text() + "\n### 审阅-无关候选\n#### 4. 用户确认\n- 结论：不采用\n")
            self.data = portal.build_data(self.root)
            asset = self.data[collection][0]
            self.assertEqual(asset["recordKey"], new_key)
            self.assertIsNotNone(asset["cover"])
            self.assertTrue(asset["cover"]["approved"])
            # The exact approved review overrides the stale waiting summary.
            self.assertEqual(asset["pendingCount"], 0 if collection == "people" else 1)
            self.assertIn("/其他资料/工作稿/素材/", asset["candidates"][0]["media"]["key"])
            self.assertIn("/参考图/", asset["cover"]["media"]["key"])
            with self.subTest(stage=stage):
                # Missing or whole-file approval links must never borrow another decision.
                valid_text = work.read_text()
                for invalid in ("", "#不存在"):
                    broken = re.sub(r"\]\(#审阅-生成记录-[^)]+\)", "](" + Path(new_key).name + invalid + ")", valid_text)
                    work.write_text(broken)
                    self.data = portal.build_data(self.root)
                    self.assertIsNone(self.data[collection][0]["cover"])

    def test_image_formal_approval_accepts_explicit_legacy_aliases(self):
        self.person_fixture()
        self.prop_fixture()
        self.scene_fixture()
        for decision_field in ("- 决定：批准采用。", "- 结论：已批准"):
            for review in self.root.glob("*/审阅记录/*.md"):
                review.write_text("# 审阅\n## 4. 用户确认\n" + decision_field, encoding="utf-8")
            data = portal.build_data(self.root)
            for kind in ("people", "props", "scenes"):
                with self.subTest(kind=kind, decision=decision_field):
                    self.assertTrue(all(a["approved"] for a in data[kind][0]["formal"]))
                    self.assertIsNotNone(data[kind][0]["cover"])

    def test_bold_record_field_labels_keep_image_approval(self):
        self.person_fixture()
        self.prop_fixture()
        self.scene_fixture()
        for review in self.root.glob("*/审阅记录/*.md"):
            review.write_text(review.read_text().replace("- 结论：", "- **结论**："))
        data = portal.build_data(self.root)
        for kind in ("people", "props", "scenes"):
            self.assertTrue(all(a["approved"] for a in data[kind][0]["formal"]))
        self.assertEqual(portal.field("- **决定**：批准采用。", "决定"), "批准采用。")

    def test_image_linked_review_overrides_stale_waiting_but_preserves_disposal(self):
        records = [("people", self.person_fixture()[1], "CH001-审阅-001.md"),
                   ("props", self.prop_fixture(), "PR001-基础-审阅.md"),
                   ("scenes", self.scene_fixture()[1], "SC001-审阅-001.md")]
        for kind, record, review_name in records:
            review = record.parent.parent.parent / "审阅记录" / review_name
            target = Path(os.path.relpath(record, review.parent)).as_posix()
            if kind != "people":
                record.write_text(record.read_text() + f"\n- 审阅记录入口：[审阅](../../审阅记录/{review_name})\n")
            for decision in ("批准采用", "修改后再审", "不采用"):
                review.write_text("# 审阅\n## 1. 审阅对象\n"
                                  f"- 对应生成记录：[生成]({target}#生成记录-001)\n"
                                  "## 4. 用户确认\n- 结论：" + decision, encoding="utf-8")
                owner = portal.build_data(self.root)[kind][0]
                with self.subTest(kind=kind, decision=decision):
                    self.assertEqual(owner["pendingCount"], 0)
                    self.assertEqual(owner["candidates"][0]["userDecision"], decision)
            record.write_text(record.read_text().replace("用户采用状态：待确认", "用户采用状态：已结束未采用"))
            review.write_text(review.read_text().replace("不采用", "待确认"))
            candidate = portal.build_data(self.root)[kind][0]["candidates"][0]
            self.assertEqual(candidate["userDecision"].rstrip("。"), "已结束未采用")
            self.assertFalse(candidate["pending"])

    def test_image_formal_approval_rejects_other_generation(self):
        records = [("people", self.person_fixture()[1]), ("props", self.prop_fixture()),
                   ("scenes", self.scene_fixture()[1])]
        for _, record in records:
            record.write_text(record.read_text().replace("| v01 |", "| v01／生成001 |"))
        for review in self.root.glob("*/审阅记录/*.md"):
            review.write_text(review.read_text() + "\n## 1. 审阅对象\n- 对应生成记录：[另一轮](生成记录.md#生成记录-002)\n")
        data = portal.build_data(self.root)
        for kind, _ in records:
            with self.subTest(kind=kind):
                asset = next(a for a in data[kind][0]["formal"] if a["version"].startswith("v01"))
                self.assertFalse(asset["approved"])
                self.assertIn("待核对", asset["statusHtml"])
        self.assertTrue(any("图片批准依据" in w for w in data["warnings"]))

    def test_image_same_generation_number_in_other_record_is_not_approval(self):
        _, record = self.person_fixture()
        record.write_text(record.read_text().replace("| v01 |", "| v01／生成001 |"))
        review = self.root / "03-人物资料/审阅记录/CH001-审阅-001.md"
        review.write_text(review.read_text() + "\n## 1. 审阅对象\n"
                          "- 对应生成记录：[其他人物](../CH002-其他/参考图/生成记录.md#生成记录-001)\n")
        data = portal.build_data(self.root)
        self.assertFalse(data["people"][0]["formal"][0]["approved"])
        self.assertIn("待核对", data["people"][0]["formal"][0]["statusHtml"])

    def test_image_same_generation_does_not_approve_other_output(self):
        _, record = self.person_fixture()
        record.write_text(record.read_text().replace(
            "- 输出候选文件：[v01](../../过程稿/CH001-肖像-草稿-v01.png)",
            "- 输出候选文件：[v01](../../过程稿/CH001-肖像-草稿-v01.png) [v02](../../过程稿/CH001-肖像-草稿-v02.png)"))
        self.put("03-人物资料/过程稿/CH001-肖像-草稿-v02.png", "second output")
        review = self.root / "03-人物资料/审阅记录/CH001-审阅-001.md"
        review.write_text("# 审阅\n## 1. 审阅对象\n"
                          "- 对应生成记录：[生成](../CH001-小林/参考图/生成记录.md#生成记录-001)\n"
                          "## 4. 用户确认\n- 结论：批准采用\n"
                          "- 批准的具体候选：[v01](../过程稿/CH001-肖像-草稿-v01.png)\n")
        candidates = portal.build_data(self.root)["people"][0]["candidates"]
        self.assertEqual([c["userDecision"] for c in candidates], ["批准采用", "审核结果待核对"])

    def test_image_formal_approval_rejects_other_candidate_version(self):
        self.prop_fixture()
        review = self.root / "05-道具资料/审阅记录/PR001-基础-审阅.md"
        review.write_text(review.read_text() + "\n- 批准的具体候选：[v02](../过程稿/PR001-基础-道具参考图-草稿-v02.png)\n")
        owner = portal.build_data(self.root)["props"][0]
        base = next(a for a in owner["formal"] if a["state"] == "基础")
        self.assertFalse(base["approved"])
        self.assertEqual(owner["cover"]["state"], "破损")

    def test_image_formal_approval_preserves_documented_save_rename(self):
        self.prop_fixture()
        review = self.root / "05-道具资料/审阅记录/PR001-基础-审阅.md"
        review.write_text(review.read_text() +
                          "\n- 批准的具体候选：[v01](../过程稿/PR001-旧名字-草稿-v01.png)\n"
                          "## 5. 采用与后续影响\n"
                          "- 正式保存位置：[正式](../PR001-盒子/参考图/PR001-基础-道具参考图.png)\n")
        owner = portal.build_data(self.root)["props"][0]
        base = next(a for a in owner["formal"] if a["state"] == "基础")
        self.assertTrue(base["approved"])

    def test_position_style_sample_preserves_confirmation_and_relative_image(self):
        text = ('### 画风与美术实现正文\n\n```text\n固定风格正文\n```\n\n'
                '#### 已确认画风样例\n\n女性样例：已确认\n\n'
                '![女性"样例](其他资料/过程稿/素材/女 样例.png)\n\n'
                '男性样例：待确认\n\n[男性候选](其他资料/过程稿/素材/男.png)')
        rendered = portal.markdown(text, portal.POSITION)
        self.assertEqual(rendered.count('<img '), 1)
        self.assertIn('src="00-%E9%A1%B9%E7%9B%AE%E5%AE%9A%E4%BD%8D/', rendered)
        self.assertIn('%E5%A5%B3%20%E6%A0%B7%E4%BE%8B.png', rendered)
        self.assertIn('alt="女性&quot;样例"', rendered)
        self.assertIn('target="_blank" rel="noopener"', rendered)
        self.assertIn('男性样例：待确认', rendered)
        self.assertLess(rendered.index('固定风格正文'), rendered.index('<img '))
        for target in ('https://example.com/a.png', '../../outside.png', 'javascript:alert(1)'):
            self.assertNotIn('<img ', portal.markdown(f'![样例]({target})', portal.POSITION))

    def test_style_sample_pair_groups_each_description_with_its_image(self):
        text = ('女性样例v04：已确认；[批准依据](审阅004.md)\n\n![女性](女.png)\n\n'
                '男性样例v05：已确认；[生成记录](生成005.md)\n\n![男性](男.png)\n\n'
                '两张保留原图。')
        rendered = portal.markdown(text, portal.POSITION)
        self.assertEqual(rendered.count('class="style-samples"'), 1)
        cards = re.findall(r'<div class="style-sample-card"[^>]*>(.*?)</div>', rendered, re.S)
        self.assertEqual(len(cards), 2)
        for card, gender in zip(cards, ('女性', '男性')):
            self.assertIn(gender + '样例', card)
            self.assertIn('alt="' + gender + '"', card)
            self.assertIn('data-doc=', card)
            self.assertEqual(card.count('<img '), 1)
        self.assertTrue(rendered.endswith('</div><p>两张保留原图。</p>'))

    def test_compilation_info_is_collapsed_without_hiding_story(self):
        source = "09-剧集制作/EP001/02-剧集剧本/EP001-C001-分场剧本.md"
        rendered = portal.markdown("剧情正文\n\n——编制信息——\n版本：v1.3\n"
                                   "[来源](EP001-本集剧本.md)\n<script>alert(1)</script>", source)
        before, details = rendered.split('<details class="intro">', 1)
        self.assertIn("剧情正文", before)
        self.assertNotIn("版本：", before)
        self.assertTrue(details.startswith("<summary>编制信息</summary>"))
        self.assertIn("版本：v1.3", details)
        self.assertIn("data-doc=", details)
        self.assertIn("&lt;script&gt;", details)
        self.assertTrue(details.endswith("</details>"))
        code = portal.markdown("```text\n——编制信息——\n```", source)
        self.assertNotIn("<details", code)

    def test_video_prompts_match_execution_identity_and_translation(self):
        episode = "09-剧集制作/EP001"
        segment = episode + "/06-生成结果/C001-场次结果/P001-分段结果"
        document = episode + "/05-视频提示词/EP001-C001-P001-视频提示词.md"
        english = "Actual <Subject 1> & dialogue"
        self.put(document, "## 提交给模型的完整提示词\n\n```text\n" + english +
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
        self.data = portal.build_data(self.root)
        videos = {}
        def visit(node):
            if node["kind"] == "video":
                videos[node["key"]] = node
            for child in node.get("children", []):
                visit(child)
        visit(self.data["catalogues"]["09-剧集制作"])
        for key, prompts in expected.items():
            self.assertEqual(videos[key]["prompts"], prompts)
        for key in excluded:
            self.assertNotIn("prompts", videos[key])
        current = (self.root / document).read_text(encoding="utf-8")
        self.put(document, current.replace("提交给模型的完整提示词", "提交给节点263的完整提示词"))
        self.data = portal.build_data(self.root)
        legacy_videos = {}
        def visit_legacy(node):
            if node["kind"] == "video":
                legacy_videos[node["key"]] = node
            for child in node.get("children", []):
                visit_legacy(child)
        visit_legacy(self.data["catalogues"]["09-剧集制作"])
        for key, prompts in expected.items():
            self.assertEqual(legacy_videos[key]["prompts"], prompts)

    def test_adopted_stage_videos_and_central_candidates_use_exact_run_prompts(self):
        episode = "09-剧集制作/EP001"
        identity = "EP001-C001-P001"
        english = "Approved execution text"
        self.put(f"{episode}/05-视频提示词/{identity}-视频提示词.md",
                 "## 提交给模型的完整提示词\n```text\n" + english +
                 "\n```\n## 中文提示词参考版\n```text\n当次中文\n```\n")
        expected = {}
        for folder, run, stage, text in [
                ("06-阶段采用视频/01-一采/C001-场次", "R001", "一采", english),
                ("06-阶段采用视频/02-二采/C001-场次", "R002", "二采", english),
                ("其他资料/候选视频", "R003", "一采", "Historical text"),
                ("其他资料/候选视频", "R004", "二采", english),
                ("06-生成结果/01-一采/C001-场次", "R007", "一采", english),
                ("其他资料/阶段采用视频/01-一采/C001-场次", "R008", "一采", english)]:
            self.put(f"{episode}/其他资料/执行附件/{identity}-{run}-{stage}/模型提示词.txt", text)
            key = f"{episode}/{folder}/{identity}-{run}-{stage}.mp4"
            self.put(key, "video fixture")
            expected[key] = {"english": text, "chinese": "当次中文" if text == english else ""}
        missing = f"{episode}/其他资料/候选视频/{identity}-R005-二采.mp4"
        self.put(missing, "video fixture")
        expected[missing] = {"english": "", "chinese": ""}
        excluded = [
            f"{episode}/06-阶段采用视频/01-一采/C002-场次/{identity}-R001-一采.mp4",
            f"{episode}/06-阶段采用视频/01-一采/C001-场次/{identity}-R002-二采.mp4",
            f"{episode}/其他资料/候选视频/EP002-C001-P001-R001-一采.mp4",
            f"{episode}/06-阶段采用视频/03-后处理/C001-场次/{identity}-R006-后处理.mp4",
            f"{episode}/其他资料/候选视频/EP001-C001-场次成片-v01.mp4",
            f"{episode}/其他资料/执行附件/{identity}-R001-一采/seg_0000_pre.mp4"]
        for key in excluded:
            self.put(key, "video fixture")
        legacy = f"{episode}/06-生成结果/C002-场次结果/P001-分段结果/01-一采"
        self.put(legacy + "/执行记录/R001-一采/模型提示词.txt", "Legacy text")
        old_video = legacy + "/选定/EP001-C002-P001-R001-一采.mp4"
        self.put(old_video, "video fixture")
        expected[old_video] = {"english": "Legacy text", "chinese": ""}
        self.data = portal.build_data(self.root)
        items = {}
        pending = [self.data["catalogues"]["09-剧集制作"]]
        while pending:
            node = pending.pop()
            items[node["key"]] = node
            pending.extend(node.get("children", []))
        for key, prompts in expected.items():
            self.assertEqual(items[key]["prompts"], prompts)
        for key in excluded:
            self.assertNotIn("prompts", items[key])

    def test_flat_storyboards_shared_records_and_director_pair_display_once(self):
        episode = "09-剧集制作/EP001"
        scene = episode + "/03-分镜脚本/EP001-C001-场次分镜.md"
        index = episode + "/03-分镜脚本/EP001-分镜索引.md"
        files = {
            scene: "# 场次分镜\n## EP001-C001-P001\n本段正文",
            index: "# 索引\n[分段](EP001-C001-场次分镜.md#ep001-c001-p001)",
            episode + "/03-分镜脚本/EP001-C002-场次分镜.md": "# 第二场",
            episode + "/04-专用素材/其他参考图/EP001-C001-P001-专用参考图-姿态-001.png": "image fixture",
            episode + "/06-阶段采用视频/01-一采/C001-场次/导演包/EP001-C001-一采定稿-导演包.mmxpack.zip": "zip fixture",
            episode + "/06-阶段采用视频/01-一采/C001-场次/导演包/EP001-C001-一采定稿.workflow.json": '{"nodes": []}',
            episode + "/06-阶段采用视频/02-二采/C001-场次/EP001-C001-P001-R002-二采.mp4": "video fixture",
            episode + "/06-阶段采用视频/03-后处理/C001-场次/EP001-C001-P001-R003-后处理.mp4": "video fixture",
            episode + "/其他资料/候选视频/EP001-C001-P001-R004-一采.mp4": "video fixture",
            episode + "/其他资料/执行附件/EP001-C001-P001-生成记录.md": "# 生成记录\n[候选](../候选视频/EP001-C001-P001-R004-一采.mp4)",
            episode + "/其他资料/执行附件/EP001-C001-P001-R004-一采/模型提示词.txt": "Actual text",
            episode + "/其他资料/执行附件/EP001-C001-P001-R004-一采/监控说明.md": "# 监控",
            episode + "/其他资料/审阅记录/EP001-C001-P001-R004-一采-审阅记录-001.md": "# 审阅\n- 决定：待审核",
        }
        for key, content in files.items():
            self.put(key, content)
        self.data = portal.build_data(self.root)
        data = self.data
        nodes, leaves = {}, []
        pending = [data["catalogues"]["09-剧集制作"]]
        while pending:
            node = pending.pop()
            nodes[node["key"]] = node
            if node["kind"] != "group":
                leaves.append(node["key"])
            pending.extend(node.get("children", []))
        self.assertEqual(set(leaves), set(files))
        self.assertEqual(len(leaves), len(set(leaves)))
        storyboard = nodes[episode + "/03-分镜脚本"]["children"]
        self.assertEqual([n["key"] for n in storyboard], [index, scene, episode + "/03-分镜脚本/EP001-C002-场次分镜.md"])
        self.assertNotIn(episode + "/06-生成结果", nodes)
        adopted = nodes[episode + "/06-阶段采用视频"]["children"]
        self.assertEqual([n["name"] for n in adopted], ["01-一采", "02-二采", "03-后处理"])
        pack_key = next(k for k in files if k.endswith(".zip"))
        canvas_key = next(k for k in files if k.endswith(".json"))
        self.assertEqual(nodes[pack_key]["kind"], "file")
        self.assertIn(".mmxpack.zip", nodes[pack_key]["url"])
        self.assertEqual(data["textPreviews"][canvas_key]["text"], files[canvas_key])
        self.assertIn('data-doc="' + scene + '"', data["documents"][index]["html"])
        self.assertIn('#ep001-c001-p001', data["documents"][index]["html"])
        self.assertIn('id="ep001-c001-p001"', data["documents"][scene]["html"])
        self.assertIn("未记录", nodes[episode]["statusHtml"])
        for key, content in files.items():
            self.assertEqual((self.root / key).read_text(encoding="utf-8"), content)

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def create_symlink(self, link, target):
        try:
            link.symlink_to(target)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows未授予创建符号链接的权限")
            raise

    def test_lf_and_crlf_sources_render_identically_without_rewriting(self):
        content = "# 定位\n- 文档版本：v1\n- 确认状态：已确认\n- 确认依据：第一条确认；第二条确认。\n\n## 内容\n正文。\n"
        path = self.root / portal.POSITION
        path.parent.mkdir(parents=True)
        rendered = []
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                raw = content.replace("\n", newline).encode("utf-8")
                path.write_bytes(raw)
                data = portal.build_data(self.root)
                self.assertIn('class="approval-items"', data["introHtml"])
                self.assertEqual(path.read_bytes(), raw)
                rendered.append((data["meta"], data["introHtml"], data["positionHtml"]))
        self.assertEqual(rendered[0], rendered[1])

    def test_catalogue_branch_keys_use_project_relative_forward_slashes(self):
        self.put("09-剧集制作/EP001/02-剧集剧本/EP001-本集剧本.md", "# 剧本")
        self.put("09-剧集制作/EP001/06-生成结果/C001-场次结果/P001-分段结果/01-一采/候选/结果.mp4", "video fixture")
        data = portal.build_data(self.root)
        pending = [data["catalogues"]["09-剧集制作"]]
        keys = []
        while pending:
            node = pending.pop()
            self.assertNotIn("\\", node["key"])
            self.assertTrue(node["key"].startswith("09-剧集制作"))
            keys.append(node["key"])
            pending.extend(node.get("children", []))
        self.assertIn("09-剧集制作/EP001/02-剧集剧本", keys)
        self.assertIn("09-剧集制作/EP001/06-生成结果/C001-场次结果/P001-分段结果/01-一采/候选", keys)


    def test_episode_materials_index_record_then_images_by_filename(self):
        for episode, prefix in (("EP001", ""), ("EP002", "EP002-")):
            root = f"09-剧集制作/{episode}/04-专用素材"
            for name in [prefix + "C002-P001-首帧参考图.png", prefix + "素材生成记录.md",
                         prefix + "C001-P002-首帧参考图.png", prefix + "素材索引.md",
                         prefix + "C001-P001-首帧参考图.png"]:
                self.put(root + "/" + name, "fixture")
        self.data = portal.build_data(self.root)
        episodes = self.data["catalogues"]["09-剧集制作"]["children"]
        for episode, prefix in zip(episodes, ("", "EP002-")):
            entries = episode["children"][0]["children"]
            self.assertEqual([e["name"] for e in entries], [prefix + name for name in
                             ["素材索引.md", "素材生成记录.md", "C001-P001-首帧参考图.png",
                              "C001-P002-首帧参考图.png", "C002-P001-首帧参考图.png"]])

    def test_indexes_then_files_then_folders_at_each_level(self):
        root = "09-剧集制作/EP001"
        paths = ["EP001-制作索引.md", "03-分镜脚本/EP001-分镜索引.md",
                 "03-分镜脚本/C001-场次分镜/EP001-C001-分镜.md",
                 "03-分镜脚本/A-说明.md", "03-分镜脚本/EP001-分镜索引-草稿-v01.md",
                 "02-剧集剧本/EP001-本集剧本.md", "02-剧集剧本/EP001-C001-分场剧本.md"]
        for path in paths:
            self.put(root + "/" + path, "# 正文")
        self.put("00-项目定位/过程稿/A-说明.md", "# 说明")
        self.put("00-项目定位/过程稿/Z-资料索引.md", "# 索引")
        self.data = portal.build_data(self.root)
        data = self.data
        children = data["catalogues"]["09-剧集制作"]["children"][0]["children"]
        self.assertEqual([c["name"] for c in children], ["EP001-制作索引.md", "02-剧集剧本", "03-分镜脚本"])
        self.assertEqual([c["name"] for c in children[2]["children"]],
                         ["EP001-分镜索引.md", "A-说明.md", "EP001-分镜索引-草稿-v01.md", "C001-场次分镜"])
        self.assertEqual([c["name"] for c in children[1]["children"]],
                         ["EP001-本集剧本.md", "EP001-C001-分场剧本.md"])
        self.assertEqual(next(g for g in data["groups"] if g["name"] == "过程稿")["files"][0]["name"], "Z-资料索引.md")
        self.assertTrue(all(root + "/" + path in data["documents"] for path in paths))

    def test_folder_previews_cover_documents_text_media_and_unknown_files(self):
        base = "00-项目定位/过程稿/"
        expected = {"md": "document", "json": "text", "txt": "text", "log": "text",
                    "png": "image", "mp4": "video", "wav": "audio", "zip": "file"}
        payload = '</script><img src=x onerror="alert(1)">'
        for extension in expected:
            self.put(base + "附件." + extension, payload)
        self.data = portal.build_data(self.root)
        data = self.data
        files = next(g for g in data["groups"] if g["name"] == "过程稿")["files"]
        self.assertEqual({Path(f["key"]).suffix[1:]: f["kind"] for f in files}, expected)
        self.assertEqual(data["textPreviews"][base + "附件.json"]["text"], payload)
        self.assertNotIn(base + "附件.png", data["textPreviews"])
        self.assertIn(base + "附件.json", data["sources"])
        self.assertNotIn(payload, data["documents"][base + "附件.md"]["html"])

    def test_plain_text_preview_is_bounded_and_invalid_utf8_does_not_break_page(self):
        base = "00-项目定位/过程稿/"
        self.put(base + "大.json", "中" * 100000)
        bad = self.put(base + "错误.log", "")
        bad.write_bytes(b"\xff\xfe")
        self.data = portal.build_data(self.root)
        previews = self.data["textPreviews"]
        self.assertLessEqual(len(previews[base + "大.json"]["text"].encode()), 256 * 1024)
        self.assertIn("截取", previews[base + "大.json"]["notice"])
        self.assertIn("UTF-8", previews[base + "错误.log"]["notice"])
        self.assertEqual(previews[base + "错误.log"]["text"], "")

    def test_catalogue_and_folders_share_preview_types(self):
        self.put("历史版本/批次/工作流.json", '{"value": 1}')
        self.data = portal.build_data(self.root)
        data = self.data
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

    def test_adopted_generation_is_formal_only_across_all_asset_kinds(self):
        records = [self.person_fixture()[1], self.prop_fixture(), self.scene_fixture()[1]]
        for record in records:
            text = record.read_text().replace("| v01 |", "| v01／生成001 |")
            generation = text[text.index("### 生成记录-001"):]
            record.write_text(text + "\n" + generation.replace("生成记录-001", "生成记录-002"))
        data = portal.build_data(self.root)
        for group in ("people", "props", "scenes"):
            owner = data[group][0]
            self.assertEqual([c["generation"] for c in owner["candidates"]], ["生成记录-002"])
            self.assertEqual(owner["pendingCount"], 1)
            self.assertTrue(any(a["version"] == "v01／生成001" for a in owner["formal"]))
            self.assertIn("生成记录-001", (self.root / owner["recordKey"]).read_text())

    def test_completed_adoption_matches_approval_when_generation_number_missing(self):
        record = self.person_fixture()[1]
        record.write_text(record.read_text().replace("用户采用状态：待确认。", "用户采用状态：已采用"))
        owner = portal.build_data(self.root)["people"][0]
        self.assertEqual(owner["candidates"], [])
        self.assertTrue(owner["formal"][0]["approved"])
        (self.root / owner["formal"][0]["media"]["key"]).unlink()
        self.assertEqual(len(portal.build_data(self.root)["people"][0]["candidates"]), 1)

    def test_approval_alone_or_missing_formal_file_keeps_candidate(self):
        records = [self.person_fixture("待确认")[1], self.prop_fixture("待确认"), self.scene_fixture("待确认")[1]]
        for record in records:
            record.write_text(record.read_text().replace("| v01 |", "| v01／生成001 |"))
        data = portal.build_data(self.root)
        for group in ("people", "props", "scenes"):
            self.assertEqual(len(data[group][0]["candidates"]), 1)
        for review in self.root.glob("*/审阅记录/*.md"):
            review.write_text(review.read_text().replace("待确认", "批准采用"))
        for image in self.root.glob("*/*/参考图/*.png"):
            image.unlink()
        data = portal.build_data(self.root)
        for group in ("people", "props", "scenes"):
            self.assertEqual(len(data[group][0]["candidates"]), 1)

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
            material = self.root / stage / "其他资料" / "过程稿" / "素材"
            material.mkdir()
            for candidate in material.parent.glob("*.png"):
                candidate.rename(material / candidate.name)
            self.put(stage + "/其他资料/过程稿/" + before[kind][0]["id"] + "-资料卡-草稿-v01.md", "# 草稿")
            record.write_text(record.read_text().replace("../../过程稿/", "../../其他资料/过程稿/素材/")
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
            self.assertTrue(all("/其他资料/过程稿/素材/" in c["media"]["key"] for c in person["candidates"]))
            groups = {g["name"]: g["files"] for g in person["groups"]}
            self.assertEqual(len(groups["执行附件"]), 2)
            keys = [item["key"] for item in groups["过程稿"]]
            self.assertIn(stage + "/其他资料/过程稿/" + person["id"] + "-资料卡-草稿-v01.md", keys)
            self.assertTrue(all(c["media"]["key"] in keys for c in person["candidates"]))
            self.assertEqual(len(keys), len(set(keys)))
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

    def test_record_based_candidates_are_pending_without_visual_review(self):
        records = [("people", self.person_fixture()[1]),
                   ("props", self.prop_fixture()), ("scenes", self.scene_fixture()[1])]
        for _, record in records:
            record.write_text(re.sub(r"- agent 画面初审结论：[^\n]*",
                "- 文件核对结论：通过\n- 看图调用状态：未调用（默认）\n"
                "- 看图授权及限定范围：不适用\n- 授权查看的发现：不适用", record.read_text()))
        before = {str(r): r.read_bytes() for _, r in records}
        self.data = portal.build_data(self.root)
        data = self.data
        for group, record in records:
            candidate = data[group][0]["candidates"][0]
            self.assertTrue(candidate["recordBasedReview"])
            self.assertTrue(candidate["pending"])
            self.assertFalse(candidate["twoStageReview"])
            self.assertFalse(candidate["visionAuthorized"])
            self.assertNotIn("technicalHtml", candidate)
            self.assertEqual(data[group][0]["pendingCount"], 1)
            self.assertEqual(record.read_bytes(), before[str(record)])

    def test_pending_label_preserves_explicit_review_state_across_record_formats(self):
        for chunk in ("- 文件核对结论：通过", "- agent 技术审查结论：不通过",
                      "- 执行状态：unknown\n- 文件核对结论：不适用", ""):
            for decision, expected in (
                ("待确认；测试候选，正式v05有效", "待确认"),
                ("待审核。用户尚未查看", "待审核"),
                ("已采用；历史曾待确认", ""),
                ("已批准，待超分", ""),
                ("历史候选已结束，未采用，不再待审", ""),
                ("未送审；实际候选尚未展示", ""),
                ("试验已结束，无输出，未采用，不再待审", ""),
                ("修改后再审", ""),
            ):
                with self.subTest(chunk=chunk, decision=decision):
                    result = portal.image_review_fields(chunk, portal.POSITION, "未记录", decision)
                    self.assertEqual(result["pendingLabel"], expected)
                    self.assertEqual(result["pending"], bool(expected))
                    self.assertIn(decision.split("；")[0].split("。")[0],
                                  result["userHtml"])

    def test_candidate_decision_reason_is_separate_safe_and_not_a_pending_state(self):
        records = [("people", self.person_fixture()[1]),
                   ("props", self.prop_fixture()), ("scenes", self.scene_fixture()[1])]
        for _, record in records:
            text = re.sub(r"- 用户采用状态：[^\n]*",
                          "- 用户采用状态：已结束未采用\n"
                          "- 用户决定原因与依据：历史曾待确认；用户结束比较 <script>bad</script>",
                          record.read_text())
            record.write_text(text)
        data = portal.build_data(self.root)
        for group, _ in records:
            candidate = data[group][0]["candidates"][0]
            self.assertIn("已结束未采用", candidate["userHtml"])
            self.assertNotIn("用户结束比较", candidate["userHtml"])
            self.assertIn("用户结束比较", candidate["userReasonHtml"])
            self.assertNotIn("<script>", candidate["userReasonHtml"])
            self.assertFalse(candidate["pending"])
            self.assertEqual(data[group][0]["pendingCount"], 0)

    def test_authorized_analysis_does_not_override_user_decision(self):
        chunk = ("- 文件核对结论：通过\n- 看图调用状态：已按授权查看\n"
                 "- 看图授权及限定范围：用户要求看左侧视格\n"
                 "- 授权查看的发现：领口有偏差 <script>bad</script>\n")
        pending = portal.image_review_fields(chunk, portal.POSITION, "未记录", "待确认")
        self.assertTrue(pending["pending"])
        self.assertTrue(pending["visionAuthorized"])
        self.assertIn("左侧视格", pending["visionScopeHtml"])
        self.assertNotIn("<script>", pending["visionFindingsHtml"])
        for decision in ("批准采用", "不采用", "已结束，未采用"):
            result = portal.image_review_fields(chunk, portal.POSITION, "未记录", decision)
            self.assertFalse(result["pending"])

    def test_two_stage_review_content_deviation_does_not_block_user_review(self):
        records = [("people", self.person_fixture()[1]),
                   ("props", self.prop_fixture()), ("scenes", self.scene_fixture()[1])]
        for group, record in records:
            record.write_text(re.sub(r"- agent 画面初审结论：[^\n]*",
                "- agent 技术审查结论：通过\n- agent 内容审查状态：已完成\n"
                "- agent 内容审查发现：有偏差；肩部裁切 <script>bad</script>", record.read_text()))
        before = {str(r): r.read_bytes() for _, r in records}
        self.data = portal.build_data(self.root)
        data = self.data
        for group, record in records:
            candidate = data[group][0]["candidates"][0]
            self.assertTrue(candidate["twoStageReview"])
            self.assertTrue(candidate["pending"])
            self.assertIn("通过", candidate["technicalHtml"])
            self.assertIn("有偏差", candidate["contentFindingsHtml"])
            self.assertNotIn("<script>", candidate["contentFindingsHtml"])
            self.assertEqual(record.read_bytes(), before[str(record)])
            self.assertIn("待确认", candidate["userHtml"])

    def test_historical_visual_review_does_not_block_pending_user_approval(self):
        _, record = self.person_fixture()
        original = record.read_text()
        for technical, content in [("不通过", "未进行"), ("待确认", "未进行"),
                                   ("通过", "未进行"), ("未记录", "已完成")]:
            with self.subTest(technical=technical, content=content):
                record.write_text(re.sub(r"- agent 画面初审结论：[^\n]*",
                    f"- agent 技术审查结论：{technical}\n- agent 内容审查状态：{content}\n"
                    "- agent 内容审查发现：技术审查未通过，未进行内容审查", original))
                self.data = portal.build_data(self.root)
                person = self.data["people"][0]
                self.assertTrue(person["candidates"][0]["pending"])
                self.assertEqual(person["pendingCount"], 1)
                self.assertTrue(person["formal"][0]["approved"])
        for decision in ("批准采用", "不采用", "历史候选已结束，未采用，不再待审"):
            result = portal.image_review_fields(
                "- agent 技术审查结论：不通过\n- agent 内容审查状态：未进行\n",
                portal.POSITION, "未记录", decision)
            self.assertFalse(result["pending"])
        record.write_text(original)
        self.data = portal.build_data(self.root)
        candidate = self.data["people"][0]["candidates"][0]
        self.assertFalse(candidate["twoStageReview"])
        self.assertTrue(candidate["pending"])
        self.assertIn("通过", candidate["agentHtml"])

    def test_scene_assets_survive_multiple_production_episodes(self):
        self.scene_fixture()
        self.data = portal.build_data(self.root)
        expected = self.data["scenes"]
        for episode, scene in (("EP001", "C001"), ("EP002", "C002")):
            self.put(f"09-剧集制作/{episode}/03-分镜脚本/{scene}-场次分镜/{episode}-{scene}-场次分镜.md", "# 分镜")
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertEqual(data["scenes"], expected)
        episodes = data["catalogues"]["09-剧集制作"]["children"]
        self.assertEqual(len(episodes), 2)
        for episode, scene in zip(episodes, ("C001", "C002")):
            self.assertEqual(episode["children"][0]["name"], "03-分镜脚本")
            self.assertEqual(episode["children"][0]["children"][0]["name"], scene + "-场次分镜")

    def test_people_index_survives_empty_media_libraries(self):
        self.person_fixture()
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertEqual(data["peopleIndex"], "03-人物资料/人物索引.md")
        self.assertIn(data["peopleIndex"], data["documents"])

    def test_media_index_does_not_create_missing_people_index(self):
        self.put("08-参考视频/参考视频索引.md", "# 参考视频索引")
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertIsNone(data["peopleIndex"])
        self.assertEqual(data["catalogues"]["08-参考视频"]["indexKey"], "08-参考视频/参考视频索引.md")

    def test_catalogue_outlines_follow_index_not_production_status(self):
        self.put("06-分集大纲/分集索引.md", "# 索引\n| 集号 | 所属故事阶段 | 一句话概要 | 大纲入口 |\n| --- | --- | --- | --- |\n| EP001 | 第一阶段 | 原概要 | [文档](EP001-分集大纲.md) |\n| EP002 | 第二阶段 | 缺文件 | [文档](EP002-分集大纲.md) |")
        source = self.put("06-分集大纲/EP001-分集大纲.md", "# EP001\n- 确认状态：已确认\n本集题名：先撑过今晚。\n## 剧情\n原剧情")
        self.data = portal.build_data(self.root)
        items = self.data["catalogues"]["06-分集大纲"]["children"]
        self.assertEqual([i["name"] for i in items], ["EP001", "EP002"])
        self.assertEqual(items[0]["category"], "第一阶段")
        self.assertEqual(items[0]["title"], "先撑过今晚")
        self.assertEqual(items[1]["title"], "")
        self.assertFalse(items[1]["doc"]["exists"])
        self.assertEqual(source.read_text("utf-8"), "# EP001\n- 确认状态：已确认\n本集题名：先撑过今晚。\n## 剧情\n原剧情")
        self.assertEqual(self.data["catalogues"]["09-剧集制作"]["children"], [])

    def test_outline_without_stage_column_remains_readable(self):
        self.put("06-分集大纲/分集索引.md", "# 索引\n| 集号 | 一句话概要 | 大纲入口 |\n| --- | --- | --- |\n| EP001 | 原概要 | [文档](EP001-分集大纲.md) |")
        self.put("06-分集大纲/EP001-分集大纲.md", "# EP001\n## 本集剧情\n正文")
        self.data = portal.build_data(self.root)
        item = self.data["catalogues"]["06-分集大纲"]["children"][0]
        self.assertEqual(item["name"], "EP001")
        self.assertEqual(item["category"], "")
        self.assertTrue(item["doc"]["exists"])
        self.assertIn("正文", item["doc"]["bodyHtml"])

    def test_catalogue_media_uses_recorded_metadata_and_missing_file(self):
        self.put("07-参考音频/参考音频索引.md", "# 索引\n| 编号 | 名称 | 分类 | 文件入口 | 参考用途与适用范围 | 来源及使用授权说明 | 实测时长 | 审核／采用状态及版本依据 |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| RA001 | 声音 | 人物声音 | [音频](人物声音/RA001.wav) | 音色 | 用户自制 | 未测 | 待确认 |\n| RA002 | 缺失 | 环境声音 | [音频](环境声音/RA002.wav) | 风 | 未记录 | 未测 | 未记录 |")
        self.put("07-参考音频/人物声音/RA001.wav", "fixture audio")
        self.put("07-参考音频/环境声音/未登记.mp3", "loose file")
        self.data = portal.build_data(self.root)
        audio = self.data["catalogues"]["07-参考音频"]
        self.assertEqual(audio["children"][0]["media"]["kind"], "audio")
        self.assertEqual(audio["children"][0]["duration"], "未测")
        self.assertIn("status-orange", audio["children"][0]["statusHtml"])
        self.assertIsNone(audio["children"][1]["media"])
        self.assertEqual(audio["children"][2]["name"], "未登记／其他文件")

    def test_reference_cards_keep_media_separate_from_adoption_evidence(self):
        for root, prefix, folder, extension, status in (
                ("07-参考音频", "RA", "正式素材", "wav", "批准采用"),
                ("08-参考视频", "RV", "人物表演与动作", "mp4", "未采用")):
            index = root + "/" + root.split("-", 1)[1] + "索引.md"
            media = folder + "/" + prefix + "001." + extension
            record = "其他资料/工作稿/索引-工作稿.md"
            self.put(root + "/" + media, "fixture media")
            self.put(root + "/" + record, "# 记录\n## 采用依据\n真实说明")
            text = "| 编号 | 名称 | 分类 | 文件入口 | 参考用途与适用范围 | 来源及使用授权说明 | 实测时长 | 审核／采用状态及版本依据 |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            text += f"| {prefix}001 | 测试 | 分类 | [媒体]({media}) | 范围 | 用户授权 | 4秒 | {status}；版本说明；[采用依据]({record}#采用依据) |\n"
            text += f"| {prefix}002 | 状态缺失 | 分类 | 待制作 | 范围 | 来源 | 未测 | 尚无记载 |\n"
            source = self.put(index, text)
            items = portal.build_data(self.root)["catalogues"][root]["children"]
            self.assertEqual(items[0]["media"]["key"], root + "/" + media)
            self.assertIn(status, items[0]["approvalHtml"])
            self.assertNotIn("版本说明", items[0]["approvalHtml"])
            self.assertIn("版本说明", items[0]["statusHtml"])
            self.assertIn('data-doc="' + root + "/" + record + '"', items[0]["statusHtml"])
            self.assertIn("未知", items[1]["approvalHtml"])
            self.assertIn("尚无记载", items[1]["statusHtml"])
            self.assertEqual(source.read_text("utf-8"), text)

    def test_reference_library_process_files_are_separate_from_unregistered_media(self):
        for root in ("07-参考音频", "08-参考视频"):
            self.put(root + "/其他资料/工作稿/索引-工作稿.md", "# 工作稿\n\n保留用户决定")
            self.put(root + "/其他资料/历史版本/索引-归档.md", "# 旧版")
            self.put(root + "/其他资料/执行附件/命令.txt", "fixture command")
            self.put(root + "/未登记.wav", "fixture media")
        self.data = portal.build_data(self.root)
        data = self.data
        for root in ("07-参考音频", "08-参考视频"):
            children = data["catalogues"][root]["children"]
            self.assertEqual([node["name"] for node in children], ["未登记／其他文件", "其他资料"])
            self.assertEqual([node["key"] for node in children[0]["children"]], [root + "/未登记.wav"])
            self.assertEqual({node["name"] for node in children[1]["children"]}, {"工作稿", "历史版本", "执行附件"})
            self.assertIn(root + "/其他资料/工作稿/索引-工作稿.md", data["documents"])
            self.assertTrue((self.root / root / "其他资料/历史版本/索引-归档.md").is_file())

    def test_catalogue_empty_libraries_do_not_create_directories(self):
        self.data = portal.build_data(self.root)
        for root in ("07-参考音频", "08-参考视频"):
            self.assertEqual(self.data["catalogues"][root]["children"], [])
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
        self.data = portal.build_data(self.root)
        ep = self.data["catalogues"]["09-剧集制作"]["children"][0]
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
        self.data = portal.build_data(self.root)
        ep = self.data["catalogues"]["09-剧集制作"]["children"][0]
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
        self.data = portal.build_data(self.root)
        ep = self.data["catalogues"]["09-剧集制作"]["children"][0]
        film = ep["children"][0]["children"][0]["children"][0]
        self.assertEqual(film["name"], "场次成片")
        self.assertEqual([n["name"] for n in film["children"]],
                         ["成片索引.md", "EP001-C001-成片说明.md", "选定", "候选", "审阅记录", "执行记录", "其他附件"])

    def test_progress_uses_current_template_project_name_without_new_timestamp(self):
        template = (Path(__file__).resolve().parents[2] / ".agents/skills/nora-ai-short-drama"
                    / "references/模板/项目进度模板.md").read_text(encoding="utf-8")
        self.assertIn("- 项目名称或代号：", template)
        self.put("项目进度.md", template.replace("- 项目名称或代号：待确认", "- 项目名称或代号：模板项目"))
        data = portal.build_data(self.root)
        self.assertEqual(data["project"], "模板项目")
        self.assertEqual(data["progressUpdated"], "未记录")

    def test_progress_legacy_project_name_and_timestamp_remain_readable(self):
        self.put("项目进度.md", "# 项目进度\n- 项目名称：旧项目\n- 更新时间：2026-10-03\n")
        data = portal.build_data(self.root)
        self.assertEqual(data["project"], "旧项目")
        self.assertEqual(data["progressUpdated"], "2026-10-03")
        self.put("项目进度.md", "# 项目进度\n- 项目名称：旧项目\n- 项目名称或代号：新项目\n")
        self.assertEqual(portal.build_data(self.root)["project"], "新项目")

    def test_integrated_scene_storyboard_links_work_without_separate_scripts(self):
        root = "09-剧集制作/EP001"
        self.put("项目进度.md", "# 项目进度\n\n- 项目名称：测试项目\n- 更新时间：2026-10-03\n\n"
                 "| 阶段名称 | 对应会话入口 | 当前状态 | 成果入口 | 待决事项 | 下一步 |\n"
                 "| --- | --- | --- | --- | --- | --- |\n"
                 "| EP001 制作 | 未记录 | 进行中 | 未记录 | 无 | 视频准备 |")
        self.put(portal.POSITION, "# 项目基本定位\n\n- 确认状态：已确认\n\n## 项目规格\n测试项目")
        story = root + "/02-剧集剧本/EP001-本集剧本.md"
        scene = root + "/03-分镜脚本/C001-场次分镜/EP001-C001-场次分镜.md"
        index = root + "/03-分镜脚本/EP001-分镜索引.md"
        prompt = root + "/05-视频提示词/EP001-C001-P001-视频提示词.md"
        self.put(story, "# 本集剧本\n\n## 1. 故事剧本正文\n\n### EP001-C001\n\n剧情和对白")
        self.put(scene, "# 场次分镜\n\n来源剧本：[C001](../../02-剧集剧本/EP001-本集剧本.md#ep001-c001)\n\n"
                 "## 1. 镜头正文\n\n镜号：EP001-SH001\n\n台词：今天按时下班。\n\n"
                 "## 2. 视频分段\n\n| 分段编号 | 包含镜号 |\n| --- | --- |\n"
                 "| EP001-C001-P001 | EP001-SH001 |\n\n### EP001-C001-P001\n\n"
                 "| 项目镜号 | H3 段内镜号 | 段内起点（秒） | 段内终点（秒） |\n"
                 "| --- | --- | --- | --- |\n| EP001-SH001 | Shot 1 | 0 | 8 |")
        self.put(index, "[P001](C001-场次分镜/EP001-C001-场次分镜.md#ep001-c001-p001)")
        self.put(prompt, "[来源P001](../03-分镜脚本/C001-场次分镜/EP001-C001-场次分镜.md#ep001-c001-p001)")
        result = self.data = portal.build_data(self.root)
        self.assertEqual(result["warnings"], [])
        data = self.data
        self.assertTrue({story, scene, index, prompt}.issubset(data["documents"]))
        self.assertIn('id="ep001-c001"', data["documents"][story]["html"])
        scene_html = data["documents"][scene]["html"]
        self.assertIn('id="ep001-c001-p001"', scene_html)
        self.assertIn('<table>', scene_html)
        self.assertEqual(scene_html.count("今天按时下班。"), 1)
        for key in (index, prompt):
            rendered = data["documents"][key]["html"]
            self.assertIn('data-doc="' + scene + '"', rendered)
            self.assertIn('#ep001-c001-p001', rendered)
        ep = data["catalogues"]["09-剧集制作"]["children"][0]
        storyboard_group = next(child for child in ep["children"] if child["name"] == "03-分镜脚本")
        scene_group = next(child for child in storyboard_group["children"] if child["name"] == "C001-场次分镜")
        self.assertEqual([child["key"] for child in scene_group["children"]], [scene])

    def video_approval_fixture(self):
        root = '09-剧集制作/EP001'
        identity = 'EP001-C001-P001'
        self.put(root + '/02-剧集剧本/EP001-本集剧本.md',
                 '# 剧本\n## 1. 故事剧本正文\n### EP001-C001\n办公室。')
        self.put(root + '/03-分镜脚本/EP001-C001-场次分镜.md',
                 '# 分镜\n## 1. 镜头正文\n### EP001-C001-P001\n镜头。')
        self.put(root + '/03-分镜脚本/EP001-分镜索引.md',
                 '# 索引\n| 分段 | 场次 | 分段计划时长（秒） |\n| --- | --- | --- |\n'
                 '| EP001-C001-P001 | EP001-C001 | 3 |')
        record = root + '/其他资料/工作稿/' + identity + '-视频制作-工作稿.md'
        table = '| 处理阶段 | 当前选定文件 | R编号 | 来源任务 | 人工批准依据 |\n| --- | --- | --- | --- | --- |\n'
        bodies, reviews = [], []
        for folder, stage in [('01-一采', '一采'), ('02-二采', '二采'), ('03-后处理', '后处理')]:
            name = f'{identity}-R001-{stage}.mp4'
            link = f'../../06-阶段采用视频/{folder}/C001-场次/{name}'
            self.put(f'{root}/06-阶段采用视频/{folder}/C001-场次/{name}', 'fixture')
            table += f'| {stage} | [视频]({link}) | R001 | 原任务 | [批准](#审阅-r001-{stage}-001) |\n'
            # An old pending execution summary must not override the actual later review.
            bodies.append(f'### R001-{stage}\n- 处理阶段：{stage}\n- 用户决定：待审核。\n')
            reviews.append(f'### 审阅-R001-{stage}-001\n#### 3. 人工审核决定\n'
                           f'- 决定：批准采用。\n- 对应具体输出：[视频]({link})。\n')
        text = '# 工作稿\n## 1. 当前选定结果\n' + table + '\n## 2. 修订版各阶段与采用记录\n' + '\n'.join(bodies) + '\n## 4. 审阅区\n' + '\n'.join(reviews)
        self.put(record, text)
        return record, text

    def test_unselected_video_candidates_do_not_warn_or_become_approved(self):
        for state in ('未选定', '尚未选定', '未采用', '尚未采用'):
            for decision in ('待审核。', '批准采用。'):
                with self.subTest(state=state, decision=decision):
                    record, text = self.video_approval_fixture()
                    for folder, stage in [('01-一采', '一采'), ('02-二采', '二采'), ('03-后处理', '后处理')]:
                        name = f'EP001-C001-P001-R001-{stage}.mp4'
                        old = f'09-剧集制作/EP001/06-阶段采用视频/{folder}/C001-场次/{name}'
                        new = f'09-剧集制作/EP001/其他资料/候选视频/{name}'
                        self.put(new, 'fixture')
                        (self.root / old).unlink()
                        text = text.replace(f'../../06-阶段采用视频/{folder}/C001-场次/{name}', f'../候选视频/{name}')
                        text = text.replace(f'| {stage} | [视频]', f'| {stage} | {state}；[视频]')
                    text = text.replace('- 决定：批准采用。', '- 决定：' + decision)
                    self.put(record, text)
                    data = portal.build_data(self.root, web_episode_navigation=True)
                    videos = data['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos']
                    self.assertEqual(len(videos), 3)
                    self.assertTrue(all(not video['approved'] for video in videos))
                    self.assertFalse(any('当前选定记录的批准依据' in warning for warning in data['warnings']))

    def test_selected_video_without_approval_still_warns(self):
        record, text = self.video_approval_fixture()
        text = text.replace('[批准](#审阅-r001-一采-001)', '无', 1)
        text = text[:text.index('## 4. 审阅区')]
        self.put(record, text)
        data = portal.build_data(self.root, web_episode_navigation=True)
        videos = data['catalogues']['09-剧集制作']['children'][0]['segments']['C001'][0]['videos']
        self.assertFalse(next(video for video in videos if video['stage'] == '一采')['approved'])
        self.assertTrue(any('EP001-C001-P001-R001-一采.mp4：当前选定记录的批准依据' in warning for warning in data['warnings']))

    def test_video_approval_follows_exact_review_for_each_stage(self):
        self.video_approval_fixture()
        data = portal.build_data(self.root, web_episode_navigation=True)
        episode = data['catalogues']['09-剧集制作']['children'][0]
        videos = episode['segments']['C001'][0]['videos']
        self.assertEqual({v['stage'] for v in videos if v['approved']}, {'一采', '二采', '后处理'})
        self.assertFalse(any('批准依据' in warning for warning in data['warnings']))

    def test_video_approval_rejects_wrong_identity_or_unapproved_linked_review(self):
        for replacement in ['待审核。', '不采用。', '批准采用／修改后再审／不采用']:
            with self.subTest(decision=replacement):
                record, text = self.video_approval_fixture()
                text = text.replace('- 用户决定：待审核。', '- 用户决定：批准采用。')
                text = text.replace('- 决定：批准采用。', '- 决定：' + replacement, 1)
                self.put(record, text)
                data = portal.build_data(self.root, web_episode_navigation=True)
                episode = data['catalogues']['09-剧集制作']['children'][0]
                self.assertFalse(next(v for v in episode['segments']['C001'][0]['videos'] if v['stage'] == '一采')['approved'])
                self.assertTrue(any('批准依据' in warning for warning in data['warnings']))
        for wrong in ['EP001-C001-P001-R002-一采.mp4', 'EP001-C001-P001-R001-二采.mp4', 'EP001-C001-P002-R001-一采.mp4']:
            with self.subTest(output=wrong):
                record, text = self.video_approval_fixture()
                start = text.index('### 审阅-R001-一采-001')
                text = text[:start] + text[start:].replace('EP001-C001-P001-R001-一采.mp4', wrong, 1)
                self.put(record, text)
                data = portal.build_data(self.root, web_episode_navigation=True)
                episode = data['catalogues']['09-剧集制作']['children'][0]
                self.assertFalse(next(v for v in episode['segments']['C001'][0]['videos'] if v['stage'] == '一采')['approved'])
                self.assertTrue(any('批准依据' in warning for warning in data['warnings']))
        record, text = self.video_approval_fixture()
        self.put(record, text.replace('#审阅-r001-一采-001', '#审阅-r001-一采-不存在', 1))
        data = portal.build_data(self.root, web_episode_navigation=True)
        episode = data['catalogues']['09-剧集制作']['children'][0]
        self.assertFalse(next(v for v in episode['segments']['C001'][0]['videos'] if v['stage'] == '一采')['approved'])
        self.assertTrue(any('批准依据' in warning for warning in data['warnings']))

    def test_legacy_video_execution_headings_match_stage_instead_of_first_same_run(self):
        text = ('### R005-后处理\n- 处理阶段：后处理。\n- 实测时长及数值来源：后处理\n'
                '### R005鞋子取景返修一采\n- 实测时长及数值来源：一采\n'
                '### R005-标准版二采\n- 实测时长及数值来源：二采\n')
        for stage in ('一采', '二采', '后处理'):
            self.assertEqual(portal.field(portal.video_record_body(text, 'R005', stage), '实测时长及数值来源'), stage)

    def test_legacy_execution_only_approval_and_linked_legacy_adoption_remain_readable(self):
        record, text = self.video_approval_fixture()
        text = text.replace('[批准](#审阅-r001-一采-001)', '用户当时明确批准')
        text = text.replace('- 用户决定：待审核。', '- 用户决定：批准采用。', 1)
        text = text.replace('- 决定：批准采用。', '- 决定：通过并采用本轮视频。')
        self.put(record, text)
        episode = portal.build_data(self.root, web_episode_navigation=True)['catalogues']['09-剧集制作']['children'][0]
        self.assertTrue(all(v['approved'] for v in episode['segments']['C001'][0]['videos']))

    def test_production_navigation_retains_segments_stages_and_candidate_selection(self):
        root = "09-剧集制作/EP001"
        self.put(root + "/03-分镜脚本/C001-场次分镜/EP001-C001-场次分镜.md", "# 场次分镜")
        self.put(root + "/03-分镜脚本/C001-场次分镜/EP001-C001-P001-分段分镜.md", "# 分镜1")
        self.put(root + "/03-分镜脚本/C001-场次分镜/EP001-C001-P002-分段分镜.md", "# 分镜2")
        self.put(root + "/05-视频提示词/C001-场次生成资料/P001-分段生成资料/EP001-C001-P001-视频提示词.md", "# 准备")
        self.put(root + "/06-生成结果/C001-场次结果/P001-分段结果/01-一采/选定/EP001-C001-P001-R001-一采.mp4", "fixture")
        self.put(root + "/06-生成结果/C001-场次结果/P001-分段结果/02-二采/候选/EP001-C001-P001-R002-二采.mp4", "fixture")
        self.put(root + "/其他资料/过程稿/EP001-C002-草稿.md", "# 非正式")
        for category in ("讨论记录", "审阅记录", "历史版本"):
            self.put(root + "/其他资料/" + category + "/EP001-记录.md", "# 记录")
        self.put(root + "/说明.md", "# 根目录文件")
        (self.root / root / "01-制作前检查").mkdir()
        self.data = portal.build_data(self.root)
        ep = self.data["catalogues"]["09-剧集制作"]["children"][0]
        self.assertEqual([s["name"] for s in ep["children"]],
                         ["说明.md", "01-制作前检查", "03-分镜脚本", "05-视频提示词", "06-生成结果", "其他资料"])
        self.assertEqual(ep["children"][1]["children"], [])
        def leaves(node):
            if node["kind"] != "group":
                return [node["key"]]
            return [key for child in node["children"] for key in leaves(child)]
        keys = leaves(ep)
        self.assertEqual(len(keys), 11)
        scene = ep["children"][2]["children"][0]
        self.assertEqual([n["name"] for n in scene["children"]],
                         ["EP001-C001-场次分镜.md", "EP001-C001-P001-分段分镜.md", "EP001-C001-P002-分段分镜.md"])
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
            self.create_symlink(self.root / "历史版本/越界.md", external)
            self.data = portal.build_data(self.root)
        data = self.data
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
        self.data = portal.build_data(self.root)
        prop = self.data["props"][0]
        self.assertEqual([a["state"] for a in prop["formal"]], ["破损", "基础"])
        self.assertEqual(prop["cover"]["state"], "基础")
        self.assertIn("status-green", prop["formal"][0]["statusHtml"])
        self.assertEqual(prop["candidates"][0]["state"], "基础；完整关闭")
        self.assertIn("status-orange", prop["candidates"][0]["userHtml"])
        self.assertEqual(prop["pendingCount"], 1)
        self.assertEqual(before, record.read_bytes())

    def test_prop_unapproved_base_falls_back_to_approved_state(self):
        self.prop_fixture("待确认。")
        self.data = portal.build_data(self.root)
        prop = self.data["props"][0]
        self.assertEqual(prop["cover"]["state"], "破损")
        self.assertFalse(prop["formal"][1]["approved"])

    def test_prop_formal_directory_displays_images_without_record(self):
        record = self.prop_fixture()
        record.unlink()
        self.data = portal.build_data(self.root)
        prop = self.data["props"][0]
        self.assertIsNone(prop["cover"])
        self.assertEqual({a["state"] for a in prop["formal"]}, {"基础", "破损"})
        self.assertTrue(all(a["directoryDiscovered"] for a in prop["formal"]))
        self.assertIn("status-green", prop["card"]["confirmationHtml"])
        self.assertFalse((self.root / "05-道具资料/讨论记录").exists())

    def test_directory_discovery_merges_records_and_excludes_nested_files(self):
        record = self.prop_fixture()
        _, scene_record = self.scene_fixture()
        before = record.read_bytes(), scene_record.read_bytes()
        self.put("05-道具资料/PR001-盒子/参考图/PR001-开启-道具参考图.webp", "open")
        self.put("05-道具资料/PR001-盒子/参考图/另一状态.JPG", "unknown name")
        self.put("05-道具资料/PR001-盒子/参考图/.隐藏.png", "hidden")
        self.put("05-道具资料/PR001-盒子/参考图/历史版本/旧图.png", "nested")
        self.put("04-场景资料/SC001-药庐/参考图/SC001-EP001-C002-场景参考图.jpg", "second scene")
        self.put("04-场景资料/SC001-药庐/参考图/SC001-平面布局.png", "plan")
        self.data = portal.build_data(self.root)
        data = self.data
        prop, scene = data["props"][0], data["scenes"][0]
        self.assertEqual({a["state"] for a in prop["formal"]}, {"破损", "基础", "开启", "另一状态"})
        self.assertEqual(next(a for a in prop["formal"] if a["state"] == "破损")["version"], "v02")
        self.assertEqual(len(scene["formal"]), 2)
        self.assertEqual(len(scene["auxiliary"]), 2)
        self.assertEqual(scene["formal"][1]["state"], "EP001-C002")
        self.assertEqual(len({a["media"]["key"] for a in prop["formal"]}), 4)
        self.assertEqual(before, (record.read_bytes(), scene_record.read_bytes()))

    def test_prop_template_enumeration_is_not_approval(self):
        self.prop_fixture("批准采用／修改后再审／不采用")
        self.data = portal.build_data(self.root)
        self.assertFalse(self.data["props"][0]["formal"][1]["approved"])

    def test_prop_missing_media_and_other_prop_records(self):
        self.prop_fixture()
        (self.root / "05-道具资料/PR001-盒子/参考图/PR001-基础-道具参考图.png").unlink()
        self.put("05-道具资料/审阅记录/PR002-其他.md", "# 其他道具")
        self.data = portal.build_data(self.root)
        prop = self.data["props"][0]
        self.assertIsNone(prop["formal"][1]["media"])
        self.assertEqual(prop["cover"]["state"], "破损")
        self.assertFalse(any("PR002" in f["key"] for g in prop["groups"] for f in g["files"]))


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
        self.data = portal.build_data(self.root)
        scene = self.data["scenes"][0]
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

    def test_scene_multiple_views_coexist_with_legacy_and_directory_images(self):
        _, record = self.scene_fixture()
        folder = "04-场景资料/SC001-药庐/参考图/"
        first = "SC001-EP001-C001-V001-场景参考图.png"
        second = "SC001-EP001-C001-V002-场景参考图.webp"
        self.put(folder + first, "view one")
        self.put(folder + second, "view two")
        text = record.read_text(encoding="utf-8")
        text = text.replace("| 正式文件 | 最初制作场次 |", "| 正式文件 | 视图编号与名称 | 最初制作场次 |")
        text = text.replace("| --- | --- | --- | --- | --- |", "| --- | --- | --- | --- | --- | --- |")
        text = text.replace("| 旧图 |", "| 无 | 旧图 |").replace("| EP001-C001 |", "| 无 | EP001-C001 |")
        text = text.replace("## 2. 逐次生成记录", (
            f"| [视图]({first}) | V001 门口看向药柜 | EP001-C001 | 晨 | v02 | [审阅](../../审阅记录/SC001-审阅-001.md) |\n\n"
            "## 2. 逐次生成记录"))
        record.write_text(text, encoding="utf-8")
        before = record.read_bytes()
        self.data = portal.build_data(self.root)
        scene = self.data["scenes"][0]
        self.assertEqual(len(scene["formal"]), 3)
        self.assertEqual(len(scene["auxiliary"]), 1)
        views = {Path(a["media"]["key"]).name: a for a in scene["formal"]}
        self.assertIn("SC001-EP001-C001-场景参考图.png", views)
        self.assertIn("V001 门口看向药柜", views[first]["state"])
        self.assertTrue(views[first]["approved"])
        self.assertEqual(views[second]["state"], "EP001-C001-V002")
        self.assertFalse(views[second]["approved"])
        self.assertEqual(record.read_bytes(), before)

    def test_scene_confirmed_card_does_not_approve_cover(self):
        self.scene_fixture("修改后再审。")
        self.data = portal.build_data(self.root)
        scene = self.data["scenes"][0]
        self.assertIsNone(scene["cover"])
        self.assertIn("status-green", scene["card"]["confirmationHtml"])

    def test_scene_formal_directory_displays_images_without_record(self):
        self.scene_fixture()
        self.put("04-场景资料/SC001-药庐/参考图/旧环境.png", "old")
        self.put("04-场景资料/SC001-药庐/参考图/生成记录.md", "# 旧记录\n用户曾批准，范围见旧记录。")
        self.data = portal.build_data(self.root)
        scene = self.data["scenes"][0]
        self.assertIsNone(scene["cover"])
        self.assertEqual(len(scene["formal"]), 1)
        self.assertEqual(len(scene["auxiliary"]), 2)
        self.assertTrue(all(a["directoryDiscovered"] for a in scene["formal"] + scene["auxiliary"]))
        self.assertEqual(scene["legacy"], [])

    def test_review_storage_and_applicability_are_independent(self):
        self.scene_fixture("不通过。")
        review = self.root / "04-场景资料/审阅记录/SC001-审阅-001.md"
        review.write_text(review.read_text("utf-8") + "\n## 5. 采用与后续影响\n- 留存用途：历史生成记录\n- 当前制作适用性：不适用；旧布局\n", encoding="utf-8")
        before = review.read_bytes()
        self.data = portal.build_data(self.root)
        scene = self.data["scenes"][0]
        asset = scene["formal"][0]
        self.assertFalse(asset["approved"])
        self.assertTrue(asset["reviewRecognized"])
        self.assertEqual(asset["retentionPurpose"], "历史生成记录")
        self.assertIn("旧布局", asset["applicability"])
        self.assertIsNone(scene["cover"])
        self.assertEqual(before, review.read_bytes())
        review.write_text(review.read_text("utf-8").replace("不通过。", "批准采用。"), encoding="utf-8")
        self.data = portal.build_data(self.root)
        scene = self.data["scenes"][0]
        self.assertTrue(scene["formal"][0]["approved"])
        self.assertIsNone(scene["cover"])

    def test_legacy_save_decision_is_not_quality_rejection_or_approval(self):
        self.scene_fixture("批准保存v03，作为比较参考")
        self.data = portal.build_data(self.root)
        asset = self.data["scenes"][0]["formal"][0]
        self.assertFalse(asset["approved"])
        self.assertFalse(asset["reviewRecognized"])
        self.assertIn("批准保存v03", asset["statusHtml"])

    def test_scene_records_isolated_and_external_images_not_loaded(self):
        self.scene_fixture()
        self.put("04-场景资料/审阅记录/SC002-别处.md", "# 另一场景")
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "outside.png"
            external.write_bytes(b"outside")
            self.create_symlink(self.root / "04-场景资料/SC001-药庐/参考图/外部.png", external)
            self.data = portal.build_data(self.root)
        scene = self.data["scenes"][0]
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
        self.data = portal.build_data(self.root)
        candidates = self.data["scenes"][0]["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[-1]["state"], "EP001-C002")
        self.assertIn("status-red", candidates[-1]["agentHtml"])
        self.assertTrue(candidates[-1]["reviews"])
        self.assertNotIn("输入", candidates[-1]["media"]["key"])


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
        self.data = portal.build_data(self.root)
        person = self.data["people"][0]
        self.assertEqual(person["stages"], ["成年", "少年"])
        self.assertEqual([a["stage"] for a in person["formal"]], ["少年", "成年", ""])
        self.assertTrue(all(a["media"] and a["approved"] for a in person["formal"]))
        self.assertEqual(person["cover"]["media"]["key"], "03-人物资料/CH001-小林/参考图/少年/正式.png")
        self.assertEqual(person["pendingCount"], 1)
        self.assertEqual(record.read_text(), text)

    def test_people_flat_registry_does_not_invent_stage_tabs(self):
        card, _ = self.person_fixture()
        card.write_text(card.read_text() + "\n## 3. 外貌与基础造型\n### 3.1 少年\n### 3.2 成年\n")
        self.data = portal.build_data(self.root)
        person = self.data["people"][0]
        self.assertEqual(person["stages"], [])
        self.assertEqual(person["formal"][0]["stage"], "")
        self.assertIsNotNone(person["cover"])

    def test_people_formal_candidate_and_approval_are_separate(self):
        card, record = self.person_fixture()
        original = (card.read_bytes(), record.read_bytes())
        self.data = portal.build_data(self.root)
        person = self.data["people"][0]
        self.assertEqual(person["id"], "CH001")
        self.assertEqual(len(person["formal"]), 1)
        self.assertEqual(person["cover"]["version"], "v01")
        self.assertEqual(person["candidates"][0]["type"], "人物上半身正面肖像图")
        self.assertIn("status-orange", person["candidates"][0]["userHtml"])
        self.assertEqual(person["pendingCount"], 1)
        self.assertEqual(original, (card.read_bytes(), record.read_bytes()))

    def test_people_unapproved_registry_image_is_not_cover(self):
        self.person_fixture("修改后再审。")
        self.data = portal.build_data(self.root)
        person = self.data["people"][0]
        self.assertIsNone(person["cover"])
        self.assertFalse(person["formal"][0]["approved"])
        self.assertIn("修改后再审", person["formal"][0]["statusHtml"])

    def test_people_history_or_loose_files_are_not_current_assets(self):
        _, record = self.person_fixture()
        record.write_text("# 记录\n## 1. 当前正式资产\n暂无\n", encoding="utf-8")
        self.put("03-人物资料/人物参考图采用总表.md", "# 旧表\n全部已采用")
        self.put("03-人物资料/历史版本/CH001-小林/旧正式.png", "old")
        self.data = portal.build_data(self.root)
        person = self.data["people"][0]
        self.assertEqual(person["formal"], [])
        self.assertIsNone(person["cover"])
        self.assertEqual(len(person["groups"][3]["files"]), 1)

    def test_people_missing_or_external_media_not_previewed(self):
        _, record = self.person_fixture()
        self.put("03-人物资料/历史版本/历史.png", "old")
        text = record.read_text("utf-8").replace("(正式.png)", "(../../历史版本/历史.png)")
        text = text.replace("(../../过程稿/CH001-肖像-草稿-v01.png)", "(https://example.test/image.png)")
        record.write_text(text, encoding="utf-8")
        self.data = portal.build_data(self.root)
        person = self.data["people"][0]
        self.assertIsNone(person["formal"][0]["media"])
        self.assertIsNone(person["cover"])
        self.assertEqual(person["candidates"], [])

    def test_people_process_groups_do_not_mix_character_ids(self):
        self.person_fixture()
        self.put("03-人物资料/审阅记录/CH002-审阅-001.md", "# 别人")
        self.put("03-人物资料/审阅记录/人物索引-审阅记录-001.md", "# 跨人物")
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertEqual(len(next(g for g in data["people"][0]["groups"] if g["name"] == "审阅记录")["files"]), 1)
        self.assertEqual(len(next(g for g in data["peopleGroups"] if g["name"] == "审阅记录")["files"]), 3)

    def test_people_prompt_code_cannot_supply_approval_fields(self):
        _, record = self.person_fixture()
        record.write_text(record.read_text("utf-8").replace("- 图片类型：", "```text\n- 用户采用状态：批准采用\n```\n- 图片类型："), encoding="utf-8")
        self.data = portal.build_data(self.root)
        self.assertIn("待确认", self.data["people"][0]["candidates"][0]["userHtml"])

    def test_empty_project_has_no_invented_status_and_creates_no_folders(self):
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertFalse(data["positionExists"])
        self.assertEqual(data["active"], [])
        self.assertEqual(data["meta"]["确认状态"], "未记录")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_formal_does_not_promote_draft(self):
        self.put("00-项目定位/过程稿/项目基本定位-草稿-v01.md", "# 草稿\n候选内容")
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertFalse(data["positionExists"])
        self.assertEqual(len(next(g for g in data["groups"] if g["name"] == "过程稿")["files"]), 1)
        self.assertNotIn("候选内容", data["positionHtml"])

    def test_real_metadata_extra_sections_and_source_bytes_are_preserved(self):
        content = "# 项目\n\n- 文档版本：v1.0\n- 更新日期：2026-09-26\n- 确认状态：待确认\n\n## 受众定位\n原词\n\n## 其他备注\n既有补充"
        path = self.put(portal.POSITION, content)
        self.data = portal.build_data(self.root)
        data = self.data
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
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertEqual([r["name"] for r in data["active"]], ["图片", "EP001"])
        self.assertEqual(data["project"], "测试剧")

    def test_relative_links_resolve_from_original_document(self):
        href, key = portal.safe_link("../项目基本定位.md", "00-项目定位/审阅记录/记录.md")
        self.assertEqual(key, portal.POSITION)
        self.assertTrue(href.endswith(".md"))
        href, key = portal.safe_link("../01-主旨与简介/主旨与简介.md#2-世界观与核心规则", portal.POSITION)
        self.assertEqual(key, "01-主旨与简介/主旨与简介.md")
        self.assertIn("#2-", href)

    def test_windows_source_links_match_portal_document_keys(self):
        href, key = portal.safe_link("../项目基本定位.md#内容", r"00-项目定位\审阅记录\记录.md")
        self.put(portal.POSITION, "# 定位\n\n## 内容\n正文")
        self.data = portal.build_data(self.root)
        self.assertIn(key, self.data["documents"])
        self.assertNotIn("%5C", href)
        self.assertNotIn("\\", key)

    def test_unsafe_links_and_raw_html_are_not_executed(self):
        for target in ("javascript:alert", "data:text/html,abc", "//evil.test", "file:///etc/passwd"):
            self.assertEqual(portal.safe_link(target, portal.POSITION), (None, None))
        rendered = portal.markdown("<script>alert(1)</script>\n[x](javascript:alert)\n![x](https://example.test/x.png)", portal.POSITION)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn('href="javascript:', rendered)

    def test_script_text_is_escaped_in_document_html(self):
        self.put(portal.POSITION, "# 文档\n\n## 内容\n</script><script>bad()</script>")
        self.data = portal.build_data(self.root)
        self.assertNotIn("</script><script>bad()", self.data["positionHtml"])
        self.assertIn("&lt;script&gt;", self.data["positionHtml"])


    def test_outside_source_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "private.md"
            target.write_text("do not read", encoding="utf-8")
            self.create_symlink(self.root / "项目进度.md", target)
            with self.assertRaises(ValueError):
                self.data = portal.build_data(self.root)

    def test_empty_field_does_not_capture_next_line(self):
        self.assertEqual(portal.field("- 文档版本：\n- 更新日期：今天", "文档版本"), "")

    def test_approval_clauses_are_separate_and_source_is_unchanged(self):
        value = "2026-09-23定位确认继续有效；2026-09-25用户明确暂定80集、不强制80集，随后批准单集时长采用新默认值，并批准剩余迁移与修改。"
        content = "# 定位\n\n- 确认依据：" + value + "\n- 适用范围：甲；乙。\n\n## 内容\n正文"
        path = self.put(portal.POSITION, content)
        self.data = portal.build_data(self.root)
        rendered = self.data["introHtml"]
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
        self.data = portal.build_data(self.root)
        story = self.data["story"]
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
        self.data = portal.build_data(self.root)
        data = self.data
        self.assertFalse(data["story"]["exists"])
        self.assertEqual(data["story"]["bodyHtml"], "")
        self.assertEqual(data["story"]["boundaryHtml"], "")
        self.assertEqual({g["name"]: len(g["files"]) for g in data["story"]["groups"]}, {"工作稿": 0, "历史版本": 1, "执行附件": 0, "过程稿": 1})
        self.assertEqual([len(g["files"]) for g in data["groups"]], [0, 0, 0])
        self.assertFalse((self.root / "01-主旨与简介/讨论记录").exists())

    def test_story_outside_source_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "private.md"
            target.write_text("private", encoding="utf-8")
            folder = self.root / "01-主旨与简介"
            folder.mkdir()
            self.create_symlink(folder / "主旨与简介.md", target)
            with self.assertRaises(ValueError):
                self.data = portal.build_data(self.root)

    def test_outline_preserves_five_chapters_tables_links_and_source(self):
        chapters = ["全剧故事主线", "故事阶段与重大转折", "主要人物作用与变化", "重要人物关系发展", "关键秘密与伏笔安排"]
        content = "# 故事大纲\n- 文档版本：v0.7\n- 更新日期：2026-09-25\n- 确认状态：已确认；原始依据。\n- 规则依据：[世界观](../01-主旨与简介/主旨与简介.md#2-世界观与核心规则)\n- 制作规格：原规格\n\n"
        content += "\n".join("## " + str(i) + ". " + name + "\n原始正文" for i, name in enumerate(chapters, 1))
        content += "\n| 秘密 | 回收 |\n| --- | --- |\n| 原秘密 | 原结局 |\n"
        source = self.put(portal.OUTLINE, content)
        self.put("02-故事大纲/审阅记录/记录.md", "# 审阅\n真实决定")
        self.data = portal.build_data(self.root)
        data = self.data
        outline = data["outline"]
        self.assertEqual(outline["meta"]["文档版本"], "v0.7")
        self.assertEqual(outline["bodyHtml"].count("<h2 "), 5)
        self.assertNotIn("<h3 ", outline["bodyHtml"])
        self.assertIn("<table>", outline["bodyHtml"])
        self.assertIn("原秘密", outline["bodyHtml"])
        self.assertIn('data-doc="01-主旨与简介/主旨与简介.md"', outline["introHtml"])
        self.assertEqual(outline["boundaryHtml"], "")
        self.assertEqual({g["name"]: len(g["files"]) for g in outline["groups"]}, {"工作稿": 0, "历史版本": 0, "执行附件": 0, "审阅记录": 1})
        self.assertEqual([len(g["files"]) for g in data["story"]["groups"]], [0, 0, 0])
        self.assertEqual(source.read_text("utf-8"), content)

    def test_outline_draft_is_not_formal_and_no_extra_folders_created(self):
        self.put("02-故事大纲/过程稿/草稿.md", "# 草稿\n候选大纲")
        self.put("02-故事大纲/历史版本/旧大纲.md", "# 旧大纲\n旧结局")
        self.data = portal.build_data(self.root)
        outline = self.data["outline"]
        self.assertFalse(outline["exists"])
        self.assertEqual(outline["bodyHtml"], "")
        self.assertEqual({g["name"]: len(g["files"]) for g in outline["groups"]}, {"工作稿": 0, "历史版本": 1, "执行附件": 0, "过程稿": 1})
        self.assertFalse((self.root / "02-故事大纲/讨论记录").exists())

    def test_rebuild_updates_view_not_source_files(self):
        source = self.put(portal.POSITION, "# 定位\n\n## 受众\n第一版")
        self.data = portal.build_data(self.root)
        source.write_text("# 定位\n\n## 受众\n第二版", encoding="utf-8")
        self.data = portal.build_data(self.root)
        self.assertIn("第二版", self.data["positionHtml"])
        self.assertEqual(source.read_text("utf-8"), "# 定位\n\n## 受众\n第二版")

    def test_tables_lists_and_code_are_readable(self):
        source = "# 标题\n\n- **重点**\n\n| 项目 | 值 |\n| --- | --- |\n| 数量 | 1 |\n\n~~~\n<b>原文</b>\n~~~"
        rendered = portal.markdown(source, portal.POSITION)
        self.assertIn("<table>", rendered)
        self.assertIn("<strong>重点</strong>", rendered)
        self.assertIn("&lt;b&gt;原文&lt;/b&gt;", rendered)

    def test_storyboard_place_labels_and_segment_shot_navigation(self):
        source = "09-剧集制作/EP001/03-分镜脚本/EP001-C001-场次分镜.md"
        text = ("- 文档版本：v13\n- 确认状态：批准采用；沿原批准\n\n"
                "**场次**：EP001-C001\n\n"
                "**地点**：[青山村，荒院卧房](../../../04-场景资料/SC001-荒院卧房/SC001-荒院卧房-资料卡.md)\n\n"
                "## 1. 镜头正文\n\n### 分段 P007\n\n"
                "**对应视频分段**：[EP001-C001-P007](#ep001-c001-p007)\n\n"
                "#### EP001-SH040\n\n**镜号**：EP001-SH040\n\n**台词**：原台词。\n\n---\n\n"
                "#### EP001-SH012\n\n**镜号**：EP001-SH012\n\n"
                "## 2. 视频分段\n\n### EP001-C001-P007\n\n"
                "- 镜头正文：[P007所含镜头](#分段-p007)")
        rendered = portal.markdown(text, source)
        self.assertEqual(portal.field(text, "文档版本"), "v13")
        self.assertIn('status-green', rendered)
        self.assertIn('<strong>场次</strong>：EP001-C001', rendered)
        self.assertIn('>青山村，荒院卧房</a>', rendered)
        self.assertIn('data-doc="04-场景资料/SC001-荒院卧房/SC001-荒院卧房-资料卡.md"', rendered)
        self.assertNotIn('资料卡v', rendered)
        for anchor in ('分段-p007', 'ep001-c001-p007'):
            self.assertIn('id="' + anchor + '"', rendered)
        self.assertIn('#%E5%88%86%E6%AE%B5-p007', rendered)
        self.assertLess(rendered.index('<h4 id="ep001-sh040"'), rendered.index('<h4 id="ep001-sh012"'))
        self.assertIn('<strong>台词</strong>：原台词。', rendered)
        self.assertIn('</p>\n<hr>\n<h4', rendered)


if __name__ == "__main__":
    unittest.main()
