from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re
from threading import Lock
import time
from typing import Any

from .dom import DocumentNode, ElementNode, TextNode
from .fetcher import (
  ASSET_FETCH_MAX_WORKERS,
  DEFAULT_HEADERS,
  FetchError,
  Resource,
  create_persistent_session_pool,
  fetch_resource,
  resolve_resource_url,
)

COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}")
MEDIA_RE = re.compile(r"@media\s+(?P<query>[^{]+)\{", re.IGNORECASE)
SIMPLE_SELECTOR_RE = re.compile(
  r"^(?P<tag>[a-zA-Z][a-zA-Z0-9_-]*)?"
  r"(?P<id>#(?:\\[0-9a-fA-F]{1,6}\s?|\\.|[a-zA-Z0-9_-])*)?"
  r"(?P<class>(\.(?:\\[0-9a-fA-F]{1,6}\s?|\\.|[a-zA-Z0-9_-])*)*)"
  r"(?P<attr>(\[[a-zA-Z_:][-a-zA-Z0-9_:.]*(=[^\]]+)?\])*)"
  r"(?P<pseudo>:[a-zA-Z][a-zA-Z0-9_-]*)?$"
)
ATTR_SELECTOR_RE = re.compile(
  r"^\[(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)(=(?P<value>[^\]]+))?\]$"
)
WIDTH_QUERY_RE = re.compile(r"\(\s*(max|min)-width\s*:\s*(\d+)px\s*\)", re.IGNORECASE)


@dataclass
class StylesheetCacheEntry:
  resource: Resource
  variant_key: str
  vary_headers: tuple[str, ...]
  cached_at_monotonic: float
  etag: str | None = None
  last_modified: str | None = None
  max_age_seconds: int | None = None
  no_cache: bool = False
  no_store: bool = False


STYLESHEET_CACHE: dict[str, list[StylesheetCacheEntry]] = {}
STYLESHEET_CACHE_LOCK = Lock()


@dataclass(frozen=True)
class StyleProperties:
  visible: bool
  hidden_reason: str | None = None
  display: str | None = None
  height: str | None = None
  flex_direction: str | None = None
  flex: str | None = None
  flex_basis: str | None = None
  grid_template_columns: str | None = None
  width: str | None = None
  overflow: str | None = None
  visibility: str | None = None
  font_weight: str | None = None
  font_style: str | None = None
  text_decoration: str | None = None
  text_align: str | None = None
  margin: str | None = None
  margin_top: str | None = None
  margin_bottom: str | None = None


@dataclass(frozen=True)
class CssRule:
  selectors: tuple[str, ...]
  declarations: dict[str, str]


@dataclass(frozen=True)
class SimpleSelector:
  tag: str | None
  selector_id: str | None
  selector_classes: tuple[str, ...]
  attr_filters: tuple[tuple[str, str | None], ...]
  pseudo: str | None
  negated: SimpleSelector | None


