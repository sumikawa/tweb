from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
import base64
import html
import hashlib
from email.message import Message
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock
import time
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from diskcache import Cache
import quickjs
import requests

from .api import TWebDocument, TWebElement
from .css import StyleContext, build_style_context
from .dom import DocumentNode, ElementNode, TextNode, _serialize_node
from .fetcher import (
  DEFAULT_HEADERS,
  Resource,
  _normalize_encoding_name,
  fetch_resource,
  resolve_resource_url,
  sanitize_url_for_log,
)
from .interactions import ButtonClickPolicy, ButtonClickResult, ButtonNetworkRequest
from .js_runtime_bridge import _bridge_source
from .js_runtime_helpers import (
  JavaScriptRuntimeError,
  _WEBPACK_JSONP_RE,
  _extract_nullish_string_receiver_method,
  _extract_webpack_jsonp_array_modules,
  _find_matching_js_pair_lenient,
  _normalize_js_exception,
  _patch_esm_exports,
  _patch_import_meta,
  _patch_js_module_stack_underflow,
  _rewrite_esm_to_classic,
  _rewrite_js_object_literal_methods,
  _safeguard_string_method_receivers,
  _split_top_level_js_items,
  _split_webpack_jsonp_array_modules,
)
from .parser import parse_fragment


LOGGER = logging.getLogger("tweb")
DEFAULT_JS_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
ASYNC_DRAIN_STABLE_TIMER_EARLY_STOP_STEPS = 32
ASYNC_DRAIN_MAX_WALL_TIME_MS = 5000
ASYNC_DRAIN_MAX_PENDING_JOBS = 64
ASYNC_DRAIN_MAX_MICROTASKS = 64
EXTERNAL_SCRIPT_PREFLIGHT_TIMEOUT_SECONDS = 3.0
PAGE_EVENT_TIME_LIMIT_SECONDS = 3.0
PREFLIGHT_MAX_PRIOR_SOURCES = 4
PREFLIGHT_MAX_PRIOR_SOURCE_CHARS = 128 * 1024
SUSPICIOUS_SCRIPT_MEMORY_LIMIT_BYTES = 8 * 1024 * 1024
SCRIPT_CACHE_DIR_ENV = "TWEB_SCRIPT_CACHE_DIR"
SCRIPT_CACHE_SUBDIR = "external_script_cache"
COMMON_SECOND_LEVEL_DOMAINS = {
  "ac",
  "co",
  "ed",
  "go",
  "lg",
  "ne",
  "or",
}

_CHARSET_RE = re.compile(r"charset\s*=\s*['\"]?\s*([a-z0-9._-]+)", re.IGNORECASE)
_HTML_META_CHARSET_RE = re.compile(
  rb"<meta[^>]+charset\s*=\s*['\"]?\s*([a-z0-9._-]+)",
  re.IGNORECASE,
)
_HTML_META_CONTENT_TYPE_CHARSET_RE = re.compile(
  rb"<meta[^>]+http-equiv\s*=\s*['\"]content-type['\"][^>]+content\s*=\s*['\"][^>]*charset\s*=\s*([a-z0-9._-]+)",
  re.IGNORECASE,
)


@dataclass
class RuntimeStats:
  timings_ms: dict[str, float] = field(default_factory=dict)
  counters: dict[str, int] = field(default_factory=dict)
  script_cache_enabled: bool = True

  def add_timing(self, name: str, started_at: float | None) -> None:
    elapsed_ms = _elapsed_ms_since(started_at)
    if elapsed_ms is None:
      return
    self.timings_ms[name] = self.timings_ms.get(name, 0.0) + elapsed_ms

  def increment(self, name: str, amount: int = 1) -> None:
    self.counters[name] = self.counters.get(name, 0) + amount

  def summary(self) -> dict[str, object]:
    return {
      "timings_ms": {
        key: round(value, 3)
        for key, value in sorted(self.timings_ms.items())
      },
      "counts": dict(sorted(self.counters.items())),
      "script_cache": {
        "enabled": self.script_cache_enabled,
        "hits": self.counters.get("script_cache_hits", 0),
        "misses": self.counters.get("script_cache_misses", 0),
        "revalidations": self.counters.get("script_cache_revalidations", 0),
        "bypasses": self.counters.get("script_cache_bypasses", 0),
        "entries": self.counters.get("script_cache_entries", 0),
      },
    }


@dataclass
class ScriptCacheEntry:
  resource: Resource
  variant_key: str
  vary_headers: tuple[str, ...]
  cached_at_monotonic: float
  cached_at_epoch_seconds: float | None = None
  etag: str | None = None
  last_modified: str | None = None
  max_age_seconds: int | None = None
  no_cache: bool = False
  no_store: bool = False


GLOBAL_EXTERNAL_SCRIPT_CACHE: dict[str, list[ScriptCacheEntry]] = {}
GLOBAL_EXTERNAL_SCRIPT_CACHE_LOCK = Lock()
GLOBAL_EXTERNAL_SCRIPT_CACHE_PERSISTENCE_LOCK = Lock()
GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE: Cache | None = None


def _should_load_external_script(document_source: str, script_source: str) -> bool:
  document_host = (urlparse(document_source).hostname or "").lower()
  script_host = (urlparse(script_source).hostname or "").lower()
  if not document_host or not script_host:
    return True
  return _site_key(document_host) == _site_key(script_host)


def _site_key(host: str) -> str:
  normalized = host.strip(".").lower()
  if not normalized:
    return normalized
  if normalized == "localhost":
    return normalized
  if ":" in normalized:
    return normalized
  parts = normalized.split(".")
  if len(parts) <= 2:
    return normalized
  if len(parts[-1]) == 2 and parts[-2] in COMMON_SECOND_LEVEL_DOMAINS and len(parts) >= 3:
    return ".".join(parts[-3:])
  return ".".join(parts[-2:])


def _iter_runtime_document_elements(document: DocumentNode):
  for child in document.children:
    if not isinstance(child, ElementNode):
      continue
    yield child
    yield from _iter_runtime_descendant_elements(child)


def _iter_runtime_descendant_elements(node: ElementNode):
  for child in node.children:
    if not isinstance(child, ElementNode):
      continue
    yield child
    yield from _iter_runtime_descendant_elements(child)


def _matches_runtime_tag_name(element: ElementNode, tag_name: str) -> bool:
  normalized = str(tag_name or "").strip().lower()
  if not normalized:
    return False
  if normalized == "*":
    return not element.tag.startswith("#")
  return element.tag.lower() == normalized


def _matches_runtime_class_names(element: ElementNode, class_names: str) -> bool:
  requested = [token for token in str(class_names or "").strip().split() if token]
  if not requested:
    return False
  existing = set(element.attrs.get("class", "").split())
  return all(token in existing for token in requested)


def _extract_declared_charset(value: str | None) -> str | None:
  if not value:
    return None
  match = _CHARSET_RE.search(value)
  if match is None:
    return None
  return _normalize_encoding_name(match.group(1).strip().lower() or None)


def _sniff_html_charset(content: bytes) -> str | None:
  head = content[:4096]
  match = _HTML_META_CHARSET_RE.search(head)
  if match is None:
    match = _HTML_META_CONTENT_TYPE_CHARSET_RE.search(head)
  if match is None:
    return None
  try:
    return _normalize_encoding_name(
      match.group(1).decode("ascii", "ignore").strip().lower() or None
    )
  except Exception:
    return None


def _decode_http_response_text(response: requests.Response, content: bytes) -> str:
  content_type = str(response.headers.get("Content-Type", ""))
  return _decode_http_response_text_with_content_type(response, content, content_type=content_type)


def _decode_http_response_text_with_content_type(
  response: requests.Response,
  content: bytes,
  *,
  content_type: str,
) -> str:
  charset = _extract_declared_charset(content_type)
  if charset is None and "html" in content_type.lower():
    charset = _sniff_html_charset(content)
  if charset:
    try:
      return content.decode(charset, errors="replace")
    except LookupError:
      pass
  apparent_encoding = getattr(response, "apparent_encoding", None)
  if apparent_encoding:
    try:
      normalized = _normalize_encoding_name(str(apparent_encoding))
      if normalized:
        return content.decode(normalized, errors="replace")
    except LookupError:
      pass
  try:
    return content.decode("utf-8", errors="replace")
  except Exception:
    return response.text


def _safe_perf_counter() -> float | None:
  try:
    return time.perf_counter()
  except BaseException:
    try:
      return time.monotonic()
    except BaseException:
      return None


def _elapsed_ms_since(started_at: float | None) -> float | None:
  if started_at is None:
    return None
  now = _safe_perf_counter()
  if now is None:
    return None
  return max(0.0, (now - started_at) * 1000.0)


def _collect_raw_node_text(node: ElementNode) -> str:
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      parts.append(child.text)
    elif isinstance(child, ElementNode):
      parts.append(_collect_raw_node_text(child))
  return "".join(parts)


def _trim_preflight_prior_sources(prior_sources: list[str] | None) -> list[str]:
  if not prior_sources:
    return []
  selected: list[str] = []
  total_chars = 0
  for source in reversed(prior_sources):
    compact = source.strip()
    if not compact:
      continue
    if len(selected) >= PREFLIGHT_MAX_PRIOR_SOURCES:
      break
    if selected and total_chars + len(compact) > PREFLIGHT_MAX_PRIOR_SOURCE_CHARS:
      break
    selected.append(source)
    total_chars += len(compact)
  selected.reverse()
  return selected


def _script_cache_dir() -> Path:
  override = os.environ.get(SCRIPT_CACHE_DIR_ENV, "").strip()
  if override:
    return Path(override).expanduser()
  xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
  if xdg_cache_home:
    return Path(xdg_cache_home).expanduser() / "tweb"
  if sys.platform == "darwin":
    return Path.home() / "Library" / "Caches" / "tweb"
  return Path.home() / ".cache" / "tweb"


def _script_cache_path() -> Path:
  return _script_cache_dir() / SCRIPT_CACHE_SUBDIR


def _is_global_external_script_cache(external_script_cache: object) -> bool:
  return external_script_cache is GLOBAL_EXTERNAL_SCRIPT_CACHE


def _cache_entry_age_seconds(entry: ScriptCacheEntry) -> float:
  if entry.cached_at_epoch_seconds is not None:
    return max(0.0, time.time() - entry.cached_at_epoch_seconds)
  return max(0.0, time.monotonic() - entry.cached_at_monotonic)


def _serialize_script_cache_entry(entry: ScriptCacheEntry) -> dict[str, object]:
  return {
    "source": entry.resource.source,
    "content": entry.resource.content,
    "headers": entry.resource.headers or {},
    "status_code": entry.resource.status_code,
    "variant_key": entry.variant_key,
    "vary_headers": list(entry.vary_headers),
    "cached_at_epoch_seconds": entry.cached_at_epoch_seconds,
    "etag": entry.etag,
    "last_modified": entry.last_modified,
    "max_age_seconds": entry.max_age_seconds,
    "no_cache": entry.no_cache,
    "no_store": entry.no_store,
  }


def _deserialize_script_cache_entry(payload: object) -> ScriptCacheEntry | None:
  if not isinstance(payload, dict):
    return None
  source = payload.get("source")
  content = payload.get("content")
  variant_key = payload.get("variant_key")
  vary_headers = payload.get("vary_headers")
  if not isinstance(source, str) or not isinstance(content, str) or not isinstance(variant_key, str):
    return None
  if not isinstance(vary_headers, list) or not all(isinstance(item, str) for item in vary_headers):
    return None
  headers = payload.get("headers")
  if not isinstance(headers, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items()):
    headers = {}
  cached_at_epoch_seconds = payload.get("cached_at_epoch_seconds")
  if not isinstance(cached_at_epoch_seconds, (int, float)):
    cached_at_epoch_seconds = None
  entry = ScriptCacheEntry(
    resource=Resource(
      source=source,
      content=content,
      headers=headers,
      status_code=payload.get("status_code") if isinstance(payload.get("status_code"), int) else None,
    ),
    variant_key=variant_key,
    vary_headers=tuple(vary_headers),
    cached_at_monotonic=time.monotonic(),
    cached_at_epoch_seconds=float(cached_at_epoch_seconds) if cached_at_epoch_seconds is not None else None,
    etag=payload.get("etag") if isinstance(payload.get("etag"), str) else None,
    last_modified=payload.get("last_modified") if isinstance(payload.get("last_modified"), str) else None,
    max_age_seconds=payload.get("max_age_seconds") if isinstance(payload.get("max_age_seconds"), int) else None,
    no_cache=bool(payload.get("no_cache")),
    no_store=bool(payload.get("no_store")),
  )
  return entry


