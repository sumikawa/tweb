from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import re
from urllib.parse import quote, unquote, urlparse

from .apollo import expand_apollo_payload
from .dom import DocumentNode, ElementNode, TextNode
from .fetcher import Resource
from .hydration import HydrationLink, HydrationSection, merge_hydration_sections
from .js_runtime_helpers import JavaScriptRuntimeError
from .parser import parse_document


HYDRATION_ROOT_NAMES = (
  "__NUXT__",
  "__NEXT_DATA__",
  "__INITIAL_STATE__",
  "__APOLLO_STATE__",
  "__PRELOADED_STATE__",
  "__data",
)

_SCRIPT_JSON_TYPES = {
  "application/json",
  "application/ld+json",
}
_MAX_TEXTS = 120
_MAX_ITEMS = 50
_MAX_DEPTH = 6
_MAX_CHUNKS = 32
_MAX_NETWORK_BODIES = 24
_MAX_BODY_CHARS = 200_000
_MAX_EMBEDDED_HTML_ITEMS = 200
_MAX_EXPENSIVE_INLINE_SCRIPT_CHARS = 262_144
_JSON_MARKER_RE = re.compile(
  r'(?:"(?:items|notes|sections|categories|subCategories|target)"\s*:)|(?:"__typename"\s*:)|(?:"href"\s*:)|(?:"key"\s*:)|(?:"value"\s*:)|(?:"children"\s*:)',
  re.DOTALL,
)
_JS_STRING_LITERAL_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.DOTALL)
_JSON_PARSE_ASSIGNMENT_RE = re.compile(
  r"""(?:window|self|globalThis)\.(?P<name>__[A-Za-z0-9_]+)\s*=\s*JSON\.parse\(\s*(?P<literal>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*\)""",
  re.DOTALL,
)
_HTML_FRAGMENT_RE = re.compile(r"<(?:article|section|div|p|h1|h2|h3|ul|ol|li|a|pre|code|table)\b", re.IGNORECASE)
_EMBEDDED_HTML_KEYS = {
  "richtext",
  "html",
  "bodyhtml",
  "contenthtml",
  "renderedhtml",
  "markup",
}
_CHALLENGE_URL_MARKERS = (
  "__challenge",
  "captcha",
  "interstitial",
  "challenge.js",
)
_NUMBERED_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*?)(\d{1,3})$")
_NUMBERED_TEXT_PREFIXES = (
  "title",
  "name",
  "label",
  "text",
  "caption",
  "headline",
  "message",
)
_NUMBERED_HREF_PREFIXES = (
  "href",
  "url",
  "link",
  "path",
  "slug",
)


@dataclass(frozen=True)
class RuntimeDataSourceSummary:
  source_type: str
  source_name: str
  texts: int
  links: int
  sections: int


@dataclass(frozen=True)
class RuntimeDataDebugInfo:
  confidence: str
  fallback_reason: str | None
  source_summaries: tuple[RuntimeDataSourceSummary, ...]
  used_site_specific_fallback: bool
  body_was_substantial: bool

  def to_dict(self) -> dict[str, object]:
    return {
      "confidence": self.confidence,
      "fallback_reason": self.fallback_reason,
      "source_summaries": [
        {
          "source_type": entry.source_type,
          "source_name": entry.source_name,
          "texts": entry.texts,
          "links": entry.links,
          "sections": entry.sections,
        }
        for entry in self.source_summaries
      ],
      "used_site_specific_fallback": self.used_site_specific_fallback,
      "body_was_substantial": self.body_was_substantial,
    }


@dataclass(frozen=True)
class RuntimeDataResult:
  texts: list[str]
  links: list[HydrationLink]
  sections: list[HydrationSection]
  debug: RuntimeDataDebugInfo


