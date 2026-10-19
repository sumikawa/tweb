from __future__ import annotations

import json
import re
from urllib.parse import quote

from .apollo import read_runtime_apollo_value
from .dom import DocumentNode
from .fetcher import fetch_resource, resolve_resource_url
from .hydration import HydrationSection, merge_hydration_sections


_KAKUYOMU_WORK_PATH_RE = re.compile(
  r"^https?://kakuyomu\.jp/works/(?P<work_id>\d+)(?:/episodes/(?P<episode_id>\d+))?(?:[/?#].*)?$"
)
_NOTE_PATH_RE = re.compile(r"^https?://(?:www\.)?note\.com(?:/|$)")
_NOTE_HOME_PATH_RE = re.compile(r"^https?://(?:www\.)?note\.com/?(?:[?#].*)?$")
_NOTE_TOPIC_PATH_RE = re.compile(r"^https?://(?:www\.)?note\.com/topic/(?P<topic>[^?#]+)")
_PENDING_RUNTIME_SECTIONS = "__tweb_pending__"


def extract_hydration_sections(
  runtime,
  source: str,
) -> list[HydrationSection]:
  if _KAKUYOMU_WORK_PATH_RE.match(source):
    return _extract_kakuyomu_toc_sections(runtime, source)
  if _NOTE_PATH_RE.match(source) is None:
    return []
  home_sections = _extract_note_home_runtime_sections(runtime, source)
  topic_sections = _extract_note_topic_runtime_sections(runtime, source)
  return merge_hydration_sections(topic_sections, home_sections)


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


def _extract_note_topic_runtime_sections(
  runtime,
  source: str,
) -> list[HydrationSection]:
  match = _NOTE_TOPIC_PATH_RE.match(source)
  if match is None:
    return []
  topic_urlname = match.group("topic").strip("/")
  if not topic_urlname:
    return []
  encoded_topic = quote(topic_urlname.replace("/", "_"), safe="")
  return _extract_note_runtime_sections_with_python_retry(
    runtime,
    source,
    endpoint=f"/api/v3/mkit_layouts/json?context=category_{encoded_topic}&page=1",
    pending_key="__twebNoteTopicSections",
    parser=_load_note_topic_sections_payload,
  )


def _extract_note_home_runtime_sections(
  runtime,
  source: str,
) -> list[HydrationSection]:
  if _NOTE_HOME_PATH_RE.match(source) is None:
    return []
  return _extract_note_runtime_sections_with_python_retry(
    runtime,
    source,
    endpoint="/api/v3/mkit_layouts/json?context=home_tl&page=1",
    pending_key="__twebNoteHomeSections",
    parser=_load_note_home_sections_payload,
  )


def _launch_note_runtime_probe(
  runtime,
  *,
  endpoint: str,
  pending_key: str,
) -> None:
  runtime.eval(
    """
    (async function() {
      window[%s] = %s;
      function normalize(text) {
        return String(text || '').replace(/\\s+/g, ' ').trim();
      }
      function encodedPath(value) {
        return String(value)
          .split('/')
          .filter(Boolean)
          .map((part) => encodeURIComponent(part))
          .join('/');
      }
      function sectionItems(section) {
        if (!section || typeof section !== 'object' || !Array.isArray(section.notes)) {
          return [];
        }
        return section.notes
          .map((note) => {
            if (!note || typeof note !== 'object') {
              return null;
            }
            const text = normalize(note.name || note.title || '');
            const key = normalize(note.key || note.noteKey || '');
            const urlname = normalize(
              note.urlname ||
              note.userUrlname ||
              (note.user && note.user.urlname) ||
              (note.author && note.author.urlname) ||
              ''
            );
            if (!text || !key || !urlname) {
              return null;
            }
            return {
              text,
              href: `/${encodedPath(urlname)}/n/${encodedPath(key)}`,
            };
          })
          .filter(Boolean);
      }
      try {
        const response = await fetch(%s);
        const payload = JSON.parse(await response.text());
        const sections = Array.isArray(payload && payload.data && payload.data.sections)
          ? payload.data.sections
              .map((section) => {
                const title = normalize(section && (
                  section.label_name || section.labelName || section.title || section.name || ''
                ));
                const items = sectionItems(section).slice(0, 12);
                if (!title || items.length < 2) {
                  return null;
                }
                return { title, items };
              })
              .filter(Boolean)
          : [];
        window[%s] = JSON.stringify(sections);
      } catch (_error) {
        window[%s] = '[]';
      }
    })()
    """
    % (
      json.dumps(pending_key),
      json.dumps(_PENDING_RUNTIME_SECTIONS),
      json.dumps(endpoint),
      json.dumps(pending_key),
      json.dumps(pending_key),
    ),
    drain_timers=False,
  )


