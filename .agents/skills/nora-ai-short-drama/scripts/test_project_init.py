"""Directory initialization tests use temporary workspaces only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from project_init import initialize


class ProjectInitializationTests(unittest.TestCase):
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
        self.assertEqual(len(report["created"]), 21)
        self.assertEqual({path.name for path in self.project.iterdir()}, {
            "00-项目定位", "01-主旨与简介", "02-故事大纲", "03-人物资料",
            "04-场景资料", "05-道具资料", "06-分集大纲", "07-参考音频",
            "08-参考视频", "09-剧集制作", "99-综合资料"})
        general = self.project / "99-综合资料/其他资料"
        self.assertTrue((general / "工作稿/素材").is_dir())
        self.assertEqual({p.name for p in general.iterdir()}, {
            "跨阶段资料", "原稿", "待分类资料", "实验资料", "工作稿", "历史版本", "执行附件"})
        self.assertFalse(list((self.project / "09-剧集制作").iterdir()))
        self.assertFalse(any(p.is_file() for p in self.project.rglob("*")))
        second = subprocess.run(command, cwd=self.workspace, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(second.stdout)["created"], [])

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
        self.assertEqual(len(result["created"]), 6)
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