def collect_runtime_data(
  document: DocumentNode,
  runtime,
  *,
  body_was_substantial: bool,
  fallback_reason: str | None,
  site_specific_sections: list[HydrationSection] | None = None,
) -> RuntimeDataResult:
  existing_links = _existing_document_links(document)
  document_control_count = _document_control_count(document)
  base_url = document.source
  source_summaries: list[RuntimeDataSourceSummary] = []
  texts: list[str] = []
  links: list[HydrationLink] = []
  sections: list[HydrationSection] = []
  (
    inline_json_payloads,
    inline_json_parse_payloads,
    inline_literal_payloads,
    inline_chunk_payloads,
  ) = _scan_inline_script_payloads(
    document,
    body_was_substantial=body_was_substantial,
    document_link_count=len(existing_links),
    document_control_count=document_control_count,
  )
  inline_source_names = {
    source_name
    for source_name, _payload in [*inline_json_payloads, *inline_json_parse_payloads]
  }

  def merge_payload(source_type: str, source_name: str, payload: object) -> None:
    normalized_payload = _normalize_runtime_payload(payload, source_name=source_name)
    payload_texts, payload_links, payload_sections = _collect_payload(
      normalized_payload,
      base_url=base_url,
      existing_links=existing_links,
    )
    if source_type == "network":
      payload_sections = _label_generic_network_sections(payload_sections, source_name)
    texts.extend(payload_texts)
    links.extend(payload_links)
    sections.extend(payload_sections)
    source_summaries.append(
      RuntimeDataSourceSummary(
        source_type=source_type,
        source_name=source_name,
        texts=len(payload_texts),
        links=len(payload_links),
        sections=len(payload_sections),
      )
    )

  def _label_generic_network_sections(
    payload_sections: list[HydrationSection],
    source_name: str,
  ) -> list[HydrationSection]:
    parsed = urlparse(source_name)
    path_name = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    path_name = re.sub(r"\.[A-Za-z0-9]+$", "", path_name)
    title = " ".join(part.capitalize() for part in re.split(r"[-_]+", path_name) if part)
    if not title:
      return payload_sections
    generic_titles = {"items", "list", "runtime sections"}
    return [
      HydrationSection(
        title=title if section.title.casefold() in generic_titles else section.title,
        items=section.items,
        role=(
          "recovered"
          if section.role is None
          and len(section.items) >= 12
          and sum(1 for _text, href in section.items if href) >= int(len(section.items) * 0.8)
          else section.role
        ),
      )
      for section in payload_sections
    ]

  for source_name, payload in _window_root_payloads(runtime, skip_names=inline_source_names):
    merge_payload("window-root", source_name, payload)
  for source_name, payload in inline_json_payloads:
    merge_payload("inline-json", source_name, payload)
  for source_name, payload in inline_json_parse_payloads:
    merge_payload("inline-json-parse", source_name, payload)
  for source_name, payload in inline_literal_payloads:
    merge_payload("inline-literal", source_name, payload)
  for source_name, payload in inline_chunk_payloads:
    merge_payload("inline-chunk", source_name, payload)
  for source_name, payload in _chunk_payloads(runtime):
    merge_payload("chunk", source_name, payload)
  for source_name, payload in _network_payloads(runtime):
    merge_payload("network", source_name, payload)

  if site_specific_sections:
    sections = merge_hydration_sections(site_specific_sections, sections)
  else:
    sections = merge_hydration_sections([], sections)
  texts = _dedupe_texts(texts)
  links = _dedupe_links(links)
  confidence = _runtime_data_confidence(sections, links, texts, body_was_substantial)
  debug = RuntimeDataDebugInfo(
    confidence=confidence,
    fallback_reason=fallback_reason,
    source_summaries=tuple(
      entry
      for entry in source_summaries
      if entry.texts or entry.links or entry.sections
    ),
    used_site_specific_fallback=bool(site_specific_sections),
    body_was_substantial=body_was_substantial,
  )
  return RuntimeDataResult(
    texts=texts,
    links=links,
    sections=sections,
    debug=debug,
  )


def _window_root_payloads(runtime, *, skip_names: set[str] | None = None) -> list[tuple[str, object]]:
  root_names = list(HYDRATION_ROOT_NAMES)
  skip_names_json = json.dumps(sorted(skip_names or ()))
  script = (
    """
    (function() {
      const roots = %s;
      const skip = new Set(%s);
      const result = [];
      roots.forEach((name) => {
        try {
          if (skip.has(name)) {
            return;
          }
          const value = window[name];
          if (value && typeof value === 'object') {
            result.push([name, value]);
          }
        } catch (_error) {
        }
      });
      return JSON.stringify(result);
    })()
    """
    % (json.dumps(root_names), skip_names_json)
  )
  try:
    payload = runtime.eval(script, drain_timers=False)
    return _decode_named_payload_list(payload)
  except JavaScriptRuntimeError as exc:
    message = str(exc).lower()
    if "memory limit exceeded" not in message and "out of memory" not in message:
      pass
  results: list[tuple[str, object]] = []
  skipped = set(skip_names or ())
  for root_name in root_names:
    if root_name in skipped:
      continue
    try:
      payload = runtime.eval(
        """
        (function() {
          try {
            const name = %s;
            const value = window[name];
            if (!value || typeof value !== 'object') {
              return '[]';
            }
            return JSON.stringify([[name, value]]);
          } catch (_error) {
            return '[]';
          }
        })()
        """
        % json.dumps(root_name),
        drain_timers=False,
      )
    except JavaScriptRuntimeError:
      continue
    results.extend(_decode_named_payload_list(payload))
  return results


def _inline_json_payloads(document: DocumentNode) -> list[tuple[str, object]]:
  return _scan_inline_script_payloads(document)[0]


def _scan_inline_script_payloads(
  document: DocumentNode,
  *,
  body_was_substantial: bool = False,
  document_link_count: int = 0,
  document_control_count: int = 0,
) -> tuple[
  list[tuple[str, object]],
  list[tuple[str, object]],
  list[tuple[str, object]],
  list[tuple[str, object]],
]:
  payloads: list[tuple[str, object]] = []
  json_parse_payloads: list[tuple[str, object]] = []
  literal_payloads: list[tuple[str, object]] = []
  chunk_payloads: list[tuple[str, object]] = []
  seen_fragments: set[str] = set()
  seen_inline_json_raws: set[str] = set()
  seen_names: set[str] = set()
  seen_chunk_fragments: set[str] = set()
  for index, script in enumerate(document.find_all("script")):
    script_type = (script.attrs.get("type") or "").strip().lower()
    script_id = (script.attrs.get("id") or "").strip()
    raw = _raw_node_text(script).strip()
    if not raw:
      continue
    skip_expensive_fragment_scan = _should_skip_expensive_inline_script_scan(
      raw,
      body_was_substantial=body_was_substantial,
      document_link_count=document_link_count,
      document_control_count=document_control_count,
    )
    if script_type in _SCRIPT_JSON_TYPES or any(name in script_id for name in HYDRATION_ROOT_NAMES):
      if raw not in seen_inline_json_raws:
        payload = _load_json_payload(raw)
        if payload is not None:
          seen_inline_json_raws.add(raw)
          name = script_id or f"script[{index}]"
          payloads.append((name, payload))

    fragments: list[str] | None = None
    if not script.attrs.get("src"):
      if "JSON.parse(" in raw:
        for match in _JSON_PARSE_ASSIGNMENT_RE.finditer(raw):
          source_name = match.group("name")
          if source_name in seen_names:
            continue
          literal = match.group("literal")
          try:
            decoded = ast.literal_eval(literal)
          except (SyntaxError, ValueError):
            continue
          payload = _load_json_payload(decoded)
          if payload is None:
            continue
          seen_names.add(source_name)
          json_parse_payloads.append((source_name, payload))
      if not skip_expensive_fragment_scan:
        fragments = _extract_json_fragments(raw)
        for fragment in fragments:
          if fragment in seen_fragments:
            continue
          loaded = _load_json_payload(fragment)
          if loaded is None:
            continue
          seen_fragments.add(fragment)
          literal_payloads.append((f"script[{index}]", loaded))

    source_name = _inline_chunk_source_name(raw, index=index)
    if source_name is None:
      continue
    chunk_strings: list[str] = []
    if not skip_expensive_fragment_scan:
      chunk_strings = _extract_inline_chunk_strings(raw)
    if not chunk_strings:
      if skip_expensive_fragment_scan:
        continue
      if fragments is None:
        fragments = _extract_json_fragments(raw)
      for fragment in fragments:
        loaded = _load_json_payload(fragment)
        if loaded is None:
          continue
        chunk_strings.extend(_chunk_candidate_strings(loaded))
    for chunk_string in chunk_strings:
      if not _JSON_MARKER_RE.search(chunk_string):
        continue
      for nested_fragment in _extract_json_fragments(chunk_string):
        if nested_fragment in seen_chunk_fragments:
          continue
        nested_loaded = _load_json_payload(nested_fragment)
        if nested_loaded is not None:
          seen_chunk_fragments.add(nested_fragment)
          chunk_payloads.append((source_name, nested_loaded))
  return payloads, json_parse_payloads, literal_payloads, chunk_payloads