def _await_runtime_sections_value(
  runtime,
  *,
  probe: str,
  pending_value: str,
  max_rounds: int = 10,
  max_time_advance_ms: int = 1000,
  max_timer_steps: int = 100,
) -> str:
  payload = runtime.eval(probe, drain_timers=False)
  for _round in range(max_rounds):
    if isinstance(payload, str) and payload != pending_value:
      return payload
    runtime._drain_async_work(
      max_time_advance_ms=max_time_advance_ms,
      max_timer_steps=max_timer_steps,
    )
    payload = runtime.eval(probe, drain_timers=False)
  if isinstance(payload, str) and payload != pending_value:
    return payload
  return "[]"


def _extract_note_runtime_sections_with_python_retry(
  runtime,
  source: str,
  *,
  endpoint: str,
  pending_key: str,
  parser,
) -> list[HydrationSection]:
  fetched_sections = _fetch_note_runtime_sections_via_python(
    runtime,
    source,
    endpoint=endpoint,
    parser=parser,
  )
  if fetched_sections:
    return fetched_sections
  last_sections: list[HydrationSection] = []
  probe = f"window[{json.dumps(pending_key)}] || '[]'"
  for _attempt in range(3):
    _launch_note_runtime_probe(
      runtime,
      endpoint=endpoint,
      pending_key=pending_key,
    )
    payload = _await_runtime_sections_value(
      runtime,
      probe=probe,
      pending_value=_PENDING_RUNTIME_SECTIONS,
    )
    last_sections = _load_sections(payload)
    if last_sections:
      return last_sections
  return last_sections


def _fetch_note_runtime_sections_via_python(
  runtime,
  source: str,
  *,
  endpoint: str,
  parser,
) -> list[HydrationSection]:
  target = resolve_resource_url(source, endpoint)
  session = getattr(runtime, "session", None)
  try:
    payload = fetch_resource(target, session=session).content
  except Exception:
    return []
  return parser(payload)


def _load_note_home_sections_payload(payload: str) -> list[HydrationSection]:
  if not isinstance(payload, str):
    return []
  try:
    data = json.loads(payload)
  except json.JSONDecodeError:
    return []
  raw_sections = data.get("data", {}).get("sections") if isinstance(data, dict) else None
  if not isinstance(raw_sections, list):
    return []
  sections: list[dict[str, object]] = []
  for raw_section in raw_sections:
    if not isinstance(raw_section, dict):
      continue
    title = _normalize_whitespace(
      raw_section.get("label_name")
      or raw_section.get("labelName")
      or raw_section.get("title")
      or raw_section.get("name")
      or ""
    )
    items = _note_home_section_items(raw_section)[:12]
    if not title or len(items) < 2:
      continue
    sections.append(
      {
        "title": title,
        "items": [
          {"text": item_text, "href": item_href}
          for item_text, item_href in items
        ],
      }
    )
  return _load_sections(json.dumps(sections))


def _note_home_section_items(section: dict[str, object]) -> list[tuple[str, str]]:
  notes = section.get("notes")
  if not isinstance(notes, list):
    return []
  items: list[tuple[str, str]] = []
  for note in notes:
    if not isinstance(note, dict):
      continue
    text = _normalize_whitespace(note.get("name") or note.get("title") or "")
    key = _normalize_whitespace(note.get("key") or note.get("noteKey") or "")
    user = note.get("user")
    author = note.get("author")
    urlname = _normalize_whitespace(
      note.get("urlname")
      or note.get("userUrlname")
      or (user.get("urlname") if isinstance(user, dict) else "")
      or (author.get("urlname") if isinstance(author, dict) else "")
      or ""
    )
    if not text or not key or not urlname:
      continue
    items.append((text, f"/{_encoded_path(urlname)}/n/{_encoded_path(key)}"))
  return items


