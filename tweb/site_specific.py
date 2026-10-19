from __future__ import annotations

import re
from urllib.parse import quote

from .apollo import read_runtime_apollo_value
from .hydration import HydrationSection


_KAKUYOMU_WORK_PATH_RE = re.compile(
  r"^https?://kakuyomu\.jp/works/(?P<work_id>\d+)(?:/episodes/(?P<episode_id>\d+))?(?:[/?#].*)?$"
)


def extract_hydration_sections(
  runtime,
  source: str,
) -> list[HydrationSection]:
  if _KAKUYOMU_WORK_PATH_RE.match(source):
    return _extract_kakuyomu_toc_sections(runtime, source)
  return []


def _extract_kakuyomu_toc_sections(
  runtime,
  source: str,
) -> list[HydrationSection]:
  match = _KAKUYOMU_WORK_PATH_RE.match(source)
  if match is None:
    return []
  work_id = match.group("work_id")
  work = read_runtime_apollo_value(
    runtime,
    state_path=("__NEXT_DATA__", "props", "pageProps", "__APOLLO_STATE__"),
    key=f"Work:{work_id}",
    fields=("__ref", "tableOfContentsV2", "chapter", "episodeUnions", "title", "id"),
  )
  if not isinstance(work, dict) or not isinstance(work.get("tableOfContentsV2"), list):
    return []
  sections: list[HydrationSection] = []
  for toc in work["tableOfContentsV2"]:
    if not isinstance(toc, dict) or not isinstance(toc.get("episodeUnions"), list):
      continue
    chapter = toc.get("chapter")
    title = _normalize_whitespace(chapter.get("title")) if isinstance(chapter, dict) else ""
    if not title:
      continue
    items: list[tuple[str, str]] = []
    for episode in toc["episodeUnions"]:
      if not isinstance(episode, dict):
        continue
      episode_id = _normalize_whitespace(episode.get("id"))
      text = _normalize_whitespace(episode.get("title"))
      if episode_id and text:
        items.append((text, f"/works/{work_id}/episodes/{quote(episode_id, safe='')}"))
    if len(items) >= 2:
      sections.append(HydrationSection(title=title, items=tuple(items)))
  return sections


def _normalize_whitespace(value: object) -> str:
  return re.sub(r"\s+", " ", str(value or "")).strip()
