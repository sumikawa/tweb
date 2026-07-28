#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import subprocess
import sys
from pathlib import Path

PROTECTED_BRANCHES = {"main"}


def run_git(args: list[str], *, capture: bool = False) -> str | None:
  result = subprocess.run(
    ["git", *args],
    check=True,
    text=True,
    capture_output=capture,
  )
  if capture:
    return result.stdout.strip()
  return None


def git_output(args: list[str]) -> str:
  output = run_git(args, capture=True)
  assert output is not None
  return output


def default_base_branch() -> str:
  for ref in ("refs/remotes/origin/HEAD", "refs/remotes/upstream/HEAD"):
    try:
      target = git_output(["symbolic-ref", "--short", ref])
    except subprocess.CalledProcessError:
      continue
    if "/" in target:
      return target.split("/", 1)[1]
  return git_output(["branch", "--show-current"]) or "main"


def repo_root() -> Path:
  common_dir = Path(git_output(["rev-parse", "--git-common-dir"])).resolve()
  if common_dir.name == ".git":
    return common_dir.parent
  return Path(git_output(["rev-parse", "--show-toplevel"])).resolve()


def default_worktree_path(branch: str) -> Path:
  return repo_root() / f"wt-{branch}"


@dataclass(frozen=True)
class WorktreeEntry:
  path: Path
  branch: str | None


def parse_worktree_list(output: str) -> list[WorktreeEntry]:
  entries: list[WorktreeEntry] = []
  current_branch = None
  current_path = None

  for line in output.splitlines():
    if line.startswith("worktree "):
      current_path = Path(line.removeprefix("worktree ")).resolve()
      current_branch = None
      continue
    if line.startswith("branch "):
      current_branch = line.removeprefix("branch ").removeprefix("refs/heads/")
      continue
    if not line and current_path is not None:
      entries.append(WorktreeEntry(path=current_path, branch=current_branch))
      current_branch = None
      current_path = None

  if current_path is not None:
    entries.append(WorktreeEntry(path=current_path, branch=current_branch))

  return entries


def list_worktrees() -> list[WorktreeEntry]:
  return parse_worktree_list(git_output(["worktree", "list", "--porcelain"]))


def registered_worktree_path(branch: str) -> Path | None:
  for entry in list_worktrees():
    if entry.branch == branch:
      return entry.path
  return None


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Remove a merged worktree and delete its branch."
  )
  parser.add_argument("branch", help="Branch to remove")
  parser.add_argument(
    "--path",
    help="Worktree path. Default: ../wt-<branch> from the repo root.",
  )
  parser.add_argument(
    "--base",
    help="Branch to check merge into. Default: origin/HEAD target or current branch.",
  )
  parser.add_argument(
    "--force",
    action="store_true",
    help="Skip merged-into-base safety check.",
  )
  return parser.parse_args()


def ensure_branch_exists(branch: str) -> None:
  run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])


def ensure_branch_removable(branch: str) -> None:
  if branch in PROTECTED_BRANCHES:
    protected = ", ".join(sorted(PROTECTED_BRANCHES))
    raise ValueError(f"refusing to remove protected branch '{branch}' ({protected})")


def ensure_merged(branch: str, base: str) -> None:
  run_git(["merge-base", "--is-ancestor", branch, base])


def remove_branch_worktree(
  branch: str,
  *,
  path: Path | None = None,
  base: str | None = None,
  force: bool = False,
) -> tuple[Path, str | None]:
  ensure_branch_removable(branch)

  resolved_path = path or registered_worktree_path(branch) or default_worktree_path(branch)
  resolved_base = base or default_base_branch()

  try:
    ensure_branch_exists(branch)
  except subprocess.CalledProcessError:
    raise ValueError(f"branch does not exist: {branch}") from None

  if not force:
    try:
      ensure_merged(branch, resolved_base)
    except subprocess.CalledProcessError:
      raise ValueError(
        f"branch '{branch}' is not merged into '{resolved_base}'. Use --force to override."
      ) from None

  try:
    run_git(["worktree", "remove", str(resolved_path)])
  except subprocess.CalledProcessError:
    raise ValueError(
      f"failed to remove worktree: {resolved_path}. Move out of that directory or pass a correct path."
    ) from None

  run_git(["branch", "-d" if not force else "-D", branch])
  run_git(["worktree", "prune"])
  return resolved_path, None if force else resolved_base


def main() -> int:
  args = parse_args()
  branch = args.branch
  path = Path(args.path).expanduser() if args.path else None

  try:
    removed_path, verified_base = remove_branch_worktree(
      branch,
      path=path,
      base=args.base,
      force=args.force,
    )
  except ValueError as exc:
    print(str(exc), file=sys.stderr)
    return 1

  print(f"removed worktree: {removed_path}")
  print(f"removed branch: {branch}")
  if verified_base is not None:
    print(f"verified merged into: {verified_base}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