def _should_skip_expensive_inline_script_scan(
  raw: str,
  *,
  body_was_substantial: bool,
  document_link_count: int,
  document_control_count: int,
) -> bool:
  return (
    body_was_substantial
    and len(raw) >= _MAX_EXPENSIVE_INLINE_SCRIPT_CHARS
    and document_link_count >= 150
    and document_control_count >= 10
  )


def _inline_chunk_payloads(document: DocumentNode) -> list[tuple[str, object]]:
  return _scan_inline_script_payloads(document)[3]


def _inline_literal_payloads(document: DocumentNode) -> list[tuple[str, object]]:
  return _scan_inline_script_payloads(document)[2]


def _inline_json_parse_payloads(document: DocumentNode) -> list[tuple[str, object]]:
  return _scan_inline_script_payloads(document)[1]


def _chunk_payloads(runtime) -> list[tuple[str, object]]:
  payload = runtime.eval(
    """
    (function() {
      const candidates = [];
      function push(name, parts) {
        const strings = [];
        (parts || []).forEach((entry) => {
          if (typeof entry === 'string') {
            strings.push(entry);
            return;
          }
          if (!Array.isArray(entry)) {
            return;
          }
          entry.forEach((part) => {
            if (typeof part === 'string') {
              strings.push(part);
            }
          });
        });
        if (strings.length) {
          candidates.push([name, strings.slice(0, %d)]);
        }
      }
      try {
        if (Array.isArray(window.__next_f)) {
          push('__next_f', window.__next_f);
        }
      } catch (_error) {
      }
      try {
        if (Array.isArray(window.webpackJsonp)) {
          push('webpackJsonp', window.webpackJsonp);
        }
      } catch (_error) {
      }
      try {
        if (typeof self !== 'undefined' && Array.isArray(self.webpackChunk_N_E)) {
          push('webpackChunk_N_E', self.webpackChunk_N_E);
        }
      } catch (_error) {
      }
      return JSON.stringify(candidates);
    })()
    """
    % _MAX_CHUNKS,
    drain_timers=False,
  )
  payloads: list[tuple[str, object]] = []
  for source_name, raw_chunks in _decode_named_payload_list(payload):
    if not isinstance(raw_chunks, list):
      continue
    for raw_chunk in raw_chunks:
      if not isinstance(raw_chunk, str) or not _JSON_MARKER_RE.search(raw_chunk):
        continue
      for fragment in _extract_json_fragments(raw_chunk):
        loaded = _load_json_payload(fragment)
        if loaded is not None:
          payloads.append((source_name, loaded))
  return payloads


def _inline_chunk_source_name(raw: str, *, index: int) -> str | None:
  if "__next_f.push" in raw or "window.__next_f" in raw or "self.__next_f" in raw:
    return "__next_f"
  if "webpackJsonp.push" in raw or "window.webpackJsonp" in raw:
    return "webpackJsonp"
  if "webpackChunk_N_E.push" in raw or "self.webpackChunk_N_E" in raw:
    return "webpackChunk_N_E"
  if "__next_f" in raw or "webpackJsonp" in raw or "webpackChunk_N_E" in raw:
    return f"script[{index}]"
  return None


def _chunk_candidate_strings(value: object) -> list[str]:
  strings: list[str] = []
  if isinstance(value, str):
    strings.append(value)
    return strings
  if not isinstance(value, list):
    return strings
  for entry in value:
    if isinstance(entry, str):
      strings.append(entry)
      continue
    if not isinstance(entry, list):
      continue
    for part in entry:
      if isinstance(part, str):
        strings.append(part)
  return strings


def _extract_inline_chunk_strings(raw: str) -> list[str]:
  strings: list[str] = []
  for match in _JS_STRING_LITERAL_RE.finditer(raw):
    literal = match.group(0)
    try:
      decoded = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
      continue
    if isinstance(decoded, str):
      strings.append(decoded)
  return strings


