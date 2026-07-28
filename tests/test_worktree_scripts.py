import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def load_module(name: str, relative_path: str):
  root = Path(__file__).resolve().parent.parent
  module_path = root / relative_path
  spec = importlib.util.spec_from_file_location(name, module_path)
  module = importlib.util.module_from_spec(spec)
  assert spec is not None and spec.loader is not None
  spec.loader.exec_module(module)
  return module


class WorktreeScriptTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.create_module = load_module("create_worktree_script", "scripts/create_worktree.py")
    cls.remove_module = load_module("remove_worktree_script", "scripts/remove_worktree.py")
    cls.clean_module = load_module("clean_worktree_script", "scripts/clean_worktrees.py")

  def test_create_default_worktree_path_uses_common_git_dir(self) -> None:
    with patch.object(
      self.create_module,
      "git_output",
      side_effect=["/tmp/repos/tweb/.git"],
    ):
      path = self.create_module.default_worktree_path("codex/session-20260601")

    self.assertEqual(path, Path("/tmp/repos/tweb/wt-codex/session-20260601").resolve())

  def test_remove_default_worktree_path_uses_common_git_dir(self) -> None:
    with patch.object(
      self.remove_module,
      "git_output",
      side_effect=["/tmp/repos/tweb/.git"],
    ):
      path = self.remove_module.default_worktree_path("codex/session-20260601")

    self.assertEqual(path, Path("/tmp/repos/tweb/wt-codex/session-20260601").resolve())

  def test_registered_worktree_path_finds_old_layout(self) -> None:
    porcelain = "\n".join([
      "worktree /tmp/repos/tweb",
      "HEAD 1111111111111111111111111111111111111111",
      "branch refs/heads/main",
      "",
      "worktree /tmp/repos/wt-codex/session-20260601",
      "HEAD 2222222222222222222222222222222222222222",
      "branch refs/heads/codex/session-20260601",
      "",
    ])
    with patch.object(self.remove_module, "git_output", return_value=porcelain):
      path = self.remove_module.registered_worktree_path("codex/session-20260601")

    self.assertEqual(path, Path("/tmp/repos/wt-codex/session-20260601").resolve())

  def test_registered_worktree_path_returns_none_when_branch_missing(self) -> None:
    porcelain = "\n".join([
      "worktree /tmp/repos/tweb",
      "HEAD 1111111111111111111111111111111111111111",
      "branch refs/heads/main",
      "",
    ])
    with patch.object(self.remove_module, "git_output", return_value=porcelain):
      path = self.remove_module.registered_worktree_path("codex/session-20260601")

    self.assertIsNone(path)

  def test_parse_worktree_list_handles_branchless_entries(self) -> None:
    porcelain = "\n".join([
      "worktree /tmp/repos/tweb",
      "HEAD 1111111111111111111111111111111111111111",
      "branch refs/heads/main",
      "",
      "worktree /tmp/repos/tweb/wt-detached",
      "HEAD 2222222222222222222222222222222222222222",
      "detached",
      "",
    ])

    entries = self.remove_module.parse_worktree_list(porcelain)

    self.assertEqual(entries[0].branch, "main")
    self.assertIsNone(entries[1].branch)

  def test_clean_skips_current_root_and_base_branch(self) -> None:
    entries = [
      self.remove_module.WorktreeEntry(Path("/tmp/repos/tweb").resolve(), "main"),
      self.remove_module.WorktreeEntry(Path("/tmp/repos/tweb/wt-current").resolve(), "codex/current"),
      self.remove_module.WorktreeEntry(Path("/tmp/repos/tweb/wt-merged").resolve(), "codex/merged"),
      self.remove_module.WorktreeEntry(Path("/tmp/repos/tweb/wt-detached").resolve(), None),
    ]

    with patch.object(self.clean_module, "list_worktrees", return_value=entries), \
         patch.object(self.clean_module, "repo_root", return_value=Path("/tmp/repos/tweb")), \
         patch("pathlib.Path.cwd", return_value=Path("/tmp/repos/tweb/wt-current")):
      candidates = self.clean_module.removable_worktrees("main")

    self.assertEqual(candidates, [("codex/merged", Path("/tmp/repos/tweb/wt-merged").resolve())])

  def test_clean_skips_protected_main_even_when_base_differs(self) -> None:
    entries = [
      self.remove_module.WorktreeEntry(Path("/tmp/repos/tweb").resolve(), "release"),
      self.remove_module.WorktreeEntry(Path("/tmp/repos/tweb/wt-main").resolve(), "main"),
      self.remove_module.WorktreeEntry(Path("/tmp/repos/tweb/wt-merged").resolve(), "codex/merged"),
    ]

    with patch.object(self.clean_module, "list_worktrees", return_value=entries), \
         patch.object(self.clean_module, "repo_root", return_value=Path("/tmp/repos/tweb")), \
         patch("pathlib.Path.cwd", return_value=Path("/tmp/repos/tweb")):
      candidates = self.clean_module.removable_worktrees("release")

    self.assertEqual(candidates, [("codex/merged", Path("/tmp/repos/tweb/wt-merged").resolve())])

  def test_clean_main_removes_only_candidates(self) -> None:
    with patch.object(
      self.clean_module,
      "removable_worktrees",
      return_value=[
        ("codex/merged-1", Path("/tmp/repos/tweb/wt-merged-1")),
        ("codex/merged-2", Path("/tmp/repos/tweb/wt-merged-2")),
      ],
    ), patch.object(self.clean_module, "default_base_branch", return_value="main"), \
         patch.object(
           self.clean_module,
           "remove_branch_worktree",
           side_effect=[
             (Path("/tmp/repos/tweb/wt-merged-1"), "main"),
             ValueError("not merged"),
           ],
         ) as remove_mock, \
         patch.object(sys, "argv", ["clean_worktrees.py"]), \
         patch("builtins.print") as print_mock:
      exit_code = self.clean_module.main()

    self.assertEqual(exit_code, 0)
    self.assertEqual(remove_mock.call_count, 2)
    print_mock.assert_any_call("removed merged worktrees: 1")

  def test_remove_branch_worktree_rejects_protected_main(self) -> None:
    with patch.object(self.remove_module, "ensure_branch_exists"), \
         patch.object(self.remove_module, "run_git") as run_git_mock:
      with self.assertRaisesRegex(ValueError, "refusing to remove protected branch 'main'"):
        self.remove_module.remove_branch_worktree("main", path=Path("/tmp/repos/tweb"))

    run_git_mock.assert_not_called()


if __name__ == "__main__":
  unittest.main()