def _global_external_script_cache_store() -> Cache | None:
  global GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE
  if GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE is not None:
    return GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE
  try:
    cache_path = _script_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE = Cache(str(cache_path))
  except Exception as exc:
    LOGGER.debug("persistent script cache open failed path=%s error=%s", _script_cache_path(), exc)
    GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE = None
  return GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE


def _load_persistent_external_script_cache_entries(target: str) -> list[ScriptCacheEntry]:
  store = _global_external_script_cache_store()
  if store is None:
    return []
  try:
    payload = store.get(target, default=None)
  except Exception as exc:
    LOGGER.debug("persistent script cache read failed target=%s error=%s", target, exc)
    return []
  if not isinstance(payload, list):
    return []
  return [
    entry
    for entry in (_deserialize_script_cache_entry(item) for item in payload)
    if entry is not None and not entry.no_store
  ]


def _persist_global_external_script_cache_target(target: str) -> None:
  store = _global_external_script_cache_store()
  if store is None:
    return
  with GLOBAL_EXTERNAL_SCRIPT_CACHE_LOCK:
    entries = [
      _serialize_script_cache_entry(entry)
      for entry in GLOBAL_EXTERNAL_SCRIPT_CACHE.get(target, [])
      if not entry.no_store
    ]
  try:
    if entries:
      store[target] = entries
    else:
      store.pop(target, None)
  except Exception as exc:
    LOGGER.debug("persistent script cache write failed target=%s error=%s", target, exc)


def _reset_external_script_cache_state_for_tests() -> None:
  global GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE
  with GLOBAL_EXTERNAL_SCRIPT_CACHE_LOCK:
    GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
  with GLOBAL_EXTERNAL_SCRIPT_CACHE_PERSISTENCE_LOCK:
    if GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE is not None:
      GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE.close()
    GLOBAL_EXTERNAL_SCRIPT_CACHE_STORE = None