def _network_payloads(runtime) -> list[tuple[str, object]]:
  payloads: list[tuple[str, object]] = []
  provider = getattr(runtime, "runtime_data_network_payloads", None)
  if not callable(provider):
    return payloads
  responses = provider()
  if not isinstance(responses, list):
    return payloads
  for response in responses:
    if not isinstance(response, dict):
      continue
    body = response.get("body")
    url = response.get("url")
    if not isinstance(body, str) or len(body) > _MAX_BODY_CHARS:
      continue
    if isinstance(url, str) and _looks_like_challenge_url(url):
      continue
    loaded = _load_json_payload(body)
    if loaded is None:
      continue
    payloads.append((str(url or "network"), loaded))
    if len(payloads) >= _MAX_NETWORK_BODIES:
      break
  return payloads


def _looks_like_challenge_url(url: str) -> bool:
  lowered = url.lower()
  return any(marker in lowered for marker in _CHALLENGE_URL_MARKERS)


def _decode_named_payload_list(payload: object) -> list[tuple[str, object]]:
  if not isinstance(payload, str):
    return []
  try:
    values = json.loads(payload)
  except json.JSONDecodeError:
    return []
  results: list[tuple[str, object]] = []
  if not isinstance(values, list):
    return results
  for entry in values:
    if (
      isinstance(entry, list)
      and len(entry) == 2
      and isinstance(entry[0], str)
    ):
      results.append((entry[0], entry[1]))
  return results


def _load_json_payload(raw: str) -> object | None:
  try:
    return json.loads(raw)
  except json.JSONDecodeError:
    return None


def _normalize_runtime_payload(payload: object, *, source_name: str | None = None) -> object:
  expanded = _expand_nuxt_data_payload(payload)
  if expanded is not None:
    payload = expanded
  return expand_apollo_payload(payload, is_apollo_state=source_name == "__APOLLO_STATE__")


def _expand_nuxt_data_payload(payload: object) -> object | None:
  if not _looks_like_nuxt_data_payload(payload):
    return None
  assert isinstance(payload, list)
  table = payload
  cache: dict[int, object] = {}
  resolving: set[int] = set()

  def resolve_slot(index: int) -> object:
    if index in cache:
      return cache[index]
    if index in resolving or index < 0 or index >= len(table):
      return None
    resolving.add(index)
    try:
      resolved = resolve_value(table[index])
      cache[index] = resolved
      return resolved
    finally:
      resolving.discard(index)

  def resolve_value(value: object) -> object:
    if isinstance(value, bool):
      return value
    if isinstance(value, int) and 0 <= value < len(table):
      return resolve_slot(value)
    if isinstance(value, list):
      if not value:
        return []
      marker = value[0] if isinstance(value[0], str) else None
      if marker in {"ShallowReactive", "Reactive"} and len(value) >= 2:
        return resolve_value(value[1])
      if marker == "Set":
        return [resolve_value(entry) for entry in value[1:]]
      if marker == "Map":
        items = value[1:]
        pairs = []
        for offset in range(0, len(items), 2):
          key = resolve_value(items[offset])
          mapped = resolve_value(items[offset + 1]) if offset + 1 < len(items) else None
          pairs.append((key, mapped))
        return pairs
      return [resolve_value(entry) for entry in value]
    if isinstance(value, dict):
      return {
        key: resolve_value(entry)
        for key, entry in value.items()
      }
    return value

  root_index = 1 if len(table) > 1 and isinstance(table[1], dict) else 0
  return resolve_slot(root_index)


def _looks_like_nuxt_data_payload(payload: object) -> bool:
  if not isinstance(payload, list) or len(payload) < 3:
    return False
  marker = payload[0]
  if not (isinstance(marker, list) and marker and marker[0] in {"ShallowReactive", "Reactive"}):
    return False
  return any(
    isinstance(entry, str) and entry in {"ShallowReactive", "Reactive", "Set", "Map"}
    for entry in payload[:8]
    if isinstance(entry, str)
  ) or any(
    isinstance(entry, list) and entry and isinstance(entry[0], str) and entry[0] in {"ShallowReactive", "Reactive", "Set", "Map"}
    for entry in payload[:8]
  )


def _extract_json_fragments(text: str) -> list[str]:
  fragments: list[str] = []
  index = 0
  while index < len(text):
    if text[index] not in "[{":
      index += 1
      continue
    end = _find_balanced_json_end(text, index)
    if end is None:
      index += 1
      continue
    fragment = text[index : end + 1]
    if _JSON_MARKER_RE.search(fragment):
      fragments.append(fragment)
    index = end + 1
  return fragments


def _find_balanced_json_end(text: str, start: int) -> int | None:
  stack = [text[start]]
  in_string = False
  escaped = False
  pairs = {"{": "}", "[": "]"}
  for index in range(start + 1, len(text)):
    char = text[index]
    if in_string:
      if escaped:
        escaped = False
        continue
      if char == "\\":
        escaped = True
        continue
      if char == '"':
        in_string = False
      continue
    if char == '"':
      in_string = True
      continue
    if char in pairs:
      stack.append(char)
      continue
    if char in "}]":
      if not stack or pairs[stack[-1]] != char:
        return None
      stack.pop()
      if not stack:
        return index
  return None


def _existing_document_links(document: DocumentNode) -> dict[str, str]:
  mapping: dict[str, str] = {}
  for anchor in document.find_all("a"):
    href = anchor.attrs.get("href")
    text = " ".join(anchor.text_content().split())
    if href and text and text not in mapping:
      mapping[text] = href
  return mapping


def _document_control_count(document: DocumentNode) -> int:
  count = 0
  for tag in ("input", "button", "select", "textarea"):
    count += len(document.find_all(tag))
  return count