@dataclass
class StyleContext:
  document: DocumentNode
  viewport_width_px: int
  media_type: str = "screen"
  session: Any = None

  def __post_init__(self) -> None:
    self.parent_map = _build_parent_map(self.document)
    self.rules = _collect_rules(
      self.document,
      viewport_width_px=self.viewport_width_px,
      media_type=self.media_type,
      session=self.session,
    )
    self.rule_index = _build_rule_index(self.rules)
    self._declarations_cache: dict[int, dict[str, str]] = {}
    self._properties_cache: dict[tuple[int, bool], StyleProperties] = {}
    self._candidate_rule_indexes_cache: dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], list[int]] = {}
    self._node_classes_cache: dict[int, frozenset[str]] = {}
    self._selector_match_cache: dict[tuple[int, str], bool] = {}
    self._simple_selector_match_cache: dict[tuple[int, str], bool] = {}
    self._ancestor_match_cache: dict[tuple[int, str], ElementNode | None] = {}
    self._rule_specificity_cache: dict[tuple[int, int], tuple[int, int, int, int] | None] = {}

  def properties(self, node: ElementNode, inherited_visible: bool = True) -> StyleProperties:
    cache_key = (id(node), inherited_visible)
    cached = self._properties_cache.get(cache_key)
    if cached is not None:
      return cached

    declarations = self._declarations(node)
    hidden_reason = _hidden_reason(
      node,
      declarations,
      inherited_visible=inherited_visible,
    )

    properties = StyleProperties(
      visible=hidden_reason is None,
      hidden_reason=hidden_reason,
      display=declarations.get("display"),
      height=declarations.get("height"),
      flex_direction=declarations.get("flex-direction"),
      flex=declarations.get("flex"),
      flex_basis=declarations.get("flex-basis"),
      grid_template_columns=declarations.get("grid-template-columns"),
      width=declarations.get("width"),
      overflow=declarations.get("overflow"),
      visibility=declarations.get("visibility"),
      font_weight=declarations.get("font-weight"),
      font_style=declarations.get("font-style"),
      text_decoration=declarations.get("text-decoration"),
      text_align=declarations.get("text-align"),
      margin=declarations.get("margin"),
      margin_top=declarations.get("margin-top"),
      margin_bottom=declarations.get("margin-bottom"),
    )
    self._properties_cache[cache_key] = properties
    return properties

  def _declarations(self, node: ElementNode) -> dict[str, str]:
    node_id = id(node)
    cached = self._declarations_cache.get(node_id)
    if cached is not None:
      return cached

    declarations = _node_declarations(
      node,
      self,
    )
    self._declarations_cache[node_id] = declarations
    return declarations

  def node_classes(self, node: ElementNode) -> frozenset[str]:
    node_id = id(node)
    cached = self._node_classes_cache.get(node_id)
    if cached is not None:
      return cached
    classes = frozenset(
      token
      for token in node.attrs.get("class", "").split()
      if token
    )
    self._node_classes_cache[node_id] = classes
    return classes

  def candidate_rule_indexes(self, node: ElementNode) -> list[int]:
    cache_key = (
      node.tag,
      node.attrs.get("id", ""),
      tuple(sorted(self.node_classes(node))),
      tuple(sorted(node.attrs)),
    )
    cached = self._candidate_rule_indexes_cache.get(cache_key)
    if cached is not None:
      return cached
    indexes = _candidate_rule_indexes(node, self.rule_index, class_names=self.node_classes(node))
    self._candidate_rule_indexes_cache[cache_key] = indexes
    return indexes

  def selector_matches(self, node: ElementNode, selector: str) -> bool:
    cache_key = (id(node), selector)
    cached = self._selector_match_cache.get(cache_key)
    if cached is not None:
      return cached
    matched = _selector_matches(node, selector, self)
    self._selector_match_cache[cache_key] = matched
    return matched

  def simple_selector_matches(self, node: ElementNode, token: str) -> bool:
    cache_key = (id(node), token)
    cached = self._simple_selector_match_cache.get(cache_key)
    if cached is not None:
      return cached
    matched = _simple_selector_matches(
      node,
      token,
      self,
    )
    self._simple_selector_match_cache[cache_key] = matched
    return matched

  def nearest_ancestor_matching(self, node: ElementNode, token: str) -> ElementNode | None:
    cache_key = (id(node), token)
    if cache_key in self._ancestor_match_cache:
      return self._ancestor_match_cache[cache_key]
    current = self.parent_map.get(id(node))
    while current is not None and not self.simple_selector_matches(current, token):
      current = self.parent_map.get(id(current))
    self._ancestor_match_cache[cache_key] = current
    return current

  def matching_rule_specificity(
    self,
    node: ElementNode,
    rule_index_value: int,
  ) -> tuple[int, int, int, int] | None:
    cache_key = (id(node), rule_index_value)
    cached = self._rule_specificity_cache.get(cache_key)
    if cached is not None:
      return cached
    specificity = _matching_rule_specificity(node, self.rules[rule_index_value], self)
    self._rule_specificity_cache[cache_key] = specificity
    return specificity


def viewport_width_px(columns: int) -> int:
  return columns * 8


def build_style_context(
  document: DocumentNode,
  viewport_columns: int,
  media_type: str = "screen",
  session: Any = None,
) -> StyleContext:
  return StyleContext(
    document=document,
    viewport_width_px=viewport_width_px(viewport_columns),
    media_type=media_type,
    session=session,
  )


def computed_style_declarations(
  document: DocumentNode,
  node: ElementNode,
  viewport_columns: int,
  media_type: str = "screen",
  session: Any = None,
) -> dict[str, str]:
  context = build_style_context(
    document,
    viewport_columns=viewport_columns,
    media_type=media_type,
    session=session,
  )
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