@dataclass
class QuickJSRuntime:
  """Minimal quick.js bridge for DOM querying and mutation."""

  document: DocumentNode
  session: object | None = None
  enable_script_cache: bool = True
  external_script_cache: dict[tuple[str, str], ScriptCacheEntry] | None = None
  trusted_script_sources: set[str] | None = None

  def __post_init__(self) -> None:
    self.trusted_script_sources = set(self.trusted_script_sources or ())
    if self.external_script_cache is None:
      self.external_script_cache = GLOBAL_EXTERNAL_SCRIPT_CACHE if self.enable_script_cache else {}
    self._stats = RuntimeStats(script_cache_enabled=self.enable_script_cache)
    self._script_cache_lock = (
      GLOBAL_EXTERNAL_SCRIPT_CACHE_LOCK
      if _is_global_external_script_cache(self.external_script_cache)
      else Lock()
    )
    self._stats_lock = Lock()
    self._preflight_cache_lock = Lock()
    self._preflight_cache: dict[tuple[str, tuple[str, ...]], bool] = {}
    self._ctx = quickjs.Context()
    self._initialize_context()

  def script_source_allowed(self, target: str) -> bool:
    resolved_target = resolve_resource_url(self.document.source, target)
    return (
      resolved_target in self.trusted_script_sources
      or _should_load_external_script(self.document.source, resolved_target)
    )

  def _initialize_context(self) -> None:
    self._ctx = quickjs.Context()
    self._ctx.set_max_stack_size(8 * 1024 * 1024)
    self._ctx.set_memory_limit(DEFAULT_JS_MEMORY_LIMIT_BYTES)
    self._node_ids = {}
    self._text_node_ids = {}
    self._node_identity_ids: dict[int, str] = {}
    self._text_node_identity_ids: dict[int, str] = {}
    self._next_node_index = 0
    self._current_script_info = None
    self._pending_async_error_message = None
    self._allow_navigation_requests = True
    self._allow_network_requests = True
    self._navigation_requests = []
    self.reload_target = None
    self._document_cookie_assignments: list[str] = []
    self._network_requests = []
    self._style_context_cache = None
    self._selector_query_cache: dict[tuple[str, str, str, int], tuple[str, ...]] = {}
    self._dom_lookup_cache: dict[tuple[str, str, str, int], tuple[str, ...]] = {}
    self._runtime_data_network_payloads = []
    self._parser_inserted_script_errors: list[dict[str, str]] = []
    self._loaded_module_urls: set[str] = set()
    self._loading_module_urls: set[str] = set()
    self._dom_mutation_count = 0
    self._selector_cache_epoch = 0
    self._sync_document_parent_references()
    self._install_bridge()
    self._seed_session_cookies()

  def _seed_session_cookies(self) -> None:
    if self.session is None or not hasattr(self.session, "cookies"):
      return
    hostname = urlparse(self.document.source).hostname or ""
    if not hostname:
      return
    cookie_header_parts: list[str] = []
    for cookie in self.session.cookies:
      domain = (cookie.domain or "").lstrip(".")
      if domain and hostname != domain and not hostname.endswith(f".{domain}"):
        continue
      cookie_header_parts.append(f"{cookie.name}={cookie.value}")
    for part in cookie_header_parts:
      try:
        self._ctx.eval(f"__twebSetCookie({json.dumps(part)});")
      except quickjs.JSException as exc:
        raise _normalize_js_exception(exc) from exc

  def eval(
    self,
    source: str,
    source_url: str | None = None,
    *,
    drain_timers: bool = True,
  ):
    started_at = _safe_perf_counter()
    self._stats.increment("eval_calls")
    if source_url is not None:
      source = _safeguard_string_method_receivers(source, {"charAt", "toLowerCase"})
      if "import.meta" in source:
        source = _patch_import_meta(source, source_url=source_url)
    self._current_script_info = None if source_url is None else {"src": source_url}
    try:
      self._sync_named_window_properties()
      result = self._ctx.eval(source)
      self._sync_named_window_properties()
      self._ctx.eval("__twebInstallJQueryLegacyShims();")
      self._drain_pending_jobs()
      if drain_timers:
        self._drain_async_work()
    except quickjs.JSException as exc:
      if self._retry_html_entity_script_source(
        source,
        source_url=source_url,
        drain_timers=drain_timers,
        error=exc,
      ):
        result = None
        self.document.sync_title()
        return result
      if source_url is not None and "unsupported keyword: export" in str(exc):
        patched_source = _patch_esm_exports(source)
        if patched_source != source:
          try:
            self._sync_named_window_properties()
            result = self._ctx.eval(patched_source)
            self._sync_named_window_properties()
            self._ctx.eval("__twebInstallJQueryLegacyShims();")
            self._drain_pending_jobs()
            if drain_timers:
              self._drain_async_work()
          except quickjs.JSException:
            pass
          else:
            self.document.sync_title()
            return result
      if self._eval_with_fallback(source, source_url=source_url, drain_timers=drain_timers, error=exc):
        result = None
      else:
        message = self._take_async_error_message()
        if message is not None:
          raise JavaScriptRuntimeError(message) from exc
        raise self._normalize_context_exception(exc) from exc
    finally:
      self._current_script_info = None
      self._stats.add_timing("script_eval", started_at)
    self.document.sync_title()
    return result

  def _retry_html_entity_script_source(
    self,
    source: str,
    *,
    source_url: str | None,
    drain_timers: bool,
    error: quickjs.JSException,
  ) -> bool:
    message = str(error)
    if "&" not in message or "SyntaxError" not in message:
      return False
    if "&" not in source:
      return False
    decoded_source = html.unescape(source)
    if decoded_source == source:
      return False
    self._initialize_context()
    self._current_script_info = None if source_url is None else {"src": source_url}
    self._sync_named_window_properties()
    result = self._ctx.eval(decoded_source)
    self._sync_named_window_properties()
    self._ctx.eval("__twebInstallJQueryLegacyShims();")
    self._drain_pending_jobs()
    if drain_timers:
      self._drain_async_work()
    return result is None or True

  def _sync_named_window_properties(self) -> None:
    started_at = _safe_perf_counter()
    try:
      synced = bool(self._ctx.eval("__twebSyncNamedWindowProperties();"))
      self._stats.increment("named_window_property_sync_calls")
      if synced:
        self._stats.increment("named_window_property_sync_runs")
      else:
        self._stats.increment("named_window_property_sync_skips")
    except quickjs.JSException as exc:
      self._stats.increment("named_window_property_sync_calls")
      self._stats.increment("named_window_property_sync_failures")
      LOGGER.debug(
        "named window property sync failed source=%s error=%s",
        self.document.source,
        exc,
      )
    finally:
      self._stats.add_timing("named_window_property_sync", started_at)

  def _normalize_context_exception(self, exc: quickjs.JSException) -> JavaScriptRuntimeError:
    normalized = _normalize_js_exception(exc)
    if str(exc).strip() != "null":
      return normalized
    context_bits: list[str] = []
    current_src = None
    if isinstance(self._current_script_info, dict):
      src = self._current_script_info.get("src")
      if isinstance(src, str) and src:
        current_src = src
        context_bits.append(f"script={src}")
    try:
      memory = self._ctx.memory()
      malloc_size = int(memory.get("malloc_size", 0) or 0)
      malloc_limit = int(memory.get("malloc_limit", 0) or 0)
    except (AttributeError, TypeError, ValueError):
      if context_bits:
        return JavaScriptRuntimeError(f"{normalized} ({', '.join(context_bits)})")
      return normalized
    if malloc_limit > 0 and malloc_size >= int(malloc_limit * 0.95):
      if current_src is not None:
        return JavaScriptRuntimeError(
          f"JavaScript memory limit exceeded (script={current_src}, malloc_size={malloc_size}, malloc_limit={malloc_limit})"
        )
      return JavaScriptRuntimeError(
        f"JavaScript memory limit exceeded (malloc_size={malloc_size}, malloc_limit={malloc_limit})"
      )
    context_bits.append(f"malloc_size={malloc_size}")
    if malloc_limit > 0:
      context_bits.append(f"malloc_limit={malloc_limit}")
    if context_bits:
      return JavaScriptRuntimeError(f"{normalized} ({', '.join(context_bits)})")
    return normalized

  def dispatch_page_events(
    self,
    *,
    time_limit_seconds: float | None = None,
    continue_on_event_callback_error: bool = False,
  ) -> None:
    started_at = _safe_perf_counter()
    try:
      with self._temporary_time_limit(time_limit_seconds):
        lifecycle_interest = self.lifecycle_event_interest()
        self._dispatch_dom_content_loaded(
          lifecycle_interest=lifecycle_interest,
          continue_on_event_callback_error=continue_on_event_callback_error,
        )
        if not any(
          lifecycle_interest.get(key, False)
          for key in ("document_load", "window_load", "pageshow", "readystatechange")
        ):
          self.eval("__twebDocumentReadyState = 'complete';", drain_timers=False)
          if continue_on_event_callback_error:
            self._log_suppressed_event_callback_errors()
          return
        if continue_on_event_callback_error:
          self.eval(
            """
            __twebDocumentReadyState = 'complete';
            if (__twebTargetHasEventInterest(document, 'readystatechange')) {
              __twebDispatchEventOnTargetIgnoreCallbackErrors(document, new Event('readystatechange'));
            }
            __twebDispatchReadyEventIgnoreCallbackErrors('load');
            if (__twebTargetHasEventInterest(window, 'pageshow')) {
              __twebDispatchEventOnTargetIgnoreCallbackErrors(window, new Event('pageshow'));
            }
            """,
            drain_timers=False,
          )
        else:
          self.eval(
            """
            __twebDocumentReadyState = 'complete';
            if (__twebTargetHasEventInterest(document, 'readystatechange')) {
              __twebDispatchEventOnTarget(document, new Event('readystatechange'));
            }
            __twebDispatchReadyEvent('load');
            if (__twebTargetHasEventInterest(window, 'pageshow')) {
              __twebDispatchEventOnTarget(window, new Event('pageshow'));
            }
            """,
            drain_timers=False,
          )
        self._drain_async_work(
          limit=100,
          max_timer_steps=0,
          max_pending_job_steps=ASYNC_DRAIN_MAX_PENDING_JOBS,
          max_microtask_steps=ASYNC_DRAIN_MAX_MICROTASKS,
          max_wall_time_ms=ASYNC_DRAIN_MAX_WALL_TIME_MS,
        )
        if continue_on_event_callback_error:
          self._log_suppressed_event_callback_errors()
    except quickjs.JSException as exc:
      message = self._take_async_error_message()
      if message is not None:
        raise JavaScriptRuntimeError(message) from exc
      raise self._normalize_context_exception(exc) from exc
    finally:
      self._stats.add_timing("page_event_dispatch", started_at)
    self.document.sync_title()

  def dispatch_dom_content_loaded(
    self,
    *,
    time_limit_seconds: float | None = None,
    continue_on_event_callback_error: bool = False,
  ) -> None:
    started_at = _safe_perf_counter()
    try:
      with self._temporary_time_limit(time_limit_seconds):
        self._dispatch_dom_content_loaded(
          lifecycle_interest=self.lifecycle_event_interest(),
          continue_on_event_callback_error=continue_on_event_callback_error,
        )
        if continue_on_event_callback_error:
          self._log_suppressed_event_callback_errors()
    except quickjs.JSException as exc:
      message = self._take_async_error_message()
      if message is not None:
        raise JavaScriptRuntimeError(message) from exc
      raise self._normalize_context_exception(exc) from exc
    finally:
      self._stats.add_timing("dom_content_loaded_dispatch", started_at)
    self.document.sync_title()

  def lifecycle_event_interest(self) -> dict[str, bool]:
    try:
      payload = self._ctx.eval(
        """
        JSON.stringify({
          dom_content_loaded: __twebTargetHasEventInterest(document, 'DOMContentLoaded'),
          document_load: __twebTargetHasEventInterest(document, 'load'),
          window_load: __twebTargetHasEventInterest(window, 'load'),
          pageshow: __twebTargetHasEventInterest(window, 'pageshow'),
          readystatechange: __twebTargetHasEventInterest(document, 'readystatechange')
        });
        """
      )
    except quickjs.JSException as exc:
      raise self._normalize_context_exception(exc) from exc
    if not isinstance(payload, str):
      return {}
    try:
      parsed = json.loads(payload)
    except (TypeError, ValueError):
      return {}
    if not isinstance(parsed, dict):
      return {}
    summary: dict[str, bool] = {}
    for key, value in parsed.items():
      if isinstance(key, str):
        summary[key] = bool(value)
    return summary

  def _dispatch_dom_content_loaded(
    self,
    *,
    lifecycle_interest: dict[str, bool] | None = None,
    continue_on_event_callback_error: bool = False,
  ) -> None:
    if lifecycle_interest is None:
      lifecycle_interest = self.lifecycle_event_interest()
    if not (
      lifecycle_interest.get("dom_content_loaded", False)
      or lifecycle_interest.get("readystatechange", False)
    ):
      self.eval("__twebDocumentReadyState = 'interactive';", drain_timers=False)
      return
    if continue_on_event_callback_error:
      self.eval(
        """
        __twebDocumentReadyState = 'interactive';
        if (__twebTargetHasEventInterest(document, 'readystatechange')) {
          __twebDispatchEventOnTargetIgnoreCallbackErrors(document, new Event('readystatechange'));
        }
        if (__twebTargetHasEventInterest(document, 'DOMContentLoaded')) {
          __twebDispatchEventOnTargetIgnoreCallbackErrors(document, new Event('DOMContentLoaded'));
        }
        if (__twebTargetHasEventInterest(window, 'DOMContentLoaded')) {
          __twebDispatchEventOnTargetIgnoreCallbackErrors(window, new Event('DOMContentLoaded'));
        }
        """,
        drain_timers=False,
      )
    else:
      self.eval(
        """
        __twebDocumentReadyState = 'interactive';
        if (__twebTargetHasEventInterest(document, 'readystatechange')) {
          __twebDispatchEventOnTarget(document, new Event('readystatechange'));
        }
        __twebDispatchReadyEvent('DOMContentLoaded');
        """,
        drain_timers=False,
      )
    self._drain_async_work(
      max_time_advance_ms=50,
      max_pending_job_steps=ASYNC_DRAIN_MAX_PENDING_JOBS,
      max_microtask_steps=ASYNC_DRAIN_MAX_MICROTASKS,
      max_wall_time_ms=ASYNC_DRAIN_MAX_WALL_TIME_MS,
    )

  def _take_suppressed_event_callback_errors(self) -> tuple[str, ...]:
    try:
      payload = self._ctx.eval(
        """
        (() => {
          const errors = Array.isArray(window.__twebSuppressedEventCallbackErrors)
            ? window.__twebSuppressedEventCallbackErrors.slice()
            : [];
          window.__twebSuppressedEventCallbackErrors = [];
          window.__twebLastAsyncError = null;
          window.__twebLastAsyncCallbackLabel = '';
          return JSON.stringify(errors);
        })()
        """
      )
    except (quickjs.JSException, SystemError):
      return ()
    if not isinstance(payload, str):
      return ()
    try:
      parsed = json.loads(payload)
    except (TypeError, ValueError):
      return ()
    if not isinstance(parsed, list):
      return ()
    return tuple(str(item) for item in parsed if isinstance(item, str))

  def _log_suppressed_event_callback_errors(self) -> None:
    errors = self._take_suppressed_event_callback_errors()
    if not errors:
      return
    self._stats.increment("ignored_event_callback_errors", len(errors))
    LOGGER.debug(
      "suppressed lifecycle callback errors count=%d first=%s",
      len(errors),
      errors[0],
    )

  @contextmanager
  def _temporary_time_limit(self, seconds: float | None):
    if seconds is None:
      yield
      return
    self._ctx.set_time_limit(seconds)
    try:
      yield
    finally:
      self._ctx.set_time_limit(-1)

  @contextmanager
  def temporary_memory_limit(self, limit_bytes: int | None):
    if limit_bytes is None:
      yield
      return
    try:
      current_limit = int(self._ctx.memory().get("malloc_limit", 0) or 0)
    except (AttributeError, TypeError, ValueError):
      current_limit = DEFAULT_JS_MEMORY_LIMIT_BYTES
    self._ctx.set_memory_limit(limit_bytes)
    try:
      yield
    finally:
      self._ctx.set_memory_limit(current_limit if current_limit > 0 else DEFAULT_JS_MEMORY_LIMIT_BYTES)

  def performance_summary(self) -> dict[str, object]:
    self._stats.counters["script_cache_entries"] = sum(
      len(entries)
      for entries in (self.external_script_cache or {}).values()
    )
    summary = self._stats.summary()
    summary["parser_inserted_script_errors"] = list(self._parser_inserted_script_errors)
    return summary

  def has_pending_timer(self, *, max_time_advance_ms: int | None = None) -> bool:
    max_due_time_expr = "null"
    if max_time_advance_ms is not None:
      try:
        current_time = int(self._ctx.eval("__twebGetCurrentTime();"))
      except quickjs.JSException as exc:
        raise _normalize_js_exception(exc) from exc
      max_due_time_expr = str(current_time + max(0, max_time_advance_ms))
    try:
      return bool(self._ctx.eval(f"__twebHasPendingTimer({max_due_time_expr});"))
    except quickjs.JSException as exc:
      raise _normalize_js_exception(exc) from exc

  def next_pending_timer_delay_ms(self) -> int | None:
    try:
      value = self._ctx.eval("__twebGetNextTimerDelay();")
    except quickjs.JSException as exc:
      raise _normalize_js_exception(exc) from exc
    if value is None:
      return None
    return max(0, int(value))

  def drain_post_load_async_work(
    self,
    *,
    max_time_advance_ms: int = 250,
    max_timer_steps: int | None = None,
  ) -> None:
    self._drain_async_work(
      limit=200,
      max_time_advance_ms=max_time_advance_ms,
      max_timer_steps=max_timer_steps,
      max_pending_job_steps=ASYNC_DRAIN_MAX_PENDING_JOBS,
      max_microtask_steps=ASYNC_DRAIN_MAX_MICROTASKS,
      max_wall_time_ms=ASYNC_DRAIN_MAX_WALL_TIME_MS,
    )

  def click_element(
    self,
    node: ElementNode,
    *,
    policy: ButtonClickPolicy = "dom-only",
    max_time_advance_ms: int | None = None,
    max_timer_steps: int | None = None,
    tolerate_async_errors_after_dom_update: bool = False,
  ) -> ButtonClickResult:
    if policy == "off":
      return ButtonClickResult(
        clicked=False,
        dom_changed=False,
        policy=policy,
        blocked_by_policy=True,
      )
    node_id = self._ensure_node_id(node)
    before_snapshot = self._document_snapshot()
    self._navigation_requests = []
    self._network_requests = []
    self._allow_navigation_requests = policy == "network"
    self._allow_network_requests = policy == "network"
    LOGGER.debug(
      "click element start source=%s node=%s policy=%s max_time_advance_ms=%s max_timer_steps=%s tolerate_async_errors_after_dom_update=%s",
      sanitize_url_for_log(self.document.source),
      self._node_debug_summary(node),
      policy,
      max_time_advance_ms,
      max_timer_steps,
      tolerate_async_errors_after_dom_update,
    )
    try:
      payload = self._ctx.eval(
        f"""
        (() => {{
          const target = __twebWrapNode({json.dumps(node_id)});
          if (!target || typeof target.click !== 'function') {{
            return JSON.stringify({{ clicked: false, defaultPrevented: false }});
          }}
          return JSON.stringify({{
            clicked: true,
            defaultPrevented: target.click() === false,
          }});
        }})()
        """
      )
      clicked = False
      if isinstance(payload, str):
        try:
          click_result = json.loads(payload)
        except (TypeError, ValueError):
          click_result = None
        if isinstance(click_result, dict):
          clicked = bool(click_result.get("clicked"))
      self._drain_pending_jobs()
      try:
        self._drain_async_work(
          max_time_advance_ms=max_time_advance_ms,
          max_timer_steps=max_timer_steps,
        )
      except JavaScriptRuntimeError as exc:
        LOGGER.debug(
          "click element async drain failed source=%s node=%s policy=%s error=%s navigation_requests=%s network_requests=%s dom_changed=%s",
          sanitize_url_for_log(self.document.source),
          self._node_debug_summary(node),
          policy,
          exc,
          [sanitize_url_for_log(item) for item in self._navigation_requests],
          [request.__dict__ for request in self._network_requests],
          before_snapshot != self._document_snapshot(),
        )
        if not tolerate_async_errors_after_dom_update or before_snapshot == self._document_snapshot():
          raise
    except quickjs.JSException as exc:
      raise _normalize_js_exception(exc) from exc
    finally:
      self._allow_navigation_requests = True
      self._allow_network_requests = True
    self.document.sync_title()
    dom_changed = before_snapshot != self._document_snapshot()
    blocked_by_policy = any(request.blocked for request in self._network_requests)
    if self._navigation_requests and policy != "network":
      blocked_by_policy = True
    LOGGER.debug(
      "click element complete source=%s node=%s clicked=%s dom_changed=%s blocked_by_policy=%s navigation_target=%s network_requests=%s",
      sanitize_url_for_log(self.document.source),
      self._node_debug_summary(node),
      clicked,
      dom_changed,
      blocked_by_policy,
      sanitize_url_for_log(self._navigation_requests[-1]) if self._navigation_requests else None,
      [request.__dict__ for request in self._network_requests],
    )
    return ButtonClickResult(
      clicked=clicked,
      dom_changed=dom_changed,
      policy=policy,
      navigation_target=self._navigation_requests[-1] if self._navigation_requests else None,
      network_requests=tuple(self._network_requests),
      blocked_by_policy=blocked_by_policy,
    )

  def _install_bridge(self) -> None:
    self._ctx.add_callable("__twebGetDocumentTitle", self._get_document_title)
    self._ctx.add_callable("__twebGetDocumentDoctype", self._get_document_doctype)
    self._ctx.add_callable("__twebSetDocumentTitle", self._set_document_title)
    self._ctx.add_callable("__twebGetDocumentNode", self._get_document_node)
    self._ctx.add_callable("__twebCreateElement", self._create_element)
    self._ctx.add_callable("__twebCreateTextNode", self._create_text_node)
    self._ctx.add_callable("__twebCreateComment", self._create_comment)
    self._ctx.add_callable("__twebCreateDocumentFragment", self._create_document_fragment)
    self._ctx.add_callable("__twebParseXmlDocument", self._parse_xml_document)
    self._ctx.add_callable("__twebQueryOne", self._query_one)
    self._ctx.add_callable("__twebQueryAll", self._query_all)
    self._ctx.add_callable("__twebGetElementById", self._get_element_by_id)
    self._ctx.add_callable("__twebGetElementsByName", self._get_elements_by_name)
    self._ctx.add_callable("__twebGetElementsByClassName", self._get_elements_by_class_name)
    self._ctx.add_callable("__twebGetElementsByTagName", self._get_elements_by_tag_name)
    self._ctx.add_callable("__twebNodeQueryOne", self._node_query_one)
    self._ctx.add_callable("__twebNodeQueryAll", self._node_query_all)
    self._ctx.add_callable("__twebNodeGetElementsByClassName", self._node_get_elements_by_class_name)
    self._ctx.add_callable("__twebNodeGetElementsByTagName", self._node_get_elements_by_tag_name)
    self._ctx.add_callable("__twebGetNodeTagName", self._get_node_tag_name)
    self._ctx.add_callable("__twebGetTextContent", self._get_text_content)
    self._ctx.add_callable("__twebSetTextContent", self._set_text_content)
    self._ctx.add_callable("__twebGetInnerHTML", self._get_inner_html)
    self._ctx.add_callable("__twebGetOuterHTML", self._get_outer_html)
    self._ctx.add_callable("__twebSetInnerHTML", self._set_inner_html)
    self._ctx.add_callable("__twebGetAttribute", self._get_attribute)
    self._ctx.add_callable("__twebGetAttributes", self._get_attributes_json)
    self._ctx.add_callable("__twebSetAttribute", self._set_attribute)
    self._ctx.add_callable("__twebRemoveAttribute", self._remove_attribute)
    self._ctx.add_callable("__twebAppendChild", self._append_child)
    self._ctx.add_callable("__twebInsertBefore", self._insert_before)
    self._ctx.add_callable("__twebRemoveNode", self._remove_node)
    self._ctx.add_callable("__twebGetParentNode", self._get_parent_node)
    self._ctx.add_callable("__twebGetChildNodes", self._get_child_nodes)
    self._ctx.add_callable("__twebCloneNode", self._clone_node)
    self._ctx.add_callable("__twebGetLocation", self._get_location_json)
    self._ctx.add_callable("__twebResolveUrl", self._resolve_url)
    self._ctx.add_callable("__twebGetCurrentScriptInfo", self._get_current_script_info_json)
    self._ctx.add_callable("__twebGetComputedStyle", self._get_computed_style_json)
    self._ctx.add_callable("__twebConsoleLog", self._console_log)
    self._ctx.add_callable("__twebCryptoDigest", self._crypto_digest)
    self._ctx.add_callable("__twebRequestReload", self._request_reload)
    self._ctx.add_callable("__twebPersistCookie", self._persist_cookie)
    self._ctx.add_callable("__twebAllowNavigation", self._allow_navigation)
    self._ctx.add_callable("__twebRecordNavigationAttempt", self._record_navigation_attempt)
    self._ctx.add_callable("__twebDocumentAppendChild", self._document_append_child)
    self._ctx.add_callable("__twebDocumentInsertBefore", self._document_insert_before)
    self._ctx.add_callable("__twebDocumentRemoveChild", self._document_remove_child)
    self._ctx.add_callable("__twebDocumentCloneNode", self._document_clone_node)
    self._ctx.add_callable("__twebDocumentContains", self._document_contains)
    self._ctx.add_callable("__twebHttpRequest", self._http_request)
    self._ctx.add_callable("__twebLoadModuleByUrl", self._load_module_by_url)
    self._ctx.add_callable("__twebLoadExternalScript", self._load_external_script)
    self._ctx.add_callable("__twebLoadExternalScriptSource", self._load_external_script_source)
    self._ctx.add_callable("__twebParserInsertedScriptPreflightSafe", self._parser_inserted_script_preflight_safe)
    self._ctx.add_callable("__twebRecordParserInsertedScriptError", self._record_parser_inserted_script_error)
    self._ctx.eval(_bridge_source())
    self._ctx.eval(
      """
      window.__twebModules = window.__twebModules || Object.create(null);
      self.__twebModules = window.__twebModules;
      function __twebDynamicImport(url) {
        __twebLoadModuleByUrl(url);
        return Promise.resolve(window.__twebModules[url] || Object.create(null));
      }
      window.__twebDynamicImport = __twebDynamicImport;
      self.__twebDynamicImport = __twebDynamicImport;
      """
    )

  def _retry_nullish_string_receivers(
    self,
    source: str,
    *,
    source_url: str | None,
    drain_timers: bool,
    error: quickjs.JSException,
  ) -> bool:
    current_error = error
    guarded_methods: set[str] = set()
    while True:
      method = _extract_nullish_string_receiver_method(str(current_error))
      if method is None or method in guarded_methods:
        return False
      guarded_methods.add(method)
      guarded_source = _safeguard_string_method_receivers(source, guarded_methods)
      if guarded_source == source:
        return False
      try:
        self._ctx.eval(guarded_source)
        self._drain_pending_jobs()
        if drain_timers:
          self._drain_async_work()
        return True
      except quickjs.JSException as retry_error:
        current_error = retry_error
        self._initialize_context()
        self._current_script_info = None if source_url is None else {"src": source_url}
        try:
          self._ctx.eval(guarded_source)
          self._drain_pending_jobs()
          if drain_timers:
            self._drain_async_work()
          return True
        except quickjs.JSException as clean_retry_error:
          current_error = clean_retry_error

  def _eval_with_fallback(
    self,
    source: str,
    *,
    source_url: str | None,
    drain_timers: bool,
    error: quickjs.JSException,
  ) -> bool:
    if self._retry_nullish_string_receivers(
      source,
      source_url=source_url,
      drain_timers=drain_timers,
      error=error,
    ):
      return True
    if "stack underflow" not in str(error):
      return False
    if not _WEBPACK_JSONP_RE.match(source):
      return False
    try:
      self._eval_webpack_jsonp_bundle(source)
      self._drain_pending_jobs()
      if drain_timers:
        self._drain_async_work()
      return True
    except (JavaScriptRuntimeError, quickjs.JSException, ValueError):
      pass
    patched_source = source
    try:
      patched_source = _patch_js_module_stack_underflow(source)
      if patched_source != source:
        try:
          self._ctx.eval(patched_source)
        except quickjs.JSException as patched_error:
          if self._retry_nullish_string_receivers(
            patched_source,
            source_url=source_url,
            drain_timers=drain_timers,
            error=patched_error,
          ):
            return True
          raise
      self._drain_pending_jobs()
      if drain_timers:
        self._drain_async_work()
    except (JavaScriptRuntimeError, quickjs.JSException, ValueError) as fallback_error:
      if patched_source != source:
        try:
          self._eval_webpack_jsonp_bundle(source)
          self._drain_pending_jobs()
          if drain_timers:
            self._drain_async_work()
          return True
        except (JavaScriptRuntimeError, quickjs.JSException, ValueError):
          pass
      if isinstance(fallback_error, quickjs.JSException):
        raise _normalize_js_exception(fallback_error) from fallback_error
      if isinstance(fallback_error, ValueError):
        raise _normalize_js_exception(error) from error
      raise fallback_error
    return True

  def _eval_webpack_jsonp_bundle(self, source: str) -> None:
    open_index = source.find("push(")
    if open_index < 0:
      raise ValueError("webpackJsonp push call not found")
    array_start = source.find("[", open_index)
    if array_start < 0:
      raise ValueError("webpackJsonp payload not found")
    payload_end = _find_matching_js_pair_lenient(source, array_start, "[", "]")
    payload = source[array_start + 1 : payload_end]
    chunk_start = payload.find("[")
    if chunk_start < 0:
      raise ValueError("webpackJsonp chunk id array not found")
    chunk_end = _find_matching_js_pair_lenient(payload, chunk_start, "[", "]")
    chunk_ids_expr = payload[chunk_start : chunk_end + 1].strip() or "[]"
    cursor = chunk_end + 1
    while cursor < len(payload) and payload[cursor] in " \n\r\t,":
      cursor += 1
    if cursor >= len(payload):
      raise ValueError("webpackJsonp payload missing modules")
    modules_start = cursor
    if payload[modules_start] not in "[{":
      raise ValueError("webpackJsonp modules payload must start with '[' or '{'")
    modules_expr, modules_end, module_items = _extract_webpack_jsonp_array_modules(payload, modules_start)
    cursor = modules_end + 1
    while cursor < len(payload) and payload[cursor] in " \n\r\t,":
      cursor += 1
    runtime_expr = payload[cursor:].strip() if cursor < len(payload) else ""
    self._ctx.eval("window.webpackJsonp = window.webpackJsonp || [];")
    try:
      initial_queue_length = int(self._ctx.eval("window.webpackJsonp.length;"))
    except quickjs.JSException as exc:
      raise _normalize_js_exception(exc) from exc

    def reset_queue_length() -> None:
      self._ctx.eval(
        f"if (window.webpackJsonp && window.webpackJsonp.length > {initial_queue_length}) window.webpackJsonp.length = {initial_queue_length};"
      )
      self._ctx.eval(
        "delete window.__twebWebpackChunkIds; delete window.__twebWebpackModules; delete window.__twebWebpackJsonpRuntime;"
      )

    def load_bundle(guarded_methods: set[str]) -> None:
      self._ctx.eval("window.__twebWebpackChunkIds = [];")
      self._ctx.eval("window.__twebWebpackModules = [];")
      self._ctx.eval(f"window.__twebWebpackChunkIds = {chunk_ids_expr};")
      for index, module_expr in enumerate(module_items):
        item = module_expr.strip()
        if not item:
          continue
        guarded_item = (
          _safeguard_string_method_receivers(item, guarded_methods)
          if guarded_methods
          else item
        )
        try:
          self._ctx.eval(f"window.__twebWebpackModules[{index}] = ({guarded_item});")
        except quickjs.JSException as exc:
          if "stack underflow" not in str(exc):
            raise
          retry_item = _rewrite_js_object_literal_methods(guarded_item)
          try:
            self._ctx.eval(f"window.__twebWebpackModules[{index}] = ({retry_item});")
          except quickjs.JSException as retry_exc:
            if "stack underflow" not in str(retry_exc):
              raise
            patched_item = _patch_js_module_stack_underflow(guarded_item)
            self._ctx.eval(f"window.__twebWebpackModules[{index}] = ({patched_item});")

      if runtime_expr:
        self._ctx.eval(f"window.__twebWebpackJsonpRuntime = {runtime_expr};")
        self._ctx.eval(
          "window.webpackJsonp.push([window.__twebWebpackChunkIds, window.__twebWebpackModules, window.__twebWebpackJsonpRuntime]);"
        )
        self._ctx.eval("delete window.__twebWebpackJsonpRuntime;")
      else:
        self._ctx.eval(
          "window.webpackJsonp.push([window.__twebWebpackChunkIds, window.__twebWebpackModules]);"
        )
      self._ctx.eval(
        "delete window.__twebWebpackChunkIds; delete window.__twebWebpackModules;"
      )

    guarded_methods: set[str] = set()
    while True:
      try:
        load_bundle(guarded_methods)
        return
      except quickjs.JSException as exc:
        method = _extract_nullish_string_receiver_method(str(exc))
        if method is None or method in guarded_methods:
          reset_queue_length()
          raise
        guarded_methods.add(method)
        reset_queue_length()

  def _get_document_title(self) -> str:
    return self.document.title

  def _set_document_title(self, text: str) -> None:
    title = self.document.find_first("title")
    if title is None:
      html = self.document.html
      if html is None:
        html = ElementNode(tag="html")
        self.document.children.append(html)
      head = html.find_first("head")
      if head is None:
        head = ElementNode(tag="head")
        body = html.find_first("body")
        insert_at = 0
        if body is not None:
          for index, child in enumerate(html.children):
            if child is body:
              insert_at = index
              break
          html.children.insert(insert_at, head)
        else:
          html.children.insert(0, head)
      title = ElementNode(tag="title")
      head.children.append(title)
    title.set_text_content(text)
    self.document.sync_title()

  def _get_document_doctype(self) -> str:
    doctype = self.document.doctype
    if doctype is None:
      return ""
    return self._ensure_node_id(doctype)

  def _get_document_node(self, kind: str) -> str:
    try:
      if kind == "body":
        node = self.document.body
        if node is None:
          html = self.document.html
          if html is None:
            html = ElementNode(tag="html")
            self.document.children.append(html)
          node = ElementNode(tag="body")
          html.children.append(node)
      elif kind == "head":
        node = self.document.find_first("head")
        if node is None:
          html = self.document.html
          if html is None:
            html = ElementNode(tag="html")
            self.document.children.append(html)
          node = ElementNode(tag="head")
          body = html.find_first("body")
          if body is None:
            html.children.insert(0, node)
          else:
            index = html.children.index(body)
            html.children.insert(index, node)
      else:
        node = self.document.html
        if node is None:
          node = ElementNode(tag="html")
          self.document.children.append(node)
      return self._ensure_node_id(node)
    except Exception:
      return ""

  def _create_element(self, tag: str) -> str:
    try:
      tag_name = str(tag or "").strip().lower() or "div"
      return self._ensure_node_id(ElementNode(tag=tag_name))
    except Exception:
      return self._ensure_node_id(ElementNode(tag="div"))

  def _create_text_node(self, text: str) -> str:
    try:
      return self._ensure_text_node_id(TextNode(text=str(text or "")))
    except Exception:
      return self._ensure_text_node_id(TextNode(text=""))

  def _create_comment(self, text: str) -> str:
    node = ElementNode(tag="#comment", attrs={"__text": str(text or "")})
    return self._ensure_node_id(node)

  def _create_document_fragment(self) -> str:
    return self._ensure_node_id(ElementNode(tag="fragment"))

  def _parse_xml_document(self, source: str) -> str:
    xml_source = str(source or "")
    namespace_prefixes = {
      uri: prefix or ""
      for prefix, uri in re.findall(
        r'xmlns(?::([A-Za-z_][\w.-]*))?\s*=\s*["\']([^"\']+)["\']',
        xml_source,
      )
    }

    def qualified_name(name: str) -> str:
      if not name.startswith("{") or "}" not in name:
        return name
      uri, local_name = name[1:].split("}", 1)
      prefix = namespace_prefixes.get(uri, "")
      return f"{prefix}:{local_name}" if prefix else local_name

    def convert(element: ET.Element) -> ElementNode:
      node = ElementNode(
        tag=qualified_name(str(element.tag)).lower(),
        attrs={qualified_name(str(key)): value for key, value in element.attrib.items()},
      )
      if element.text:
        node.children.append(TextNode(text=element.text))
      for child in element:
        node.children.append(convert(child))
        if child.tail:
          node.children.append(TextNode(text=child.tail))
      return node

    try:
      root = convert(ET.fromstring(xml_source))
    except (ET.ParseError, TypeError, ValueError):
      return ""
    return self._ensure_node_id(root)

  def _query_one(self, selector: str) -> str:
    matches = self._cached_selector_matches("document", "", selector)
    if not matches:
      return ""
    return matches[0]

  def _query_all(self, selector: str) -> str:
    return json.dumps(list(self._cached_selector_matches("document", "", selector)))

  def _get_element_by_id(self, element_id: str) -> str:
    target = str(element_id or "")
    if not target:
      return ""
    matches = self._cached_dom_lookup("document-id", "", target)
    if not matches:
      return ""
    return matches[0]

  def _get_elements_by_tag_name(self, tag_name: str) -> str:
    return json.dumps(list(self._cached_dom_lookup("document-tag", "", str(tag_name or ""))))

  def _get_elements_by_name(self, name: str) -> str:
    return json.dumps(list(self._cached_dom_lookup("document-name", "", str(name or ""))))

  def _get_elements_by_class_name(self, class_names: str) -> str:
    return json.dumps(list(self._cached_dom_lookup("document-class", "", str(class_names or ""))))

  def _node_query_one(self, node_id: str, selector: str) -> str:
    node = self._node_ids.get(node_id)
    if node is None:
      return ""
    matches = self._cached_selector_matches("node", node_id, selector)
    if not matches:
      return ""
    return matches[0]

  def _node_query_all(self, node_id: str, selector: str) -> str:
    node = self._node_ids.get(node_id)
    if node is None:
      return json.dumps([])
    return json.dumps(list(self._cached_selector_matches("node", node_id, selector)))

  def _node_get_elements_by_tag_name(self, node_id: str, tag_name: str) -> str:
    node = self._node_ids.get(node_id)
    if node is None or isinstance(node, TextNode):
      return json.dumps([])
    return json.dumps(list(self._cached_dom_lookup("node-tag", node_id, str(tag_name or ""))))

  def _node_get_elements_by_class_name(self, node_id: str, class_names: str) -> str:
    node = self._node_ids.get(node_id)
    if node is None or isinstance(node, TextNode):
      return json.dumps([])
    return json.dumps(list(self._cached_dom_lookup("node-class", node_id, str(class_names or ""))))

  def _get_node_tag_name(self, node_id: str) -> str:
    try:
      node = self._lookup_node(node_id)
    except KeyError:
      return ""
    if isinstance(node, TextNode):
      return "#text"
    return node.tag

  def _get_text_content(self, node_id: str) -> str:
    try:
      node = self._lookup_node(node_id)
    except KeyError:
      return ""
    if isinstance(node, TextNode):
      return node.text
    if node.tag in {"script", "style", "template", "textarea"}:
      return _collect_raw_node_text(node)
    return node.text_content()

  def _set_text_content(self, node_id: str, text: str) -> None:
    try:
      node = self._lookup_node(node_id)
    except KeyError:
      return
    if isinstance(node, TextNode):
      node.text = text
      self._record_text_only_dom_mutation()
      return
    node.set_text_content(text)
    self._invalidate_style_context_cache()

  def _get_inner_html(self, node_id: str) -> str:
    node = self._node_ids.get(node_id)
    if node is None:
      return ""
    return node.inner_html()

  def _get_outer_html(self, node_id: str) -> str:
    try:
      node = self._lookup_node(node_id)
    except KeyError:
      return ""
    return _serialize_node(node)

  def _set_inner_html(self, node_id: str, html: str) -> None:
    node = self._node_ids.get(node_id)
    if node is None:
      return
    for child in node.children:
      self._set_parent_references(child, None)
    node.set_children(parse_fragment(self.document.source, html))
    for child in node.children:
      self._set_parent_references(child, node)
    self._reindex_descendants(node)
    self._invalidate_style_context_cache()

  def _get_attribute(self, node_id: str, name: str):
    node = self._node_ids.get(node_id)
    if node is None:
      return None
    return node.attrs.get(name)

  def _get_attributes_json(self, node_id: str) -> str:
    node = self._node_ids.get(node_id)
    if node is None:
      return "{}"
    return json.dumps(node.attrs)

  def _set_attribute(self, node_id: str, name: str, value: str) -> None:
    node = self._node_ids.get(node_id)
    if node is None:
      return
    node.attrs[name] = value
    self._invalidate_style_context_cache()

  def _remove_attribute(self, node_id: str, name: str) -> None:
    node = self._node_ids.get(node_id)
    if node is None:
      return
    node.attrs.pop(name, None)
    self._invalidate_style_context_cache()

  def _append_child(self, parent_id: str, child_id: str) -> str:
    parent = self._node_ids[parent_id]
    child_node = self._lookup_node(child_id)
    if isinstance(child_node, ElementNode):
      if child_node is parent or self._is_descendant_element(parent, child_node):
        return self._ensure_node_id(child_node)
    child = self._detach_node(child_id)
    if isinstance(child, ElementNode) and child.tag == "fragment":
      for grandchild in list(child.children):
        parent.append_child(grandchild)
        self._set_parent_references(grandchild, parent)
      child.children = []
      self._invalidate_style_context_cache()
      return child_id
    parent.append_child(child)
    self._set_parent_references(child, parent)
    self._invalidate_style_context_cache()
    if isinstance(child, ElementNode):
      return self._ensure_node_id(child)
    return child_id

  def _remove_node(self, node_id: str) -> None:
    node = self._lookup_node(node_id)
    if isinstance(node, ElementNode):
      parent = self._find_parent_element(node)
      if parent is not None:
        parent.children = [child for child in parent.children if child is not node]
        self._set_parent_references(node, None)
        self._invalidate_style_context_cache()
        return
      self.document.children = [
        child for child in self.document.children if child is not node
      ]
      self._set_parent_references(node, None)
      self._invalidate_style_context_cache()
      return

    parent = self._find_parent_text(node)
    if parent is not None:
      parent.children = [child for child in parent.children if child is not node]
      self._set_parent_references(node, None)
      self._record_text_only_dom_mutation()

  def _insert_before(self, parent_id: str, child_id: str, reference_id: str) -> str:
    parent = self._node_ids[parent_id]
    child_node = self._lookup_node(child_id)
    if isinstance(child_node, ElementNode):
      if child_node is parent or self._is_descendant_element(parent, child_node):
        return self._ensure_node_id(child_node)
    child = self._detach_node(child_id)
    reference = self._lookup_node(reference_id)
    if isinstance(child, ElementNode) and child.tag == "fragment":
      if reference not in parent.children:
        for grandchild in list(child.children):
          parent.append_child(grandchild)
          self._set_parent_references(grandchild, parent)
      else:
        index = parent.children.index(reference)
        for grandchild in list(child.children):
          parent.children.insert(index, grandchild)
          self._set_parent_references(grandchild, parent)
          index += 1
      child.children = []
      self._invalidate_style_context_cache()
      return child_id
    if reference not in parent.children:
      parent.append_child(child)
    else:
      index = parent.children.index(reference)
      parent.children.insert(index, child)
    self._set_parent_references(child, parent)
    self._invalidate_style_context_cache()
    if isinstance(child, ElementNode):
      return self._ensure_node_id(child)
    return child_id

  def _get_parent_node(self, node_id: str) -> str:
    if node_id not in self._node_ids and node_id not in self._text_node_ids:
      return ""
    node = self._lookup_node(node_id)
    if isinstance(node, ElementNode):
      parent = self._find_parent_element(node)
      return "" if parent is None else self._ensure_node_id(parent)
    parent = self._find_parent_text(node)
    return "" if parent is None else self._ensure_node_id(parent)

  def _get_child_nodes(self, node_id: str) -> str:
    node = self._lookup_node(node_id)
    if isinstance(node, TextNode):
      return json.dumps([])
    child_ids: list[str] = []
    for child in node.children:
      if isinstance(child, ElementNode):
        child_ids.append(self._ensure_node_id(child))
      else:
        child_ids.append(self._ensure_text_node_id(child))
    return json.dumps(child_ids)

  def _clone_node(self, node_id: str, deep: bool) -> str:
    node = self._lookup_node(node_id)
    cloned = self._clone_dom_node(node, deep)
    if isinstance(cloned, TextNode):
      return self._ensure_text_node_id(cloned)
    return self._ensure_node_id(cloned)

  def _get_location_json(self) -> str:
    parsed = urlparse(self.document.source)
    protocol = f"{parsed.scheme}:" if parsed.scheme else ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    host = f"{hostname}{port}" if hostname else ""
    origin = f"{parsed.scheme}://{host}" if parsed.scheme and host else ""
    pathname = parsed.path or "/"
    search = f"?{parsed.query}" if parsed.query else ""
    hash_value = f"#{parsed.fragment}" if parsed.fragment else ""
    return json.dumps(
      {
        "href": self.document.source,
        "protocol": protocol,
        "host": host,
        "hostname": hostname,
        "pathname": pathname,
        "search": search,
        "hash": hash_value,
        "origin": origin,
      }
    )

  def _resolve_url(self, base: str, target: str) -> str:
    return resolve_resource_url(base, target)

  def _console_log(self, level: str, *parts) -> None:
    return None

  def _crypto_digest(self, algorithm: str, base64_data: str) -> str:
    normalized = str(algorithm or "").strip().lower().replace("_", "-")
    if normalized not in {"sha-256", "sha256"}:
      raise ValueError(f"unsupported digest algorithm: {algorithm}")
    data = base64.b64decode(base64_data.encode("ascii")) if base64_data else b""
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")

  def _document_append_child(self, child_id: str) -> str:
    child = self._detach_node(child_id)
    if isinstance(child, ElementNode) and child.tag == "fragment":
      for grandchild in list(child.children):
        self.document.children.append(grandchild)
        self._set_parent_references(grandchild, None)
        if isinstance(grandchild, ElementNode):
          self._reindex_descendants(grandchild)
      child.children = []
      self._invalidate_style_context_cache()
      return child_id
    self.document.children.append(child)
    self._set_parent_references(child, None)
    self._invalidate_style_context_cache()
    if isinstance(child, ElementNode):
      self._reindex_descendants(child)
      return self._ensure_node_id(child)
    return child_id

  def _document_insert_before(self, child_id: str, reference_id: str) -> str:
    child = self._detach_node(child_id)
    reference = self._lookup_node(reference_id)
    if reference not in self.document.children:
      return self._document_append_child(child_id)
    index = self.document.children.index(reference)
    if isinstance(child, ElementNode) and child.tag == "fragment":
      for grandchild in list(child.children):
        self.document.children.insert(index, grandchild)
        self._set_parent_references(grandchild, None)
        if isinstance(grandchild, ElementNode):
          self._reindex_descendants(grandchild)
        index += 1
      child.children = []
      self._invalidate_style_context_cache()
      return child_id
    self.document.children.insert(index, child)
    self._set_parent_references(child, None)
    self._invalidate_style_context_cache()
    if isinstance(child, ElementNode):
      self._reindex_descendants(child)
      return self._ensure_node_id(child)
    return child_id

  def _document_remove_child(self, child_id: str) -> None:
    child = self._lookup_node(child_id)
    self.document.children = [entry for entry in self.document.children if entry is not child]
    self._set_parent_references(child, None)
    self._invalidate_style_context_cache()

  def _document_clone_node(self, deep: bool) -> str:
    cloned = ElementNode(tag="html")
    if self.document.html is not None:
      cloned = self._clone_dom_node(self.document.html, deep)
      if isinstance(cloned, TextNode):
        cloned = ElementNode(tag="html")
    return self._ensure_node_id(cloned)

  def _document_contains(self, node_id: str) -> bool:
    try:
      candidate = self._lookup_node(node_id)
    except KeyError:
      return False
    for child in self.document.children:
      if child is candidate:
        return True
      if isinstance(child, ElementNode) and isinstance(candidate, ElementNode):
        if self._is_descendant_element(child, candidate):
          return True
      if isinstance(child, ElementNode) and isinstance(candidate, TextNode):
        if self._find_parent_text(candidate) is not None:
          return True
    return False

  def _get_current_script_info_json(self) -> str:
    return json.dumps(self._current_script_info)

  def _node_debug_summary(self, node: ElementNode | None) -> str:
    if node is None:
      return "none"
    attrs = node.attrs
    parts = [node.tag]
    for key in ("id", "class", "name", "type", "role", "value"):
      value = attrs.get(key, "").strip()
      if value:
        parts.append(f"{key}={value[:80]}")
    text = node.text_content().strip()
    if text:
      collapsed = " ".join(text.split())
      parts.append(f"text={collapsed[:80]}")
    return " ".join(parts)

  def _document_snapshot(self) -> str:
    if self.document.html is not None:
      return _serialize_node(self.document.html)
    return "".join(
      child.text if isinstance(child, TextNode) else _serialize_node(child)
      for child in self.document.children
    )

  def _get_computed_style_json(self, node_id: str) -> str:
    node = self._lookup_node(node_id)
    if not isinstance(node, ElementNode):
      return "{}"
    declarations = self._computed_style_declarations(node)
    return json.dumps(declarations)

  def _computed_style_declarations(self, node: ElementNode) -> dict[str, str]:
    context = self._style_context()
    chain: list[ElementNode] = []
    current: ElementNode | None = node
    while current is not None:
      chain.append(current)
      current = context.parent_map.get(id(current))
    chain.reverse()

    declarations: dict[str, str] = {}
    for ancestor in chain[:-1]:
      ancestor_declarations = context._declarations(ancestor)
      declarations.update(
        {
          key: value
          for key, value in ancestor_declarations.items()
          if key.startswith("--")
        }
      )
    declarations.update(context._declarations(node))
    return declarations

  def _style_context(self) -> StyleContext:
    if self._style_context_cache is None:
      started_at = _safe_perf_counter()
      self._style_context_cache = build_style_context(
        self.document,
        viewport_columns=160,
        session=self.session,
      )
      self._stats.increment("style_cache_rebuilds")
      self._stats.add_timing("style_rebuild", started_at)
    return self._style_context_cache

  def _invalidate_style_context_cache(self) -> None:
    self._dom_mutation_count += 1
    self._selector_cache_epoch += 1
    self._stats.increment("dom_mutations")
    self._stats.increment("style_cache_invalidations")
    self._style_context_cache = None
    self._selector_query_cache.clear()

  def _record_text_only_dom_mutation(self) -> None:
    self._dom_mutation_count += 1
    self._stats.increment("dom_mutations")
    self._stats.increment("text_only_dom_mutations")

  def _cached_selector_matches(
    self,
    scope: str,
    scope_id: str,
    selector: str,
  ) -> tuple[str, ...]:
    cache_key = (scope, scope_id, selector, self._selector_cache_epoch)
    cached = self._selector_query_cache.get(cache_key)
    if cached is not None:
      self._stats.increment("selector_query_cache_hits")
      return cached
    self._stats.increment("selector_query_cache_misses")
    if scope == "document":
      try:
        raw_matches = TWebDocument(self.document).select(selector)
      except ValueError:
        cached = ()
      else:
        cached = tuple(self._ensure_node_id(match.node) for match in raw_matches)
    else:
      node = self._node_ids.get(scope_id)
      if node is None:
        cached = ()
      else:
        try:
          raw_matches = TWebElement(node).select(selector)
        except ValueError:
          cached = ()
        else:
          cached = tuple(self._ensure_node_id(match.node) for match in raw_matches)
    self._selector_query_cache[cache_key] = cached
    return cached

  def _cached_dom_lookup(
    self,
    lookup_kind: str,
    scope_id: str,
    needle: str,
  ) -> tuple[str, ...]:
    cache_key = (lookup_kind, scope_id, needle, self._selector_cache_epoch)
    cached = self._dom_lookup_cache.get(cache_key)
    if cached is not None:
      self._stats.increment("dom_lookup_cache_hits")
      return cached
    self._stats.increment("dom_lookup_cache_misses")
    if lookup_kind == "document-id":
      cached = self._compute_document_id_lookup(needle)
    elif lookup_kind == "document-tag":
      cached = self._compute_document_tag_lookup(needle)
    elif lookup_kind == "document-name":
      cached = self._compute_document_name_lookup(needle)
    elif lookup_kind == "document-class":
      cached = self._compute_document_class_lookup(needle)
    elif lookup_kind == "node-tag":
      cached = self._compute_node_tag_lookup(scope_id, needle)
    elif lookup_kind == "node-class":
      cached = self._compute_node_class_lookup(scope_id, needle)
    else:
      cached = ()
    self._dom_lookup_cache[cache_key] = cached
    return cached

  def _compute_document_id_lookup(self, target: str) -> tuple[str, ...]:
    for element in _iter_runtime_document_elements(self.document):
      if element.attrs.get("id") == target:
        return (self._ensure_node_id(element),)
    return ()

  def _compute_document_tag_lookup(self, tag_name: str) -> tuple[str, ...]:
    return tuple(
      self._ensure_node_id(element)
      for element in _iter_runtime_document_elements(self.document)
      if _matches_runtime_tag_name(element, tag_name)
    )

  def _compute_document_name_lookup(self, name: str) -> tuple[str, ...]:
    return tuple(
      self._ensure_node_id(element)
      for element in _iter_runtime_document_elements(self.document)
      if (element.attrs.get("name") or "") == name
    )

  def _compute_document_class_lookup(self, class_names: str) -> tuple[str, ...]:
    return tuple(
      self._ensure_node_id(element)
      for element in _iter_runtime_document_elements(self.document)
      if _matches_runtime_class_names(element, class_names)
    )

  def _compute_node_tag_lookup(self, node_id: str, tag_name: str) -> tuple[str, ...]:
    node = self._node_ids.get(node_id)
    if node is None or isinstance(node, TextNode):
      return ()
    return tuple(
      self._ensure_node_id(element)
      for element in _iter_runtime_descendant_elements(node)
      if _matches_runtime_tag_name(element, tag_name)
    )

  def _compute_node_class_lookup(self, node_id: str, class_names: str) -> tuple[str, ...]:
    node = self._node_ids.get(node_id)
    if node is None or isinstance(node, TextNode):
      return ()
    return tuple(
      self._ensure_node_id(element)
      for element in _iter_runtime_descendant_elements(node)
      if _matches_runtime_class_names(element, class_names)
    )

  def load_external_script_source(self, target: str) -> str:
    resource = self._fetch_external_script_resource(target)
    return resource.content

  def eval_module(
    self,
    source: str,
    *,
    source_url: str,
    drain_timers: bool = True,
  ) -> None:
    normalized_url = resolve_resource_url(self.document.source, source_url)
    if normalized_url in self._loaded_module_urls or normalized_url in self._loading_module_urls:
      return
    self._loading_module_urls.add(normalized_url)
    try:
      rewritten_source, dependencies = _rewrite_esm_to_classic(
        source,
        source_url=normalized_url,
        resolve_specifier=lambda specifier: resolve_resource_url(normalized_url, specifier),
      )
      for dependency_url in dependencies:
        dependency_source = self.load_external_script_source(dependency_url)
        self.eval_module(
          dependency_source,
          source_url=dependency_url,
          drain_timers=False,
        )
      self.eval(
        rewritten_source,
        source_url=normalized_url,
        drain_timers=drain_timers,
      )
      self._loaded_module_urls.add(normalized_url)
    finally:
      self._loading_module_urls.discard(normalized_url)

  def script_preflight_safe(
    self,
    source: str,
    *,
    prior_sources: list[str] | None = None,
  ) -> bool:
    if not source.strip():
      return True
    trimmed_prior_sources = _trim_preflight_prior_sources(prior_sources)
    cache_key = (
      hashlib.sha256(source.encode("utf-8")).hexdigest(),
      tuple(
        hashlib.sha256(entry.encode("utf-8")).hexdigest()
        for entry in trimmed_prior_sources
      ),
    )
    with self._preflight_cache_lock:
      cached_result = self._preflight_cache.get(cache_key)
    if cached_result is not None:
      return cached_result
    payload = {
      "page_source": self.document.source,
      "prior_sources": trimmed_prior_sources,
      "source": source,
    }
    try:
      completed = subprocess.run(
        [sys.executable, "-m", "tweb.quickjs_probe"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=EXTERNAL_SCRIPT_PREFLIGHT_TIMEOUT_SECONDS,
      )
    except (OSError, subprocess.SubprocessError):
      return True
    result = completed.returncode >= 0
    with self._preflight_cache_lock:
      self._preflight_cache[cache_key] = result
    return result

  def external_script_preflight_safe(
    self,
    source: str,
    *,
    prior_sources: list[str] | None = None,
  ) -> bool:
    return self.script_preflight_safe(source, prior_sources=prior_sources)

  def _fetch_external_script_resource(self, target: str) -> Resource:
    resolved_target = resolve_resource_url(self.document.source, target)
    if not self.script_source_allowed(resolved_target):
      raise ValueError(f"third-party script blocked: {resolved_target}")
    request_context = self._cache_request_context(resolved_target)
    with self._script_cache_lock:
      cache_entry = self._find_script_cache_entry(resolved_target, request_context=request_context)
    if not self.enable_script_cache:
      with self._stats_lock:
        self._stats.increment("script_cache_bypasses")
      return self._download_script_resource(resolved_target)
    if cache_entry is not None and not self._should_revalidate_script(cache_entry):
      with self._stats_lock:
        self._stats.increment("script_cache_hits")
      return cache_entry.resource
    conditional_headers = self._script_revalidation_headers(cache_entry)
    resource = self._download_script_resource(
      resolved_target,
      request_headers=conditional_headers if conditional_headers else None,
    )
    if resource.status_code == 304 and cache_entry is not None:
      with self._stats_lock:
        self._stats.increment("script_cache_revalidations")
      with self._script_cache_lock:
        cache_entry.cached_at_monotonic = time.monotonic()
        cache_entry.cached_at_epoch_seconds = time.time()
        if resource.headers:
          cache_entry.resource.headers = resource.headers
          self._refresh_script_cache_policy(cache_entry, resource.headers)
      self._persist_external_script_cache_if_needed(resolved_target)
      return cache_entry.resource
    with self._stats_lock:
      if cache_entry is None:
        self._stats.increment("script_cache_misses")
      elif conditional_headers:
        self._stats.increment("script_cache_revalidations")
      else:
        self._stats.increment("script_cache_misses")
    with self._script_cache_lock:
      self._store_script_cache_entry(resolved_target, resource, request_context=request_context)
    self._persist_external_script_cache_if_needed(resolved_target)
    return resource

  def _find_script_cache_entry(
    self,
    resolved_target: str,
    *,
    request_context: dict[str, str],
  ) -> ScriptCacheEntry | None:
    entries = (self.external_script_cache or {}).get(resolved_target, [])
    if not entries and self.enable_script_cache and _is_global_external_script_cache(self.external_script_cache):
      loaded_entries = _load_persistent_external_script_cache_entries(resolved_target)
      if loaded_entries:
        current_entries = list((self.external_script_cache or {}).get(resolved_target, []))
        if not current_entries:
          self.external_script_cache[resolved_target] = loaded_entries
          entries = loaded_entries
        else:
          entries = current_entries
    for entry in entries:
      if entry.variant_key == self._vary_variant_key(entry.vary_headers, request_context=request_context):
        return entry
    return None

  def _download_script_resource(
    self,
    resolved_target: str,
    *,
    request_headers: dict[str, str] | None = None,
  ) -> Resource:
    started_at = _safe_perf_counter()
    resource = fetch_resource(
      resolved_target,
      session=self.session,
      request_headers=request_headers,
    )
    with self._stats_lock:
      self._stats.increment("external_script_fetches")
      self._stats.increment("external_script_bytes", len(resource.content.encode("utf-8")))
      self._stats.add_timing("external_script_fetch", started_at)
    return resource

  def _store_script_cache_entry(
    self,
    resolved_target: str,
    resource: Resource,
    *,
    request_context: dict[str, str],
  ) -> None:
    headers = resource.headers or {}
    vary_headers = _parse_vary_headers(headers)
    if "*" in vary_headers:
      self.external_script_cache.pop(resolved_target, None)
      return
    variant_key = self._vary_variant_key(vary_headers, request_context=request_context)
    entry = ScriptCacheEntry(
      resource=resource,
      variant_key=variant_key,
      vary_headers=vary_headers,
      cached_at_monotonic=time.monotonic(),
      cached_at_epoch_seconds=time.time(),
      etag=headers.get("ETag") or headers.get("etag"),
      last_modified=headers.get("Last-Modified") or headers.get("last-modified"),
    )
    self._refresh_script_cache_policy(entry, headers)
    if entry.no_store:
      entries = (self.external_script_cache or {}).get(resolved_target, [])
      filtered = [item for item in entries if item.variant_key != variant_key]
      if filtered:
        self.external_script_cache[resolved_target] = filtered
      else:
        self.external_script_cache.pop(resolved_target, None)
      return
    entries = [
      item
      for item in (self.external_script_cache or {}).get(resolved_target, [])
      if item.variant_key != variant_key
    ]
    entries.append(entry)
    self.external_script_cache[resolved_target] = entries

  def _refresh_script_cache_policy(
    self,
    entry: ScriptCacheEntry,
    headers: dict[str, str],
  ) -> None:
    cache_control = (headers.get("Cache-Control") or headers.get("cache-control") or "").lower()
    entry.no_store = "no-store" in cache_control
    entry.no_cache = "no-cache" in cache_control or "must-revalidate" in cache_control
    entry.max_age_seconds = None
    for part in cache_control.split(","):
      name, _, value = part.strip().partition("=")
      if name == "max-age":
        try:
          entry.max_age_seconds = max(0, int(value))
        except ValueError:
          entry.max_age_seconds = None

  def _should_revalidate_script(self, entry: ScriptCacheEntry) -> bool:
    if entry.no_cache:
      return True
    if entry.max_age_seconds is None:
      return False
    age_seconds = _cache_entry_age_seconds(entry)
    return age_seconds >= entry.max_age_seconds

  def _persist_external_script_cache_if_needed(self, resolved_target: str) -> None:
    if not self.enable_script_cache or not _is_global_external_script_cache(self.external_script_cache):
      return
    with GLOBAL_EXTERNAL_SCRIPT_CACHE_PERSISTENCE_LOCK:
      _persist_global_external_script_cache_target(resolved_target)

  def _script_revalidation_headers(
    self,
    entry: ScriptCacheEntry | None,
  ) -> dict[str, str]:
    if entry is None:
      return {}
    headers: dict[str, str] = {}
    if entry.etag:
      headers["If-None-Match"] = entry.etag
    if entry.last_modified:
      headers["If-Modified-Since"] = entry.last_modified
    return headers

  def _script_variant_key(self, resolved_target: str) -> str:
    return self._vary_variant_key((), request_context=self._cache_request_context(resolved_target))

  def _cache_request_context(self, resolved_target: str) -> dict[str, str]:
    return {
      "user-agent": DEFAULT_HEADERS.get("User-Agent", ""),
      "accept-language": DEFAULT_HEADERS.get("Accept-Language", ""),
      "cookie": self._cache_cookie_header(resolved_target),
    }

  def _cache_cookie_header(self, resolved_target: str) -> str:
    if self.session is None or not hasattr(self.session, "cookies"):
      return ""
    cookie_jar = getattr(self.session, "cookies", None)
    if cookie_jar is None or not hasattr(cookie_jar, "get_dict"):
      return ""
    try:
      values = cookie_jar.get_dict(domain=None, path=None)
    except Exception:
      return ""
    if not isinstance(values, dict):
      return ""
    return "; ".join(f"{name}={value}" for name, value in sorted(values.items()))

  def _vary_variant_key(
    self,
    vary_headers: tuple[str, ...],
    *,
    request_context: dict[str, str],
  ) -> str:
    if not vary_headers:
      return hashlib.sha256(b"").hexdigest()
    payload = "|".join(
      f"{header}={request_context.get(header, '')}"
      for header in vary_headers
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

  def _load_external_script(self, target: str) -> None:
    resolved_target = resolve_resource_url(self.document.source, target)
    if not self.script_source_allowed(resolved_target):
      return
    try:
      source = self.load_external_script_source(target)
      self.eval(source, source_url=resolved_target, drain_timers=False)
    except Exception as exc:
      self._pending_async_error_message = str(exc).strip()
      raise

  def _load_external_script_source(self, target: str) -> str:
    resolved_target = resolve_resource_url(self.document.source, target)
    if not self.script_source_allowed(resolved_target):
      return ""
    return self.load_external_script_source(resolved_target)

  def _record_parser_inserted_script_error(self, target: str, message: str) -> None:
    self._stats.increment("parser_inserted_script_errors")
    if len(self._parser_inserted_script_errors) >= 20:
      return
    self._parser_inserted_script_errors.append({
      "src": resolve_resource_url(self.document.source, str(target or "")),
      "error": str(message or "JavaScript error")[:2000],
    })

  def _parser_inserted_script_preflight_safe(self, source: str, prior_sources_json: str) -> bool:
    compact = str(source or "").strip()
    if len(compact) < 128 * 1024 and not ("JSON.parse(" in compact and len(compact) >= 4_096):
      return True
    try:
      payload = json.loads(str(prior_sources_json or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
      payload = []
    prior_sources = [str(entry) for entry in payload] if isinstance(payload, list) else []
    return self.script_preflight_safe(compact, prior_sources=prior_sources)

  def sync_document_cookies(self, session) -> None:
    self.session = session
    for value in self._document_cookie_assignments:
      self._store_document_cookie(value)

  def _persist_cookie(self, value: str) -> None:
    self._document_cookie_assignments.append(value)
    self._store_document_cookie(value)

  def _store_document_cookie(self, value: str) -> None:
    if self.session is None or not isinstance(getattr(self.session, "cookies", None), requests.cookies.RequestsCookieJar):
      return
    if urlparse(self.document.source).scheme not in {"http", "https"}:
      return
    # CookieJar applies domain/path/Secure/expiry rules to a document's origin.
    headers = Message()
    headers.add_header("Set-Cookie", value)
    request = requests.Request("GET", self.document.source).prepare()
    self.session.cookies.extract_cookies(
      requests.cookies.MockResponse(headers), requests.cookies.MockRequest(request),
    )

  def _request_reload(self, target: str) -> None:
    self._record_navigation_attempt(target)
    if self._allow_navigation_requests:
      self.reload_target = resolve_resource_url(self.document.source, target)

  def _allow_navigation(self) -> bool:
    return self._allow_navigation_requests

  def _load_module_by_url(self, target: str) -> bool:
    normalized_target = resolve_resource_url(self.document.source, target)
    source = self.load_external_script_source(normalized_target)
    self.eval_module(source, source_url=normalized_target, drain_timers=False)
    return True

  def _record_navigation_attempt(self, target: str) -> None:
    self._navigation_requests.append(resolve_resource_url(self.document.source, target))

  def _http_request(
    self,
    method: str,
    target: str,
    body: str,
    headers_json: str,
    override_mime_type: str = "",
  ) -> str:
    resolved_target = resolve_resource_url(self.document.source, target)
    resolved_target = self._rewrite_x_api_target(resolved_target)
    blocked = not self._allow_network_requests
    self._network_requests.append(
      ButtonNetworkRequest(
        method=method.upper(),
        url=resolved_target,
        blocked=blocked,
      )
    )
    if blocked:
      LOGGER.debug(
        "http request blocked source=%s method=%s url=%s",
        sanitize_url_for_log(self.document.source),
        method.upper(),
        sanitize_url_for_log(resolved_target),
      )
      return json.dumps(
        {
          "url": resolved_target,
          "status": 0,
          "statusText": "Blocked by tweb button click policy",
          "ok": False,
          "redirected": False,
          "text": "",
          "headers": {},
        }
      )
    parsed = urlparse(resolved_target)
    if parsed.scheme in {"http", "https"}:
      headers = json.loads(headers_json) if headers_json else {}
      origin = self._get_location_origin()
      if origin and "origin" not in headers:
        headers["origin"] = origin
      if self.document.source and "referer" not in headers:
        headers["referer"] = self.document.source
      headers.setdefault("accept", "*/*")
      headers.setdefault("accept-language", "en-US,en;q=0.9")
      headers.setdefault(
        "user-agent",
        (
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0.0.0 Safari/537.36"
        ),
      )
      request = requests.request if self.session is None else self.session.request
      response = request(
        method.upper(),
        resolved_target,
        data=body or None,
        headers=headers or None,
        timeout=30,
        stream=False,
      )
      try:
        final_url = str(getattr(response, "url", "") or resolved_target)
        raw_history = getattr(response, "history", ())
        history = tuple(raw_history) if isinstance(raw_history, (list, tuple)) else ()
        redirected = bool(history) or final_url != resolved_target
        LOGGER.debug(
          "http request complete source=%s method=%s requested_url=%s final_url=%s status=%s redirected=%s redirect_count=%d",
          sanitize_url_for_log(self.document.source),
          method.upper(),
          sanitize_url_for_log(resolved_target),
          sanitize_url_for_log(final_url),
          getattr(response, "status_code", None),
          redirected,
          len(history),
        )
        content = getattr(response, "content", None)
        if not isinstance(content, (bytes, bytearray)):
          fallback_text = response.text
          content = fallback_text.encode("utf-8")
        content_type = str(response.headers.get("Content-Type", ""))
        override_charset = _extract_declared_charset(override_mime_type)
        if override_charset:
          if ";" in override_mime_type or "/" in override_mime_type:
            content_type = override_mime_type
          else:
            content_type = f"text/plain; charset={override_charset}"
        text = _decode_http_response_text_with_content_type(
          response,
          bytes(content),
          content_type=content_type,
        )
        if (
          "json" in content_type.lower()
          or text.lstrip().startswith("{")
          or text.lstrip().startswith("[")
        ):
          self._runtime_data_network_payloads.append(
            {
              "url": final_url,
              "content_type": content_type,
              "body": text[:200000],
            }
          )
          self._runtime_data_network_payloads = self._runtime_data_network_payloads[-24:]
      finally:
        response.close()
      return json.dumps(
        {
          "url": final_url,
          "status": response.status_code,
          "statusText": response.reason or "",
          "ok": 200 <= response.status_code < 300,
          "redirected": redirected,
          "text": text,
          "base64Body": base64.b64encode(content).decode("ascii"),
          "headers": dict(response.headers),
        }
      )

    resource = fetch_resource(resolved_target)
    if (
      resource.content.lstrip().startswith("{")
      or resource.content.lstrip().startswith("[")
    ):
      self._runtime_data_network_payloads.append(
        {
          "url": str(resource.source),
          "content_type": "application/json",
          "body": resource.content[:200000],
        }
      )
      self._runtime_data_network_payloads = self._runtime_data_network_payloads[-24:]
    return json.dumps(
      {
        "url": resource.source,
        "status": 200,
        "statusText": "OK",
        "ok": True,
        "redirected": False,
        "text": resource.content,
        "headers": {},
      }
    )

  def runtime_data_network_payloads(self) -> list[dict[str, str]]:
    return list(self._runtime_data_network_payloads)

  def _get_location_origin(self) -> str:
    parsed = urlparse(self.document.source)
    if not parsed.scheme or not parsed.hostname:
      return ""
    if parsed.port:
      return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}"

  def _rewrite_x_api_target(self, target: str) -> str:
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"}:
      return target
    if parsed.hostname not in {"api.x.com", "api.twitter.com"}:
      return target
    rewrite_prefixes = (
      "/1.1/graphql/app_context",
      "/1.1/graphql/error_log",
      "/1.1/graphql/user_flow",
      "/1.1/graphql/viewer_context",
      "/1.1/jot/client_event",
      "/1.1/jot/error_log",
    )
    if not any(parsed.path.startswith(prefix) for prefix in rewrite_prefixes):
      return target
    origin = self._get_location_origin()
    if not origin:
      return target
    rewritten = f"{origin}/i/api{parsed.path}"
    if parsed.query:
      rewritten = f"{rewritten}?{parsed.query}"
    return rewritten

  def _drain_async_work(
    self,
    limit: int = 1000,
    *,
    max_time_advance_ms: int | None = None,
    max_timer_steps: int | None = None,
    max_pending_job_steps: int | None = None,
    max_microtask_steps: int | None = None,
    max_wall_time_ms: int | None = None,
  ) -> None:
    started_at = _safe_perf_counter()
    if max_timer_steps is None and len(TWebDocument(self.document).links()) >= 200:
      max_timer_steps = 8
    max_due_time_expr = "null"
    if max_time_advance_ms is not None:
      try:
        current_time = int(self._ctx.eval("__twebGetCurrentTime();"))
      except quickjs.JSException as exc:
        self._stats.add_timing("async_drain", started_at)
        raise self._normalize_context_exception(exc) from exc
      max_due_time_expr = str(current_time + max(0, max_time_advance_ms))
    timer_steps = 0
    stable_timer_steps = 0
    pending_job_steps = 0
    microtask_steps = 0
    for _ in range(limit):
      if max_wall_time_ms is not None:
        elapsed_ms = _elapsed_ms_since(started_at)
        if elapsed_ms is not None and elapsed_ms >= max(0, max_wall_time_ms):
          self._stats.increment("async_drain_early_stops")
          self._stats.add_timing("async_drain", started_at)
          return
      progressed = False
      jobs_before = self._stats.counters.get("pending_jobs_executed", 0)
      microtasks_before = self._stats.counters.get("microtasks_executed", 0)
      timers_before = self._stats.counters.get("timers_executed", 0)
      dom_before = self._dom_mutation_count
      payloads_before = len(self._runtime_data_network_payloads)
      while self._execute_pending_job():
        pending_job_steps += 1
        progressed = True
        if max_pending_job_steps is not None and pending_job_steps >= max(0, max_pending_job_steps):
          self._stats.increment("async_drain_early_stops")
          self._stats.add_timing("async_drain", started_at)
          return
      try:
        if self._ctx.eval("__twebRunNextMicrotask();"):
          microtask_steps += 1
          self._stats.increment("microtasks_executed")
          progressed = True
          if max_microtask_steps is not None and microtask_steps >= max(0, max_microtask_steps):
            self._stats.increment("async_drain_early_stops")
            self._stats.add_timing("async_drain", started_at)
            return
          while self._execute_pending_job():
            pending_job_steps += 1
            progressed = True
            if max_pending_job_steps is not None and pending_job_steps >= max(0, max_pending_job_steps):
              self._stats.increment("async_drain_early_stops")
              self._stats.add_timing("async_drain", started_at)
              return
        run_timer = max_timer_steps is None or timer_steps < max_timer_steps
        if run_timer:
          LOGGER.debug(
            "async drain timer start step=%d max_steps=%s max_due_time=%s dom_mutations=%d",
            timer_steps + 1,
            max_timer_steps,
            max_due_time_expr,
            self._dom_mutation_count,
          )
        if run_timer and self._ctx.eval(f"__twebRunNextTimer({max_due_time_expr});"):
          timer_steps += 1
          self._stats.increment("timers_executed")
          progressed = True
          while self._execute_pending_job():
            pending_job_steps += 1
            progressed = True
            if max_pending_job_steps is not None and pending_job_steps >= max(0, max_pending_job_steps):
              self._stats.increment("async_drain_early_stops")
              self._stats.add_timing("async_drain", started_at)
              return
      except quickjs.JSException as exc:
        self._stats.add_timing("async_drain", started_at)
        raise _normalize_js_exception(exc) from exc
      except SystemError as exc:
        self._stats.add_timing("async_drain", started_at)
        self._raise_async_callback_error(exc)
      if not progressed:
        self._stats.add_timing("async_drain", started_at)
        return
      jobs_after = self._stats.counters.get("pending_jobs_executed", 0)
      microtasks_after = self._stats.counters.get("microtasks_executed", 0)
      timers_after = self._stats.counters.get("timers_executed", 0)
      dom_after = self._dom_mutation_count
      payloads_after = len(self._runtime_data_network_payloads)
      only_stable_timer_progress = (
        timers_after > timers_before
        and jobs_after == jobs_before
        and microtasks_after == microtasks_before
        and dom_after == dom_before
        and payloads_after == payloads_before
      )
      if only_stable_timer_progress:
        stable_timer_steps += 1
        if stable_timer_steps >= ASYNC_DRAIN_STABLE_TIMER_EARLY_STOP_STEPS:
          LOGGER.debug(
            "async drain early stop source=%s reason=stable_timers timer_steps=%d stable_timer_steps=%d pending_job_steps=%d microtask_steps=%d dom_mutations=%d payloads=%d current_script=%s next_timer_delay_ms=%s",
            sanitize_url_for_log(self.document.source),
            timer_steps,
            stable_timer_steps,
            pending_job_steps,
            microtask_steps,
            self._dom_mutation_count,
            len(self._runtime_data_network_payloads),
            self._current_script_info,
            self.next_pending_timer_delay_ms(),
          )
          self._stats.increment("async_drain_early_stops")
          self._stats.add_timing("async_drain", started_at)
          return
      else:
        stable_timer_steps = 0
    self._stats.add_timing("async_drain", started_at)
    LOGGER.debug(
      "async drain failed source=%s reason=limit timer_steps=%d stable_timer_steps=%d pending_job_steps=%d microtask_steps=%d max_due_time=%s max_timer_steps=%s max_pending_job_steps=%s max_microtask_steps=%s max_wall_time_ms=%s dom_mutations=%d payloads=%d current_script=%s next_timer_delay_ms=%s navigation_requests=%s network_requests=%s",
      sanitize_url_for_log(self.document.source),
      timer_steps,
      stable_timer_steps,
      pending_job_steps,
      microtask_steps,
      max_due_time_expr,
      max_timer_steps,
      max_pending_job_steps,
      max_microtask_steps,
      max_wall_time_ms,
      self._dom_mutation_count,
      len(self._runtime_data_network_payloads),
      self._current_script_info,
      self.next_pending_timer_delay_ms(),
      [sanitize_url_for_log(item) for item in self._navigation_requests],
      [request.__dict__ for request in self._network_requests],
    )
    raise JavaScriptRuntimeError("pending JavaScript work exceeded limit")

  def _drain_pending_jobs(self, limit: int = 1000) -> None:
    for _ in range(limit):
      if not self._execute_pending_job():
        return
    raise JavaScriptRuntimeError("pending JavaScript jobs exceeded limit")

  def _execute_pending_job(self) -> bool:
    try:
      executed = bool(self._ctx.execute_pending_job())
    except SystemError as exc:
      self._raise_async_callback_error(exc)
    if executed:
      self._stats.increment("pending_jobs_executed")
    return executed

  def _raise_async_callback_error(self, original_error: BaseException) -> None:
    message = self._pending_async_error_message
    self._pending_async_error_message = None
    if message is None:
      message = self._take_async_error_message()
    if message is not None:
      raise JavaScriptRuntimeError(message) from original_error
    raise JavaScriptRuntimeError(str(original_error)) from original_error

  def _take_async_error_message(self) -> str | None:
    try:
      message = self._ctx.eval(
        """
        (() => {
          const error = window.__twebLastAsyncError;
          const callbackLabel = typeof window.__twebLastAsyncCallbackLabel === 'string'
            ? window.__twebLastAsyncCallbackLabel
            : '';
          window.__twebLastAsyncError = null;
          window.__twebLastAsyncCallbackLabel = '';
          if (error === undefined || error === null) {
            if (error !== null) {
              return null;
            }
            return callbackLabel ? `null [callback=${callbackLabel}]` : 'null';
          }
          if (typeof error === 'string') {
            return callbackLabel ? `${error} [callback=${callbackLabel}]` : error;
          }
          const errorCallbackLabel = error && typeof error.__twebCallbackLabel === 'string'
            ? error.__twebCallbackLabel
            : callbackLabel;
          const stack = error && typeof error.stack === 'string'
            ? error.stack.trim()
            : '';
          if (error && typeof error.message === 'string' && error.message) {
            const base = errorCallbackLabel ? `${error.message} [callback=${errorCallbackLabel}]` : error.message;
            if (!stack) {
              return base;
            }
            return stack.startsWith(error.message) ? stack : `${base}\n${stack}`;
          }
          const fallback = String(error);
          return errorCallbackLabel ? `${fallback} [callback=${errorCallbackLabel}]` : fallback;
        })()
        """
      )
    except (quickjs.JSException, SystemError):
      return None
    return message if isinstance(message, str) else None

  def _clone_dom_node(
    self,
    node: ElementNode | TextNode,
    deep: bool,
  ) -> ElementNode | TextNode:
    if isinstance(node, TextNode):
      return TextNode(text=node.text)
    cloned = ElementNode(tag=node.tag, attrs=dict(node.attrs))
    if deep:
      cloned.children = [self._clone_dom_node(child, True) for child in node.children]
    return cloned

  def _lookup_node(self, node_id: str) -> ElementNode | TextNode:
    if node_id in self._node_ids:
      return self._node_ids[node_id]
    return self._text_node_ids[node_id]

  def _ensure_node_id(self, node: ElementNode) -> str:
    identity = id(node)
    existing_id = self._node_identity_ids.get(identity)
    if existing_id is not None and self._node_ids.get(existing_id) is node:
      return existing_id
    self._next_node_index += 1
    node_id = f"js{self._next_node_index}"
    self._node_ids[node_id] = node
    self._node_identity_ids[identity] = node_id
    return node_id

  def _ensure_text_node_id(self, node: TextNode) -> str:
    identity = id(node)
    existing_id = self._text_node_identity_ids.get(identity)
    if existing_id is not None and self._text_node_ids.get(existing_id) is node:
      return existing_id
    self._next_node_index += 1
    node_id = f"js{self._next_node_index}"
    self._text_node_ids[node_id] = node
    self._text_node_identity_ids[identity] = node_id
    return node_id

  def _reindex_descendants(self, node: ElementNode) -> None:
    for child in node.children:
      if isinstance(child, ElementNode):
        self._ensure_node_id(child)
        self._reindex_descendants(child)
      else:
        self._ensure_text_node_id(child)

  def _detach_node(self, node_id: str) -> ElementNode | TextNode:
    node = self._lookup_node(node_id)
    self._remove_node(node_id)
    return node

  def _find_parent_element(self, target: ElementNode) -> ElementNode | None:
    if hasattr(target, "_tweb_parent"):
      parent = getattr(target, "_tweb_parent", None)
      return parent if isinstance(parent, ElementNode) else None
    for candidate in self._parent_search_roots(target):
      parent = self._find_parent_within(candidate, target)
      if parent is not None:
        self._set_parent_references(target, parent)
        return parent
    return None

  def _find_parent_text(self, target: TextNode) -> ElementNode | None:
    if hasattr(target, "_tweb_parent"):
      parent = getattr(target, "_tweb_parent", None)
      return parent if isinstance(parent, ElementNode) else None
    for candidate in self._parent_search_roots(None):
      parent = self._find_text_parent_within(candidate, target)
      if parent is not None:
        self._set_parent_references(target, parent)
        return parent
    return None

  def _sync_document_parent_references(self) -> None:
    for child in self.document.children:
      self._set_parent_references(child, None)

  def _set_parent_references(
    self,
    node: ElementNode | TextNode,
    parent: ElementNode | None,
  ) -> None:
    setattr(node, "_tweb_parent", parent)
    if isinstance(node, ElementNode):
      for child in node.children:
        self._set_parent_references(child, node)

  def _parent_search_roots(self, target: ElementNode | None) -> list[ElementNode]:
    roots: list[ElementNode] = []
    seen: set[int] = set()
    for child in self.document.children:
      if isinstance(child, ElementNode):
        candidate_id = id(child)
        if candidate_id in seen or child is target:
          continue
        seen.add(candidate_id)
        roots.append(child)
    for child in self._node_ids.values():
      if not isinstance(child, ElementNode):
        continue
      candidate_id = id(child)
      if candidate_id in seen or child is target:
        continue
      seen.add(candidate_id)
      roots.append(child)
    return roots

  def _find_parent_within(self, node: ElementNode, target: ElementNode) -> ElementNode | None:
    stack = [node]
    while stack:
      current = stack.pop()
      for child in current.children:
        if child is target:
          return current
        if isinstance(child, ElementNode):
          stack.append(child)
    return None

  def _find_text_parent_within(self, node: ElementNode, target: TextNode) -> ElementNode | None:
    stack = [node]
    while stack:
      current = stack.pop()
      for child in current.children:
        if child is target:
          return current
        if isinstance(child, ElementNode):
          stack.append(child)
    return None

  def _is_descendant_text(self, target: TextNode, node: ElementNode) -> bool:
    for child in node.children:
      if child is target:
        return True
      if isinstance(child, ElementNode) and self._is_descendant_text(target, child):
        return True
    return False

  def _is_descendant_element(self, target: ElementNode, node: ElementNode) -> bool:
    for child in node.children:
      if child is target:
        return True
      if isinstance(child, ElementNode) and self._is_descendant_element(target, child):
        return True
    return False


def _parse_vary_headers(headers: dict[str, str]) -> tuple[str, ...]:
  vary_value = headers.get("Vary") or headers.get("vary") or ""
  parts: list[str] = []
  for item in vary_value.split(","):
    normalized = item.strip().lower()
    if normalized:
      parts.append(normalized)
  return tuple(parts)