def _collect_payload(
  payload: object,
  *,
  base_url: str,
  existing_links: dict[str, str],
) -> tuple[list[str], list[HydrationLink], list[HydrationSection]]:
  texts: list[str] = []
  links: list[HydrationLink] = []
  sections: list[HydrationSection] = []
  seen_objects: set[int] = set()
  seen_texts: set[str] = set()
  seen_links: set[tuple[str, str]] = set()
  seen_sections: set[str] = set()
  normalized_text_cache: dict[str, str] = {}
  resolved_href_cache: dict[str, str | None] = {}
  label_cache: dict[int, str] = {}
  section_title_cache: dict[str, str] = {}
  role_hint_cache: dict[tuple[str | None, str | None], str | None] = {}

  def normalize_text_cached(value: object) -> str:
    cache_key = str(value or "")
    cached = normalized_text_cache.get(cache_key)
    if cached is not None:
      return cached
    normalized = _normalize_text(cache_key)
    normalized_text_cache[cache_key] = normalized
    return normalized

  def resolve_href_cached(href: object, *, base_url: str = base_url) -> str | None:
    if not isinstance(href, str):
      return None
    cached = resolved_href_cache.get(href)
    if href in resolved_href_cache:
      return cached
    resolved = _resolve_href(href, base_url=base_url)
    resolved_href_cache[href] = resolved
    return resolved

  def label_for_cached(value: dict[object, object]) -> str:
    cache_key = id(value)
    cached = label_cache.get(cache_key)
    if cached is not None:
      return cached
    label = _label_for(value, normalize_text=normalize_text_cached)
    label_cache[cache_key] = label
    return label

  def section_title_cached(key_hint: str) -> str:
    cached = section_title_cache.get(key_hint)
    if cached is not None:
      return cached
    title = _section_title_from_key(key_hint)
    section_title_cache[key_hint] = title
    return title

  def role_hint_cached(key_hint: str | None, parent_hint: str | None) -> str | None:
    cache_key = (key_hint, parent_hint)
    if cache_key in role_hint_cache:
      return role_hint_cache[cache_key]
    role = _role_hint(key_hint, parent_hint)
    role_hint_cache[cache_key] = role
    return role

  def remember_text(value: object) -> None:
    normalized = normalize_text_cached(value)
    if not normalized or normalized in seen_texts or len(texts) >= _MAX_TEXTS:
      return
    if normalized.startswith("http://") or normalized.startswith("https://"):
      return
    if normalized.count(" ") == 0 and len(normalized) < 24 and not _contains_cjk(normalized):
      return
    seen_texts.add(normalized)
    texts.append(normalized)

  def remember_link(text: object, href: object) -> None:
    normalized_text = normalize_text_cached(text)
    resolved_href = resolve_href_cached(href)
    if not normalized_text or not resolved_href:
      return
    key = (normalized_text, resolved_href)
    if key in seen_links:
      return
    seen_links.add(key)
    links.append(HydrationLink(text=normalized_text, href=resolved_href))

  def remember_section(title: object, items: list[tuple[str, str | None]], role: str | None) -> None:
    normalized_title = normalize_text_cached(title)
    if not normalized_title:
      return
    key = normalized_title.lower()
    if key in seen_sections:
      return
    item_limit = 200 if role == "recovered" else _MAX_ITEMS
    normalized_items: list[tuple[str, str | None]] = []
    for item_text, item_href in items[:item_limit]:
      normalized_item_text = normalize_text_cached(item_text)
      if not normalized_item_text:
        continue
      normalized_items.append(
        (normalized_item_text, resolve_href_cached(item_href) if item_href else None)
      )
    if len(normalized_items) < 2:
      return
    seen_sections.add(key)
    for item_text, item_href in normalized_items:
      if item_href:
        remember_link(item_text, item_href)
    sections.append(
      HydrationSection(
        title=normalized_title,
        items=tuple(normalized_items),
        role=role,
      )
    )

  def remember_html(value: object, key_hint: str | None, label_hint: str | None) -> None:
    html = str(value or "")
    if not _looks_like_embedded_html(key_hint, html):
      return
    title, items, html_texts, html_links = _extract_embedded_html_payload(
      html,
      base_url=base_url,
    )
    for text in html_texts:
      remember_text(text)
    for link_text, link_href in html_links:
      remember_link(link_text, link_href)
    if items:
      remember_section(title or label_hint, items, "recovered")

  def visit(value: object, depth: int, key_hint: str | None = None) -> None:
    if value is None or depth > _MAX_DEPTH:
      return
    if isinstance(value, str):
      remember_text(value)
      return
    if isinstance(value, (int, float, bool)):
      return
    object_id = id(value)
    if object_id in seen_objects:
      return
    if isinstance(value, dict):
      seen_objects.add(object_id)
      label = label_for_cached(value)
      href = _derive_href(
        value,
        key_hint=key_hint,
        base_url=base_url,
        existing_links=existing_links,
        label=label,
        normalize_text=normalize_text_cached,
        resolve_href=resolve_href_cached,
      )
      if label and href:
        remember_link(label, href)
      numbered_items = _section_items_from_numbered_dict_fields(
        value,
        base_url=base_url,
        existing_links=existing_links,
        normalize_text=normalize_text_cached,
        resolve_href=resolve_href_cached,
      )
      if len(numbered_items) >= 2:
        remember_section(
          label or section_title_cached(key_hint or "items"),
          numbered_items,
          role_hint_cached(key_hint, None),
        )
      for child_key, entry in value.items():
        if isinstance(entry, str):
          remember_html(entry, str(child_key), label or str(child_key))
        handled_as_section = False
        if isinstance(entry, dict):
          items = _section_items_from_numbered_dict_fields(
            entry,
            base_url=base_url,
            existing_links=existing_links,
            normalize_text=normalize_text_cached,
            resolve_href=resolve_href_cached,
          )
          if len(items) >= 2:
            remember_section(
              label or label_for_cached(entry) or section_title_cached(str(child_key)),
              items,
              role_hint_cached(str(child_key), key_hint),
            )
            handled_as_section = True
        if isinstance(entry, list):
          fragment_text = _joined_fragment_text(entry)
          if fragment_text:
            remember_text(fragment_text)
          if label:
            items = _section_items_from_list(
              entry,
              key_hint=str(child_key),
              base_url=base_url,
              existing_links=existing_links,
              normalize_text=normalize_text_cached,
              resolve_href=resolve_href_cached,
              label_for=label_for_cached,
            )
            if len(items) >= 2:
              remember_section(label, items, role_hint_cached(str(child_key), key_hint))
              handled_as_section = True
        if handled_as_section:
          continue
        if child_key not in {"id", "uuid", "key"}:
          visit(entry, depth + 1, str(child_key))
      return
    if isinstance(value, list):
      seen_objects.add(object_id)
      if key_hint:
        items = _section_items_from_list(
          value,
          key_hint=key_hint,
          base_url=base_url,
          existing_links=existing_links,
          normalize_text=normalize_text_cached,
          resolve_href=resolve_href_cached,
          label_for=label_for_cached,
        )
        if len(items) >= 2:
          remember_section(section_title_cached(key_hint), items, role_hint_cached(key_hint, None))
      for entry in value[:30]:
        visit(entry, depth + 1, key_hint)

  visit(payload, 0, None)
  return texts, links, sections


