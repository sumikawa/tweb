from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import inspect
import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlparse

from .css import build_style_context
from .dom import DocumentNode, ElementNode, TextNode
from .fetcher import (
  ASSET_FETCH_MAX_WORKERS,
  BrowserRenderFetcher,
  BrowserRenderRequest,
  BrowserRenderResult,
  Resource,
  create_session,
  create_persistent_session_pool,
  fetch_rendered_resource,
  fetch_resource,
  resolve_resource_url,
  sanitize_url_for_log,
)
from .hydration import HydrationLink, HydrationSection, merge_hydration_sections, populate_disclosure_sections
from .interactions import (
  ButtonClickPolicy,
  ButtonClickResult,
  ControlDebugInfo,
  ControlSubmissionPreview,
  FormControl,
  FormSubmission,
  activate_disclosure_control,
  append_text_control,
  activate_tab_control,
  backspace_text_control,
  collect_checkbox_controls,
  collect_form_controls,
  cycle_select_control,
  describe_control,
  describe_controls,
  find_control_node,
  register_parents_for_interactions,
  select_radio_control,
  set_text_control,
  submit_form_control,
  sync_interactive_document,
  tab_control_navigation_target,
  toggle_checkbox_control,
)
from .parser import parse_document
from .js_runtime_helpers import JavaScriptRuntimeError, _should_reset_runtime_after_js_error
from .runtime_data import HYDRATION_ROOT_NAMES, RuntimeDataDebugInfo, collect_runtime_data
from .site_specific import extract_hydration_sections as _extract_site_specific_hydration_sections_impl

