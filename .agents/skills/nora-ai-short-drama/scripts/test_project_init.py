"""Directory initialization tests use temporary workspaces only."""
import json
from itertools import product
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from project_init import initialize


class ProjectInitializationTests(unittest.TestCase):
    def test_shared_units_reuse_preparation_layout_without_creating_numbered_episodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for unit in ('片头', '片尾'):
                report = initialize(root, unit)
                self.assertEqual(report['episode'], unit)
                self.assertTrue((root / '09-剧集制作' / unit / '04-专用素材').is_dir())
                self.assertFalse(initialize(root, unit)['created'])
            self.assertEqual(sorted(path.name for path in (root / '09-剧集制作').iterdir()), ['片头', '片尾'])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.project = self.workspace / "projects/测试 短片"

    def test_agent_cli_creates_complete_project_without_content_or_episodes(self):
        command = [sys.executable, str(Path(__file__).with_name("project_init.py")),
                   "--project", "projects/测试 短片"]
        first = subprocess.run(command, cwd=self.workspace, text=True, capture_output=True, check=True)
        report = json.loads(first.stdout)
        self.assertEqual(report["project"], str(self.project.resolve()))
        self.assertTrue(report["index_added"])
        index = self.project.parent / "项目总索引.md"
        self.assertEqual(report["project_index"], str(index.resolve()))
        self.assertEqual(index.read_text(encoding="utf-8"), "# 项目总索引\n\n| 编号 | 项目名称 |\n| --- | --- |\n| 01 | 测试 短片 |\n")
        self.assertEqual(len(report["created"]), 22)
        self.assertEqual({path.name for path in self.project.iterdir()}, {
            "00-项目定位", "01-主旨与简介", "02-故事大纲", "03-人物资料",
            "04-场景资料", "05-道具资料", "06-分集大纲", "07-参考音频",
            "08-参考视频", "09-剧集制作", "98-成片交付", "99-综合资料"})
        general = self.project / "99-综合资料/其他资料"
        self.assertTrue((general / "工作稿/素材").is_dir())
        self.assertEqual({p.name for p in general.iterdir()}, {
            "跨阶段资料", "原稿", "待分类资料", "实验资料", "工作稿", "历史版本", "执行附件"})
        self.assertFalse(list((self.project / "09-剧集制作").iterdir()))
        self.assertEqual(list((self.project / "98-成片交付").iterdir()), [])
        self.assertFalse(any(p.is_file() for p in self.project.rglob("*")))
        second = subprocess.run(command, cwd=self.workspace, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(second.stdout)["created"], [])
        self.assertFalse(json.loads(second.stdout)["index_added"])

    def test_optional_selections_create_only_selected_directories(self):
        for cover, intro, outro in product((False, True), repeat=3):
            with self.subTest(cover=cover, intro=intro, outro=outro):
                project = self.project.with_name(f"配套-{cover}-{intro}-{outro}")
                selections = dict(cover=cover, intro=intro, outro=outro)
                initialize(project, **selections)
                self.assertEqual((project / "10-社交媒体资料/封面资料").exists(), cover)
                for unit, selected in (("片头", intro), ("片尾", outro)):
                    path = project / "09-剧集制作" / unit
                    self.assertEqual(path.exists(), selected)
                    if selected:
                        self.assertEqual({p.name for p in path.iterdir()}, {
                            "01-制作前检查", "02-剧集剧本", "03-分镜脚本",
                            "04-专用素材", "05-视频提示词"})
                self.assertTrue((project / "98-成片交付").is_dir())
                self.assertEqual(list((project / "98-成片交付").iterdir()), [])
                self.assertFalse(any(p.is_file() for p in project.rglob("*")))
                self.assertFalse((project / "09-剧集制作/EP001").exists())
                self.assertEqual(initialize(project, **selections)["created"], [])

    def test_later_selection_preserves_existing_content_and_does_not_delete(self):
        initialize(self.project)
        result = initialize(self.project, cover=True, outro=True)
        self.assertTrue(result["created"])
        export = self.project / "98-成片交付/用户剪辑导出.mp4"
        export.write_bytes(b"user export")
        source = self.project / "09-剧集制作/片尾/02-剧集剧本/片尾-本集剧本.md"
        source.write_text("已有内容", encoding="utf-8")
        self.assertEqual(initialize(self.project)["created"], [])
        self.assertTrue((self.project / "10-社交媒体资料/封面资料").is_dir())
        self.assertEqual(source.read_text(encoding="utf-8"), "已有内容")
        self.assertEqual(export.read_bytes(), b"user export")

    def test_cli_optional_flags_and_episode_combination(self):
        command = [sys.executable, str(Path(__file__).with_name("project_init.py")),
                   "--project", str(self.project)]
        result = subprocess.run(command + ["--cover", "--intro", "--outro"],
                                text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)["mode"], "project")
        self.assertTrue((self.project / "10-社交媒体资料/封面资料").is_dir())
        for unit in ("片头", "片尾"):
            self.assertTrue((self.project / "09-剧集制作" / unit / "05-视频提示词").is_dir())
        invalid = subprocess.run(command + ["--episode", "EP001", "--cover"],
                                 text=True, capture_output=True)
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("不能与--episode同时使用", invalid.stderr)
        self.assertFalse((self.project / "09-剧集制作/EP001").exists())

    def test_release_directory_repair_preserves_user_exports_and_index(self):
        initialize(self.project)
        release = self.project / "98-成片交付"
        files = [release / "用户已有导出.mp4", release / "片头/片头.mp4", release / "EP001/成片/第1集.mp4"]
        for file in files:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"user export")
        before = {file: file.stat().st_mtime_ns for file in files}
        index = self.project.parent / "项目总索引.md"
        index_before = index.stat().st_mtime_ns
        result = initialize(self.project, "EP001")
        self.assertTrue((release / "EP001/成片").is_dir())
        self.assertFalse(initialize(self.project)["created"])
        for file in files:
            self.assertEqual(file.read_bytes(), b"user export")
            self.assertEqual(file.stat().st_mtime_ns, before[file])
        self.assertEqual(index.stat().st_mtime_ns, index_before)

    def test_release_subdirectory_file_conflict_stops_before_creating_directories(self):
        release = self.project / "98-成片交付"
        release.mkdir(parents=True)
        conflict = release / "EP001"
        conflict.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            initialize(self.project, "EP001")
        self.assertEqual(list(self.project.iterdir()), [release])
        self.assertEqual(list(release.iterdir()), [conflict])
        self.assertEqual(conflict.read_bytes(), b"keep")
        self.assertFalse((self.project.parent / "项目总索引.md").exists())

    def test_selected_directory_conflict_fails_before_creating_other_directories(self):
        self.project.mkdir(parents=True)
        conflict = self.project / "10-社交媒体资料/封面资料"
        conflict.parent.mkdir()
        conflict.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            initialize(self.project, cover=True, intro=True)
        self.assertEqual(list(self.project.iterdir()), [conflict.parent])
        self.assertEqual(conflict.read_bytes(), b"keep")

    def test_new_project_appends_and_repeat_preserves_manual_order_and_text(self):
        initialize(self.project)
        other = self.project.with_name("第二个项目")
        index = self.project.parent / "项目总索引.md"
        source = "# 项目总索引\n\n说明保留。\n\n1. 已有项目\n2. 测试 短片\n"
        index.write_text(source, encoding="utf-8")
        self.assertTrue(initialize(other)["index_added"])
        expected = source + "3. 第二个项目\n"
        self.assertEqual(index.read_text(encoding="utf-8"), expected)
        before = index.stat().st_mtime_ns
        self.assertFalse(initialize(self.project)["index_added"])
        initialize(other, "片尾")
        self.assertEqual(index.read_text(encoding="utf-8"), expected)
        self.assertEqual(index.stat().st_mtime_ns, before)

    def test_table_append_preserves_order_and_repeat_does_not_rewrite(self):
        initialize(self.project)
        index = self.project.parent / "项目总索引.md"
        source = "# 项目总索引\n\n| 编号 | 项目名称 |\n| --- | --- |\n| 01 | 已有项目 |\n| 02 | 测试 短片 |\n"
        index.write_text(source, encoding="utf-8")
        other = self.project.with_name("第二个项目")
        self.assertTrue(initialize(other)["index_added"])
        self.assertEqual(index.read_text(encoding="utf-8"), source + "| 03 | 第二个项目 |\n")
        before = index.stat().st_mtime_ns
        self.assertFalse(initialize(other)["index_added"])
        initialize(other, "EP001")
        self.assertEqual(index.stat().st_mtime_ns, before)

    def test_repair_adds_missing_registration_without_touching_other_entries(self):
        initialize(self.project)
        index = self.project.parent / "项目总索引.md"
        index.write_text("# 项目总索引\n\n1. 另一个项目\n", encoding="utf-8")
        result = initialize(self.project)
        self.assertEqual(result["created"], [])
        self.assertTrue(result["index_added"])
        self.assertEqual(index.read_text(encoding="utf-8"), "# 项目总索引\n\n1. 另一个项目\n2. 测试 短片\n")

    def test_repeat_and_missing_directory_repair_preserve_existing_documents(self):
        initialize(self.project)
        source = self.project / "00-项目定位/项目基本定位.md"
        source.write_bytes("已确认内容".encode("utf-8"))
        before = source.stat().st_mtime_ns
        (self.project / "07-参考音频").rmdir()
        result = initialize(self.project)
        self.assertEqual(result["created"], ["07-参考音频"])
        self.assertEqual(source.read_bytes(), "已确认内容".encode("utf-8"))
        self.assertEqual(source.stat().st_mtime_ns, before)

    def test_episode_only_creates_requested_preparation_directories(self):
        initialize(self.project)
        result = initialize(self.project, "EP002")
        episode = self.project / "09-剧集制作/EP002"
        self.assertEqual({p.name for p in episode.iterdir()}, {
            "01-制作前检查", "02-剧集剧本", "03-分镜脚本", "04-专用素材", "05-视频提示词"})
        self.assertEqual(len(result["created"]), 7)
        self.assertTrue((self.project / "98-成片交付/EP002/成片").is_dir())
        self.assertFalse((self.project / "09-剧集制作/EP001").exists())
        self.assertFalse((episode / "其他资料").exists())
        self.assertFalse((episode / "06-阶段采用视频").exists())
        self.assertEqual(initialize(self.project, "EP002")["created"], [])

    def test_invalid_episode_and_missing_project_create_nothing(self):
        for episode in ("EP000", "EP1", "EP001/../../escape"):
            with self.subTest(episode=episode), self.assertRaises(ValueError):
                initialize(self.project, episode)
        with self.assertRaises(FileNotFoundError):
            initialize(self.project, "EP001")
        self.assertFalse(self.project.exists())

    def test_file_conflict_fails_without_partial_directory_creation(self):
        self.project.mkdir(parents=True)
        conflict = self.project / "05-道具资料"
        conflict.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            initialize(self.project)
        self.assertEqual(list(self.project.iterdir()), [conflict])
        self.assertEqual(conflict.read_bytes(), b"keep")

    def test_external_symlink_is_rejected_before_creating_directories(self):
        self.project.mkdir(parents=True)
        outside = self.workspace / "outside"
        outside.mkdir()
        (self.project / "99-综合资料").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            initialize(self.project)
        self.assertFalse(list(outside.iterdir()))
        self.assertEqual(len(list(self.project.iterdir())), 1)

    def test_cli_reports_conflicting_file_with_nonzero_exit(self):
        self.project.parent.mkdir(parents=True)
        self.project.write_bytes(b"keep")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("project_init.py")),
                                 "--project", str(self.project)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("目录位置已有文件", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.project.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