def _section_items_from_list(
  entries: list[object],
  *,
  key_hint: str,
  base_url: str,
  existing_links: dict[str, str],
  normalize_text=None,
  resolve_href=None,
  label_for=None,
) -> list[tuple[str, str | None]]:
  normalize_text = normalize_text or _normalize_text
  resolve_href = resolve_href or _resolve_href
  label_for = label_for or _label_for
  items: list[tuple[str, str | None]] = []
  seen: set[tuple[str, str | None]] = set()
  for entry in entries[:_MAX_ITEMS]:
    if not isinstance(entry, dict):
      continue
    text = label_for(entry)
    href = _derive_href(
      entry,
      key_hint=key_hint,
      base_url=base_url,
      existing_links=existing_links,
      label=text,
      normalize_text=normalize_text,
      resolve_href=resolve_href,
    )
    normalized_text = normalize_text(text)
    normalized_href = resolve_href(href, base_url=base_url) if href else None
    if not normalized_text:
      continue
    item = (normalized_text, normalized_href)
    if item in seen:
      continue
    seen.add(item)
    items.append(item)
  if items:
    return items
  return _section_items_from_nested_entry_lists(
    entries,
    key_hint=key_hint,
    base_url=base_url,
    existing_links=existing_links,
  )


def _section_items_from_numbered_dict_fields(
  value: dict[object, object],
  *,
  base_url: str,
  existing_links: dict[str, str],
  normalize_text=None,
  resolve_href=None,
) -> list[tuple[str, str | None]]:
  normalize_text = normalize_text or _normalize_text
  resolve_href = resolve_href or _resolve_href
  grouped: dict[int, dict[str, object]] = {}
  for raw_key, raw_value in value.items():
    if not isinstance(raw_key, str):
      continue
    match = _NUMBERED_FIELD_RE.match(raw_key)
    if match is None:
      continue
    prefix = match.group(1).lower()
    index = int(match.group(2))
    if prefix not in _NUMBERED_TEXT_PREFIXES and prefix not in _NUMBERED_HREF_PREFIXES:
      continue
    grouped.setdefault(index, {})[prefix] = raw_value

  items: list[tuple[str, str | None]] = []
  seen: set[tuple[str, str | None]] = set()
  for index in sorted(grouped):
    entry = grouped[index]
    text = ""
    href: str | None = None
    for prefix in _NUMBERED_TEXT_PREFIXES:
      normalized = normalize_text(entry.get(prefix))
      if normalized:
        text = normalized
        break
    for prefix in _NUMBERED_HREF_PREFIXES:
      candidate = entry.get(prefix)
      if candidate is None:
        continue
      href = resolve_href(candidate, base_url=base_url)
      if href:
        break
    if not text:
      continue
    if href is None and text in existing_links:
      href = resolve_href(existing_links[text], base_url=base_url)
    item = (text, href)
    if item in seen:
      continue
    seen.add(item)
    items.append(item)
    if len(items) >= _MAX_ITEMS:
      break
  return items


def _joined_fragment_text(entries: list[object]) -> str:
  parts: list[str] = []
  for entry in entries[:24]:
    text = _fragment_entry_text(entry)
    if text:
      parts.append(text)
  normalized = _normalize_text(" ".join(parts))
  if len(normalized) < 24 and not _contains_cjk(normalized):
    return ""
  return normalized


def _fragment_entry_text(entry: object) -> str:
  if isinstance(entry, str):
    return _normalize_text(entry)
  if not isinstance(entry, dict):
    return ""
  parts: list[str] = []
  value = entry.get("value")
  if isinstance(value, str) and not _looks_like_fragment_placeholder(value):
    parts.append(value)
  children = entry.get("children")
  if isinstance(children, list):
    for child in children[:12]:
      child_text = _fragment_entry_text(child)
      if child_text:
        parts.append(child_text)
  return _normalize_text(" ".join(parts))


def _looks_like_fragment_placeholder(value: str) -> bool:
  normalized = value.strip()
  if not normalized:
    return True
  if " " in normalized or _contains_cjk(normalized):
    return False
  return normalized[:1].islower() or normalized.endswith("Icon") or normalized.endswith("Link") or normalized.endswith("Text")