def _load_note_topic_sections_payload(payload: str) -> list[HydrationSection]:
  if not isinstance(payload, str):
    return []
  try:
    data = json.loads(payload)
  except json.JSONDecodeError:
    return []
  raw_sections = data.get("data", {}).get("sections") if isinstance(data, dict) else None
  if not isinstance(raw_sections, list):
    return []
  sections: list[dict[str, object]] = []
  for raw_section in raw_sections:
    if not isinstance(raw_section, dict):
      continue
    title = _normalize_whitespace(
      raw_section.get("label_name")
      or raw_section.get("labelName")
      or raw_section.get("title")
      or raw_section.get("name")
      or ""
    )
    items = _note_topic_section_items(raw_section)[:12]
    if not title or len(items) < 2:
      continue
    sections.append(
      {
        "title": title,
        "items": [
          {"text": item_text, "href": item_href}
          for item_text, item_href in items
        ],
      }
    )
  return _load_sections(json.dumps(sections))


def _note_topic_section_items(section: dict[str, object]) -> list[tuple[str, str | None]]:
  notes = section.get("notes")
  if isinstance(notes, list):
    items: list[tuple[str, str | None]] = []
    for note in notes:
      if not isinstance(note, dict):
        continue
      text = _normalize_whitespace(note.get("name") or note.get("title") or "")
      if not text:
        continue
      external_url = note.get("external_url") or note.get("externalUrl")
      if isinstance(external_url, str) and external_url:
        items.append((text, external_url))
        continue
      key = _normalize_whitespace(note.get("key") or note.get("noteKey") or "")
      user = note.get("user")
      author = note.get("author")
      urlname = _normalize_whitespace(
        note.get("urlname")
        or note.get("userUrlname")
        or (user.get("urlname") if isinstance(user, dict) else "")
        or (author.get("urlname") if isinstance(author, dict) else "")
        or ""
      )
      if not key or not urlname:
        continue
      items.append((text, f"/{_encoded_path(urlname)}/n/{_encoded_path(key)}"))
    return items
  related_users = section.get("relatedUsers")
  if not isinstance(related_users, list):
    return []
  items = []
  for user in related_users:
    if not isinstance(user, dict):
      continue
    text = _normalize_whitespace(user.get("nickname") or user.get("name") or user.get("urlname") or "")
    urlname = _normalize_whitespace(user.get("urlname") or "")
    if not text:
      continue
    items.append((text, f"/{_encoded_path(urlname)}" if urlname else None))
  return items


def _normalize_whitespace(value: object) -> str:
  return re.sub(r"\s+", " ", str(value or "")).strip()


def _encoded_path(value: object) -> str:
  return "/".join(
    quote(part, safe="")
    for part in str(value).split("/")
    if part
  )


def _load_sections(payload: str) -> list[HydrationSection]:
  if not isinstance(payload, str):
    return []
  try:
    values = json.loads(payload)
  except json.JSONDecodeError:
    return []
  sections: list[HydrationSection] = []
  for entry in values:
    if not isinstance(entry, dict) or not isinstance(entry.get("title"), str):
      continue
    items = entry.get("items")
    if not isinstance(items, list):
      continue
    normalized_items: list[tuple[str, str | None]] = []
    for item in items:
      if not isinstance(item, dict) or not isinstance(item.get("text"), str):
        continue
      href = item.get("href")
      normalized_items.append((item["text"], href if isinstance(href, str) else None))
    if len(normalized_items) < 2:
      continue
    sections.append(
      HydrationSection(
        title=entry["title"],
        items=tuple(normalized_items),
        role=entry.get("role") if isinstance(entry.get("role"), str) else None,
      )
    )
  return sections
