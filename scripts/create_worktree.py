#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path


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


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Create a branch and its dedicated git worktree."
  )
  parser.add_argument("branch", help="New branch name")
  parser.add_argument(
    "--path",
    help="Worktree path. Default: ../wt-<branch> from the repo root.",
  )
  parser.add_argument(
    "--base",
    help="Base branch or commit to branch from. Default: origin/HEAD target or current branch.",
  )
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  branch = args.branch
  path = Path(args.path).expanduser() if args.path else default_worktree_path(branch)
  base = args.base or default_base_branch()

  if path.exists():
    print(f"worktree path already exists: {path}", file=sys.stderr)
    return 1

  try:
    run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    print(f"branch already exists: {branch}", file=sys.stderr)
    return 1
  except subprocess.CalledProcessError:
    pass

  path.parent.mkdir(parents=True, exist_ok=True)
  run_git(["worktree", "add", "-b", branch, str(path), base])
  print(f"created branch: {branch}")
  print(f"created worktree: {path}")
  print(f"base: {base}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