def _section_items_from_nested_entry_lists(
  entries: list[object],
  *,
  key_hint: str,
  base_url: str,
  existing_links: dict[str, str],
  normalize_text=None,
  resolve_href=None,
  label_for=None,
) -> list[tuple[str, str | None]]:
  normalize_text = normalize_text or _normalize_text
  resolve_href = resolve_href or _resolve_href
  label_for = label_for or _label_for
  items: list[tuple[str, str | None]] = []
  seen: set[tuple[str, str | None]] = set()
  for entry in entries[:24]:
    if not isinstance(entry, dict):
      continue
    for nested_key, nested_value in entry.items():
      if not isinstance(nested_value, list):
        continue
      if not _looks_like_section_item_list(nested_key, nested_value):
        continue
      nested_items = _section_items_from_list(
        nested_value,
        key_hint=str(nested_key),
        base_url=base_url,
        existing_links=existing_links,
        normalize_text=normalize_text,
        resolve_href=resolve_href,
        label_for=label_for,
      )
      for item in nested_items:
        if item in seen:
          continue
        seen.add(item)
        items.append(item)
        if len(items) >= _MAX_ITEMS:
          return items
  return items


def _label_for(value: dict[object, object], normalize_text=None) -> str:
  normalize_text = normalize_text or _normalize_text
  for key in ("title", "name", "label", "text", "headline", "displayName", "message", "description"):
    if key in value:
      normalized = normalize_text(value.get(key))
      if normalized:
        return normalized
  return ""


def _derive_href(
  value: dict[object, object],
  *,
  key_hint: str | None,
  base_url: str,
  existing_links: dict[str, str],
  label: str | None = None,
  normalize_text=None,
  resolve_href=None,
) -> str | None:
  normalize_text = normalize_text or _normalize_text
  resolve_href = resolve_href or _resolve_href
  direct = (
    value.get("href")
    or value.get("url")
    or value.get("link")
    or value.get("path")
    or value.get("noteUrl")
    or value.get("externalUrl")
  )
  resolved_direct = resolve_href(direct, base_url=base_url)
  if resolved_direct:
    return resolved_direct
  label = label if label is not None else _label_for(value, normalize_text=normalize_text)
  if label and label in existing_links:
    return resolve_href(existing_links[label], base_url=base_url)
  user = value.get("user") if isinstance(value.get("user"), dict) else {}
  author = value.get("author") if isinstance(value.get("author"), dict) else {}
  urlname = normalize_text(
    value.get("urlname")
    or value.get("userUrlname")
    or user.get("urlname")
    or author.get("urlname")
  )
  key = normalize_text(value.get("key") or value.get("noteKey") or "")
  eng_name = normalize_text(value.get("engName") or "")
  parent_dir = normalize_text(value.get("parentDir") or "")
  slug = normalize_text(value.get("slug") or value.get("pathname") or "")
  if urlname and key and re.fullmatch(r"n[a-z0-9]+", key, re.IGNORECASE):
    return f"/{_encoded_path(urlname)}/n/{_encoded_path(key)}"
  if parent_dir and eng_name:
    return f"/{_encoded_path(parent_dir)}/{_encoded_path(eng_name)}"
  if key_hint == "subCategories" and eng_name:
    return f"/topic/{_encoded_path(eng_name)}"
  if slug:
    if not slug.startswith("/"):
      slug = f"/{slug}"
    return slug
  return None


def _resolve_href(href: object, *, base_url: str) -> str | None:
  if not isinstance(href, str):
    return None
  normalized = href.strip()
  if not normalized:
    return None
  if normalized.startswith(("http://", "https://")):
    return normalized
  if normalized.startswith(("/", "./", "../")):
    return normalized
  return None


def _section_title_from_key(key_hint: str) -> str:
  if key_hint in {"notes", "note", "target"}:
    return "Articles"
  if key_hint == "sections":
    return "Runtime Sections"
  normalized = re.sub(r"[_-]+", " ", key_hint).strip()
  if not normalized:
    return "Runtime Data"
  return normalized.title()


def _role_hint(key_hint: str | None, parent_hint: str | None) -> str | None:
  hints = " ".join(part for part in [key_hint or "", parent_hint or ""]).lower()
  if any(token in hints for token in ("nav", "menu", "category", "topic", "sidebar", "toc")):
    return "nav"
  return None


def _looks_like_section_item_list(key_hint: str, entries: list[object]) -> bool:
  lowered = key_hint.lower()
  if lowered in {"notes", "items", "target", "articles", "entries"}:
    return True
  return any(_looks_like_note_entry(entry) for entry in entries[:8] if isinstance(entry, dict))


def _looks_like_note_entry(entry: dict[object, object]) -> bool:
  note_type = _normalize_text(entry.get("type") or entry.get("__typename") or entry.get("kind") or "")
  key = _normalize_text(entry.get("key") or entry.get("noteKey") or "")
  has_label = bool(_label_for(entry))
  if has_label and key and re.fullmatch(r"n[a-z0-9]+", key, re.IGNORECASE):
    return True
  return has_label and "note" in note_type.lower()


def _normalize_text(value: object) -> str:
  normalized = re.sub(r"\s+", " ", str(value or "")).strip()
  if not normalized:
    return ""
  if len(normalized) > 240:
    return ""
  if re.fullmatch(r"[0-9a-f-]{24,}", normalized, re.IGNORECASE):
    return ""
  if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", normalized):
    return ""
  if any(token == normalized.lower() for token in ("true", "false", "null", "undefined", "default", "article")):
    return ""
  if re.match(r"^(rgba?|hsla?)\(", normalized, re.IGNORECASE):
    return ""
  if normalized.startswith("cubic-bezier("):
    return ""
  if re.match(r"^\d{2}:twcamp\^", normalized):
    return ""
  if re.search(r"[{};]", normalized):
    return ""
  return normalized