def _collect_rules(
  document: DocumentNode,
  viewport_width_px: int,
  media_type: str,
  session: Any,
) -> list[CssRule]:
  rules: list[CssRule] = []
  for css_text in _iter_stylesheet_texts(
    document,
    viewport_width_px=viewport_width_px,
    media_type=media_type,
    session=session,
  ):
    rules.extend(_parse_stylesheet(css_text, viewport_width_px, media_type))
  return rules


def _iter_stylesheet_texts(
  document: DocumentNode,
  viewport_width_px: int,
  media_type: str,
  session: Any,
):
  prefetched_stylesheets = _prefetch_stylesheet_texts(
    document,
    viewport_width_px=viewport_width_px,
    media_type=media_type,
    session=session,
  )
  for child in document.children:
    if isinstance(child, ElementNode):
      yield from _iter_stylesheet_texts_for_node(
        child,
        document=document,
        viewport_width_px=viewport_width_px,
        media_type=media_type,
        session=session,
        prefetched_stylesheets=prefetched_stylesheets,
      )


def _iter_stylesheet_texts_for_node(
  node: ElementNode,
  document: DocumentNode,
  viewport_width_px: int,
  media_type: str,
  session: Any,
  prefetched_stylesheets: dict[int, str | None],
):
  if node.tag == "style":
    css_text = _style_text_content(node)
    if css_text:
      yield css_text
  elif node.tag == "link" and _is_stylesheet_link(node):
    css_text = prefetched_stylesheets.get(id(node))
    if id(node) not in prefetched_stylesheets:
      css_text = _load_stylesheet_text(
        document.source,
        node.attrs.get("href", ""),
        media=node.attrs.get("media"),
        viewport_width_px=viewport_width_px,
        media_type=media_type,
        session=session,
      )
    if css_text:
      yield css_text

  for child in node.children:
    if isinstance(child, ElementNode):
      yield from _iter_stylesheet_texts_for_node(
        child,
        document=document,
        viewport_width_px=viewport_width_px,
        media_type=media_type,
        session=session,
        prefetched_stylesheets=prefetched_stylesheets,
      )


def _prefetch_stylesheet_texts(
  document: DocumentNode,
  *,
  viewport_width_px: int,
  media_type: str,
  session: Any,
) -> dict[int, str | None]:
  nodes = _collect_stylesheet_link_nodes(
    document,
    viewport_width_px=viewport_width_px,
    media_type=media_type,
  )
  if len(nodes) < 2:
    return {}
  prefetched: dict[int, str | None] = {}
  parallel_session = create_persistent_session_pool(session)
  with ThreadPoolExecutor(max_workers=min(ASSET_FETCH_MAX_WORKERS, len(nodes))) as executor:
    futures = {
      id(node): executor.submit(
        _load_stylesheet_text,
        document.source,
        node.attrs.get("href", ""),
        media=node.attrs.get("media"),
        viewport_width_px=viewport_width_px,
        media_type=media_type,
        session=parallel_session,
      )
      for node in nodes
    }
    for node_id, future in futures.items():
      prefetched[node_id] = future.result()
  return prefetched


def _collect_stylesheet_link_nodes(
  document: DocumentNode,
  *,
  viewport_width_px: int,
  media_type: str,
) -> list[ElementNode]:
  nodes: list[ElementNode] = []
  for child in document.children:
    if isinstance(child, ElementNode):
      _collect_stylesheet_link_nodes_for_node(
        child,
        viewport_width_px=viewport_width_px,
        media_type=media_type,
        nodes=nodes,
      )
  return nodes


def _collect_stylesheet_link_nodes_for_node(
  node: ElementNode,
  *,
  viewport_width_px: int,
  media_type: str,
  nodes: list[ElementNode],
) -> None:
  media_query = node.attrs.get("media")
  if (
    node.tag == "link"
    and _is_stylesheet_link(node)
    and (not media_query or _media_query_matches(media_query, viewport_width_px, media_type))
  ):
    nodes.append(node)
  for child in node.children:
    if isinstance(child, ElementNode):
      _collect_stylesheet_link_nodes_for_node(
        child,
        viewport_width_px=viewport_width_px,
        media_type=media_type,
        nodes=nodes,
      )


