#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
  sys.path.insert(0, str(SCRIPT_DIR))

from remove_worktree import (
  PROTECTED_BRANCHES,
  default_base_branch,
  list_worktrees,
  remove_branch_worktree,
  repo_root,
)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Remove all merged worktrees except the current and base worktrees."
  )
  parser.add_argument(
    "--base",
    help="Branch to check merges into. Default: origin/HEAD target or current branch.",
  )
  parser.add_argument(
    "--force",
    action="store_true",
    help="Skip merged-into-base safety check for every candidate.",
  )
  return parser.parse_args()


def removable_worktrees(base: str) -> list[tuple[str, Path]]:
  current_path = Path.cwd().resolve()
  root_path = repo_root().resolve()
  candidates: list[tuple[str, Path]] = []

  for entry in list_worktrees():
    if entry.branch is None:
      continue
    if entry.path == current_path:
      continue
    if entry.path == root_path:
      continue
    if entry.branch == base:
      continue
    if entry.branch in PROTECTED_BRANCHES:
      continue
    candidates.append((entry.branch, entry.path))

  return candidates


def main() -> int:
  args = parse_args()
  base = args.base or default_base_branch()
  candidates = removable_worktrees(base)

  if not candidates:
    print("no removable merged worktrees found")
    return 0

  removed_count = 0
  for branch, path in candidates:
    try:
      removed_path, verified_base = remove_branch_worktree(
        branch,
        path=path,
        base=base,
        force=args.force,
      )
    except ValueError:
      continue

    print(f"removed worktree: {removed_path}")
    print(f"removed branch: {branch}")
    if verified_base is not None:
      print(f"verified merged into: {verified_base}")
    removed_count += 1

  if removed_count == 0:
    print("no removable merged worktrees found")
    return 0

  print(f"removed merged worktrees: {removed_count}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