def _looks_like_embedded_html(key_hint: str | None, value: str) -> bool:
  if not value or "<" not in value or ">" not in value:
    return False
  lowered_key = (key_hint or "").strip().lower()
  if lowered_key in _EMBEDDED_HTML_KEYS:
    return True
  return bool(_HTML_FRAGMENT_RE.search(value))


def _extract_embedded_html_payload(
  html: str,
  *,
  base_url: str,
) -> tuple[str, list[tuple[str, str | None]], list[str], list[tuple[str, str]]]:
  document = parse_document(Resource(source=base_url, content=f"<html><body>{html}</body></html>"))
  body = document.body
  if body is None:
    return ("Embedded Content", [], [], [])
  heading = ""
  for tag in ("h1", "h2", "h3"):
    node = body.find_first(tag)
    if node is None:
      continue
    heading = _normalize_embedded_html_text(node.text_content())
    if heading:
      break
  if not heading:
    heading = "Embedded Content"
  items: list[tuple[str, str | None]] = []
  texts: list[str] = []
  links: list[tuple[str, str]] = []
  seen_items: set[tuple[str, str | None]] = set()
  for node, _ancestors in _iter_embedded_html_paths(body):
    if node.tag in {"script", "style", "template"}:
      continue
    if node.tag == "a":
      text = _normalize_embedded_html_text(node.text_content())
      href = _resolve_href(node.attrs.get("href"), base_url=base_url)
      if text and href:
        link_item = (text, href)
        if link_item not in links:
          links.append(link_item)
        if link_item not in seen_items and len(items) < _MAX_EMBEDDED_HTML_ITEMS:
          items.append(link_item)
          seen_items.add(link_item)
      continue
    if node.tag not in {"p", "li", "pre", "code", "blockquote"}:
      continue
    text = _normalize_embedded_html_text(node.text_content())
    if not text:
      continue
    texts.append(text)
    item = (text, None)
    if item in seen_items or len(items) >= _MAX_EMBEDDED_HTML_ITEMS:
      continue
    items.append(item)
    seen_items.add(item)
  paragraph_like_items = sum(1 for item_text, item_href in items if item_text and item_href is None)
  should_append_chunk_fallback = (
    sum(len(item_text) for item_text, _href in items) < 2400
    and paragraph_like_items < 2
  )
  if should_append_chunk_fallback:
    full_text = _normalize_embedded_html_block_text(body.text_content())
    if heading and full_text.startswith(heading):
      full_text = full_text[len(heading):].strip()
    for chunk in _chunk_embedded_html_text(full_text):
      texts.append(chunk)
      item = (chunk, None)
      if item in seen_items or len(items) >= _MAX_EMBEDDED_HTML_ITEMS:
        continue
      items.append(item)
      seen_items.add(item)
  return (heading, items, texts[:_MAX_TEXTS], links[:_MAX_ITEMS])


def _normalize_embedded_html_text(value: object) -> str:
  normalized = re.sub(r"\s+", " ", str(value or "")).strip()
  if not normalized:
    return ""
  if len(normalized) > 220:
    normalized = normalized[:217].rstrip() + "..."
  return normalized


def _normalize_embedded_html_block_text(value: object) -> str:
  return re.sub(r"\s+", " ", str(value or "")).strip()


def _chunk_embedded_html_text(text: str) -> list[str]:
  normalized = _normalize_embedded_html_block_text(text)
  if not normalized:
    return []
  chunks: list[str] = []
  start = 0
  max_chunk = 220
  min_chunk = 120
  while start < len(normalized) and len(chunks) < _MAX_EMBEDDED_HTML_ITEMS:
    remaining = normalized[start:]
    if len(remaining) <= max_chunk:
      chunks.append(remaining)
      break
    split_at = max(
      remaining.rfind(". ", 0, max_chunk),
      remaining.rfind("。", 0, max_chunk),
      remaining.rfind("! ", 0, max_chunk),
      remaining.rfind("? ", 0, max_chunk),
      remaining.rfind(" ", 0, max_chunk),
    )
    if split_at < min_chunk:
      split_at = max_chunk
    chunk = remaining[:split_at].strip()
    if chunk:
      chunks.append(chunk)
    start += split_at
  return chunks


def _iter_embedded_html_paths(
  root: ElementNode,
  ancestors: tuple[ElementNode, ...] = (),
):
  yield (root, ancestors)
  for child in root.children:
    if isinstance(child, ElementNode):
      yield from _iter_embedded_html_paths(child, ancestors + (root,))


def _contains_cjk(text: str) -> bool:
  return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text))


def _encoded_path(value: str) -> str:
  return "/".join(quote(part, safe="") for part in value.split("/") if part)


def _dedupe_texts(values: list[str]) -> list[str]:
  deduped: list[str] = []
  seen: set[str] = set()
  for value in values:
    if value in seen:
      continue
    seen.add(value)
    deduped.append(value)
  return deduped


def _dedupe_links(values: list[HydrationLink]) -> list[HydrationLink]:
  deduped: list[HydrationLink] = []
  seen: set[tuple[str, str]] = set()
  for value in values:
    key = (value.text, value.href)
    if key in seen:
      continue
    seen.add(key)
    deduped.append(value)
  return deduped


def _runtime_data_confidence(
  sections: list[HydrationSection],
  links: list[HydrationLink],
  texts: list[str],
  body_was_substantial: bool,
) -> str:
  if sections:
    return "high"
  if links and not body_was_substantial:
    return "medium"
  if texts and not body_was_substantial:
    return "low"
  return "none"


def _raw_node_text(node: ElementNode) -> str:
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      parts.append(child.text)
    elif isinstance(child, ElementNode):
      parts.append(_raw_node_text(child))
  return "".join(parts)