SELECTOR_TOKEN_RE = re.compile(
  r"^(?P<tag>[a-zA-Z_][a-zA-Z0-9_-]*)?"
  r"(?P<id>#[a-zA-Z_][a-zA-Z0-9_:-]*)?"
  r"(?P<class>(\.[a-zA-Z_][a-zA-Z0-9_-]*)*)"
  r"(?P<attrs>(\[[^\]]+\])*)$"
)
ATTR_SELECTOR_RE = re.compile(
  r"^\[(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)"
  r"(?:(?P<operator>\^=|\$=|\*=|~=|\|=|=)(?P<value>[^\]]+))?\]$"
)
UUID_LIKE_RE = re.compile(
  r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ISO_DATETIME_LIKE_RE = re.compile(
  r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
NON_HTTP_URL_LIKE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://\S+$")

BrowserRenderPolicy = Literal["never", "auto", "always"]
BrowserRenderTrigger = Literal["disabled", "auto-fallback", "manual-retry"]
LOGGER = logging.getLogger("tweb")

COMMON_SECOND_LEVEL_DOMAINS = {
  "ac",
  "co",
  "ed",
  "go",
  "lg",
  "ne",
  "or",
}


@dataclass(frozen=True)
class Link:
  text: str
  href: str


@dataclass(frozen=True)
class AgentSnapshotOption:
  value: str
  label: str
  selected: bool


@dataclass(frozen=True)
class AgentSnapshotLink:
  text: str
  href: str


@dataclass(frozen=True)
class AgentSnapshotControl:
  control_id: str
  kind: str
  name: str
  label: str
  value: str = ""
  checked: bool = False
  options: tuple[AgentSnapshotOption, ...] = ()
  input_type: str = ""
  disabled: bool = False
  readonly: bool = False
  visible: bool = True
  hidden_reason: str | None = None
  supported_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSnapshotNode:
  node_id: str
  parent_id: str
  node_type: str
  tag: str | None = None
  text: str | None = None
  attrs: dict[str, str] | None = None
  visible: bool | None = None
  hidden_reason: str | None = None
  display: str | None = None
  flex_direction: str | None = None
  grid_template_columns: str | None = None
  visibility: str | None = None
  font_weight: str | None = None
  font_style: str | None = None
  text_decoration: str | None = None
  skipped: bool = False


@dataclass(frozen=True)
class AgentActionRequest:
  action: str
  control_id: str
  value: str = ""
  reverse: bool = False
  current_source: str = ""
  policy: ButtonClickPolicy = "dom-only"
  confirmed: bool = False


@dataclass(frozen=True)
class AgentActionResult:
  action: str
  control_id: str
  status: str = "ok"
  changed: bool = False
  reason: str | None = None
  available_actions: tuple[str, ...] = ()
  requires_confirmation: bool = False
  submission: dict[str, object] | None = None
  button_click: dict[str, object] | None = None
  debug: dict[str, object] | None = None

  def to_dict(self) -> dict[str, object]:
    return asdict(self)


@dataclass(frozen=True)
class AgentPageSnapshot:
  source: str
  title: str
  body_text: str
  links: tuple[AgentSnapshotLink, ...]
  form_controls: tuple[AgentSnapshotControl, ...]
  dom_nodes: tuple[AgentSnapshotNode, ...]

  def to_dict(self) -> dict[str, object]:
    return asdict(self)

  def link(self, *, href: str | None = None, text: str | None = None) -> AgentSnapshotLink | None:
    matches = self.find_links(href=href, text=text, limit=1)
    return matches[0] if matches else None

  def find_links(
    self,
    *,
    href: str | None = None,
    text: str | None = None,
    text_contains: str | None = None,
    limit: int | None = None,
  ) -> tuple[AgentSnapshotLink, ...]:
    matches: list[AgentSnapshotLink] = []
    for link in self.links:
      if href is not None and link.href != href:
        continue
      if text is not None and link.text != text:
        continue
      if text_contains is not None and not _casefold_contains(link.text, text_contains):
        continue
      matches.append(link)
      if limit is not None and len(matches) >= limit:
        break
    return tuple(matches)

  def control(self, control_id: str) -> AgentSnapshotControl | None:
    for control in self.form_controls:
      if control.control_id == control_id:
        return control
    return None

  def find_controls(
    self,
    *,
    kind: str | None = None,
    name: str | None = None,
    label_contains: str | None = None,
    input_type: str | None = None,
    limit: int | None = None,
  ) -> tuple[AgentSnapshotControl, ...]:
    matches: list[AgentSnapshotControl] = []
    for control in self.form_controls:
      if kind is not None and control.kind != kind:
        continue
      if name is not None and control.name != name:
        continue
      if input_type is not None and control.input_type != input_type:
        continue
      if label_contains is not None and not _casefold_contains(control.label, label_contains):
        continue
      matches.append(control)
      if limit is not None and len(matches) >= limit:
        break
    return tuple(matches)

  def node(self, node_id: str) -> AgentSnapshotNode | None:
    for node in self.dom_nodes:
      if node.node_id == node_id:
        return node
    return None

  def find_nodes(
    self,
    *,
    node_type: str | None = None,
    tag: str | None = None,
    text_contains: str | None = None,
    attrs: dict[str, str] | None = None,
    visible: bool | None = None,
    parent_id: str | None = None,
    include_skipped: bool = True,
    limit: int | None = None,
  ) -> tuple[AgentSnapshotNode, ...]:
    matches: list[AgentSnapshotNode] = []
    for node in self.dom_nodes:
      if node_type is not None and node.node_type != node_type:
        continue
      if tag is not None and node.tag != tag:
        continue
      if visible is not None and node.visible != visible:
        continue
      if parent_id is not None and node.parent_id != parent_id:
        continue
      if not include_skipped and node.skipped:
        continue
      if text_contains is not None and not _casefold_contains(node.text or "", text_contains):
        continue
      if attrs is not None and not _snapshot_attrs_match(node.attrs, attrs):
        continue
      matches.append(node)
      if limit is not None and len(matches) >= limit:
        break
    return tuple(matches)


@dataclass
class TWebAgentActions:
  document: "TWebDocument"

  def toggle_checkbox(self, control_id: str) -> bool:
    return self.document.toggle_checkbox(control_id)

  def set_text_control(self, control_id: str, value: str) -> bool:
    return self.document.set_text_control(control_id, value)

  def append_text_to_control(self, control_id: str, text: str) -> bool:
    return self.document.append_text_to_control(control_id, text)

  def backspace_control_text(self, control_id: str) -> bool:
    return self.document.backspace_control_text(control_id)

  def cycle_select_control(self, control_id: str, reverse: bool = False) -> bool:
    return self.document.cycle_select_control(control_id, reverse=reverse)

  def select_radio_control(self, control_id: str) -> bool:
    return self.document.select_radio_control(control_id)

  def submit_form_control(self, control_id: str, current_source: str) -> FormSubmission | None:
    return self.document.submit_form_control(control_id, current_source)

  def debug_control(self, control_id: str, current_source: str | None = None) -> ControlDebugInfo | None:
    return self.document.debug_control(control_id, current_source=current_source)

  def debug_controls(self, current_source: str | None = None) -> tuple[ControlDebugInfo, ...]:
    return self.document.debug_controls(current_source=current_source)

  def click_button_control(
    self,
    control_id: str,
    *,
    session=None,
    policy: ButtonClickPolicy = "dom-only",
  ) -> ButtonClickResult:
    return self.document.click_button_control(
      control_id,
      session=session,
      policy=policy,
    )

  def invoke(
    self,
    request: AgentActionRequest,
    *,
    session=None,
  ) -> AgentActionResult:
    return self.document.invoke_agent_action(request, session=session)


@dataclass(frozen=True)
class TWebElement:
  node: ElementNode

  @property
  def name(self) -> str:
    return self.node.tag

  @property
  def attrs(self) -> dict[str, str]:
    return self.node.attrs

  @property
  def text(self) -> str:
    return self.get_text()

  def get(self, key: str, default: str | None = None) -> str | None:
    return self.node.attrs.get(key, default)

  def get_text(self, separator: str = " ", strip: bool = True) -> str:
    parts = _collect_text_parts(self.node)
    text = separator.join(part for part in parts if part)
    return text.strip() if strip else text

  def find(self, name: str | None = None, attrs: dict[str, str] | None = None) -> "TWebElement | None":
    matches = self.find_all(name=name, attrs=attrs, limit=1)
    return matches[0] if matches else None

  def find_all(
    self,
    name: str | None = None,
    attrs: dict[str, str] | None = None,
    limit: int | None = None,
  ) -> list["TWebElement"]:
    matches: list[TWebElement] = []
    for element in _iter_descendant_elements(self.node):
      if _matches_filters(element, name=name, attrs=attrs):
        matches.append(TWebElement(element))
        if limit is not None and len(matches) >= limit:
          break
    return matches

  def select(self, selector: str) -> list["TWebElement"]:
    return [TWebElement(node) for node in _select_nodes(self.node, selector)]


@dataclass
class TWebDocument:
  """Phase 5 document API with BeautifulSoup-like basics."""

  document: DocumentNode
  browser_rendered_via_chrome: bool = False

  def __post_init__(self) -> None:
    self._js_runtime = None
    self.reloaded_resource: Resource | None = None
    self._last_runtime_data_debug: RuntimeDataDebugInfo | None = None
    self._last_javascript_debug: dict[str, object] | None = None
    register_parents_for_interactions(self.document)
    sync_interactive_document(self.document)

  @property
  def title(self) -> str:
    return self.document.title

  def root(self) -> ElementNode | None:
    return self.document.root

  @property
  def html(self) -> TWebElement | None:
    node = self.document.html
    return None if node is None else TWebElement(node)

  @property
  def body(self) -> TWebElement | None:
    node = self.document.body
    return None if node is None else TWebElement(node)

  def body_text(self, *, visible_only: bool = False) -> str:
    body = self.body
    if body is None:
      root = self.root()
      if root is None:
        return ""
      if not visible_only:
        return TWebElement(root).get_text()
      return _collect_visible_text(root, self.document)
    if not visible_only:
      return body.get_text()
    return _collect_visible_text(body.node, self.document)

  def links(self) -> list[Link]:
    links: list[Link] = []
    for element in self.find_all("a"):
      href = element.attrs.get("href", "").strip()
      if not href:
        continue
      links.append(Link(text=element.get_text(), href=href))
    return links

  def hydration_debug(self) -> dict[str, object] | None:
    debug = self._last_runtime_data_debug
    if debug is None:
      return None
    return debug.to_dict()

  def javascript_debug(self) -> dict[str, object] | None:
    if self._last_javascript_debug is None:
      return None
    return dict(self._last_javascript_debug)

  def snapshot(
    self,
    *,
    max_depth: int | None = None,
    include_script_like: bool = False,
    viewport_columns: int = 160,
  ) -> AgentPageSnapshot:
    style_context = build_style_context(
      self.document,
      viewport_columns=viewport_columns,
      session=None,
    )
    controls = tuple(_snapshot_controls(self.document, self.form_controls(), style_context=style_context))
    links = tuple(AgentSnapshotLink(text=link.text, href=link.href) for link in self.links())
    dom_nodes = tuple(
      _snapshot_dom_nodes(
        self.document,
        max_depth=max_depth,
        include_script_like=include_script_like,
        viewport_columns=viewport_columns,
        style_context=style_context,
      )
    )
    return AgentPageSnapshot(
      source=self.document.source,
      title=self.title,
      body_text=self.body_text(),
      links=links,
      form_controls=controls,
      dom_nodes=dom_nodes,
    )

  def agent_actions(self) -> TWebAgentActions:
    return TWebAgentActions(self)

  def find(self, name: str | None = None, attrs: dict[str, str] | None = None) -> TWebElement | None:
    matches = self.find_all(name=name, attrs=attrs, limit=1)
    return matches[0] if matches else None

  def find_all(
    self,
    name: str | None = None,
    attrs: dict[str, str] | None = None,
    limit: int | None = None,
  ) -> list[TWebElement]:
    matches: list[TWebElement] = []
    for element in _iter_document_elements(self.document):
      if _matches_filters(element, name=name, attrs=attrs):
        matches.append(TWebElement(element))
        if limit is not None and len(matches) >= limit:
          break
    return matches

  def select(self, selector: str) -> list[TWebElement]:
    root = self.root()
    if root is None:
      return []
    return [TWebElement(node) for node in _select_nodes(root, selector)]

  def execute_script(
    self,
    source: str,
    *,
    session=None,
    source_url: str | None = None,
  ):
    from .js_runtime import JavaScriptRuntimeError
    from .js_runtime import SUSPICIOUS_SCRIPT_MEMORY_LIMIT_BYTES

    runtime = self._runtime(session=session)
    suspicious_inline_script = source_url is None and _should_preflight_inline_script(source)
    if source_url is None and _looks_like_unbounded_memory_allocation_script(source):
      raise JavaScriptRuntimeError("JavaScript memory limit exceeded")
    if (
      suspicious_inline_script
      and not runtime.script_preflight_safe(source)
    ):
      raise JavaScriptRuntimeError("JavaScript memory limit exceeded")
    with runtime.temporary_memory_limit(
      SUSPICIOUS_SCRIPT_MEMORY_LIMIT_BYTES if suspicious_inline_script else None
    ):
      result = runtime.eval(source, source_url=source_url)
    register_parents_for_interactions(self.document)
    sync_interactive_document(self.document)
    return result

  def execute_inline_scripts(self, ignore_errors: bool = True) -> None:
    from .js_runtime import JavaScriptRuntimeError, PAGE_EVENT_TIME_LIMIT_SECONDS

    initial_body = self.document.body
    initial_main = initial_body.find_first("main") if initial_body is not None else None
    initial_main_attrs = dict(initial_main.attrs) if initial_main is not None else None
    initial_main_ancestor_specs = _build_ancestor_specs(initial_body, initial_main)
    runtime = self._runtime(reset=True)

    for script in self.find_all("script"):
      script_type = (script.get("type") or "").strip().lower()
      if script.get("src"):
        continue
      if script_type and script_type not in {"text/javascript", "application/javascript", "module"}:
        continue
      source = _collect_raw_text(script.node)
      if not source.strip():
        continue
      try:
        runtime.eval(source, drain_timers=False)
      except JavaScriptRuntimeError as exc:
        if not ignore_errors:
          raise
        if _should_reset_runtime_after_js_error(exc):
          runtime = self._runtime(reset=True)
    runtime.dispatch_page_events(time_limit_seconds=None)
    self._last_runtime_data_debug = _augment_sparse_body_from_hydration(
      self.document,
      runtime,
      initial_main_attrs=initial_main_attrs,
      initial_main_ancestor_specs=initial_main_ancestor_specs,
      extra_sections=None,
    )
    register_parents_for_interactions(self.document)
    sync_interactive_document(self.document)

  def execute_embedded_scripts(
    self,
    *,
    ignore_errors: bool = True,
    session=None,
    browser_render_policy: BrowserRenderPolicy = "never",
    browser_render_fetcher: BrowserRenderFetcher | None = None,
    use_script_cache: bool = True,
  ) -> None:
    # Reloading must preserve HTTP cookies and remain bounded even if a server
    # keeps returning the same JavaScript challenge.
    self.reloaded_resource = None
    for reload_count in range(4):
      self._execute_embedded_scripts_once(
        ignore_errors=ignore_errors,
        session=session,
        browser_render_policy=browser_render_policy,
        browser_render_fetcher=browser_render_fetcher,
        use_script_cache=use_script_cache,
      )
      target = getattr(self._js_runtime, "reload_target", None)
      if target is None or self.browser_rendered_via_chrome:
        return
      if urlparse(target).scheme not in {"http", "https"}:
        LOGGER.debug("javascript reload skipped source=%s reason=non-http-target", sanitize_url_for_log(target))
        return
      if reload_count == 3:
        LOGGER.debug("javascript reload stopped source=%s reason=reload-limit limit=3", sanitize_url_for_log(target))
        return
      LOGGER.debug("javascript reload source=%s attempt=%d", sanitize_url_for_log(target), reload_count + 1)
      if session is None:
        session = create_session()
        self._js_runtime.sync_document_cookies(session)
      resource = fetch_resource(target, session=session)
      self.document = parse_document(resource)
      self._js_runtime = None
      self.reloaded_resource = resource
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)

  def _execute_embedded_scripts_once(
    self,
    *,
    ignore_errors: bool,
    session,
    browser_render_policy: BrowserRenderPolicy,
    browser_render_fetcher: BrowserRenderFetcher | None,
    use_script_cache: bool,
  ) -> None:
    from .js_runtime import JavaScriptRuntimeError, PAGE_EVENT_TIME_LIMIT_SECONDS

    started_at = _safe_perf_counter()
    initial_body = self.document.body
    initial_body_clone = _clone_dom_node(initial_body) if initial_body is not None else None
    if initial_body_clone is not None:
      _materialize_react_bailout_segments(initial_body_clone)
    initial_main = initial_body.find_first("main") if initial_body is not None else None
    initial_had_main = initial_main is not None
    initial_main_attrs = dict(initial_main.attrs) if initial_main is not None else None
    initial_main_ancestor_specs = _build_ancestor_specs(initial_body, initial_main)
    if _should_skip_embedded_scripts_for_static_page(self):
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
      total_ms = _elapsed_ms_since(started_at)
      self.browser_rendered_via_chrome = False
      self._last_runtime_data_debug = RuntimeDataDebugInfo(
        confidence="none",
        fallback_reason="body-already-readable-static-page",
        source_summaries=(),
        used_site_specific_fallback=False,
        body_was_substantial=True,
      )
      self._last_javascript_debug = {
        "timings_ms": {
          "browser_render": 0.0,
          "embedded_scripts_total": round(total_ms, 3),
          "hydration": 0.0,
        },
        "counts": {
          "embedded_scripts_skipped_for_static_page": 1,
        },
        "script_cache": {},
        "parser_inserted_script_errors": [],
        "ignored_script_errors": [],
        "slow_scripts": [],
        "browser_rendered_via_chrome": False,
      }
      LOGGER.debug(
        "javascript performance source=%s summary=%s",
        sanitize_url_for_log(self.document.source),
        json.dumps(self._last_javascript_debug, ensure_ascii=True, sort_keys=True),
      )
      return
    pre_script_metrics = _ExecutionDocumentMetrics(self)
    trusted_script_sources = _linked_app_script_sources(self)
    runtime = self._runtime(
      session=session,
      reset=True,
      enable_script_cache=use_script_cache,
      trusted_script_sources=trusted_script_sources,
    )
    runtime.session = create_persistent_session_pool(runtime.session)
    skip_delayed_external_scripts = _should_skip_delayed_external_scripts_for_static_page(
      self,
      metrics=pre_script_metrics,
    )
    prefetched_script_executor, prefetched_script_sources = _prefetch_external_script_sources(
      self,
      runtime,
      skip_delayed_external_scripts=skip_delayed_external_scripts,
    )
    delayed_external_scripts: list[tuple[int, str, str, str]] = []
    slow_script_entries: list[dict[str, object]] = []
    ignored_script_errors: list[dict[str, object]] = []
    inline_scripts = 0
    external_scripts = 0
    delayed_scripts = 0
    skipped_delayed_external_scripts = 0
    skipped_large_inline_scripts = 0
    skipped_large_delayed_scripts = 0
    preflight_skips = 0
    runtime_resets = 0
    bootstrap_replays = 0
    evaluated_script_sources: list[str] = []
    replayable_bootstrap_scripts: list[tuple[str, str | None]] = []
    python_phase_timings: dict[str, float] = {}

    try:
      for index, script in enumerate(self.find_all("script")):
        script_type = (script.get("type") or "").strip().lower()
        if script_type and script_type not in {"text/javascript", "application/javascript", "module"}:
          continue

        source: str | None = None
        src = (script.get("src") or "").strip()
        is_delayed_external = _script_is_delayed(script, script_type)
        if src:
          target = resolve_resource_url(self.document.source, src)
          if not _should_load_external_script(
            self.document.source,
            target,
            trusted_script_sources=trusted_script_sources,
          ):
            LOGGER.debug("embedded script skipped as third-party src=%s", sanitize_url_for_log(target))
            continue
          if skip_delayed_external_scripts and is_delayed_external:
            LOGGER.debug(
              "embedded delayed script skipped before fetch for rich static page index=%d src=%s",
              index,
              sanitize_url_for_log(target),
            )
            delayed_scripts += 1
            skipped_delayed_external_scripts += 1
            continue
          try:
            prefetched_source = prefetched_script_sources.get(target)
            source = runtime.load_external_script_source(target) if prefetched_source is None else prefetched_source.result()
          except Exception:
            if ignore_errors:
              continue
            raise
          if ignore_errors and _should_preflight_inline_script(source) and not runtime.external_script_preflight_safe(
            source,
            prior_sources=evaluated_script_sources,
          ):
            LOGGER.debug(
              "embedded script preflight skipped index=%d src=%s reason=process-crash-risk",
              index,
              sanitize_url_for_log(target),
            )
            preflight_skips += 1
            continue
          external_scripts += 1
          if is_delayed_external:
            delayed_external_scripts.append((index, target, source, script_type))
            delayed_scripts += 1
            continue
        else:
          source = _collect_raw_text(script.node)
          if not source.strip():
            continue
          inline_scripts += 1
          if _should_skip_large_inline_script_for_static_page(self, source, metrics=pre_script_metrics):
            LOGGER.debug(
              "embedded inline script skipped for rich static page index=%d chars=%d",
              index,
              len(source),
            )
            skipped_large_inline_scripts += 1
            continue
          if ignore_errors and _should_preflight_inline_script(source) and not runtime.script_preflight_safe(
            source,
            prior_sources=evaluated_script_sources,
          ):
            LOGGER.debug(
              "embedded inline script preflight skipped index=%d reason=process-crash-risk chars=%d",
              index,
              len(source),
            )
            preflight_skips += 1
            continue

        LOGGER.debug(
          "embedded script eval start index=%d kind=%s type=%s src=%s chars=%d",
          index,
          "external" if src else "inline",
          script_type or "-",
          sanitize_url_for_log(target) if src else "-",
          len(source),
        )
        eval_started_at = _safe_perf_counter()
        try:
          if script_type == "module":
            runtime.eval_module(
              source,
              source_url=target if src else f"{self.document.source}#inline-module-{index}",
              drain_timers=False,
            )
          else:
            runtime.eval(
              source,
              source_url=target if src else None,
              drain_timers=False,
            )
          evaluated_script_sources.append(source)
          if script_type != "module" and _should_replay_bootstrap_script(source):
            replayable_bootstrap_scripts.append((source, target if src else None))
        except JavaScriptRuntimeError as exc:
          reset_runtime = _should_reset_runtime_after_embedded_script_error(exc, is_external=bool(src))
          if len(ignored_script_errors) < 20:
            ignored_script_errors.append({
              "index": index,
              "kind": "external" if src else "inline",
              "type": script_type or "classic",
              "src": target if src else f"{self.document.source}#inline-{index}",
              "delayed": False,
              "error": str(exc),
              "runtime_reset": reset_runtime,
            })
          LOGGER.debug(
            "embedded script eval failed index=%d kind=%s type=%s src=%s error=%s",
            index,
            "external" if src else "inline",
            script_type or "-",
            sanitize_url_for_log(target) if src else "-",
            exc,
          )
          if not ignore_errors:
            raise
          if reset_runtime:
            LOGGER.debug(
              "embedded script runtime reset index=%d kind=%s src=%s reason=%s",
              index,
              "external" if src else "inline",
              sanitize_url_for_log(target) if src else "-",
              exc,
            )
            runtime_resets += 1
            runtime = self._runtime(
              session=session,
              reset=True,
              enable_script_cache=use_script_cache,
              trusted_script_sources=trusted_script_sources,
            )
            runtime.session = create_persistent_session_pool(runtime.session)
            bootstrap_replays += _replay_bootstrap_scripts(runtime, replayable_bootstrap_scripts)
        finally:
          slow_script_entries.append({
            "index": index,
            "kind": "external" if src else "inline",
            "type": script_type or "classic",
            "src": target if src else f"{self.document.source}#inline-{index}",
            "chars": len(source),
            "delayed": False,
            "duration_ms": round(_elapsed_ms_since(eval_started_at), 3),
          })
    finally:
      if prefetched_script_executor is not None:
        prefetched_script_executor.shutdown(wait=True, cancel_futures=False)
    for delayed_index, target, source, script_type in delayed_external_scripts:
      if _should_skip_large_delayed_script_for_static_page(self, source, metrics=pre_script_metrics):
        LOGGER.debug(
          "embedded delayed script skipped for rich static page index=%d src=%s chars=%d",
          delayed_index,
          sanitize_url_for_log(target),
          len(source),
        )
        skipped_large_delayed_scripts += 1
        continue
      LOGGER.debug(
        "embedded delayed script eval start index=%d kind=external type=%s src=%s chars=%d",
        delayed_index,
        script_type or "classic-delayed",
        sanitize_url_for_log(target),
        len(source),
      )
      eval_started_at = _safe_perf_counter()
      try:
        if script_type == "module":
          runtime.eval_module(
            source,
            source_url=target,
            drain_timers=False,
          )
        else:
          runtime.eval(
            source,
            source_url=target,
            drain_timers=False,
          )
        evaluated_script_sources.append(source)
        if script_type != "module" and _should_replay_bootstrap_script(source):
          replayable_bootstrap_scripts.append((source, target))
      except Exception as exc:
        reset_runtime = (
          isinstance(exc, JavaScriptRuntimeError)
          and _should_reset_runtime_after_embedded_script_error(exc, is_external=True)
        )
        if len(ignored_script_errors) < 20:
          ignored_script_errors.append({
            "index": delayed_index,
            "kind": "external",
            "type": script_type or "classic-delayed",
            "src": target,
            "delayed": True,
            "error": str(exc),
            "runtime_reset": reset_runtime,
          })
        LOGGER.debug(
          "embedded delayed script eval failed index=%d type=%s src=%s error=%s",
          delayed_index,
          script_type or "classic-delayed",
          sanitize_url_for_log(target),
          exc,
        )
        if not ignore_errors:
          raise
        if reset_runtime:
          LOGGER.debug(
            "embedded delayed script runtime reset index=%d src=%s reason=%s",
            delayed_index,
            sanitize_url_for_log(target),
            exc,
          )
          runtime_resets += 1
          runtime = self._runtime(
            session=session,
            reset=True,
            enable_script_cache=use_script_cache,
            trusted_script_sources=trusted_script_sources,
          )
          runtime.session = create_persistent_session_pool(runtime.session)
          bootstrap_replays += _replay_bootstrap_scripts(runtime, replayable_bootstrap_scripts)
      finally:
        slow_script_entries.append({
          "index": delayed_index,
          "kind": "external",
          "type": script_type or "classic-delayed",
          "src": target,
          "chars": len(source),
          "delayed": True,
          "duration_ms": round(_elapsed_ms_since(eval_started_at), 3),
        })
    try:
      note_topic_sections = _extract_site_specific_hydration_sections(runtime, self.document.source)
    except Exception as exc:
      LOGGER.debug(
        "embedded script pre-dispatch hydration extraction failed source=%s error=%s",
        sanitize_url_for_log(self.document.source),
        exc,
      )
      if not ignore_errors:
        raise
      note_topic_sections = []
    had_pre_dispatch_pending_timer = False
    try:
      had_pre_dispatch_pending_timer = runtime.has_pending_timer(max_time_advance_ms=1_000)
    except Exception:
      had_pre_dispatch_pending_timer = False
    lifecycle_event_interest = _runtime_lifecycle_event_interest(runtime)
    post_script_metrics = _ExecutionDocumentMetrics(self) if delayed_scripts >= 20 else None
    skip_expensive_page_events = _should_skip_expensive_page_events(
      self,
      delayed_script_count=delayed_scripts,
      lifecycle_event_interest=lifecycle_event_interest,
      metrics=post_script_metrics,
    )
    if not skip_expensive_page_events:
      try:
        runtime.dispatch_page_events(
          time_limit_seconds=None,
          continue_on_event_callback_error=ignore_errors,
        )
      except Exception as exc:
        LOGGER.debug(
          "embedded script page events failed source=%s error=%s",
          sanitize_url_for_log(self.document.source),
          exc,
        )
        if not ignore_errors:
          raise
    else:
      LOGGER.debug(
        "embedded script load events skipped source=%s delayed_scripts=%d body_len=%d links=%d controls=%d",
        sanitize_url_for_log(self.document.source),
        delayed_scripts,
        len(_document_raw_text(self.document)) if post_script_metrics is None else post_script_metrics.raw_body_len(),
        len(self.links()) if post_script_metrics is None else post_script_metrics.link_count(),
        len(self.form_controls()) if post_script_metrics is None else post_script_metrics.control_count(),
      )
      if _should_dispatch_dom_content_loaded_for_static_page(self, metrics=post_script_metrics):
        try:
          runtime.dispatch_dom_content_loaded(
            time_limit_seconds=None,
            continue_on_event_callback_error=ignore_errors,
          )
        except Exception as exc:
          LOGGER.debug(
            "embedded script DOMContentLoaded event failed source=%s error=%s",
            sanitize_url_for_log(self.document.source),
            exc,
          )
          if not ignore_errors:
            raise
    if _should_retry_sparse_post_load_async_drain(
      self,
      runtime,
      had_pre_dispatch_pending_timer=had_pre_dispatch_pending_timer,
    ):
      retry_windows = (250, 1_000, 5_000, 10_000) if ignore_errors else (250, 1_000)
      for max_time_advance_ms in retry_windows:
        try:
          if not runtime.has_pending_timer(max_time_advance_ms=max_time_advance_ms):
            continue
          runtime.drain_post_load_async_work(
            max_time_advance_ms=max_time_advance_ms,
          )
        except Exception as exc:
          LOGGER.debug(
            "embedded script post-load async retry failed source=%s advance_ms=%d error=%s",
            sanitize_url_for_log(self.document.source),
            max_time_advance_ms,
            exc,
          )
          if not ignore_errors:
            raise
        if _document_visible_text(self.document):
          break
    elif _should_drain_delayed_post_load_async_work(
      self,
      runtime,
      delayed_script_count=delayed_scripts,
    ):
      try:
        runtime.drain_post_load_async_work(
          max_time_advance_ms=1_000,
        )
      except Exception as exc:
        LOGGER.debug(
          "embedded delayed script post-load drain failed source=%s error=%s",
          sanitize_url_for_log(self.document.source),
          exc,
        )
        if not ignore_errors:
          raise
    try:
      note_topic_sections = merge_hydration_sections(
        _extract_site_specific_hydration_sections(runtime, self.document.source),
        note_topic_sections,
      )
    except Exception as exc:
      LOGGER.debug(
        "embedded script post-dispatch hydration extraction failed source=%s error=%s",
        sanitize_url_for_log(self.document.source),
        exc,
      )
      if not ignore_errors:
        raise
    if _needs_initial_body_restore(self.document, initial_body_clone):
      restore_sections = _collect_restore_candidate_sections(
        self.document,
        runtime,
        site_specific_sections=note_topic_sections,
      )
      _restore_initial_body_on_client_failure(
        self.document,
        initial_body_clone,
        restore_sections,
        initial_main_attrs=initial_main_attrs,
        initial_main_ancestor_specs=initial_main_ancestor_specs,
      )
    helper_started_at = _safe_perf_counter()
    _restore_noscript_iframe_shells(
      self.document,
      session=session,
    )
    _record_timing(python_phase_timings, "noscript_iframe_restore", helper_started_at)
    cleanup_metrics = _ExecutionDocumentMetrics(self)
    helper_started_at = _safe_perf_counter()
    _prune_inline_loading_placeholders(self.document, metrics=cleanup_metrics)
    _record_timing(python_phase_timings, "inline_loading_placeholder_prune", helper_started_at)
    helper_started_at = _safe_perf_counter()
    _prune_visible_client_failure_shells(self.document, metrics=cleanup_metrics)
    _record_timing(python_phase_timings, "visible_client_failure_prune", helper_started_at)
    self.browser_rendered_via_chrome = False
    browser_render_started_at = _safe_perf_counter()
    _maybe_replace_with_browser_rendered_document(
      self,
      session=session,
      initial_had_main=initial_had_main,
      browser_render_policy=browser_render_policy,
      runtime_sections=note_topic_sections,
      browser_render_fetcher=browser_render_fetcher or fetch_rendered_resource,
    )
    browser_render_ms = _elapsed_ms_since(browser_render_started_at)
    hydration_started_at = _safe_perf_counter()
    if not self.browser_rendered_via_chrome:
      helper_started_at = _safe_perf_counter()
      self._last_runtime_data_debug = _augment_sparse_body_from_hydration(
        self.document,
        runtime,
        initial_main_attrs=initial_main_attrs,
        initial_main_ancestor_specs=initial_main_ancestor_specs,
        extra_sections=note_topic_sections,
        perf_timings=python_phase_timings,
      )
      _record_timing(python_phase_timings, "augment_sparse_body_from_hydration", helper_started_at)
      helper_started_at = _safe_perf_counter()
      should_restore_initial_body = _should_restore_initial_body_after_hydration(
        self.document,
        initial_body_clone,
      )
      _record_timing(python_phase_timings, "should_restore_initial_body_after_hydration", helper_started_at)
      if should_restore_initial_body:
        body = self.document.body
        if body is not None and initial_body_clone is not None:
          helper_started_at = _safe_perf_counter()
          body.attrs = dict(initial_body_clone.attrs)
          body.children = [_clone_dom_node(child) for child in initial_body_clone.children]
          _record_timing(python_phase_timings, "restore_initial_body_clone", helper_started_at)
          helper_started_at = _safe_perf_counter()
          self._last_runtime_data_debug = _augment_sparse_body_from_hydration(
            self.document,
            runtime,
            initial_main_attrs=initial_main_attrs,
            initial_main_ancestor_specs=initial_main_ancestor_specs,
            extra_sections=note_topic_sections,
            perf_timings=python_phase_timings,
          )
          _record_timing(python_phase_timings, "augment_sparse_body_from_hydration", helper_started_at)
      helper_started_at = _safe_perf_counter()
      _maybe_replace_with_alternate_html_document(
        self,
        session=session,
      )
      _record_timing(python_phase_timings, "alternate_html_replace", helper_started_at)
      helper_started_at = _safe_perf_counter()
      register_parents_for_interactions(self.document)
      _record_timing(python_phase_timings, "register_parents_for_interactions", helper_started_at)
      helper_started_at = _safe_perf_counter()
      sync_interactive_document(self.document)
      _record_timing(python_phase_timings, "sync_interactive_document", helper_started_at)
      cleanup_metrics = _ExecutionDocumentMetrics(self)
      helper_started_at = _safe_perf_counter()
      _prune_inline_loading_placeholders(self.document, metrics=cleanup_metrics)
      _record_timing(python_phase_timings, "inline_loading_placeholder_prune", helper_started_at)
      helper_started_at = _safe_perf_counter()
      _prune_visible_client_failure_shells(self.document, metrics=cleanup_metrics)
      _record_timing(python_phase_timings, "visible_client_failure_prune", helper_started_at)
    hydration_ms = _elapsed_ms_since(hydration_started_at)
    total_ms = _elapsed_ms_since(started_at)
    javascript_debug = runtime.performance_summary()
    if not isinstance(javascript_debug, dict):
      javascript_debug = {}
    timings = dict(javascript_debug.get("timings_ms", {}))
    timings.update(python_phase_timings)
    timings["browser_render"] = round(browser_render_ms, 3)
    timings["hydration"] = round(hydration_ms, 3)
    timings["embedded_scripts_total"] = round(total_ms, 3)
    counts = dict(javascript_debug.get("counts", {}))
    counts["embedded_inline_scripts"] = inline_scripts
    counts["embedded_external_scripts"] = external_scripts
    counts["embedded_delayed_scripts"] = delayed_scripts
    counts["skipped_delayed_external_scripts"] = skipped_delayed_external_scripts
    counts["skipped_large_inline_scripts"] = skipped_large_inline_scripts
    counts["skipped_large_delayed_scripts"] = skipped_large_delayed_scripts
    counts["embedded_preflight_skips"] = preflight_skips
    counts["ignored_script_errors"] = len(ignored_script_errors)
    counts["runtime_resets_after_ignored_errors"] = runtime_resets
    counts["bootstrap_script_replays"] = bootstrap_replays
    counts["trusted_cross_site_script_sources"] = len(trusted_script_sources)
    self._last_javascript_debug = {
      "timings_ms": timings,
      "counts": counts,
      "script_cache": javascript_debug.get("script_cache", {}),
      "parser_inserted_script_errors": javascript_debug.get("parser_inserted_script_errors", []),
      "ignored_script_errors": ignored_script_errors,
      "slow_scripts": sorted(
        slow_script_entries,
        key=lambda entry: (float(entry["duration_ms"]), int(entry["chars"])),
        reverse=True,
      )[:10],
      "browser_rendered_via_chrome": self.browser_rendered_via_chrome,
    }
    LOGGER.debug(
      "javascript performance source=%s summary=%s",
      sanitize_url_for_log(self.document.source),
      json.dumps(self._last_javascript_debug, ensure_ascii=True, sort_keys=True),
    )

  def checkbox_controls(self) -> list[FormControl]:
    return collect_checkbox_controls(self.document)

  def toggle_checkbox(self, control_id: str) -> bool:
    toggled = toggle_checkbox_control(self.document, control_id)
    if toggled:
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
    return toggled

  def form_controls(self) -> list[FormControl]:
    return collect_form_controls(self.document)

  def append_text_to_control(self, control_id: str, text: str) -> bool:
    changed = append_text_control(self.document, control_id, text)
    if changed:
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
    return changed

  def backspace_control_text(self, control_id: str) -> bool:
    changed = backspace_text_control(self.document, control_id)
    if changed:
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
    return changed

  def set_text_control(self, control_id: str, value: str) -> bool:
    changed = set_text_control(self.document, control_id, value)
    if changed:
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
    return changed

  def cycle_select_control(self, control_id: str, reverse: bool = False) -> bool:
    changed = cycle_select_control(self.document, control_id, reverse=reverse)
    if changed:
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
    return changed

  def select_radio_control(self, control_id: str) -> bool:
    changed = select_radio_control(self.document, control_id)
    if changed:
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
    return changed

  def submit_form_control(self, control_id: str, current_source: str) -> FormSubmission | None:
    return submit_form_control(self.document, control_id, current_source)

  def debug_control(self, control_id: str, current_source: str | None = None) -> ControlDebugInfo | None:
    source = current_source or self.document.source
    return describe_control(self.document, control_id, source)

  def debug_controls(self, current_source: str | None = None) -> tuple[ControlDebugInfo, ...]:
    source = current_source or self.document.source
    return tuple(describe_controls(self.document, source))

  def click_button_control(
    self,
    control_id: str,
    *,
    session=None,
    policy: ButtonClickPolicy = "dom-only",
  ) -> ButtonClickResult:
    node = find_control_node(self.document, control_id)
    if node is None:
      return ButtonClickResult(clicked=False, dom_changed=False, policy=policy)
    control = next((item for item in self.form_controls() if item.control_id == control_id), None)
    if control is None or control.kind not in {"button", "tab", "picker"}:
      return ButtonClickResult(clicked=False, dom_changed=False, policy=policy)
    if control.kind == "tab" and "tab" not in node.attrs.get("role", "").strip().lower().split():
      navigation_target = tab_control_navigation_target(self.document, control_id, self.document.source)
      if navigation_target is not None:
        return ButtonClickResult(
          clicked=True,
          dom_changed=False,
          policy=policy,
          navigation_target=navigation_target,
        )
      if activate_tab_control(self.document, control_id):
        register_parents_for_interactions(self.document)
        sync_interactive_document(self.document)
        return ButtonClickResult(clicked=True, dom_changed=True, policy=policy)
    if control.kind == "button" and activate_disclosure_control(self.document, control_id):
      register_parents_for_interactions(self.document)
      sync_interactive_document(self.document)
      return ButtonClickResult(clicked=True, dom_changed=True, policy=policy)
    runtime = self._runtime(session=session)
    click_kwargs = {}
    if control.kind == "tab":
      click_kwargs = {
        "max_time_advance_ms": 50,
        "max_timer_steps": 5,
        "tolerate_async_errors_after_dom_update": True,
      }
    clicked = runtime.click_element(node, policy=policy, **click_kwargs)
    register_parents_for_interactions(self.document)
    sync_interactive_document(self.document)
    return clicked

  def invoke_agent_action(
    self,
    request: AgentActionRequest,
    *,
    session=None,
  ) -> AgentActionResult:
    action = request.action.strip().lower()
    control_id = request.control_id
    current_source = request.current_source or self.document.source
    control = next((item for item in self.form_controls() if item.control_id == control_id), None)
    if control is None:
      return AgentActionResult(
        action=action,
        control_id=control_id,
        status="not_found",
        reason="control_not_found",
      )
    supported_actions = _supported_actions_for_control(control)
    if action not in supported_actions:
      return AgentActionResult(
        action=action,
        control_id=control_id,
        status="unsupported",
        reason="action_not_supported_for_control",
        available_actions=supported_actions,
      )
    if (
      action in {"set_text", "append_text", "backspace_text"}
      and control.input_type == "password"
      and not request.confirmed
    ):
      return AgentActionResult(
        action=action,
        control_id=control_id,
        status="requires_confirmation",
        reason="password_input_requires_confirmation",
        available_actions=supported_actions,
        requires_confirmation=True,
      )
    if action == "set_text":
      return AgentActionResult(
        action=action,
        control_id=control_id,
        available_actions=supported_actions,
        changed=self.set_text_control(control_id, request.value),
      )
    if action == "append_text":
      return AgentActionResult(
        action=action,
        control_id=control_id,
        available_actions=supported_actions,
        changed=self.append_text_to_control(control_id, request.value),
      )
    if action == "backspace_text":
      return AgentActionResult(
        action=action,
        control_id=control_id,
        available_actions=supported_actions,
        changed=self.backspace_control_text(control_id),
      )
    if action == "toggle_checkbox":
      return AgentActionResult(
        action=action,
        control_id=control_id,
        available_actions=supported_actions,
        changed=self.toggle_checkbox(control_id),
      )
    if action == "cycle_select":
      return AgentActionResult(
        action=action,
        control_id=control_id,
        available_actions=supported_actions,
        changed=self.cycle_select_control(control_id, reverse=request.reverse),
      )
    if action == "select_radio":
      return AgentActionResult(
        action=action,
        control_id=control_id,
        available_actions=supported_actions,
        changed=self.select_radio_control(control_id),
      )
    if action == "submit_form":
      submission = self.submit_form_control(control_id, current_source)
      return AgentActionResult(
        action=action,
        control_id=control_id,
        status="ok" if submission is not None else "unsupported",
        reason=None if submission is not None else "control_cannot_submit",
        available_actions=supported_actions,
        submission=None if submission is None else {
          "method": submission.method,
          "action": submission.action,
          "enctype": submission.enctype,
          "url": submission.url(),
          "form_data": submission.form_data(),
        },
      )
    if action == "click_button":
      result = self.click_button_control(control_id, session=session, policy=request.policy)
      return AgentActionResult(
        action=action,
        control_id=control_id,
        status="blocked" if result.interaction_blocked else "ok",
        changed=result.dom_changed,
        reason="blocked_by_policy" if result.interaction_blocked else None,
        available_actions=supported_actions,
        button_click={
          "clicked": result.clicked,
          "dom_changed": result.dom_changed,
          "policy": result.policy,
          "classification": result.classification,
          "navigation_target": result.navigation_target,
          "blocked_by_policy": result.blocked_by_policy,
          "network_requests": [asdict(item) for item in result.network_requests],
        },
      )
    if action == "debug_control":
      debug = self.debug_control(control_id, current_source=current_source)
      return AgentActionResult(
        action=action,
        control_id=control_id,
        status="ok" if debug is not None else "unsupported",
        reason=None if debug is not None else "debug_information_unavailable",
        available_actions=supported_actions,
        debug=None if debug is None else debug.to_dict(),
      )
    return AgentActionResult(
      action=action,
      control_id=control_id,
      status="unsupported",
      reason="unknown_action",
      available_actions=supported_actions,
    )

  def _runtime(self, *, session=None, reset: bool = False, **runtime_kwargs):
    from .js_runtime import QuickJSRuntime

    if reset or self._js_runtime is None:
      self._js_runtime = QuickJSRuntime(self.document, session=session, **runtime_kwargs)
    return self._js_runtime


def _collect_text_parts(node: ElementNode) -> list[str]:
  if node.tag in {"script", "style", "noscript"}:
    return []
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      text = " ".join(child.text.split())
      if text:
        parts.append(text)
      continue
    parts.extend(_collect_text_parts(child))
  return parts


def _document_raw_text(document: DocumentNode) -> str:
  body = document.body
  if body is None:
    root = document.root
    if root is None:
      return ""
    return " ".join(part for part in _collect_text_parts(root) if part).strip()
  return " ".join(part for part in _collect_text_parts(body) if part).strip()


def _document_visible_text(
  document: DocumentNode,
  node: ElementNode | None = None,
  *,
  exclude: ElementNode | None = None,
) -> str:
  target = node
  if target is None:
    target = document.body or document.root
  if target is None:
    return ""
  return _collect_visible_text(target, document, exclude=exclude).strip()


def _inline_visible_body_length(
  document: DocumentNode,
  *,
  character_limit: int,
) -> int:
  body = document.body or document.root
  if body is None:
    return 0
  return len(_collect_inline_visible_text(body, character_limit=character_limit).strip())


def _should_skip_embedded_scripts_for_static_page(document: "TWebDocument") -> bool:
  body = document.document.body
  if body is None:
    return False
  main = body.find_first("main") or body
  body_preview = _collect_inline_visible_text(body, character_limit=4096).strip()
  main_preview = _collect_inline_visible_text(main, character_limit=4096).strip()
  if len(body_preview) < 4000 or len(main_preview) < 3000:
    return False
  if _looks_like_client_script_failure(body_preview) or _looks_like_client_script_failure(main_preview):
    return False
  raw_body_len = len(_document_raw_text(document.document))
  if raw_body_len < 5000:
    return False
  link_count = len(document.links())
  if link_count < 500:
    return False
  control_count = _count_potential_static_controls(body, limit=10)
  if control_count < 10:
    return False
  return True


def _count_potential_static_controls(node: ElementNode, *, limit: int) -> int:
  count = 0
  for candidate in node.iter_nodes():
    if not isinstance(candidate, ElementNode):
      continue
    if candidate.tag in {"input", "button", "select", "textarea"}:
      if candidate.tag != "input" or candidate.attrs.get("type", "").strip().lower() != "hidden":
        count += 1
    elif candidate.tag == "label" and candidate.attrs.get("for", "").strip():
      count += 1
    else:
      role_tokens = {
        token.strip().lower()
        for token in candidate.attrs.get("role", "").split()
        if token.strip()
      }
      if role_tokens.intersection({"button", "tab", "checkbox", "radio", "switch", "menuitem"}):
        count += 1
      elif candidate.tag == "a" and candidate.attrs.get("href", "").strip().lower().startswith("javascript:"):
        count += 1
    if count >= limit:
      return count
  return count


def _collect_visible_text(
  node: ElementNode,
  document: DocumentNode,
  *,
  viewport_columns: int = 160,
  exclude: ElementNode | None = None,
) -> str:
  style_context = build_style_context(
    document,
    viewport_columns=viewport_columns,
    session=None,
  )
  parts = _collect_visible_text_parts(
    node,
    style_context=style_context,
    inherited_visible=True,
    exclude=exclude,
  )
  return " ".join(part for part in parts if part).strip()


def _collect_inline_visible_text(
  node: ElementNode,
  *,
  exclude: ElementNode | None = None,
  character_limit: int | None = None,
) -> str:
  parts: list[str] = []
  characters = 0

  def walk(current: ElementNode) -> bool:
    nonlocal characters
    if exclude is not None and current is exclude:
      return False
    if current.tag in {"script", "style", "noscript"}:
      return False
    style = (current.attrs.get("style") or "").replace(" ", "").lower()
    if "display:none" in style or "visibility:hidden" in style:
      return False
    if current.attrs.get("hidden") is not None:
      return False
    if (current.attrs.get("aria-hidden") or "").strip().lower() == "true":
      return False
    for child in current.children:
      if isinstance(child, TextNode):
        text = " ".join(child.text.split())
        if not text:
          continue
        parts.append(text)
        characters += len(text)
        if character_limit is not None and characters >= character_limit:
          return True
        continue
      if walk(child):
        return True
    return False

  walk(node)
  return " ".join(parts).strip()


def _collect_visible_text_parts(
  node: ElementNode,
  *,
  style_context,
  inherited_visible: bool,
  exclude: ElementNode | None = None,
) -> list[str]:
  if exclude is not None and node is exclude:
    return []
  if node.tag in {"script", "style", "noscript"}:
    return []
  properties = style_context.properties(node, inherited_visible=inherited_visible)
  if not properties.visible:
    return []
  if node.tag == "select":
    options = node.find_all("option")
    selected = [option for option in options if "selected" in option.attrs]
    if not selected and "multiple" not in node.attrs and options:
      selected = options[:1]
    return [
      text
      for option in selected
      if (text := " ".join(option.text_content().split()))
    ]
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      text = " ".join(child.text.split())
      if text:
        parts.append(text)
      continue
    parts.extend(
      _collect_visible_text_parts(
        child,
        style_context=style_context,
        inherited_visible=properties.visible,
        exclude=exclude,
      )
    )
  return parts


def _has_substantial_visible_content_outside_placeholder(
  main: ElementNode,
  placeholder: ElementNode | None,
  document: DocumentNode,
) -> bool:
  if placeholder is None:
    return False
  visible_text = _collect_visible_text(main, document, exclude=placeholder).strip()
  return len(visible_text) > 240 and not _looks_like_client_script_failure(visible_text)


def _snapshot_controls(
  document: DocumentNode,
  controls: list[FormControl],
  *,
  style_context,
) -> list[AgentSnapshotControl]:
  snapshots: list[AgentSnapshotControl] = []
  for control in controls:
    control_node = find_control_node(document, control.control_id)
    visible = True
    hidden_reason = None
    if control_node is not None:
      properties = style_context.properties(control_node)
      visible = properties.visible
      hidden_reason = properties.hidden_reason
    snapshots.append(
      AgentSnapshotControl(
        control_id=control.control_id,
        kind=control.kind,
        name=control.name,
        label=control.label,
        value=control.value,
        checked=control.checked,
        options=tuple(
          AgentSnapshotOption(
            value=option.value,
            label=option.label,
            selected=option.selected,
          )
          for option in control.options
        ),
        input_type=control.input_type,
        disabled=control.disabled,
        readonly=control.readonly,
        visible=visible,
        hidden_reason=hidden_reason,
        supported_actions=_supported_actions_for_control(control),
      )
    )
  return snapshots


def _supported_actions_for_control(control: FormControl) -> tuple[str, ...]:
  if control.disabled:
    return ("debug_control",)
  if control.kind in {"text", "textarea"}:
    if control.readonly:
      return ("debug_control",)
    return ("set_text", "append_text", "backspace_text", "debug_control")
  if control.kind == "select":
    return ("cycle_select", "debug_control")
  if control.kind == "radio":
    return ("select_radio", "debug_control")
  if control.kind == "checkbox":
    return ("toggle_checkbox", "debug_control")
  if control.kind == "submit":
    return ("submit_form", "debug_control")
  if control.kind in {"button", "tab", "picker"}:
    return ("click_button", "debug_control")
  return ("debug_control",)


def _snapshot_dom_nodes(
  document: DocumentNode,
  *,
  max_depth: int | None,
  include_script_like: bool,
  viewport_columns: int,
  style_context=None,
) -> list[AgentSnapshotNode]:
  if style_context is None:
    style_context = build_style_context(
      document,
      viewport_columns=viewport_columns,
      session=None,
    )
  counter = {"value": 0}
  nodes: list[AgentSnapshotNode] = []
  for child in document.children:
    nodes.extend(
      _snapshot_dom_node(
        child,
        depth=0,
        parent_id="document",
        parent_tag=None,
        inherited_visible=True,
        max_depth=max_depth,
        include_script_like=include_script_like,
        style_context=style_context,
        counter=counter,
      )
    )
  return nodes


def _snapshot_dom_node(
  node: ElementNode | TextNode,
  *,
  depth: int,
  parent_id: str,
  parent_tag: str | None,
  inherited_visible: bool,
  max_depth: int | None,
  include_script_like: bool,
  style_context,
  counter: dict[str, int],
) -> list[AgentSnapshotNode]:
  node_id = _next_snapshot_node_id(counter)

  if isinstance(node, TextNode):
    if parent_tag in {"script", "style"} and not include_script_like:
      return []
    text = _normalize_snapshot_text(node.text)
    if not text:
      return []
    return [
      AgentSnapshotNode(
        node_id=node_id,
        parent_id=parent_id,
        node_type="text",
        text=text,
      )
    ]

  if not include_script_like and node.tag in {"script", "style"}:
    return [
      AgentSnapshotNode(
        node_id=node_id,
        parent_id=parent_id,
        node_type="element",
        tag=node.tag,
        skipped=True,
      )
    ]

  properties = style_context.properties(node, inherited_visible=inherited_visible)
  nodes = [
    AgentSnapshotNode(
      node_id=node_id,
      parent_id=parent_id,
      node_type="element",
      tag=node.tag,
      attrs=dict(node.attrs),
      visible=properties.visible,
      hidden_reason=properties.hidden_reason,
      display=properties.display,
      flex_direction=properties.flex_direction,
      grid_template_columns=properties.grid_template_columns,
      visibility=properties.visibility,
      font_weight=properties.font_weight,
      font_style=properties.font_style,
      text_decoration=properties.text_decoration,
    )
  ]
  if max_depth is not None and depth >= max_depth:
    return nodes

  for child in node.children:
    nodes.extend(
      _snapshot_dom_node(
        child,
        depth=depth + 1,
        parent_id=node_id,
        parent_tag=node.tag,
        inherited_visible=properties.visible,
        max_depth=max_depth,
        include_script_like=include_script_like,
        style_context=style_context,
        counter=counter,
      )
    )
  return nodes


def _next_snapshot_node_id(counter: dict[str, int]) -> str:
  counter["value"] += 1
  return f"node-{counter['value']}"


def _casefold_contains(value: str, needle: str) -> bool:
  return needle.casefold() in value.casefold()


def _snapshot_attrs_match(
  node_attrs: dict[str, str] | None,
  expected_attrs: dict[str, str],
) -> bool:
  if not expected_attrs:
    return True
  if not node_attrs:
    return False
  for key, value in expected_attrs.items():
    if node_attrs.get(key) != value:
      return False
  return True


def _normalize_snapshot_text(text: str) -> str:
  return " ".join(text.split())


def _should_load_external_script(
  document_source: str,
  script_source: str,
  *,
  trusted_script_sources: set[str] | None = None,
) -> bool:
  if trusted_script_sources and script_source in trusted_script_sources:
    return True
  document_host = (urlparse(document_source).hostname or "").lower()
  script_host = (urlparse(script_source).hostname or "").lower()
  if not document_host or not script_host:
    return True
  return _site_key(document_host) == _site_key(script_host)


def _linked_app_script_sources(document: "TWebDocument") -> set[str]:
  stylesheet_paths_by_host: dict[str, list[tuple[str, ...]]] = {}
  for link in document.find_all("link"):
    rel_tokens = {token.casefold() for token in (link.get("rel") or "").split()}
    href = (link.get("href") or "").strip()
    if "stylesheet" not in rel_tokens or not href:
      continue
    target = resolve_resource_url(document.document.source, href)
    parsed = urlparse(target)
    host = (parsed.hostname or "").lower()
    if not host:
      continue
    path_parts = tuple(part for part in parsed.path.split("/") if part)
    stylesheet_paths_by_host.setdefault(host, []).append(path_parts)

  trusted: set[str] = set()
  for script in document.find_all("script"):
    src = (script.get("src") or "").strip()
    if not src:
      continue
    target = resolve_resource_url(document.document.source, src)
    if _should_load_external_script(document.document.source, target):
      continue
    parsed = urlparse(target)
    host = (parsed.hostname or "").lower()
    script_path = tuple(part for part in parsed.path.split("/") if part)
    if any(
      _common_path_prefix_length(script_path, stylesheet_path) >= 2
      for stylesheet_path in stylesheet_paths_by_host.get(host, [])
    ):
      trusted.add(target)
  return trusted


def _common_path_prefix_length(left: tuple[str, ...], right: tuple[str, ...]) -> int:
  length = 0
  for left_part, right_part in zip(left, right):
    if left_part != right_part:
      break
    length += 1
  return length


def _safe_perf_counter() -> float | None:
  try:
    return time.perf_counter()
  except BaseException:
    try:
      return time.monotonic()
    except BaseException:
      return None


def _elapsed_ms_since(started_at: float | None) -> float:
  if started_at is None:
    return 0.0
  now = _safe_perf_counter()
  if now is None:
    return 0.0
  return max(0.0, (now - started_at) * 1000.0)


def _record_timing(timings: dict[str, float], name: str, started_at: float | None) -> None:
  elapsed_ms = _elapsed_ms_since(started_at)
  timings[name] = round(timings.get(name, 0.0) + elapsed_ms, 3)


@dataclass
class _ExecutionDocumentMetrics:
  document: "TWebDocument"
  _raw_body_len: int | None = None
  _visible_body_len: int | None = None
  _link_count: int | None = None
  _control_count: int | None = None
  _delayed_external_script_count: int | None = None

  def invalidate(self) -> None:
    self._raw_body_len = None
    self._visible_body_len = None
    self._link_count = None
    self._control_count = None
    self._delayed_external_script_count = None

  def raw_body_len(self) -> int:
    if self._raw_body_len is None:
      self._raw_body_len = len(self.document.body_text().strip())
    return self._raw_body_len

  def visible_body_len(self) -> int:
    if self._visible_body_len is None:
      self._visible_body_len = len(self.document.body_text(visible_only=True).strip())
    return self._visible_body_len

  def link_count(self) -> int:
    if self._link_count is None:
      self._link_count = len(self.document.links())
    return self._link_count

  def control_count(self) -> int:
    if self._control_count is None:
      self._control_count = len(self.document.form_controls())
    return self._control_count

  def delayed_external_script_count(self) -> int:
    if self._delayed_external_script_count is None:
      delayed_external_scripts = 0
      for script in self.document.find_all("script"):
        script_type = (script.get("type") or "").strip().lower()
        if script_type and script_type not in {"text/javascript", "application/javascript", "module"}:
          continue
        src = (script.get("src") or "").strip()
        if src and _script_is_delayed(script, script_type):
          delayed_external_scripts += 1
      self._delayed_external_script_count = delayed_external_scripts
    return self._delayed_external_script_count


def _should_skip_expensive_page_events(
  document: "TWebDocument",
  *,
  delayed_script_count: int,
  lifecycle_event_interest: Mapping[str, bool] | None = None,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> bool:
  if metrics is None:
    full_body_len = len(_document_raw_text(document.document))
    link_count = len(document.links())
    control_count = len(document.form_controls())
  else:
    full_body_len = metrics.raw_body_len()
    link_count = metrics.link_count()
    control_count = metrics.control_count()
  lifecycle_interest = dict(lifecycle_event_interest or {})
  needs_post_dom_lifecycle = any(
    lifecycle_interest.get(key, False)
    for key in ("document_load", "window_load", "pageshow", "readystatechange")
  )
  main = document.document.body.find_first("main") if document.document.body is not None else None
  if main is not None:
    main_text_len = len(_normalize_space(main.text_content()))
    if main_text_len >= 500:
      visible_main_threshold = max(100, int(main_text_len * 0.1))
      inline_visible_main_len = len(
        _collect_inline_visible_text(main, character_limit=visible_main_threshold + 32).strip()
      )
      if inline_visible_main_len < visible_main_threshold:
        visible_main_len = len(_collect_visible_text(main, document.document))
        if visible_main_len < visible_main_threshold:
          return False
      else:
        root = document.document.root
        root_class = ""
        if root is not None:
          root_class = (root.attrs.get("class") or "").strip()
        if root_class:
          visible_main_len = len(_collect_visible_text(main, document.document))
          if visible_main_len < visible_main_threshold:
            return False
    if _document_has_hidden_content_hint(main):
      return False
  if delayed_script_count >= 20:
    if link_count < 40:
      return False
    if full_body_len < 2000:
      return False
    visible_len = metrics.visible_body_len() if metrics is not None else _inline_visible_body_length(document.document, character_limit=2032)
    return visible_len >= 2000
  if full_body_len < 1000:
    return False
  if link_count < 150:
    return False
  visible_len = metrics.visible_body_len() if metrics is not None else _inline_visible_body_length(document.document, character_limit=1832)
  if visible_len < 1000:
    return False
  if (
    full_body_len > max(int(visible_len * 5), visible_len + 12000)
    and not (link_count >= 400 and control_count >= 20 and visible_len >= 1800)
  ):
    return False
  if needs_post_dom_lifecycle:
    return False
  if control_count >= 15:
    return True
  return link_count >= 150 and visible_len >= 1800


def _runtime_lifecycle_event_interest(runtime) -> dict[str, bool]:
  getter = getattr(runtime, "lifecycle_event_interest", None)
  if not callable(getter):
    return {}
  try:
    interest = getter()
  except Exception:
    return {}
  if not isinstance(interest, Mapping):
    return {}
  summary: dict[str, bool] = {}
  for key, value in interest.items():
    if isinstance(key, str):
      summary[key] = bool(value)
  return summary


def _should_skip_large_inline_script_for_static_page(
  document: "TWebDocument",
  source: str,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> bool:
  if len(source) < 512 * 1024:
    return False
  return _should_skip_large_script_for_static_page(document, source, metrics=metrics)


def _should_skip_large_delayed_script_for_static_page(
  document: "TWebDocument",
  source: str,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> bool:
  if len(source) < 256 * 1024:
    return False
  return _should_skip_large_script_for_static_page(document, source, metrics=metrics)


def _should_skip_large_script_for_static_page(
  document: "TWebDocument",
  source: str,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> bool:
  if metrics is None:
    full_body_len = len(_document_raw_text(document.document))
    visible_body_len = len(_document_visible_text(document.document))
    link_count = len(document.links())
    control_count = len(document.form_controls())
  else:
    full_body_len = metrics.raw_body_len()
    visible_body_len = metrics.visible_body_len()
    link_count = metrics.link_count()
    control_count = metrics.control_count()
  if full_body_len < 3000 or visible_body_len < 2000:
    return False
  if full_body_len > max(int(visible_body_len * 5), visible_body_len + 12000):
    return False
  if len(source) >= 512 * 1024:
    return link_count >= 150 and control_count >= 10
  return link_count >= 180 and control_count >= 10 and visible_body_len >= 3000


def _script_is_delayed(script: ElementNode, script_type: str) -> bool:
  return script.get("async") is not None or script.get("defer") is not None or script_type == "module"


def _should_skip_delayed_external_scripts_for_static_page(
  document: "TWebDocument",
  *,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> bool:
  delayed_external_scripts = (
    metrics.delayed_external_script_count()
    if metrics is not None
    else sum(
      1
      for script in document.find_all("script")
      if (
        (script_type := (script.get("type") or "").strip().lower()) in {"", "text/javascript", "application/javascript", "module"}
        and (src := (script.get("src") or "").strip())
        and _script_is_delayed(script, script_type)
        and src
      )
    )
  )
  if delayed_external_scripts < 20:
    return False
  if metrics is None:
    full_body_len = len(_document_raw_text(document.document))
    visible_body_len = len(_document_visible_text(document.document))
    link_count = len(document.links())
    control_count = len(document.form_controls())
  else:
    full_body_len = metrics.raw_body_len()
    visible_body_len = metrics.visible_body_len()
    link_count = metrics.link_count()
    control_count = metrics.control_count()
  if delayed_external_scripts >= 40:
    if full_body_len < 2000 or visible_body_len < 1500:
      return False
  else:
    if full_body_len < 5000 or visible_body_len < 4000:
      return False
  if full_body_len > max(int(visible_body_len * 5), visible_body_len + 12000):
    return False
  if delayed_external_scripts >= 40:
    return link_count >= 40 and control_count >= 20
  return link_count >= 150 and control_count >= 40


def _should_dispatch_dom_content_loaded_for_static_page(
  document: "TWebDocument",
  *,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> bool:
  if metrics is None:
    link_count = len(document.links())
    visible_body_len = _inline_visible_body_length(document.document, character_limit=2032)
  else:
    link_count = metrics.link_count()
    visible_body_len = metrics.visible_body_len()
  if link_count >= 400:
    return visible_body_len < 2000
  if link_count >= 200 and visible_body_len >= 2000:
    return False
  return True


def _prefetch_external_script_sources(
  document: "TWebDocument",
  runtime,
  *,
  skip_delayed_external_scripts: bool = False,
) -> tuple[ThreadPoolExecutor | None, dict[str, Future[str]]]:
  targets: list[str] = []
  seen_targets: set[str] = set()
  for script in document.find_all("script"):
    script_type = (script.get("type") or "").strip().lower()
    if script_type and script_type not in {"text/javascript", "application/javascript", "module"}:
      continue
    src = (script.get("src") or "").strip()
    if not src:
      continue
    if skip_delayed_external_scripts and _script_is_delayed(script, script_type):
      continue
    target = resolve_resource_url(document.document.source, src)
    if not runtime.script_source_allowed(target):
      continue
    if target in seen_targets:
      continue
    seen_targets.add(target)
    targets.append(target)
  if len(targets) < 2:
    return None, {}
  executor = ThreadPoolExecutor(max_workers=min(ASSET_FETCH_MAX_WORKERS, len(targets)))
  futures = {
    target: executor.submit(runtime.load_external_script_source, target)
    for target in targets
  }
  return executor, futures


def _site_key(host: str) -> str:
  normalized = host.strip(".").lower()
  if not normalized:
    return normalized
  if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", normalized):
    return normalized
  if ":" in normalized:
    return normalized
  if normalized == "localhost":
    return normalized
  parts = normalized.split(".")
  if len(parts) <= 2:
    return normalized
  if len(parts[-1]) == 2 and parts[-2] in COMMON_SECOND_LEVEL_DOMAINS and len(parts) >= 3:
    return ".".join(parts[-3:])
  return ".".join(parts[-2:])


def _collect_raw_text(node: ElementNode) -> str:
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      parts.append(child.text)
    else:
      parts.append(_collect_raw_text(child))
  return "".join(parts)


def _clone_dom_node(node: ElementNode | TextNode) -> ElementNode | TextNode:
  if isinstance(node, TextNode):
    return TextNode(text=node.text)
  cloned = ElementNode(tag=node.tag, attrs=dict(node.attrs))
  cloned.children = [_clone_dom_node(child) for child in node.children]
  return cloned


def _restore_initial_body_on_client_failure(
  document: DocumentNode,
  initial_body_clone: ElementNode | None,
  runtime_sections: list[HydrationSection],
  *,
  initial_main_attrs: dict[str, str] | None = None,
  initial_main_ancestor_specs: list[tuple[str, dict[str, str]]] | None = None,
) -> None:
  if initial_body_clone is None:
    return
  if not _needs_initial_body_restore(document, initial_body_clone):
    return
  if not runtime_sections and not _looks_like_initial_body_clobber(document, initial_body_clone):
    return
  body = document.body
  if body is None:
    return
  if _restore_initial_layout_shell(
    document,
    initial_body_clone,
    initial_main_attrs=initial_main_attrs,
    initial_main_ancestor_specs=initial_main_ancestor_specs,
  ):
    return
  body.attrs = dict(initial_body_clone.attrs)
  body.children = [_clone_dom_node(child) for child in initial_body_clone.children]
  _materialize_react_bailout_segments(body)


def _needs_initial_body_restore(
  document: DocumentNode,
  initial_body_clone: ElementNode | None,
) -> bool:
  if initial_body_clone is None:
    return False
  body = document.body
  if body is None:
    return False
  raw_text = _document_raw_text(document)
  if raw_text and not _looks_like_client_script_failure(raw_text):
    return _looks_like_initial_body_clobber(document, initial_body_clone)
  current_text = _document_visible_text(document)
  return _looks_like_client_script_failure(current_text) or (
    not current_text and _looks_like_client_script_failure(raw_text)
  ) or _looks_like_initial_body_clobber(document, initial_body_clone)


def _looks_like_initial_body_clobber(
  document: DocumentNode,
  initial_body_clone: ElementNode | None,
) -> bool:
  if initial_body_clone is None:
    return False
  initial_text = " ".join(initial_body_clone.text_content().split()).strip()
  if len(initial_text) < 500:
    return False
  current_document = TWebDocument(document)
  raw_text = _document_raw_text(document)
  threshold = max(8, min(80, len(initial_text) // 20))
  body = document.body
  if body is not None:
    visible_preview = _collect_inline_visible_text(body, character_limit=threshold + 32).strip()
    if len(visible_preview) > threshold and not _looks_like_client_script_failure(visible_preview):
      return False
  visible_text = _document_visible_text(document)
  current_text = visible_text or raw_text
  if len(current_text) > threshold:
    return False
  initial_links = sum(
    1
    for node in _iter_descendant_elements(initial_body_clone)
    if node.tag == "a" and (node.attrs.get("href") or "").strip()
  )
  current_links = len(current_document.links())
  if initial_links >= 20 and current_links > max(1, initial_links // 5):
    return False
  initial_controls = sum(
    1
    for node in _iter_descendant_elements(initial_body_clone)
    if node.tag in {"input", "select", "textarea", "button"}
  )
  current_controls = len(current_document.form_controls())
  if initial_controls >= 3 and current_controls > initial_controls + 1:
    return False
  return True


def _should_restore_initial_body_after_hydration(
  document: DocumentNode,
  initial_body_clone: ElementNode | None,
) -> bool:
  if initial_body_clone is None:
    return False
  body = document.body
  if body is None or not _contains_hydration_marker(body):
    return False
  initial_text = " ".join(initial_body_clone.text_content().split()).strip()
  if len(initial_text) < 600:
    return False
  current_preview = _collect_inline_visible_text(body, character_limit=512).strip()
  if len(current_preview) < 200:
    return False
  current_controls = len(TWebDocument(document).form_controls())
  initial_controls = sum(
    1
    for node in _iter_descendant_elements(initial_body_clone)
    if node.tag in {"input", "select", "textarea", "button"}
  )
  if current_controls >= initial_controls + 3:
    return False
  if current_preview.startswith("Hydration Data"):
    return True
  initial_preview = _collect_inline_visible_text(initial_body_clone, character_limit=512).strip()
  if initial_preview:
    preview_similarity = SequenceMatcher(a=initial_preview, b=current_preview).ratio()
    if preview_similarity >= 0.35:
      return False
    if (
      not _looks_like_client_script_failure(current_preview)
      and len(current_preview) >= max(400, len(initial_preview) // 2)
    ):
      return False
  current_text = _document_visible_text(document)
  if len(current_text) < 200:
    return False
  similarity = SequenceMatcher(a=initial_text, b=current_text).ratio()
  return similarity < 0.35


def _collect_restore_candidate_sections(
  document: DocumentNode,
  runtime,
  *,
  site_specific_sections: list[HydrationSection],
) -> list[HydrationSection]:
  result = collect_runtime_data(
    document,
    runtime,
    body_was_substantial=False,
    fallback_reason="restore-initial-body-probe",
    site_specific_sections=site_specific_sections,
  )
  return _filter_hydration_sections(result.sections)


def _restore_initial_layout_shell(
  document: DocumentNode,
  initial_body_clone: ElementNode,
  *,
  initial_main_attrs: dict[str, str] | None = None,
  initial_main_ancestor_specs: list[tuple[str, dict[str, str]]] | None = None,
) -> bool:
  body = document.body
  if body is None:
    return False
  initial_parent = _ensure_recreated_main_parent(initial_body_clone, initial_main_ancestor_specs) or initial_body_clone
  current_parent = _ensure_recreated_main_parent(body, initial_main_ancestor_specs) or body
  initial_main = initial_parent.find_first("main")
  current_main = current_parent.find_first("main")
  restored = False

  if current_main is None and initial_main is not None:
    main_attrs = dict(initial_main.attrs)
    if initial_main_attrs is not None:
      main_attrs = dict(initial_main_attrs)
    current_main = ElementNode(tag="main", attrs=main_attrs)
    insert_at = _find_main_insertion_index(current_parent)
    current_parent.children.insert(insert_at, current_main)
    restored = True

  if current_main is not None and initial_main is not None:
    current_main_text = _collect_visible_text(current_main, document).strip()
    raw_main_text = current_main.text_content().strip()
    if (
      _looks_like_client_script_failure(current_main_text)
      or (not current_main_text and _looks_like_client_script_failure(raw_main_text))
      or (not current_main.children and initial_main.children)
    ):
      current_main.attrs = dict(initial_main.attrs)
      current_main.children = [_clone_dom_node(child) for child in initial_main.children]
      restored = True

  if _restore_missing_layout_siblings(current_parent, initial_parent):
    restored = True
  if restored:
    _materialize_react_bailout_segments(body)
  return restored


def _restore_missing_layout_siblings(
  current_parent: ElementNode,
  initial_parent: ElementNode,
) -> bool:
  restored = False
  for index, initial_child in enumerate(initial_parent.children):
    if not isinstance(initial_child, ElementNode):
      continue
    if initial_child.tag == "main":
      continue
    if not _looks_like_restorable_layout_container(initial_child):
      continue
    existing = _find_child_by_tag_and_attrs(current_parent, initial_child.tag, initial_child.attrs)
    if existing is not None:
      continue
    current_parent.children.insert(
      min(index, len(current_parent.children)),
      _clone_dom_node(initial_child),
    )
    restored = True
  return restored


def _looks_like_restorable_layout_container(node: ElementNode) -> bool:
  if node.tag in {"aside", "nav", "header", "footer"}:
    return True
  if node.tag not in {"div", "section", "article"}:
    return False
  if _looks_like_nav_container(node) or _looks_like_content_container(node):
    return True
  values = [
    node.attrs.get("class", ""),
    node.attrs.get("id", ""),
    node.attrs.get("aria-label", ""),
  ]
  haystack = " ".join(value.lower() for value in values if value)
  return any(token in haystack for token in ("shell", "layout", "pane", "rail", "sidebar", "timeline", "content"))


def _materialize_react_bailout_segments(root: ElementNode) -> None:
  while True:
    pair = _find_react_bailout_segment_pair(root)
    if pair is None:
      return
    template, source = pair
    parent = _find_parent_element(root, template)
    source_parent = _find_parent_element(root, source)
    if parent is None or source_parent is None:
      return
    template_index = parent.children.index(template)
    start_index = template_index
    if template_index > 0:
      previous = parent.children[template_index - 1]
      if isinstance(previous, ElementNode) and previous.tag == "#comment" and previous.attrs.get("__text") in {"$?", "$!"}:
        previous.attrs["__text"] = "$"
        start_index = template_index
    end_index = template_index
    depth = 0
    for index in range(template_index + 1, len(parent.children)):
      candidate = parent.children[index]
      if not isinstance(candidate, ElementNode) or candidate.tag != "#comment":
        continue
      marker = candidate.attrs.get("__text", "")
      if marker in {"$", "$?", "$!"}:
        depth += 1
        continue
      if marker == "/$":
        if depth == 0:
          end_index = index
          break
        depth -= 1
    replacement_children = [_clone_dom_node(child) for child in source.children]
    parent.children[start_index:end_index] = replacement_children
    if source in source_parent.children:
      source_parent.children.remove(source)


def _find_react_bailout_segment_pair(root: ElementNode) -> tuple[ElementNode, ElementNode] | None:
  for node, _ancestors in _iter_element_paths(root):
    if node.tag != "template":
      continue
    template_id = str(node.attrs.get("id") or "")
    if not template_id.startswith("B:"):
      continue
    suffix = template_id[2:]
    if not suffix:
      continue
    source = _find_element_with_id(root, f"S:{suffix}")
    if source is None:
      continue
    return (node, source)
  return None


def _document_has_hydration_root_hint(document: DocumentNode) -> bool:
  runtime_markers = [*HYDRATION_ROOT_NAMES, "__next_f", "webpackJsonp", "webpackChunk_N_E"]
  for script in document.find_all("script"):
    script_id = script.attrs.get("id", "")
    script_type = (script.attrs.get("type") or "").strip().lower()
    script_source = script.attrs.get("src", "")
    script_target = (script.attrs.get("data-target") or "").strip().lower()
    script_text = _collect_raw_text(script)
    if script_type == "application/json" and (
      script_target
      or "richText" in script_text
      or "<article" in script_text
      or '"html"' in script_text
    ):
      return True
    if any(
      root_name in script_id
      or root_name in script_source
      or root_name in script_text
      for root_name in runtime_markers
    ):
      return True
  return False


def _document_has_hidden_content_hint(node: ElementNode) -> bool:
  return _inspect_hidden_dom(node)["has_hidden_content_hint"]


def _document_has_hidden_node(node: ElementNode) -> bool:
  return _inspect_hidden_dom(node)["has_hidden_node"]


def _inspect_hidden_dom(node: ElementNode) -> dict[str, bool]:
  style = (node.attrs.get("style") or "").replace(" ", "").lower()
  is_hidden = (
    "display:none" in style
    or "visibility:hidden" in style
    or node.attrs.get("hidden") is not None
    or (node.attrs.get("aria-hidden") or "").strip().lower() == "true"
  )
  has_hidden_node = is_hidden
  has_hidden_content_hint = is_hidden and _hidden_subtree_has_recoverable_content(node)
  for child in node.children:
    if not isinstance(child, ElementNode):
      continue
    child_state = _inspect_hidden_dom(child)
    if child_state["has_hidden_node"]:
      has_hidden_node = True
    if child_state["has_hidden_content_hint"]:
      has_hidden_content_hint = True
    if has_hidden_node and has_hidden_content_hint:
      break
  return {
    "has_hidden_content_hint": has_hidden_content_hint,
    "has_hidden_node": has_hidden_node,
  }


def _hidden_subtree_has_recoverable_content(node: ElementNode) -> bool:
  if node.tag in {"iframe", "img", "svg", "path", "script", "style", "noscript", "template"}:
    return False
  text_chars = 0
  heading_text_chars = 0
  significant_links = 0
  stack: list[ElementNode] = [node]
  visited = 0
  while stack and visited < 128:
    current = stack.pop()
    visited += 1
    if current.tag in {"script", "style", "noscript", "template", "iframe", "svg", "path"}:
      continue
    if current.tag in {"h1", "h2", "h3", "h4"}:
      heading_text_chars += len(_normalize_space(current.text_content()))
    if current.tag == "a":
      href = current.attrs.get("href")
      text = _normalize_space(current.text_content())
      if href and _is_significant_hidden_dom_item(text, href=href):
        significant_links += 1
    for child in current.children:
      if isinstance(child, TextNode):
        text_chars += len(_normalize_space(child.text))
      elif isinstance(child, ElementNode):
        stack.append(child)
    if text_chars >= 80 or significant_links >= 2:
      return True
    if heading_text_chars >= 4 and (text_chars >= 40 or significant_links >= 1):
      return True
  return False


def _should_preflight_inline_script(source: str) -> bool:
  compact = source.strip()
  if len(compact) >= 128 * 1024:
    return True
  if "JSON.parse(" in compact and len(compact) >= 4_096:
    return True
  if _looks_like_unbounded_memory_allocation_script(compact):
    return True
  return False


def _looks_like_unbounded_memory_allocation_script(source: str) -> bool:
  compact = source.strip()
  return (
    ("while (true)" in compact or "for (;;)" in compact)
    and ".repeat(" in compact
    and ".push(" in compact
  )


def _extract_site_specific_hydration_sections(
  runtime,
  source: str,
) -> list[HydrationSection]:
  return _extract_site_specific_hydration_sections_impl(runtime, source)


def _extract_head_description_fallback(document: DocumentNode) -> str:
  candidates: list[str] = []
  seen: set[str] = set()
  for node in document.find_all("meta"):
    key = ((node.attrs.get("name") or node.attrs.get("property") or "").strip().lower())
    if key not in {"description", "og:description", "twitter:description"}:
      continue
    value = " ".join((node.attrs.get("content") or "").split()).strip()
    if len(value) < 80:
      continue
    normalized = value.casefold()
    if normalized in seen:
      continue
    seen.add(normalized)
    candidates.append(value)
  return candidates[0] if candidates else ""


def _append_head_description_fallback(
  document: DocumentNode,
  text: str,
  *,
  initial_main_attrs: dict[str, str] | None = None,
  initial_main_ancestor_specs: list[tuple[str, dict[str, str]]] | None = None,
) -> bool:
  body = document.body
  if body is None or not text:
    return False
  body_target, body_replace, _include_heading = _select_hydration_body_target(
    body,
    initial_main_attrs=initial_main_attrs,
    initial_main_ancestor_specs=initial_main_ancestor_specs,
  )
  if _contains_hydration_marker(body_target):
    return False
  section = ElementNode(tag="section", attrs={"data-tweb-head-fallback": "description"})
  paragraph = ElementNode(tag="p")
  paragraph.append_child(TextNode(text=text))
  section.append_child(paragraph)
  if body_replace:
    body_target.children = [section]
  else:
    body_target.append_child(section)
  return True


def _restore_noscript_iframe_shells(
  document: DocumentNode,
  *,
  session=None,
) -> None:
  source = document.source
  parsed_source = urlparse(source)
  if parsed_source.scheme not in {"http", "https"}:
    return
  fetched_cache: dict[str, DocumentNode | None] = {}
  root = document.root
  if root is None:
    return
  for node in (root, *_iter_descendant_elements(root)):
    if not _is_noscript_iframe_shell_candidate(node):
      continue
    iframe_src = _extract_noscript_iframe_src(node, source=source)
    if iframe_src is None:
      continue
    parsed_iframe = urlparse(iframe_src)
    if parsed_iframe.scheme not in {"http", "https"} or parsed_iframe.netloc != parsed_source.netloc:
      continue
    if iframe_src not in fetched_cache:
      try:
        fetched_cache[iframe_src] = parse_document(fetch_resource(iframe_src, session=session))
      except Exception as exc:
        LOGGER.debug(
          "noscript iframe shell fetch failed source=%s iframe=%s error=%s",
          sanitize_url_for_log(source),
          sanitize_url_for_log(iframe_src),
          exc,
        )
        fetched_cache[iframe_src] = None
    replacement = fetched_cache[iframe_src]
    if replacement is None:
      continue
    replacement_body = replacement.body or replacement.root
    if replacement_body is None:
      continue
    replacement_children = [
      _clone_dom_node(child)
      for child in replacement_body.children
      if not (isinstance(child, ElementNode) and child.tag == "noscript")
    ]
    if not replacement_children:
      continue
    node.children = replacement_children


def _is_noscript_iframe_shell_candidate(node: ElementNode) -> bool:
  if node.tag not in {"header", "footer", "nav", "aside", "section", "div"}:
    return False
  text = _normalize_space(node.text_content())
  if len(text) >= 40:
    return False
  links = sum(1 for child in _iter_descendant_elements(node) if child.tag == "a")
  if links > 1:
    return False
  return _find_noscript_iframe(node) is not None


def _extract_noscript_iframe_src(node: ElementNode, *, source: str) -> str | None:
  iframe = _find_noscript_iframe(node)
  if iframe is None:
    return None
  src = (iframe.attrs.get("src") or "").strip()
  if not src:
    return None
  return resolve_resource_url(source, src)


def _find_noscript_iframe(node: ElementNode) -> ElementNode | None:
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag != "noscript":
      continue
    iframe = child.find_first("iframe")
    if iframe is not None:
      return iframe
  return None

def _augment_sparse_body_from_hydration(
  document: DocumentNode,
  runtime,
  *,
  initial_main_attrs: dict[str, str] | None = None,
  initial_main_ancestor_specs: list[tuple[str, dict[str, str]]] | None = None,
  extra_sections: list[HydrationSection] | None = None,
  perf_timings: dict[str, float] | None = None,
) -> RuntimeDataDebugInfo | None:
  body = document.body
  if body is None:
    return None
  full_visible_body_text = ""
  runtime_sections = extra_sections
  if runtime_sections is None:
    helper_started_at = _safe_perf_counter()
    runtime_sections = _extract_site_specific_hydration_sections(runtime, document.source)
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_extract_site_specific_sections", helper_started_at)
  helper_started_at = _safe_perf_counter()
  has_hydration_root_hint = _document_has_hydration_root_hint(document)
  if perf_timings is not None:
    _record_timing(perf_timings, "augment_hydration_root_hint", helper_started_at)
  helper_started_at = _safe_perf_counter()
  has_network_payload_hint = _runtime_has_network_payloads(runtime)
  if perf_timings is not None:
    _record_timing(perf_timings, "augment_network_payload_hint", helper_started_at)
  helper_started_at = _safe_perf_counter()
  hidden_dom_state = _inspect_hidden_dom(body)
  if perf_timings is not None:
    _record_timing(perf_timings, "augment_hidden_dom_inspect", helper_started_at)
  has_hidden_content_hint = hidden_dom_state["has_hidden_content_hint"]
  has_hidden_probe_hint = hidden_dom_state["has_hidden_node"]
  helper_started_at = _safe_perf_counter()
  raw_body_text = (
    TWebDocument(document).body_text().strip()
    if has_hidden_probe_hint
    else _document_raw_text(document)
  )
  if perf_timings is not None:
    _record_timing(perf_timings, "augment_raw_body_text", helper_started_at)
  should_probe_visible_body = (
    not raw_body_text
    or _looks_like_client_script_failure(raw_body_text)
    or bool(runtime_sections)
    or has_hydration_root_hint
    or has_network_payload_hint
    or has_hidden_content_hint
  )
  body_text = raw_body_text
  inline_visible_preview_truncated = False
  if should_probe_visible_body:
    helper_started_at = _safe_perf_counter()
    visible_body_text = _collect_inline_visible_text(body, character_limit=512).strip()
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_inline_visible_preview", helper_started_at)
    inline_visible_preview_truncated = len(visible_body_text) >= 480
    body_text = visible_body_text
    if (
      (not body_text or _looks_like_client_script_failure(body_text) or len(body_text) <= 160)
      and (bool(runtime_sections) or has_hydration_root_hint or not body_text)
    ):
      visible_body_text = _document_visible_text(document)
      body_text = visible_body_text
      full_visible_body_text = visible_body_text
    if not body_text and _looks_like_client_script_failure(raw_body_text):
      body_text = raw_body_text
  body_has_substantial_content = (
    bool(body_text)
    and len(body_text) > 160
    and not _looks_like_client_script_failure(body_text)
  )
  fast_path_debug = _maybe_apply_disclosure_hydration_fast_path(
    document,
    runtime_sections=runtime_sections,
    body_was_substantial=body_has_substantial_content,
  )
  if fast_path_debug is not None:
    return fast_path_debug
  needs_exact_visible_body_text = (
    body_has_substantial_content
    and not full_visible_body_text
    and (
      bool(runtime_sections)
      or has_hydration_root_hint
      or has_network_payload_hint
      or not raw_body_text
      or _looks_like_client_script_failure(raw_body_text)
    )
  )
  if needs_exact_visible_body_text:
    helper_started_at = _safe_perf_counter()
    full_visible_body_text = _document_visible_text(document)
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_exact_visible_body_text", helper_started_at)
  hydration_body_text = full_visible_body_text or body_text
  hydration_body_length = len(hydration_body_text or raw_body_text)
  if body_has_substantial_content and inline_visible_preview_truncated and not full_visible_body_text:
    hydration_body_length = max(hydration_body_length, 600)
  has_hidden_content_surplus = (
    body_has_substantial_content
    and has_hidden_content_hint
    and len(raw_body_text) >= max(900, int(max(1, hydration_body_length) * 1.5))
  )
  current_links = 0
  current_controls = 0
  current_document: TWebDocument | None = None

  def ensure_current_document_counts() -> None:
    nonlocal current_document, current_links, current_controls
    if current_document is None:
      counts_started_at = _safe_perf_counter()
      current_document = TWebDocument(document)
      current_links = len(current_document.links())
      current_controls = len(current_document.form_controls())
      if perf_timings is not None:
        _record_timing(perf_timings, "augment_current_document_scan", counts_started_at)

  if body_has_substantial_content and has_hidden_content_hint:
    ensure_current_document_counts()
  should_merge_hidden_dom_sections = (
    has_hidden_content_surplus
    or (body_has_substantial_content and has_hidden_content_hint and current_links <= 50 and current_controls <= 5)
  )
  hidden_dom_sections: list[HydrationSection] | None = None
  should_merge_sparse_link_sections = False
  sparse_document_link_sections: list[HydrationSection] | None = None

  if body_has_substantial_content and (
    has_hidden_content_hint
    or bool(runtime_sections)
    or has_hydration_root_hint
    or has_network_payload_hint
  ):
    ensure_current_document_counts()
    should_merge_sparse_link_sections = _should_merge_sparse_document_link_sections_for_substantial_body(
      current_links=current_links,
      current_controls=current_controls,
      hydration_body_length=hydration_body_length,
      has_hidden_content_hint=has_hidden_content_hint,
    )

  def load_hidden_dom_sections() -> list[HydrationSection]:
    nonlocal hidden_dom_sections
    if hidden_dom_sections is None:
      hidden_started_at = _safe_perf_counter()
      hidden_dom_sections = _extract_hidden_dom_sections(document)
      if perf_timings is not None:
        _record_timing(perf_timings, "augment_extract_hidden_dom_sections", hidden_started_at)
    return hidden_dom_sections

  def load_sparse_document_link_sections() -> list[HydrationSection]:
    nonlocal sparse_document_link_sections
    if sparse_document_link_sections is None:
      link_started_at = _safe_perf_counter()
      sparse_document_link_sections = _extract_sparse_document_link_sections(document)
      if perf_timings is not None:
        _record_timing(perf_timings, "augment_extract_sparse_document_links", link_started_at)
    return sparse_document_link_sections
  if (
    body_has_substantial_content
    and not runtime_sections
    and not has_hydration_root_hint
    and not has_network_payload_hint
    and not should_merge_hidden_dom_sections
  ):
    return RuntimeDataDebugInfo(
      confidence="none",
      fallback_reason="body-already-readable-without-runtime-hints",
      source_summaries=(),
      used_site_specific_fallback=False,
      body_was_substantial=True,
    )
  try:
    helper_started_at = _safe_perf_counter()
    result = collect_runtime_data(
      document,
      runtime,
      body_was_substantial=body_has_substantial_content,
      fallback_reason=None if runtime_sections else "generic-runtime-collector",
      site_specific_sections=runtime_sections,
    )
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_collect_runtime_data", helper_started_at)
  except JavaScriptRuntimeError as exc:
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_collect_runtime_data", helper_started_at)
    message = str(exc).lower()
    if not body_has_substantial_content and "out of memory" not in message:
      raise
    fallback_reason = (
      "runtime-collector-oom"
      if "out of memory" in message
      else "runtime-collector-failed-with-substantial-body"
    )
    result = RuntimeDataDebugInfo(
      confidence="none",
      fallback_reason=fallback_reason,
      source_summaries=(),
      used_site_specific_fallback=bool(runtime_sections),
      body_was_substantial=body_has_substantial_content,
    )
    values, links, sections = [], [], runtime_sections or []
    debug = result
  else:
    values, links, sections = result.texts, result.links, result.sections
    debug = result.debug
  if sections:
    helper_started_at = _safe_perf_counter()
    populated_titles = populate_disclosure_sections(document, sections)
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_populate_disclosure_sections", helper_started_at)
    if populated_titles:
      sections = [entry for entry in sections if entry.title not in populated_titles]
  helper_started_at = _safe_perf_counter()
  values = _filter_hydration_values(values)
  links = _filter_hydration_links(links)
  sections = _filter_hydration_sections(sections)
  sections = _drop_low_signal_hydration_sections(
    sections,
    body_has_substantial_content=body_has_substantial_content,
  )
  if perf_timings is not None:
    _record_timing(perf_timings, "augment_filter_hydration_results", helper_started_at)
  if body_has_substantial_content:
    helper_started_at = _safe_perf_counter()
    sections = _drop_duplicate_body_sections(
      sections,
      body_text=hydration_body_text,
    )
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_drop_duplicate_body_sections", helper_started_at)
  if not body_has_substantial_content:
    sections = merge_hydration_sections(
      sections,
      load_hidden_dom_sections(),
    )
    sections = merge_hydration_sections(
      sections,
      _extract_sparse_document_link_sections(document),
    )
  elif hydration_body_length < 600:
    if has_hidden_content_hint:
      sections = merge_hydration_sections(
        sections,
        load_hidden_dom_sections(),
      )
    sections = merge_hydration_sections(
      sections,
      _extract_sparse_document_link_sections(document),
    )
  if body_has_substantial_content:
    if current_links == 0 and current_controls == 0:
      ensure_current_document_counts()
    helper_started_at = _safe_perf_counter()
    has_missing_recovered_body_section = _has_missing_recovered_body_section(
      hydration_body_text,
      sections,
    )
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_missing_recovered_body_check", helper_started_at)
    if (
      hydration_body_length <= 1000
      and (
        (0 < current_links <= 12 and 0 < current_controls <= 3)
        or current_controls >= 5
      )
      and not has_missing_recovered_body_section
    ):
      return debug
    if should_merge_hidden_dom_sections:
      sections = merge_hydration_sections(
        sections,
        load_hidden_dom_sections(),
      )
    if should_merge_sparse_link_sections:
      sections = merge_hydration_sections(
        sections,
        load_sparse_document_link_sections(),
      )
    helper_started_at = _safe_perf_counter()
    if not _is_missing_extracted_content(hydration_body_text, values, links, sections):
      if perf_timings is not None:
        _record_timing(perf_timings, "augment_missing_extracted_content_check", helper_started_at)
      return debug
    if perf_timings is not None:
      _record_timing(perf_timings, "augment_missing_extracted_content_check", helper_started_at)
  if not values and not links and not sections:
    if not body_text:
      description_fallback = _extract_head_description_fallback(document)
      if _append_head_description_fallback(
        document,
        description_fallback,
        initial_main_attrs=initial_main_attrs,
        initial_main_ancestor_specs=initial_main_ancestor_specs,
      ):
        return debug
    return debug
  section_titles = {entry.title for entry in sections}
  section_items = {text for entry in sections for text, _href in entry.items}
  nav_target, nav_replace = _select_hydration_nav_target(body)
  body_target, body_replace, include_heading = _select_hydration_body_target(
    body,
    initial_main_attrs=initial_main_attrs,
    initial_main_ancestor_specs=initial_main_ancestor_specs,
  )
  if runtime_sections and _looks_like_client_script_failure(body_target.text_content()):
    body_replace = True
  if nav_target is not None and _contains_hydration_marker(nav_target):
    return
  if _contains_hydration_marker(body_target):
    return

  if nav_target is None:
    body_sections = sections
    nav_sections: list[HydrationSection] = []
  else:
    body_sections, nav_sections = _partition_hydration_sections(sections)
    body_sections = _drop_duplicate_nav_body_sections(body_sections, nav_target)
  body_section = ElementNode(tag="section", attrs={"data-tweb-hydration": "1", "data-tweb-hydration-role": "body"})
  if include_heading:
    heading = ElementNode(tag="h2")
    heading.append_child(TextNode(text="Hydration Data"))
    body_section.append_child(heading)
  nav_section = None
  if nav_sections and nav_target is not None:
    nav_section = ElementNode(tag="section", attrs={"data-tweb-hydration": "1", "data-tweb-hydration-role": "nav"})
  for entry in body_sections[:8]:
    injected = False
    if entry.role != "recovered":
      injected = _append_section_items_to_existing_heading(body, entry)
    if injected:
      continue
    block = _build_hydration_section_block(entry)
    body_section.append_child(block)
  if nav_section is not None:
    for entry in nav_sections[:8]:
      block = _build_hydration_section_block(entry)
      nav_section.append_child(block)
  append_unstructured_fallbacks = (
    (not body_has_substantial_content or hydration_body_length < 600)
    and not (runtime_sections and body_sections)
  )
  if append_unstructured_fallbacks:
    for link in links[:12]:
      paragraph = ElementNode(tag="p")
      anchor = ElementNode(tag="a", attrs={"href": link.href})
      anchor.append_child(TextNode(text=link.text))
      paragraph.append_child(anchor)
      body_section.append_child(paragraph)
    linked_texts = {link.text for link in links}
    for value in values[:40]:
      if value in linked_texts or value in section_titles or value in section_items:
        continue
      paragraph = ElementNode(tag="p")
      paragraph.append_child(TextNode(text=value))
      body_section.append_child(paragraph)
  if len(body_section.children) == 1:
    only_child = body_section.children[0]
    if isinstance(only_child, ElementNode) and only_child.tag == "h2":
      body_section.children = []

  if nav_target is not None and nav_section is not None and nav_section.children:
    if nav_replace:
      nav_target.children = [nav_section]
    else:
      nav_target.children.append(nav_section)

  if body_replace:
    body_target.children = [body_section]
  else:
    if body_section.children:
      if body_has_substantial_content:
        body_target.children.append(body_section)
      else:
        body_target.children.insert(0, body_section)
  _prune_duplicate_nav_sections(document)
  return debug


def _maybe_apply_disclosure_hydration_fast_path(
  document: DocumentNode,
  *,
  runtime_sections: list[HydrationSection] | None,
  body_was_substantial: bool,
) -> RuntimeDataDebugInfo | None:
  if not body_was_substantial or not runtime_sections:
    return None
  populated_titles = populate_disclosure_sections(document, runtime_sections)
  if not all(section.title in populated_titles for section in runtime_sections):
    return None
  return RuntimeDataDebugInfo(
    confidence="high",
    fallback_reason="body-already-readable-with-disclosure-sections",
    source_summaries=(),
    used_site_specific_fallback=bool(populated_titles),
    body_was_substantial=True,
  )


def _runtime_has_network_payloads(runtime) -> bool:
  provider = getattr(runtime, "runtime_data_network_payloads", None)
  if not callable(provider):
    return False
  try:
    payloads = provider()
  except Exception:
    return False
  return isinstance(payloads, list) and bool(payloads)


def _is_missing_extracted_content(
  body_text: str,
  values: list[str],
  links: list[HydrationLink],
  sections: list[HydrationSection],
) -> bool:
  for value in values[:24]:
    if len(value) >= 40 and value not in body_text:
      return True
  for link in links[:12]:
    if link.text and link.text not in body_text:
      return True
  for section in sections[:8]:
    for item_text, _href in section.items[:6]:
      if section.role == "recovered":
        if item_text and item_text not in body_text and len(item_text) >= 24:
          return True
        continue
      if not _is_missing_hydration_item_candidate(item_text, href=_href):
        continue
      if item_text and item_text not in body_text:
        return True
  return False


def _has_missing_recovered_body_section(
  body_text: str,
  sections: list[HydrationSection],
) -> bool:
  for section in sections[:8]:
    if section.role != "recovered":
      continue
    missing_long_items = [
      item_text
      for item_text, _href in section.items[:8]
      if item_text and len(item_text) >= 24 and item_text not in body_text
    ]
    if len(missing_long_items) >= 2:
      return True
  return False


def _drop_duplicate_body_sections(
  sections: list[HydrationSection],
  *,
  body_text: str,
) -> list[HydrationSection]:
  normalized_body = _normalize_space(body_text)
  if not normalized_body:
    return sections
  return [
    section
    for section in sections
    if not _section_already_present_in_body(section, normalized_body)
  ]


def _section_already_present_in_body(
  section: HydrationSection,
  normalized_body: str,
) -> bool:
  title = _normalize_space(section.title)
  title_present = not title or title in normalized_body
  if not title_present:
    return False
  long_items: list[str] = []
  all_items: list[str] = []
  for item_text, _href in section.items:
    normalized_item = _normalize_space(item_text)
    if not normalized_item:
      continue
    all_items.append(normalized_item)
    if len(normalized_item) >= 24:
      long_items.append(normalized_item)
    if len(all_items) >= 10 and len(long_items) >= 6:
      break
  if not all_items:
    return False
  long_matches = sum(1 for item in long_items[:6] if item in normalized_body)
  exact_matches = sum(1 for item in all_items[:10] if item in normalized_body)
  if section.role == "recovered":
    return long_matches >= 2 or exact_matches >= 3
  return bool(title) and (long_matches >= 2 or exact_matches >= 3)


def _maybe_replace_with_alternate_html_document(
  document: TWebDocument,
  *,
  session,
) -> None:
  if session is None:
    return
  source = document.document.source
  parsed_source = urlparse(source)
  if parsed_source.scheme not in {"http", "https"}:
    return
  body = document.document.body
  if body is None:
    return
  quick_visible_text = _collect_inline_visible_text(body, character_limit=480).strip()
  if len(quick_visible_text) > 400:
    return
  current_visible_text = document.body_text(visible_only=True).strip()
  if len(current_visible_text) > 400:
    return
  candidate_href = _find_alternate_html_href(document.document, source=source)
  if candidate_href is None:
    return
  try:
    alternate_resource = fetch_resource(candidate_href, session=session)
  except Exception as exc:
    LOGGER.debug(
      "alternate html fallback fetch failed source=%s href=%s error=%s",
      sanitize_url_for_log(source),
      sanitize_url_for_log(candidate_href),
      exc,
    )
    return
  alternate_document = TWebDocument(parse_document(alternate_resource))
  alternate_visible_text = alternate_document.body_text(visible_only=True).strip()
  if len(alternate_visible_text) <= len(current_visible_text) + 40:
    return
  LOGGER.debug(
    "alternate html fallback replaced source=%s href=%s visible_before=%d visible_after=%d",
    sanitize_url_for_log(source),
    sanitize_url_for_log(candidate_href),
    len(current_visible_text),
    len(alternate_visible_text),
  )
  document.document = alternate_document.document


def _should_retry_sparse_post_load_async_drain(
  document: TWebDocument,
  runtime,
  *,
  had_pre_dispatch_pending_timer: bool = False,
) -> bool:
  body = document.document.body
  if body is None:
    return False
  raw_text = _document_raw_text(document.document)
  if len(raw_text) >= 80:
    return False
  inline_visible_text = _collect_inline_visible_text(body, character_limit=160).strip()
  if len(inline_visible_text) >= 40:
    return False
  visible_body_text = _document_visible_text(document.document)
  if inline_visible_text and len(visible_body_text) >= 40:
    return False
  if document.links() or document.form_controls():
    return False
  if not had_pre_dispatch_pending_timer and body.find_first("main") is None:
    return False
  try:
    # Only bootstrap chains that are already near-ready may unlock longer staged work.
    # A lone far-future timer must not make an otherwise empty page wait for seconds.
    if not runtime.has_pending_timer(max_time_advance_ms=1_000):
      return False
  except Exception:
    return False
  return True


def _should_drain_delayed_post_load_async_work(
  document: TWebDocument,
  runtime,
  *,
  delayed_script_count: int,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> bool:
  if _should_skip_expensive_page_events(
    document,
    delayed_script_count=delayed_script_count,
    metrics=metrics,
  ):
    return False
  try:
    next_timer_delay_ms = runtime.next_pending_timer_delay_ms()
    LOGGER.debug(
      "embedded delayed script pending timer delay_ms=%s delayed_scripts=%d",
      next_timer_delay_ms,
      delayed_script_count,
    )
    if next_timer_delay_ms is None or next_timer_delay_ms > 1_000:
      return False
  except Exception:
    return False
  summary = runtime.performance_summary()
  counts = summary.get("counts", {}) if isinstance(summary, dict) else {}
  if not isinstance(counts, dict):
    return False
  dom_mutations = int(counts.get("dom_mutations", 0) or 0)
  pending_jobs = int(counts.get("pending_jobs_executed", 0) or 0)
  timers_executed = int(counts.get("timers_executed", 0) or 0)
  return dom_mutations > 0 and (
    delayed_script_count > 0
    or pending_jobs > 0
    or timers_executed > 0
  )


def _find_alternate_html_href(document: DocumentNode, *, source: str) -> str | None:
  source_parts = urlparse(source)
  for anchor in document.find_all("a"):
    href = (anchor.attrs.get("href") or "").strip()
    if not href or "/html/?" not in href:
      continue
    resolved = resolve_resource_url(source, href)
    resolved_parts = urlparse(resolved)
    if resolved_parts.scheme not in {"http", "https"}:
      continue
    if resolved_parts.netloc != source_parts.netloc:
      continue
    return resolved
  return None


def _build_hydration_section_block(entry: HydrationSection) -> ElementNode:
  block = ElementNode(tag="section")
  title = ElementNode(tag="h3")
  title.append_child(TextNode(text=entry.title))
  block.append_child(title)
  item_limit = 200 if entry.role == "recovered" else 24
  items = entry.items[:item_limit]
  if entry.role != "recovered":
    block.append_child(_build_hydration_listing(items))
    return block

  paragraphs = [(item_text, item_href) for item_text, item_href in items if not item_href]
  links = [(item_text, item_href) for item_text, item_href in items if item_href]
  for item_text, _item_href in paragraphs:
    paragraph = ElementNode(
      tag="div",
      attrs={"data-tweb-recovered-text": "1", "style": "display: block;"},
    )
    paragraph.append_child(TextNode(text=item_text))
    block.append_child(paragraph)
  if links:
    block.append_child(_build_hydration_listing(links))
  return block


def _build_hydration_listing(
  items: tuple[tuple[str, str | None], ...] | list[tuple[str, str | None]],
) -> ElementNode:
  listing = ElementNode(
    tag="ul",
    attrs={"data-tweb-hydration-role": "section-items"},
  )
  for item_text, item_href in items:
    child = ElementNode(tag="li")
    if item_href:
      anchor = ElementNode(tag="a", attrs={"href": item_href})
      anchor.append_child(TextNode(text=item_text))
      child.append_child(anchor)
    else:
      child.append_child(TextNode(text=item_text))
    listing.append_child(child)
  return listing


def _extract_hidden_dom_sections(
  document: DocumentNode,
  *,
  viewport_columns: int = 160,
) -> list[HydrationSection]:
  body = document.body
  if body is None:
    return []
  root = body.find_first("main") or body
  style_context = build_style_context(
    document,
    viewport_columns=viewport_columns,
    session=None,
  )
  sections = _extract_hidden_dom_titled_sections(
    root,
    style_context=style_context,
  )
  items: list[tuple[str, str | None]] = []
  seen: set[tuple[str, str | None]] = set()
  _collect_hidden_dom_items(
    root,
    style_context=style_context,
    inherited_visible=True,
    hidden_ancestor=False,
    inside_anchor=False,
    items=items,
    seen=seen,
  )
  if len(items) >= 2:
    sections.append(HydrationSection(title="Recovered Content", items=tuple(items[:200]), role="recovered"))
  return sections


def _extract_hidden_dom_titled_sections(
  root: ElementNode,
  *,
  style_context: StyleContext,
) -> list[HydrationSection]:
  sections: list[HydrationSection] = []
  seen_titles: set[str] = set()
  for node, ancestors in _iter_element_paths(root):
    if node.tag not in {"section", "article", "div", "aside"}:
      continue
    properties = style_context.properties(node, inherited_visible=all(
      style_context.properties(ancestor, inherited_visible=True).visible
      for ancestor in ancestors
    ))
    if properties.visible:
      continue
    if _should_skip_hidden_dom_subtree(node):
      continue
    section = _hidden_dom_section_from_node(node)
    if section is None:
      continue
    key = section.title.casefold()
    if key in seen_titles:
      continue
    seen_titles.add(key)
    sections.append(section)
  return sections


def _hidden_dom_section_from_node(node: ElementNode) -> HydrationSection | None:
  heading = (
    node.find_first("h1")
    or node.find_first("h2")
    or node.find_first("h3")
    or node.find_first("h4")
  )
  if heading is None:
    return None
  title = _normalize_space(heading.text_content())
  if not title or len(title) < 4:
    return None
  items: list[tuple[str, str | None]] = []
  seen: set[tuple[str, str | None]] = set()
  for anchor in node.find_all("a"):
    href = anchor.attrs.get("href")
    text = _normalize_space(anchor.text_content())
    if not href or not _is_significant_hidden_dom_item(text, href=href):
      continue
    item = (text, href)
    if item in seen:
      continue
    seen.add(item)
    items.append(item)
  if len(items) >= 2:
    return HydrationSection(title=title, items=tuple(items[:12]), role="recovered")
  prose = _normalize_space(node.text_content())
  if len(prose) < 80:
    return None
  return HydrationSection(title=title, items=((prose, None),), role="recovered")


def _extract_sparse_document_link_sections(document: DocumentNode) -> list[HydrationSection]:
  body = document.body
  if body is None:
    return []
  items: list[tuple[str, str | None]] = []
  seen: set[tuple[str, str | None]] = set()
  for anchor in document.find_all("a"):
    href = anchor.attrs.get("href")
    text = " ".join(anchor.text_content().split())
    if not href or not text:
      continue
    if len(text) < 28 and " " not in text:
      continue
    if text.lower() in {"read more", "more", "here", "learn more"}:
      continue
    item = (text, href)
    if item in seen:
      continue
    seen.add(item)
    items.append(item)
    if len(items) >= 200:
      break
  if len(items) < 6:
    return []
  return [HydrationSection(title="Recovered Links", items=tuple(items), role="recovered")]


def _should_merge_sparse_document_link_sections_for_substantial_body(
  *,
  current_links: int,
  current_controls: int,
  hydration_body_length: int,
  has_hidden_content_hint: bool,
) -> bool:
  if current_links <= 0 or current_links > 120:
    return False
  if current_controls > 8:
    return False
  if hydration_body_length > 4_000:
    return False
  if has_hidden_content_hint:
    return current_links <= 120
  return current_links <= 24


def _collect_hidden_dom_items(
  node: ElementNode,
  *,
  style_context: StyleContext,
  inherited_visible: bool,
  hidden_ancestor: bool,
  inside_anchor: bool,
  items: list[tuple[str, str | None]],
  seen: set[tuple[str, str | None]],
) -> None:
  if node.tag in {"script", "style", "noscript", "template"}:
    return
  properties = style_context.properties(node, inherited_visible=inherited_visible)
  is_hidden = hidden_ancestor or not properties.visible
  if _should_skip_hidden_dom_subtree(node):
    return
  if is_hidden and not inside_anchor and node.tag == "a":
    href = node.attrs.get("href")
    text = " ".join(node.text_content().split())
    _append_hidden_dom_item(items, seen, text=text, href=href)
    inside_anchor = True
  for child in node.children:
    if isinstance(child, TextNode):
      if is_hidden and not inside_anchor:
        _append_hidden_dom_item(
          items,
          seen,
          text=" ".join(child.text.split()),
          href=None,
        )
      continue
    _collect_hidden_dom_items(
      child,
      style_context=style_context,
      inherited_visible=properties.visible,
      hidden_ancestor=is_hidden,
      inside_anchor=inside_anchor,
      items=items,
      seen=seen,
    )


def _append_hidden_dom_item(
  items: list[tuple[str, str | None]],
  seen: set[tuple[str, str | None]],
  *,
  text: str,
  href: str | None,
) -> None:
  if not _is_significant_hidden_dom_item(text, href=href):
    return
  entry = (text, href)
  if entry in seen:
    return
  seen.add(entry)
  items.append(entry)


def _is_significant_hidden_dom_item(
  text: str,
  *,
  href: str | None,
) -> bool:
  if not _is_significant_hydration_text(text, href=href):
    return False
  if href:
    return len(text) >= 12
  return len(text) >= 40


def _should_reset_runtime_after_embedded_script_error(
  error: JavaScriptRuntimeError,
  *,
  is_external: bool,
) -> bool:
  if not _should_reset_runtime_after_js_error(error):
    return False
  message = str(error).strip().lower()
  if message.startswith("null") and not is_external:
    return False
  return True


def _should_replay_bootstrap_script(source: str) -> bool:
  if not source or len(source) > 100_000:
    return False
  if _looks_like_jquery_library(source):
    return True
  declaration_count = len(re.findall(r"\b(?:const|let|var)\s+[A-Za-z_$]", source))
  if declaration_count < 5:
    return False
  side_effect_markers = (
    "document.",
    "document[",
    ".appendChild(",
    ".insertBefore(",
    ".removeChild(",
    ".addEventListener(",
    "setTimeout(",
    "setInterval(",
    "fetch(",
    "XMLHttpRequest",
    "new Vue(",
    "Vue.component(",
  )
  return not any(marker in source for marker in side_effect_markers)


def _looks_like_jquery_library(source: str) -> bool:
  header = source[:1_024]
  footer = source[-2_048:]
  return (
    "jQuery JavaScript Library" in header
    and ".jQuery=" in footer
    and ".$=" in footer
  )


def _replay_bootstrap_scripts(runtime, scripts: list[tuple[str, str | None]]) -> int:
  replayed = 0
  seen: set[str] = set()
  for source, source_url in scripts:
    if source in seen:
      continue
    seen.add(source)
    try:
      runtime.eval(source, source_url=source_url, drain_timers=False)
    except JavaScriptRuntimeError as exc:
      LOGGER.debug(
        "embedded bootstrap script replay failed src=%s error=%s",
        sanitize_url_for_log(source_url) if source_url else "-",
        exc,
      )
      continue
    replayed += 1
  return replayed


def _should_skip_hidden_dom_subtree(node: ElementNode) -> bool:
  if node.tag in {"header", "footer", "nav"}:
    return True
  if _looks_like_loading_indicator(node):
    return True
  if _looks_like_content_container(node):
    return False
  text_length = len(_normalize_space(node.text_content()))
  if node.tag == "aside":
    return text_length <= 160
  if _looks_like_nav_container(node):
    return text_length <= 160
  return False


def _filter_hydration_values(values: list[str]) -> list[str]:
  return [value for value in values if _is_significant_hydration_text(value)]


def _filter_hydration_links(links: list[HydrationLink]) -> list[HydrationLink]:
  return [
    link
    for link in links
    if _is_significant_hydration_text(link.text, href=link.href)
  ]


def _filter_hydration_sections(
  sections: list[HydrationSection],
) -> list[HydrationSection]:
  filtered_sections: list[HydrationSection] = []
  for section in sections:
    items = tuple(
      (item_text, item_href)
      for item_text, item_href in section.items
      if _is_significant_hydration_text(item_text, href=item_href)
    )
    if not items:
      continue
    filtered_sections.append(
      HydrationSection(
        title=" ".join(section.title.split()),
        role=section.role,
        items=items,
      )
    )
  return filtered_sections


def _drop_low_signal_hydration_sections(
  sections: list[HydrationSection],
  *,
  body_has_substantial_content: bool,
) -> list[HydrationSection]:
  if not body_has_substantial_content:
    return sections
  low_signal_titles = {"items", "list", "overviewfiles", "runtime sections"}
  return [
    section
    for section in sections
    if section.role == "recovered" or section.title.casefold() not in low_signal_titles
  ]


def _is_significant_hydration_text(
  text: str,
  *,
  href: str | None = None,
) -> bool:
  normalized = " ".join(text.split())
  if not normalized:
    return False
  folded = normalized.casefold()
  if UUID_LIKE_RE.fullmatch(normalized):
    return False
  if ISO_DATETIME_LIKE_RE.fullmatch(normalized):
    return False
  if "arn:aws:iam::" in folded:
    return False
  if "rum-put-batch-metrics" in folded:
    return False
  if folded.startswith("ap-") and ":3" in folded and " " not in folded[:64]:
    return False
  if NON_HTTP_URL_LIKE_RE.fullmatch(normalized):
    scheme = normalized.split(":", 1)[0].lower()
    if scheme not in {"http", "https"}:
      return False
  return True


def _is_missing_hydration_item_candidate(
  text: str,
  *,
  href: str | None = None,
) -> bool:
  return bool(href) and _is_significant_hydration_text(text, href=href)


def _append_section_items_to_existing_heading(
  body: ElementNode,
  section: HydrationSection,
) -> bool:
  heading = _find_heading_with_text(body, section.title)
  if heading is None:
    return False
  parent = _find_parent_element(body, heading)
  if parent is None:
    return False
  for item_text, _href in section.items[:3]:
    if item_text and item_text in parent.text_content():
      return False
  listing = ElementNode(tag="ul", attrs={"data-tweb-hydration": "1", "data-tweb-hydration-role": "section-items"})
  for item_text, item_href in section.items[:12]:
    child = ElementNode(tag="li")
    if item_href:
      anchor = ElementNode(tag="a", attrs={"href": item_href})
      anchor.append_child(TextNode(text=item_text))
      child.append_child(anchor)
    else:
      child.append_child(TextNode(text=item_text))
    listing.append_child(child)
  insert_at = parent.children.index(heading) + 1
  parent.children.insert(insert_at, listing)
  return True


def _find_heading_with_text(body: ElementNode, text: str) -> ElementNode | None:
  normalized = " ".join(text.split())
  if not normalized:
    return None
  for heading_name in ("h1", "h2", "h3"):
    for candidate in body.find_all(heading_name):
      if " ".join(candidate.text_content().split()) == normalized:
        return candidate
  return None


def _find_parent_element(root: ElementNode, target: ElementNode) -> ElementNode | None:
  for child in root.children:
    if child is target:
      return root
    if isinstance(child, ElementNode):
      parent = _find_parent_element(child, target)
      if parent is not None:
        return parent
  return None


def _build_ancestor_specs(
  root: ElementNode | None,
  target: ElementNode | None,
) -> list[tuple[str, dict[str, str]]] | None:
  if root is None or target is None:
    return None
  chain = _find_ancestor_chain(root, target)
  if not chain:
    return None
  return [(node.tag, dict(node.attrs)) for node in chain]


def _find_ancestor_chain(
  root: ElementNode,
  target: ElementNode,
  ancestors: tuple[ElementNode, ...] = (),
) -> list[ElementNode] | None:
  for child in root.children:
    if child is target:
      return list(ancestors)
    if isinstance(child, ElementNode):
      found = _find_ancestor_chain(child, target, ancestors + (child,))
      if found is not None:
        return found
  return None


def _select_hydration_body_target(
  body: ElementNode,
  *,
  initial_main_attrs: dict[str, str] | None = None,
  initial_main_ancestor_specs: list[tuple[str, dict[str, str]]] | None = None,
) -> tuple[ElementNode, bool, bool]:
  main = body.find_first("main")
  if main is None:
    if initial_main_attrs is not None:
      main = ElementNode(tag="main", attrs=dict(initial_main_attrs))
      parent = _locate_recreated_main_parent(body, initial_main_ancestor_specs) or body
      insert_at = _find_main_insertion_index(parent)
      parent.children.insert(insert_at, main)
      return (main, False, True)
    return (body, False, True)
  for node, _ancestors in _iter_element_paths(main):
    if not _looks_like_content_container(node):
      continue
    if len(node.text_content().strip()) > 40:
      continue
    return (node, False, False)
  split_layout_target = _find_non_nav_main_child_target(main)
  if split_layout_target is not None:
    return (split_layout_target, False, False)
  placeholder = _find_loading_placeholder_container(main)
  if placeholder is not None:
    return (placeholder, True, False)
  return (main, False, True)


def _find_non_nav_main_child_target(main: ElementNode) -> ElementNode | None:
  element_children = [child for child in main.children if isinstance(child, ElementNode)]
  if len(element_children) < 2:
    return None
  nav_like_children = [child for child in element_children if _looks_like_nav_container(child)]
  if not nav_like_children:
    return None
  candidates = [
    child
    for child in element_children
    if child not in nav_like_children
    and child.tag not in {"script", "style"}
    and len(child.text_content().strip()) <= 40
  ]
  if len(candidates) != 1:
    return None
  return candidates[0]


def _locate_recreated_main_parent(
  body: ElementNode,
  ancestor_specs: list[tuple[str, dict[str, str]]] | None,
) -> ElementNode | None:
  if not ancestor_specs:
    return None
  current = body
  for tag, attrs in ancestor_specs:
    match = _find_child_by_tag_and_attrs(current, tag, attrs)
    if match is None:
      break
    current = match
  return current


def _ensure_recreated_main_parent(
  body: ElementNode,
  ancestor_specs: list[tuple[str, dict[str, str]]] | None,
) -> ElementNode | None:
  if not ancestor_specs:
    return None
  current = body
  for tag, attrs in ancestor_specs:
    match = _find_child_by_tag_and_attrs(current, tag, attrs)
    if match is None:
      match = ElementNode(tag=tag, attrs=dict(attrs))
      insert_at = _find_main_insertion_index(current)
      current.children.insert(insert_at, match)
    current = match
  return current


def _find_child_by_tag_and_attrs(
  root: ElementNode,
  tag: str,
  attrs: dict[str, str],
) -> ElementNode | None:
  for child in root.children:
    if not isinstance(child, ElementNode):
      continue
    if child.tag != tag:
      continue
    if all(child.attrs.get(key) == value for key, value in attrs.items()):
      return child
  return None


def _find_element_with_id(root: ElementNode, element_id: str) -> ElementNode | None:
  for node, _ancestors in _iter_element_paths(root):
    if node.attrs.get("id") == element_id:
      return node
  return None


def _find_main_insertion_index(parent: ElementNode) -> int:
  for index, child in enumerate(parent.children):
    if not isinstance(child, ElementNode):
      continue
    if child.tag in {"footer", "script"}:
      return index
  return len(parent.children)


def _select_hydration_nav_target(body: ElementNode) -> tuple[ElementNode | None, bool]:
  main = body.find_first("main")
  for node, ancestors in _iter_element_paths(body):
    if node.tag != "aside":
      continue
    if main is not None and main in ancestors:
      continue
    return (node, False)
  if main is None:
    return (None, False)
  for node, _ancestors in _iter_element_paths(main):
    if not _looks_like_nav_container(node):
      continue
    if len(node.text_content().strip()) > 40:
      continue
    return (node, True)
  for node, ancestors in _iter_element_paths(body):
    if node.tag != "nav":
      continue
    if main is not None and main in ancestors:
      continue
    if len(node.text_content().strip()) > 40:
      continue
    return (node, False)
  return (None, False)


def _partition_hydration_sections(
  sections: list[HydrationSection],
) -> tuple[list[HydrationSection], list[HydrationSection]]:
  body_sections: list[HydrationSection] = []
  nav_sections: list[HydrationSection] = []
  for section in sections:
    if _is_topic_nav_section(section):
      nav_sections.append(section)
    else:
      body_sections.append(section)
  return body_sections, nav_sections


def _drop_duplicate_nav_body_sections(
  sections: list[HydrationSection],
  nav_target: ElementNode | None,
) -> list[HydrationSection]:
  if nav_target is None:
    return sections
  nav_text = _normalize_space(nav_target.text_content())
  if not nav_text:
    return sections
  filtered: list[HydrationSection] = []
  for section in sections:
    if _looks_like_duplicate_nav_body_section(section, nav_text):
      continue
    filtered.append(section)
  return filtered


def _looks_like_duplicate_nav_body_section(
  section: HydrationSection,
  nav_text: str,
) -> bool:
  title = _normalize_space(section.title)
  items = [_normalize_space(item_text) for item_text, _href in section.items if _normalize_space(item_text)]
  if len(items) < 4:
    return False
  if any(len(item) > 40 for item in items):
    return False
  if title.casefold() not in {"categories", "category", "recovered links"}:
    return False
  matched_items = sum(1 for item in items if item in nav_text)
  return matched_items >= max(4, len(items) - 1)


def _prune_duplicate_nav_sections(document: DocumentNode) -> None:
  body = document.body
  if body is None:
    return
  nav_target, _nav_replace = _select_hydration_nav_target(body)
  main = body.find_first("main")
  if nav_target is None or main is None:
    return
  nav_text = _normalize_space(nav_target.text_content())
  if not nav_text:
    return
  duplicate_sections: list[ElementNode] = []
  for node, _ancestors in _iter_element_paths(main):
    if node.tag != "section":
      continue
    section = _hydration_section_from_dom(node)
    if section is None:
      continue
    if _looks_like_duplicate_nav_body_section(section, nav_text):
      duplicate_sections.append(node)
  for section in duplicate_sections:
    parent = _find_parent_element(main, section)
    if parent is None:
      continue
    if section in parent.children:
      parent.children.remove(section)


def _hydration_section_from_dom(node: ElementNode) -> HydrationSection | None:
  heading = node.find_first("h3")
  if heading is None:
    return None
  title = _normalize_space(heading.text_content())
  if not title:
    return None
  items: list[tuple[str, str | None]] = []
  for child in node.find_all("li"):
    text = _normalize_space(child.text_content())
    if not text:
      continue
    anchor = child.find_first("a")
    items.append((text, anchor.attrs.get("href") if anchor is not None else None))
  if len(items) < 2:
    return None
  return HydrationSection(title=title, items=tuple(items))


def _is_topic_nav_section(section: HydrationSection) -> bool:
  if section.role == "nav":
    return True
  items = [
    (text, href)
    for text, href in section.items
    if isinstance(href, str) and href
  ]
  if len(items) < 2:
    return False
  topic_links = [href for _text, href in items if href.startswith("/topic/") and "/n/" not in href]
  if len(topic_links) != len(items):
    return False
  return all(len(" ".join(text.split())) <= 24 for text, _href in items)


def _find_loading_placeholder_container(root: ElementNode) -> ElementNode | None:
  for node, ancestors in _iter_element_paths(root):
    if not _looks_like_loading_indicator(node):
      continue
    for ancestor in reversed(ancestors):
      if ancestor.tag not in {"div", "section", "article", "main"}:
        continue
      if len(ancestor.text_content().strip()) > 40:
        continue
      return ancestor
    if root.tag in {"div", "section", "article", "main"} and len(root.text_content().strip()) <= 40:
      return root
  return None


def _looks_like_loading_indicator(node: ElementNode) -> bool:
  values = [
    node.tag,
    node.attrs.get("class", ""),
    node.attrs.get("id", ""),
    node.attrs.get("aria-label", ""),
  ]
  haystack = " ".join(value.lower() for value in values if value)
  return any(token in haystack for token in ("loading", "loader", "spinner", "skeleton", "placeholder", "shimmer", "pending", "progress"))


def _looks_like_nav_container(node: ElementNode) -> bool:
  values = [
    node.tag,
    node.attrs.get("class", ""),
    node.attrs.get("id", ""),
    node.attrs.get("aria-label", ""),
  ]
  haystack = " ".join(value.lower() for value in values if value)
  return any(token in haystack for token in ("nav", "menu", "category", "sidebar", "aside", "toc"))


def _normalize_space(value: str) -> str:
  return " ".join(value.split()).strip()


def _looks_like_content_container(node: ElementNode) -> bool:
  values = [
    node.tag,
    node.attrs.get("class", ""),
    node.attrs.get("id", ""),
    node.attrs.get("aria-label", ""),
  ]
  haystack = " ".join(value.lower() for value in values if value)
  return any(
    token in haystack
    for token in (
      "timeline__body",
      "timeline-body",
      "feed-body",
      "content-body",
      "content-panel",
      "article-list",
    )
  )


def _contains_hydration_marker(node: ElementNode) -> bool:
  for candidate in node.find_all("section"):
    if candidate.attrs.get("data-tweb-hydration") == "1":
      return True
  return False


def _iter_element_paths(
  node: ElementNode,
  ancestors: tuple[ElementNode, ...] = (),
):
  yield (node, ancestors)
  next_ancestors = ancestors + (node,)
  for child in node.children:
    if isinstance(child, ElementNode):
      yield from _iter_element_paths(child, next_ancestors)


def _looks_like_client_script_failure(text: str) -> bool:
  lowered = text.lower()
  explicit_markers = (
    "google 検索にアクセスできない場合",
    "access google search",
    "enable javascript to continue search",
    "検索を続行するには、javascript を有効",
  )
  if any(marker in lowered for marker in explicit_markers):
    return True
  markers = (
    "javascript is not available",
    "javascript is disabled",
    "please enable javascript",
    "supported browser",
    "something went wrong",
    "try again",
    "privacy related extensions",
    "申し訳ありません",
    "障害が発生しております",
    "復旧作業中",
    "問い合わせフォーム",
  )
  return sum(1 for marker in markers if marker in lowered) >= 2


def _looks_like_client_script_failure_shell(document: TWebDocument) -> bool:
  return _looks_like_client_script_failure(_document_raw_text(document.document))


def _prune_visible_client_failure_shells(
  document: DocumentNode,
  *,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> None:
  body = document.body
  if body is None:
    return
  raw_body_text = _document_raw_text(document)
  if not raw_body_text:
    return
  looks_like_failure = _looks_like_client_script_failure(raw_body_text)
  if not looks_like_failure and not _looks_like_loading_cluster(raw_body_text):
    return
  if metrics is not None and metrics.visible_body_len() <= 240:
    return
  candidates = _find_prunable_client_failure_shells(
    body,
    document,
    allow_loading_clusters=not looks_like_failure,
  )
  if not looks_like_failure and not candidates:
    return
  for candidate in candidates:
    parent = _find_parent_element(body, candidate)
    if parent is None:
      continue
    parent.children = [child for child in parent.children if child is not candidate]


def _prune_inline_loading_placeholders(
  document: DocumentNode,
  *,
  metrics: _ExecutionDocumentMetrics | None = None,
) -> None:
  body = document.body
  if body is None:
    return
  raw_body_text = _document_raw_text(document).casefold()
  if not raw_body_text or "load" not in raw_body_text:
    return
  inline_visible_preview = _collect_inline_visible_text(body, character_limit=384).strip()
  body_visible_len = len(inline_visible_preview)
  if 240 < body_visible_len < 320:
    body_visible_len = metrics.visible_body_len() if metrics is not None else len(_collect_visible_text(body, document).strip())
  if body_visible_len <= 240:
    return
  candidates: list[ElementNode] = []
  for node, _ancestors in _iter_element_paths(body):
    if node is body or node.tag not in {"div", "section", "article", "span"}:
      continue
    if not _looks_like_loading_indicator(node):
      continue
    visible_text = _collect_inline_visible_text(node, character_limit=64).strip()
    normalized_visible_text = visible_text.casefold()
    if normalized_visible_text not in {"loading...", "loading", "loader", "notice loading..."}:
      continue
    if body_visible_len - len(visible_text) <= 240:
      continue
    candidates.append(node)
  for candidate in candidates:
    parent = _find_parent_element(body, candidate)
    if parent is None:
      continue
    parent.children = [child for child in parent.children if child is not candidate]


def _find_prunable_client_failure_shells(
  body: ElementNode,
  document: DocumentNode,
  *,
  allow_loading_clusters: bool = False,
) -> list[ElementNode]:
  candidates: list[ElementNode] = []

  def walk(node: ElementNode) -> None:
    if node is body:
      for child in node.children:
        if isinstance(child, ElementNode):
          walk(child)
      return
    if _is_prunable_client_failure_shell(
      node,
      body,
      document,
      allow_loading_clusters=allow_loading_clusters,
    ):
      candidates.append(node)
      return
    for child in node.children:
      if isinstance(child, ElementNode):
        walk(child)

  walk(body)
  return candidates


def _is_prunable_client_failure_shell(
  node: ElementNode,
  body: ElementNode,
  document: DocumentNode,
  *,
  allow_loading_clusters: bool = False,
) -> bool:
  if node.tag not in {"div", "section", "article", "aside", "main"}:
    return False
  visible_text = _collect_visible_text(node, document).strip()
  if not visible_text or len(visible_text) > 500:
    return False
  if not _looks_like_client_script_failure(visible_text):
    if not allow_loading_clusters or not _looks_like_loading_cluster(visible_text):
      return False
  visible_outside = _collect_visible_text(body, document, exclude=node).strip()
  return len(visible_outside) > 240 and not _looks_like_client_script_failure(visible_outside)


def _looks_like_loading_cluster(text: str) -> bool:
  normalized = " ".join(text.split()).strip().casefold()
  if not normalized:
    return False
  loading_count = normalized.count("loading...")
  if loading_count >= 3:
    return True
  tokens = normalized.split()
  if len(tokens) < 3:
    return False
  loading_like_tokens = {"loading...", "loading", "loader", "placeholder"}
  matched = sum(1 for token in tokens if token in loading_like_tokens)
  return matched >= 3 and matched >= max(3, len(tokens) // 2)


def _log_browser_render_decision(
  source: str,
  action: str,
  *,
  policy: BrowserRenderPolicy,
  reason: str,
  **details,
) -> None:
  detail_parts = [f"{key}={value}" for key, value in details.items()]
  suffix = f" {' '.join(detail_parts)}" if detail_parts else ""
  LOGGER.debug(
    "browser-render decision source=%s action=%s policy=%s reason=%s%s",
    sanitize_url_for_log(source),
    action,
    policy,
    reason,
    suffix,
  )


def _browser_render_trigger(policy: BrowserRenderPolicy) -> BrowserRenderTrigger:
  if policy == "always":
    return "manual-retry"
  if policy == "auto":
    return "auto-fallback"
  return "disabled"


def _classify_browser_render_fetch_error(exc: Exception) -> str:
  message = str(exc).lower()
  if "provider unavailable" in message:
    return "provider-unavailable"
  if "unavailable" in message and "chrome/chromium not found" in message:
    return "provider-unavailable"
  if "only supports remote urls" in message:
    return "unsupported-target"
  if "empty dom" in message:
    return "empty-dom"
  if "failed to render" in message:
    return "render-command-failed"
  return exc.__class__.__name__.lower()


def _normalize_browser_render_result(
  result: BrowserRenderResult | Resource,
  *,
  request: BrowserRenderRequest,
) -> Resource:
  if isinstance(result, Resource):
    return result
  return Resource(
    source=result.source or request.target,
    content=result.content,
    headers=result.headers,
    status_code=result.status_code,
  )


def _invoke_browser_render_fetcher(
  browser_render_fetcher: BrowserRenderFetcher,
  *,
  request: BrowserRenderRequest,
  session,
) -> Resource:
  try:
    signature = inspect.signature(browser_render_fetcher)
    parameters = list(signature.parameters.values())
  except (TypeError, ValueError):
    parameters = []
  if parameters:
    first = parameters[0]
    if first.name == "request" or first.annotation is BrowserRenderRequest:
      result = browser_render_fetcher(request, session=session)
    else:
      result = browser_render_fetcher(request.target, session=session)
  else:
    result = browser_render_fetcher(request, session=session)
  return _normalize_browser_render_result(result, request=request)


def _contains_client_render_bailout_marker(body: ElementNode | None) -> bool:
  if body is None:
    return False
  for template in body.find_all("template"):
    if template.attrs.get("data-dgst") == "BAILOUT_TO_CLIENT_SIDE_RENDERING":
      return True
  return False


def _maybe_replace_with_browser_rendered_document(
  document: TWebDocument,
  *,
  session=None,
  initial_had_main: bool,
  browser_render_policy: BrowserRenderPolicy,
  runtime_sections: list[HydrationSection] | None = None,
  browser_render_fetcher: BrowserRenderFetcher | None = None,
) -> None:
  browser_render_fetcher = browser_render_fetcher or fetch_rendered_resource
  trigger = _browser_render_trigger(browser_render_policy)
  if browser_render_policy == "never":
    _log_browser_render_decision(
      document.document.source,
      "skip",
      policy=browser_render_policy,
      reason="policy-never",
      trigger=trigger,
    )
    return
  if browser_render_policy == "auto" and getattr(document._js_runtime, "reload_target", None) is not None:
    _log_browser_render_decision(
      document.document.source, "skip", policy=browser_render_policy,
      reason="javascript-reload-pending", trigger=trigger,
    )
    return
  source = document.document.source
  if not source.startswith(("http://", "https://")):
    _log_browser_render_decision(
      source,
      "skip",
      policy=browser_render_policy,
      reason="non-http-source",
      trigger=trigger,
    )
    return
  body = document.document.body
  current_main = body.find_first("main") if body is not None else None
  current_has_main = body.find_first("main") is not None if body is not None else False
  has_bailout_marker = _contains_client_render_bailout_marker(body)
  loading_placeholder = _find_loading_placeholder_container(current_main) if current_main is not None else None
  has_loading_placeholder = loading_placeholder is not None
  has_runtime_sections = bool(runtime_sections)
  has_hydration_root_hint = _document_has_hydration_root_hint(document.document)
  raw_text = _document_raw_text(document.document)
  current_text = raw_text
  should_try = browser_render_policy == "always"
  decision_reason = "policy-always" if should_try else "initial"
  if browser_render_policy == "auto":
    substantial_bailout_main = False
    hydration_can_fill_bailout_main = False
    if has_bailout_marker and current_main is not None:
      bailout_main_text = _collect_visible_text(current_main, document.document).strip()
      substantial_bailout_main = (
        len(bailout_main_text) > 400
        and not _looks_like_client_script_failure(bailout_main_text)
      )
      if substantial_bailout_main:
        should_try = False
        decision_reason = "main-visible-text-substantial-despite-bailout-marker"
      elif has_hydration_root_hint:
        hydration_can_fill_bailout_main = True
        should_try = False
        decision_reason = "hydration-hints-can-fill-main-despite-bailout-marker"
    structural_signal = (
      (initial_had_main and not current_has_main)
      or has_bailout_marker
      or has_loading_placeholder
    )
    if structural_signal and not substantial_bailout_main and not hydration_can_fill_bailout_main:
      should_try = True
      reasons: list[str] = []
      if initial_had_main and not current_has_main:
        reasons.append("main-removed")
      if has_bailout_marker:
        reasons.append("client-render-bailout-marker")
      if has_loading_placeholder:
        reasons.append("loading-placeholder")
      decision_reason = ",".join(reasons)
    elif raw_text and not _looks_like_client_script_failure(raw_text):
      should_try = False
      decision_reason = "raw-text-looks-healthy"
    else:
      current_text = _document_visible_text(document.document)
      should_try = (
        _looks_like_client_script_failure(current_text)
        or (not current_text and _looks_like_client_script_failure(raw_text))
      )
      if _looks_like_client_script_failure(current_text):
        decision_reason = "visible-text-looks-like-client-failure"
      elif not current_text and _looks_like_client_script_failure(raw_text):
        decision_reason = "raw-text-looks-like-client-failure-visible-empty"
      else:
        decision_reason = "visible-text-looks-healthy"
  if not should_try:
    _log_browser_render_decision(
      source,
      "skip",
      policy=browser_render_policy,
      reason=decision_reason,
      trigger=trigger,
      initial_had_main=initial_had_main,
      current_has_main=current_has_main,
      has_bailout_marker=has_bailout_marker,
      has_loading_placeholder=has_loading_placeholder,
      raw_text_len=len(raw_text),
      visible_text_len=len(current_text),
      runtime_sections=has_runtime_sections,
    )
    return
  _log_browser_render_decision(
    source,
    "try",
    policy=browser_render_policy,
    reason=decision_reason,
    trigger=trigger,
    initial_had_main=initial_had_main,
    current_has_main=current_has_main,
    has_bailout_marker=has_bailout_marker,
    has_loading_placeholder=has_loading_placeholder,
    raw_text_len=len(raw_text),
    visible_text_len=len(current_text),
    runtime_sections=has_runtime_sections,
  )
  if (
    should_try
    and browser_render_policy == "auto"
    and has_runtime_sections
  ):
    _log_browser_render_decision(
      source,
      "skip",
      policy=browser_render_policy,
      reason="runtime-sections-can-fill-main",
      trigger=trigger,
      current_has_main=current_has_main,
      runtime_sections=has_runtime_sections,
    )
    return
  if (
    should_try
    and browser_render_policy == "auto"
    and has_loading_placeholder
    and current_main is not None
  ):
    if _has_substantial_visible_content_outside_placeholder(
      current_main,
      loading_placeholder,
      document.document,
    ):
      visible_text_outside_placeholder = _collect_visible_text(
        current_main,
        document.document,
        exclude=loading_placeholder,
      ).strip()
      _log_browser_render_decision(
        source,
        "skip",
        policy=browser_render_policy,
        reason="substantial-content-outside-loading-placeholder",
        trigger=trigger,
        visible_text_len=len(visible_text_outside_placeholder),
      )
      return
    current_main_text = _collect_visible_text(current_main, document.document)
    if len(current_main_text) > 400 and not _looks_like_client_script_failure(current_main_text):
      _log_browser_render_decision(
        source,
        "skip",
        policy=browser_render_policy,
        reason="main-visible-text-substantial-despite-loading-placeholder",
        trigger=trigger,
        visible_text_len=len(current_main_text),
      )
      return
  try:
    request = BrowserRenderRequest(target=source)
    rendered_resource = _invoke_browser_render_fetcher(
      browser_render_fetcher,
      request=request,
      session=session,
    )
    rendered = TWebDocument(parse_document(rendered_resource))
  except Exception as exc:
    _log_browser_render_decision(
      source,
      "skip",
      policy=browser_render_policy,
      reason="browser-render-fetch-failed",
      trigger=trigger,
      failure_class=_classify_browser_render_fetch_error(exc),
      error=repr(exc),
    )
    return
  rendered_text = rendered.body_text().strip()
  rendered_body = rendered.document.body
  rendered_has_main = rendered_body.find_first("main") is not None if rendered_body is not None else False
  if not rendered_text:
    _log_browser_render_decision(
      source,
      "skip",
      policy=browser_render_policy,
      reason="browser-rendered-document-empty",
      trigger=trigger,
    )
    return
  if not rendered_has_main and len(rendered_text) <= len(current_text):
    _log_browser_render_decision(
      source,
      "skip",
      policy=browser_render_policy,
      reason="browser-rendered-document-not-better",
      trigger=trigger,
      rendered_has_main=rendered_has_main,
      rendered_text_len=len(rendered_text),
      current_text_len=len(current_text),
    )
    return
  document.document.source = rendered.document.source
  document.document.children = rendered.document.children
  document.document.sync_title()
  document._js_runtime = None
  document.browser_rendered_via_chrome = True
  _log_browser_render_decision(
    source,
    "apply",
    policy=browser_render_policy,
    reason="browser-rendered-document-accepted",
    trigger=trigger,
    rendered_has_main=rendered_has_main,
    rendered_text_len=len(rendered_text),
    current_text_len=len(current_text),
  )
  register_parents_for_interactions(document.document)
  sync_interactive_document(document.document)


def _iter_document_elements(document: DocumentNode):
  for child in document.children:
    if isinstance(child, ElementNode):
      yield child
      yield from _iter_descendant_elements(child)


def _iter_descendant_elements(node: ElementNode):
  for child in node.children:
    if isinstance(child, ElementNode):
      yield child
      yield from _iter_descendant_elements(child)


def _matches_filters(
  node: ElementNode,
  name: str | None = None,
  attrs: dict[str, str] | None = None,
) -> bool:
  if name is not None and node.tag != name:
    return False
  if attrs:
    for key, value in attrs.items():
      if node.attrs.get(key) != value:
        return False
  return True


def _select_nodes(root: ElementNode, selector: str) -> list[ElementNode]:
  matched: list[ElementNode] = []
  for group in _split_selector_groups(selector):
    tokens = _tokenize_selector_group(group)
    if not tokens:
      continue

    current: list[ElementNode] = [root]
    for index, (combinator, token) in enumerate(tokens):
      matcher = _parse_simple_selector(token)
      next_nodes: list[ElementNode] = []
      for base in current:
        if index == 0:
          candidates = [base]
          candidates.extend(_iter_descendant_elements(base))
        elif combinator == ">":
          candidates = [
            child for child in base.children if isinstance(child, ElementNode)
          ]
        else:
          candidates = list(_iter_descendant_elements(base))
        for node in candidates:
          if matcher(node):
            next_nodes.append(node)
      current = _dedupe_nodes(next_nodes)
    matched.extend(current)
  return _dedupe_nodes(matched)


def _parse_simple_selector(token: str):
  match = SELECTOR_TOKEN_RE.match(token)
  if match is None:
    raise ValueError(f"unsupported selector: {token}")

  tag = match.group("tag")
  selector_id = match.group("id")
  selector_classes = [item[1:] for item in re.findall(r"\.[a-zA-Z][a-zA-Z0-9_-]*", match.group("class"))]
  attrs_text = match.group("attrs") or ""
  attr_filters: list[tuple[str, str | None, str | None]] = []
  if attrs_text:
    for attr_match in re.findall(r"\[[^\]]+\]", attrs_text):
      parsed = ATTR_SELECTOR_RE.match(attr_match)
      if parsed is None:
        raise ValueError(f"unsupported selector: {token}")
      raw_value = parsed.group("value")
      attr_filters.append(
        (
          parsed.group("name"),
          raw_value.strip("\"'") if raw_value is not None else None,
          parsed.group("operator"),
        )
      )

  def matcher(node: ElementNode) -> bool:
    if tag is not None and node.tag != tag:
      return False
    if selector_id is not None and node.attrs.get("id") != selector_id[1:]:
      return False
    if selector_classes:
      classes = set(node.attrs.get("class", "").split())
      if not all(class_name in classes for class_name in selector_classes):
        return False
    for attr_name, attr_value, attr_operator in attr_filters:
      actual_value = node.attrs.get(attr_name)
      if actual_value is None:
        return False
      if attr_value is None:
        continue
      if attr_operator in {None, "="}:
        if actual_value != attr_value:
          return False
      elif attr_operator == "^=":
        if not actual_value.startswith(attr_value):
          return False
      elif attr_operator == "$=":
        if not actual_value.endswith(attr_value):
          return False
      elif attr_operator == "*=":
        if attr_value not in actual_value:
          return False
      elif attr_operator == "~=":
        if attr_value not in actual_value.split():
          return False
      elif attr_operator == "|=":
        if actual_value != attr_value and not actual_value.startswith(f"{attr_value}-"):
          return False
      else:
        raise ValueError(f"unsupported selector: {token}")
    return True

  return matcher


def _split_selector_groups(selector: str) -> list[str]:
  groups: list[str] = []
  current: list[str] = []
  bracket_depth = 0
  quote: str | None = None
  for char in selector:
    if quote is not None:
      current.append(char)
      if char == quote:
        quote = None
      continue
    if char in {'"', "'"}:
      quote = char
      current.append(char)
      continue
    if char == "[":
      bracket_depth += 1
      current.append(char)
      continue
    if char == "]":
      bracket_depth = max(0, bracket_depth - 1)
      current.append(char)
      continue
    if char == "," and bracket_depth == 0:
      part = "".join(current).strip()
      if part:
        groups.append(part)
      current = []
      continue
    current.append(char)
  part = "".join(current).strip()
  if part:
    groups.append(part)
  return groups


def _tokenize_selector_group(selector: str) -> list[tuple[str | None, str]]:
  tokens: list[tuple[str | None, str]] = []
  current: list[str] = []
  bracket_depth = 0
  quote: str | None = None
  next_combinator: str | None = None

  def flush() -> None:
    nonlocal current, next_combinator
    token = "".join(current).strip()
    if token:
      tokens.append((next_combinator, token))
      next_combinator = " "
    current = []

  for char in selector:
    if quote is not None:
      current.append(char)
      if char == quote:
        quote = None
      continue
    if char in {'"', "'"}:
      quote = char
      current.append(char)
      continue
    if char == "[":
      bracket_depth += 1
      current.append(char)
      continue
    if char == "]":
      bracket_depth = max(0, bracket_depth - 1)
      current.append(char)
      continue
    if bracket_depth == 0 and char == ">":
      flush()
      next_combinator = ">"
      continue
    if bracket_depth == 0 and char.isspace():
      flush()
      continue
    current.append(char)
  flush()
  if tokens:
    first_combinator, first_token = tokens[0]
    tokens[0] = (None, first_token)
  return tokens


def _dedupe_nodes(nodes: list[ElementNode]) -> list[ElementNode]:
  seen: set[int] = set()
  unique: list[ElementNode] = []
  for node in nodes:
    node_id = id(node)
    if node_id in seen:
      continue
    seen.add(node_id)
    unique.append(node)
  return unique