def _is_stylesheet_link(node: ElementNode) -> bool:
  href = node.attrs.get("href", "").strip()
  if not href:
    return False
  rel_values = {value.lower() for value in node.attrs.get("rel", "").split()}
  if "stylesheet" in rel_values:
    return True
  return "preload" in rel_values and node.attrs.get("as", "").strip().lower() == "style"


def _style_text_content(node: ElementNode) -> str:
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      parts.append(child.text)
  return "".join(parts)


def _load_stylesheet_text(
  base_source: str,
  href: str,
  media: str | None,
  viewport_width_px: int,
  media_type: str,
  session: Any,
) -> str | None:
  if media and not _media_query_matches(media.strip(), viewport_width_px, media_type):
    return None

  target = resolve_resource_url(base_source, href)
  request_context = _cache_request_context(target, session=session)
  cache_entry = _find_stylesheet_cache_entry(target, request_context=request_context)
  if cache_entry is not None and not _should_revalidate_stylesheet(cache_entry):
    return cache_entry.resource.content

  request_headers = _stylesheet_revalidation_headers(cache_entry)

  try:
    resource = fetch_resource(
      target,
      session=session,
      request_headers=request_headers if request_headers else None,
    )
  except FetchError:
    return None

  if resource.status_code == 304 and cache_entry is not None:
    cache_entry.cached_at_monotonic = time.monotonic()
    if resource.headers:
      cache_entry.resource.headers = resource.headers
      _refresh_stylesheet_cache_policy(cache_entry, resource.headers)
    return cache_entry.resource.content

  _store_stylesheet_cache_entry(target, resource, request_context=request_context)
  return resource.content


def _find_stylesheet_cache_entry(
  target: str,
  *,
  request_context: dict[str, str],
) -> StylesheetCacheEntry | None:
  with STYLESHEET_CACHE_LOCK:
    entries = list(STYLESHEET_CACHE.get(target, []))
  for entry in entries:
    if entry.variant_key == _vary_variant_key(entry.vary_headers, request_context=request_context):
      return entry
  return None


def _store_stylesheet_cache_entry(
  target: str,
  resource: Resource,
  *,
  request_context: dict[str, str],
) -> None:
  headers = resource.headers or {}
  vary_headers = _parse_vary_headers(headers)
  if "*" in vary_headers:
    with STYLESHEET_CACHE_LOCK:
      STYLESHEET_CACHE.pop(target, None)
    return
  variant_key = _vary_variant_key(vary_headers, request_context=request_context)
  entry = StylesheetCacheEntry(
    resource=resource,
    variant_key=variant_key,
    vary_headers=vary_headers,
    cached_at_monotonic=time.monotonic(),
    etag=headers.get("ETag") or headers.get("etag"),
    last_modified=headers.get("Last-Modified") or headers.get("last-modified"),
  )
  _refresh_stylesheet_cache_policy(entry, headers)
  with STYLESHEET_CACHE_LOCK:
    if entry.no_store:
      entries = STYLESHEET_CACHE.get(target, [])
      STYLESHEET_CACHE[target] = [item for item in entries if item.variant_key != variant_key]
      if not STYLESHEET_CACHE[target]:
        STYLESHEET_CACHE.pop(target, None)
      return
    entries = [item for item in STYLESHEET_CACHE.get(target, []) if item.variant_key != variant_key]
    entries.append(entry)
    STYLESHEET_CACHE[target] = entries


def _refresh_stylesheet_cache_policy(
  entry: StylesheetCacheEntry,
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
      break


def _should_revalidate_stylesheet(entry: StylesheetCacheEntry) -> bool:
  if entry.no_store or entry.no_cache:
    return True
  if entry.max_age_seconds is None:
    return False
  age_seconds = time.monotonic() - entry.cached_at_monotonic
  return age_seconds >= entry.max_age_seconds


def _stylesheet_revalidation_headers(entry: StylesheetCacheEntry | None) -> dict[str, str]:
  if entry is None:
    return {}
  headers: dict[str, str] = {}
  if entry.etag:
    headers["If-None-Match"] = entry.etag
  if entry.last_modified:
    headers["If-Modified-Since"] = entry.last_modified
  return headers


def _stylesheet_variant_key(
  resolved_target: str,
  *,
  base_source: str,
  session: Any,
) -> str:
  del base_source
  return _vary_variant_key((), request_context=_cache_request_context(resolved_target, session=session))


def _cache_request_context(resolved_target: str, *, session: Any) -> dict[str, str]:
  return {
    "user-agent": DEFAULT_HEADERS.get("User-Agent", ""),
    "accept-language": DEFAULT_HEADERS.get("Accept-Language", ""),
    "cookie": _cache_cookie_header(resolved_target, session=session),
  }


def _cache_cookie_header(resolved_target: str, *, session: Any) -> str:
  if session is None or not hasattr(session, "cookies"):
    return ""
  cookie_jar = getattr(session, "cookies", None)
  if cookie_jar is None or not hasattr(cookie_jar, "get_dict"):
    return ""
  try:
    values = cookie_jar.get_dict(domain=None, path=None)
  except Exception:
    return ""
  if not isinstance(values, dict):
    return ""
  return "; ".join(f"{name}={value}" for name, value in sorted(values.items()))


def _parse_vary_headers(headers: dict[str, str]) -> tuple[str, ...]:
  vary_value = headers.get("Vary") or headers.get("vary") or ""
  parts = []
  for item in vary_value.split(","):
    normalized = item.strip().lower()
    if normalized:
      parts.append(normalized)
  return tuple(parts)


def _vary_variant_key(vary_headers: tuple[str, ...], *, request_context: dict[str, str]) -> str:
  if not vary_headers:
    return hashlib.sha256(b"").hexdigest()
  payload = "|".join(
    f"{header}={request_context.get(header, '')}"
    for header in vary_headers
  )
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_stylesheet(
  css_text: str,
  viewport_width_px: int,
  media_type: str,
) -> list[CssRule]:
  css_text = COMMENT_RE.sub("", css_text)
  rules: list[CssRule] = []
  remaining = css_text

  while True:
    match = MEDIA_RE.search(remaining)
    if match is None:
      break

    prefix = remaining[: match.start()]
    rules.extend(_parse_plain_rules(prefix))

    query = match.group("query").strip()
    block_start = match.end() - 1
    block_end = _find_matching_brace(remaining, block_start)
    if block_end == -1:
      break
    block = remaining[block_start + 1 : block_end]
    if _media_query_matches(query, viewport_width_px, media_type):
      rules.extend(_parse_plain_rules(block))
    remaining = remaining[block_end + 1 :]

  rules.extend(_parse_plain_rules(remaining))
  return rules


def _parse_plain_rules(css_text: str) -> list[CssRule]:
  rules: list[CssRule] = []
  for match in RULE_RE.finditer(css_text):
    selectors = tuple(
      selector.strip()
      for selector in match.group("selectors").split(",")
      if selector.strip()
    )
    declarations = _parse_declarations(match.group("body"))
    if selectors and declarations:
      rules.append(CssRule(selectors=selectors, declarations=declarations))
  return rules


def _parse_declarations(body: str) -> dict[str, str]:
  declarations: dict[str, str] = {}
  for item in body.split(";"):
    if ":" not in item:
      continue
    key, value = item.split(":", 1)
    key = key.strip().lower()
    value = value.strip()
    if key and value:
      declarations[key] = value
  return declarations


def _find_matching_brace(text: str, open_index: int) -> int:
  depth = 0
  for index in range(open_index, len(text)):
    char = text[index]
    if char == "{":
      depth += 1
    elif char == "}":
      depth -= 1
      if depth == 0:
        return index
  return -1


def _media_query_matches(query: str, viewport_width_px: int, media_type: str) -> bool:
  parts = [part.strip() for part in query.split("and")]
  for part in parts:
    lowered = part.lower()
    if lowered in {"screen", "all", "print"}:
      if lowered == "all":
        continue
      if lowered != media_type:
        return False
      continue

    width_match = WIDTH_QUERY_RE.fullmatch(lowered)
    if width_match is not None:
      kind, raw_value = width_match.groups()
      value = int(raw_value)
      if kind == "max" and viewport_width_px > value:
        return False
      if kind == "min" and viewport_width_px < value:
        return False
      continue

    return False
  return True


def _node_declarations(
  node: ElementNode,
  style_context: StyleContext,
) -> dict[str, str]:
  declarations: dict[str, str] = {}
  winning_rules: dict[str, tuple[tuple[int, int, int, int], int]] = {}
  for rule_index_value in style_context.candidate_rule_indexes(node):
    rule = style_context.rules[rule_index_value]
    specificity = style_context.matching_rule_specificity(node, rule_index_value)
    if specificity is None:
      continue
    for key, value in rule.declarations.items():
      current = winning_rules.get(key)
      if current is not None and current > (specificity, rule_index_value):
        continue
      winning_rules[key] = (specificity, rule_index_value)
      declarations[key] = value

  inline_style = node.attrs.get("style", "")
  if inline_style:
    declarations.update(_parse_declarations(inline_style))
  return declarations


def _hidden_reason(
  node: ElementNode,
  declarations: dict[str, str],
  inherited_visible: bool,
) -> str | None:
  if not inherited_visible:
    return "ancestor_hidden"
  if "hidden" in node.attrs:
    return "hidden_attr"
  if node.attrs.get("aria-hidden", "").strip().lower() == "true":
    return "aria_hidden"
  if _has_hidden_class(node):
    return "hidden_class"
  if declarations.get("display", "").strip().lower() == "none":
    return "display_none"
  if declarations.get("visibility", "").strip().lower() == "hidden":
    if _looks_like_unmounted_splide(node):
      return None
    return "visibility_hidden"
  if _has_zero_extent_clipped_content(declarations):
    return "zero_height_clipped"
  return None


def _has_zero_extent_clipped_content(declarations: dict[str, str]) -> bool:
  height = declarations.get("height", "").strip().lower()
  if height not in {"0", "0px", "0rem", "0em", "0%"}:
    return False
  overflow = declarations.get("overflow", "").strip().lower()
  return overflow in {"auto", "hidden", "clip", "scroll"}


def _looks_like_unmounted_splide(node: ElementNode) -> bool:
  classes = {
    token.strip().lower()
    for token in node.attrs.get("class", "").split()
    if token.strip()
  }
  if "splide" not in classes:
    return False
  if "is-initialized" in classes or "is-active" in classes:
    return False
  return bool(node.text_content().strip())


def _has_hidden_class(node: ElementNode) -> bool:
  classes = {
    token.strip().lower()
    for token in node.attrs.get("class", "").split()
    if token.strip()
  }
  if "ishidden" in classes:
    return True
  return any(
    token.endswith("-ishidden") or token.endswith("_ishidden")
    for token in classes
  )


def _candidate_rule_indexes(
  node: ElementNode,
  rule_index: dict[tuple[str, str], list[int]],
  *,
  class_names: frozenset[str] | None = None,
) -> list[int]:
  candidate_keys = [("all", "")]
  if node.tag:
    candidate_keys.append(("tag", node.tag))

  selector_id = node.attrs.get("id")
  if selector_id:
    candidate_keys.append(("id", selector_id))

  for class_name in class_names if class_names is not None else node.attrs.get("class", "").split():
    if class_name:
      candidate_keys.append(("class", class_name))

  for attr_name in node.attrs:
    candidate_keys.append(("attr", attr_name))

  seen: set[int] = set()
  indexes: list[int] = []
  for key in candidate_keys:
    for rule_index_value in rule_index.get(key, []):
      if rule_index_value in seen:
        continue
      seen.add(rule_index_value)
      indexes.append(rule_index_value)
  indexes.sort()
  return indexes


def _build_rule_index(rules: list[CssRule]) -> dict[tuple[str, str], list[int]]:
  selector_candidates: list[tuple[int, tuple[tuple[str, str], ...]]] = []
  key_counts: dict[tuple[str, str], int] = {}
  for rule_index_value, rule in enumerate(rules):
    for selector in rule.selectors:
      candidates = _selector_anchor_candidates(selector)
      selector_candidates.append((rule_index_value, candidates))
      for key in candidates:
        key_counts[key] = key_counts.get(key, 0) + 1

  index: dict[tuple[str, str], list[int]] = {}
  seen_rule_keys: set[tuple[int, tuple[str, str]]] = set()
  for rule_index_value, candidates in selector_candidates:
    key = min(
      candidates,
      key=lambda candidate: (
        key_counts.get(candidate, 0),
        _selector_anchor_priority(candidate),
        candidate,
      ),
    )
    if (rule_index_value, key) in seen_rule_keys:
      continue
    seen_rule_keys.add((rule_index_value, key))
    index.setdefault(key, []).append(rule_index_value)
  return index


def _selector_matches(
  node: ElementNode,
  selector: str,
  style_context: StyleContext,
) -> bool:
  tokens = _selector_tokens(selector)
  if not tokens:
    return False
  if not style_context.simple_selector_matches(node, tokens[-1][1]):
    return False

  current = node
  for index in range(len(tokens) - 1, 0, -1):
    combinator = tokens[index][0]
    token = tokens[index - 1][1]
    if combinator == ">":
      current = style_context.parent_map.get(id(current))
      if current is None or not style_context.simple_selector_matches(current, token):
        return False
      continue

    current = style_context.nearest_ancestor_matching(current, token)
    if current is None:
      return False
  return True


def _simple_selector_matches(node: ElementNode, token: str, style_context: StyleContext) -> bool:
  selector = _parse_simple_selector(token)
  return _selector_object_matches(
    node,
    selector,
    class_names=style_context.node_classes(node),
  )


def _selector_object_matches(
  node: ElementNode,
  selector: SimpleSelector | None,
  *,
  class_names: frozenset[str] | None = None,
) -> bool:
  if selector is None:
    return False

  if selector.tag is not None and node.tag != selector.tag:
    return False
  if selector.selector_id is not None and node.attrs.get("id") != selector.selector_id:
    return False
  if selector.selector_classes:
    classes = class_names if class_names is not None else frozenset(node.attrs.get("class", "").split())
    if not all(class_name in classes for class_name in selector.selector_classes):
      return False
  for attr_name, attr_value in selector.attr_filters:
    if attr_name not in node.attrs:
      return False
    if attr_value is not None and node.attrs.get(attr_name) != attr_value:
      return False
  if selector.pseudo is not None:
    if selector.pseudo != "root":
      return False
    if node.tag != "html":
      return False
  if selector.negated is not None and _selector_object_matches(node, selector.negated):
    return False
  return True


@lru_cache(maxsize=None)
def _selector_tokens(selector: str) -> tuple[tuple[str | None, str], ...]:
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

  index = 0
  while index < len(selector):
    char = selector[index]
    if char == "\\":
      escape_text, escape_end = _consume_css_escape(selector, index)
      current.append(escape_text)
      index = escape_end
      continue
    if quote is not None:
      current.append(char)
      if char == quote:
        quote = None
      index += 1
      continue
    if char in {'"', "'"}:
      quote = char
      current.append(char)
      index += 1
      continue
    if char == "[":
      bracket_depth += 1
      current.append(char)
      index += 1
      continue
    if char == "]":
      bracket_depth = max(0, bracket_depth - 1)
      current.append(char)
      index += 1
      continue
    if bracket_depth == 0 and char == ">":
      flush()
      next_combinator = ">"
      index += 1
      continue
    if bracket_depth == 0 and char.isspace():
      flush()
      index += 1
      continue
    current.append(char)
    index += 1
  flush()
  if tokens:
    first_combinator, first_token = tokens[0]
    tokens[0] = (None, first_token)
  return tuple(tokens)


@lru_cache(maxsize=None)
def _selector_anchor_candidates(selector: str) -> tuple[tuple[str, str], ...]:
  tokens = _selector_tokens(selector)
  if not tokens:
    return (("all", ""),)
  simple = _parse_simple_selector(tokens[-1][1])
  if simple is None:
    return (("all", ""),)
  candidates: list[tuple[str, str]] = []
  if simple.selector_id is not None:
    candidates.append(("id", simple.selector_id))
  candidates.extend(("class", class_name) for class_name in simple.selector_classes)
  candidates.extend(("attr", attr_name) for attr_name, _ in simple.attr_filters)
  if simple.tag is not None:
    candidates.append(("tag", simple.tag))
  if not candidates:
    candidates.append(("all", ""))
  return tuple(candidates)


def _selector_anchor_priority(key: tuple[str, str]) -> int:
  kind = key[0]
  if kind == "id":
    return 0
  if kind == "class":
    return 1
  if kind == "attr":
    return 2
  if kind == "tag":
    return 3
  return 4


@lru_cache(maxsize=None)
def _parse_simple_selector(token: str) -> SimpleSelector | None:
  negated: SimpleSelector | None = None
  not_marker = ":not("
  if token.endswith(")") and not_marker in token:
    start = token.rfind(not_marker)
    if start != -1:
      negated_token = token[start + len(not_marker):-1].strip()
      if not negated_token:
        return None
      negated = _parse_simple_selector(negated_token)
      if negated is None:
        return None
      token = token[:start]

  match = SIMPLE_SELECTOR_RE.match(token)
  if match is None:
    return None

  attr_filters: list[tuple[str, str | None]] = []
  attrs_text = match.group("attr") or ""
  if attrs_text:
    for attr_text in re.findall(r"\[[^\]]+\]", attrs_text):
      attr_match = ATTR_SELECTOR_RE.match(attr_text)
      if attr_match is None:
        return None
      raw_value = attr_match.group("value")
      attr_filters.append(
        (
          attr_match.group("name"),
          raw_value.strip("\"'") if raw_value is not None else None,
        )
      )

  return SimpleSelector(
    tag=match.group("tag"),
    selector_id=_css_unescape_identifier(match.group("id")[1:]) if match.group("id") is not None else None,
    selector_classes=tuple(
      _css_unescape_identifier(item[1:])
      for item in re.findall(r"\.(?:\\[0-9a-fA-F]{1,6}\s?|\\.|[a-zA-Z0-9_-])+", match.group("class"))
    ),
    attr_filters=tuple(attr_filters),
    pseudo=match.group("pseudo")[1:] if match.group("pseudo") is not None else None,
    negated=negated,
  )


def _css_unescape_identifier(value: str) -> str:
  return re.sub(r"\\([0-9a-fA-F]{1,6}\s?|.)", _decode_css_escape, value)


def _decode_css_escape(match: re.Match[str]) -> str:
  escaped = match.group(1)
  hex_digits = escaped.rstrip()
  if hex_digits and all(char in "0123456789abcdefABCDEF" for char in hex_digits):
    return chr(int(hex_digits, 16))
  return escaped


def _consume_css_escape(text: str, index: int) -> tuple[str, int]:
  end = index + 1
  while end < len(text) and len(text[index + 1:end + 1]) <= 6 and text[end] in "0123456789abcdefABCDEF":
    end += 1
  if end > index + 1:
    if end < len(text) and text[end].isspace():
      end += 1
    return text[index:end], end
  if end < len(text):
    end += 1
  return text[index:end], end


def _matching_rule_specificity(
  node: ElementNode,
  rule: CssRule,
  style_context: StyleContext,
) -> tuple[int, int, int, int] | None:
  matched: list[tuple[int, int, int, int]] = []
  for selector in rule.selectors:
    if style_context.selector_matches(node, selector):
      matched.append(_selector_specificity(selector))
  if not matched:
    return None
  return max(matched)


@lru_cache(maxsize=None)
def _selector_specificity(selector: str) -> tuple[int, int, int, int]:
  id_count = 0
  class_like_count = 0
  tag_count = 0
  for _, token in _selector_tokens(selector):
    simple = _parse_simple_selector(token)
    token_ids, token_class_like, token_tags = _simple_selector_specificity(simple)
    id_count += token_ids
    class_like_count += token_class_like
    tag_count += token_tags
  return (0, id_count, class_like_count, tag_count)


def _simple_selector_specificity(selector: SimpleSelector | None) -> tuple[int, int, int]:
  if selector is None:
    return (0, 0, 0)
  id_count = 1 if selector.selector_id is not None else 0
  class_like_count = len(selector.selector_classes) + len(selector.attr_filters)
  if selector.pseudo is not None:
    class_like_count += 1
  tag_count = 1 if selector.tag is not None else 0
  negated_ids, negated_class_like, negated_tags = _simple_selector_specificity(selector.negated)
  return (
    id_count + negated_ids,
    class_like_count + negated_class_like,
    tag_count + negated_tags,
  )


def _build_parent_map(document: DocumentNode) -> dict[int, ElementNode | None]:
  parent_map: dict[int, ElementNode | None] = {}
  for child in document.children:
    if isinstance(child, ElementNode):
      _register_parents(child, None, parent_map)
  return parent_map


def _register_parents(
  node: ElementNode,
  parent: ElementNode | None,
  parent_map: dict[int, ElementNode | None],
) -> None:
  parent_map[id(node)] = parent
  for child in node.children:
    if isinstance(child, ElementNode):
      _register_parents(child, node, parent_map)
