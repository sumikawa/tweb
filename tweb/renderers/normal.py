from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
import logging
from typing import Any
import unicodedata

from ..css import StyleContext, StyleProperties, _parse_declarations, build_style_context, style_properties_from_declarations
from ..dom import DocumentNode, ElementNode, TextNode
from ..interactions import (
  _button_token as _interaction_button_token,
  _checkbox_token,
  _control_label,
  _display_input_value,
  _ensure_control_id,
  _form_owner,
  _input_token,
  _is_aria_selected,
  _is_tab_node,
  _role_tokens,
  _radio_token,
  _select_options,
  _select_token,
  _synthetic_clickable_button_control,
  _tab_label,
  _tab_token,
  _textarea_token,
  _textarea_value,
)

LOGGER = logging.getLogger("tweb")


BLOCK_TAGS = {
  "article",
  "aside",
  "blockquote",
  "body",
  "dd",
  "details",
  "dl",
  "dt",
  "div",
  "figcaption",
  "figure",
  "fieldset",
  "footer",
  "form",
  "header",
  "hr",
  "legend",
  "li",
  "main",
  "nav",
  "ol",
  "p",
  "pre",
  "section",
  "summary",
  "table",
  "ul",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
INLINE_CONTAINER_TAGS = {"a", "button", "em", "label", "span", "strong"}
SKIP_TAGS = {"#comment", "head", "meta", "noscript", "script", "style", "template", "title"}
PUNCTUATION = {".", ",", "!", "?", ";", ":", ")", "]"}
OPENING_PUNCTUATION = {"(", "[", "{"}
COLUMN_SEPARATOR = " | "
ANSI_BOLD = "\x1b[1m"
ANSI_BOLD_RESET = "\x1b[22m"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
INTERACTIVE_MARKER_RE = re.compile(r"\x1b\[(?P<marker>9910|9911);(?P<entry>\d+)m")
FORBIDDEN_LINE_START_PUNCTUATION = {
  ",",
  ".",
  "!",
  "?",
  ":",
  ";",
  "、",
  "。",
  "，",
  "．",
  "！",
  "？",
}


@dataclass(frozen=True)
class RenderedLinkMetadata:
  start: int
  end: int
  text: str
  href: str
  index: int


@dataclass(frozen=True)
class RenderedControlMetadata:
  start: int
  end: int
  text: str
  control_id: str
  label: str
  kind: str
  index: int
  source_kind: str = "token"


@dataclass(frozen=True)
class NormalRenderResult:
  text: str
  link_spans: tuple[RenderedLinkMetadata, ...] = ()
  control_spans: tuple[RenderedControlMetadata, ...] = ()


@dataclass(frozen=True)
class _PendingLinkMetadata:
  text: str
  href: str


@dataclass(frozen=True)
class _PendingControlMetadata:
  text: str
  control_id: str
  label: str
  kind: str
  source_kind: str = "token"


@dataclass
class RenderState:
  document: DocumentNode
  width: int = 80
  link_style: str = "none"
  text_styles: bool = True
  style_context: StyleContext | None = None
  max_blocks: int | None = None
  include_controls: bool = True
  include_control_metadata: bool = True
  truncated: bool = False
  interactive_entries: list[tuple[str, _PendingLinkMetadata | _PendingControlMetadata]] = field(default_factory=list)
  child_properties_cache: dict[tuple[int, bool], StyleProperties | None] = field(default_factory=dict)
  node_by_id_cache: dict[str, ElementNode] | None = None
  labelledby_targets_cache: dict[str, ElementNode | None] | None = None
  control_metadata_cache: dict[int, tuple[str, str, str] | None] = field(default_factory=dict)
  list_marker_cache: dict[int, str] | None = None
  lightweight_style_only: bool = False

  def can_append_block(self) -> bool:
    return not self.truncated and (
      self.max_blocks is None or self.max_blocks > 0
    )

  def append_block(self, blocks: list["RenderBlock"], block: "RenderBlock") -> None:
    if not self.can_append_block():
      self.truncated = True
      return
    blocks.append(block)
    if self.max_blocks is not None:
      self.max_blocks -= 1

  def annotate_link(self, text: str, href: str) -> str:
    if not text:
      return text
    entry_id = len(self.interactive_entries)
    self.interactive_entries.append(("link", _PendingLinkMetadata(text=text, href=href)))
    return f"{_interactive_marker(9910, entry_id)}{text}{_interactive_marker(9911, entry_id)}"

  def annotate_control(
    self,
    text: str,
    *,
    control_id: str,
    label: str,
    kind: str,
    source_kind: str = "token",
  ) -> str:
    if not text:
      return text
    if not self.include_control_metadata:
      return text
    entry_id = len(self.interactive_entries)
    self.interactive_entries.append((
      "control",
      _PendingControlMetadata(
        text=text,
        control_id=control_id,
        label=label,
        kind=kind,
        source_kind=source_kind,
      ),
    ))
    return f"{_interactive_marker(9910, entry_id)}{text}{_interactive_marker(9911, entry_id)}"


@dataclass(frozen=True)
class RenderBlock:
  text: str
  kind: str = "paragraph"
  text_align: str | None = None
  compact_spacing: bool = False


@dataclass(frozen=True)
class TableRow:
  cells: tuple[str, ...]
  is_header: bool = False


@dataclass(frozen=True)
class PaneTarget:
  path: tuple[int, ...]


def render_normal(
  document: DocumentNode,
  width: int = 80,
  viewport_columns: int | None = None,
  link_style: str = "none",
  text_styles: bool = True,
  max_blocks: int | None = None,
  session: Any = None,
  *,
  main_only: bool = False,
) -> str:
  return render_normal_with_metadata(
    document,
    width=width,
    viewport_columns=viewport_columns,
    link_style=link_style,
    text_styles=text_styles,
    max_blocks=max_blocks,
    include_controls=True,
    include_control_metadata=True,
    session=session,
    main_only=main_only,
  ).text


def render_normal_with_metadata(
  document: DocumentNode,
  width: int = 80,
  viewport_columns: int | None = None,
  link_style: str = "none",
  text_styles: bool = True,
  max_blocks: int | None = None,
  include_controls: bool = True,
  include_control_metadata: bool = True,
  session: Any = None,
  *,
  main_only: bool = False,
) -> NormalRenderResult:
  state = _create_render_state(
    document,
    width=width,
    viewport_columns=viewport_columns,
    link_style=link_style,
    text_styles=text_styles,
    max_blocks=max_blocks,
    include_controls=include_controls,
    include_control_metadata=include_control_metadata,
    session=session,
  )
  root = _find_main_content_root(document, state) if main_only else None
  return _render_normal_root(state, root or document.body or document.root, include_title=True)


def _create_render_state(
  document: DocumentNode,
  *,
  width: int = 80,
  viewport_columns: int | None = None,
  link_style: str = "none",
  text_styles: bool = True,
  max_blocks: int | None = None,
  include_controls: bool = True,
  include_control_metadata: bool = True,
  session: Any = None,
) -> RenderState:
  lightweight_style_only = _should_use_lightweight_style_render(document)
  return RenderState(
    document=document,
    width=width,
    link_style=link_style,
    text_styles=text_styles,
    style_context=None if lightweight_style_only else build_style_context(
      document,
      viewport_columns=viewport_columns or max(width, 160),
      session=session,
    ),
    max_blocks=max_blocks,
    include_controls=include_controls,
    include_control_metadata=include_control_metadata,
    lightweight_style_only=lightweight_style_only,
  )


def _render_normal_root(
  state: RenderState,
  root: ElementNode | None,
  *,
  include_title: bool,
) -> NormalRenderResult:
  blocks: list[RenderBlock] = []
  if include_title and state.document.title:
    state.append_block(blocks, RenderBlock(state.document.title, kind="title"))
    state.append_block(
      blocks,
      RenderBlock("=" * min(len(state.document.title), state.width), kind="title_rule"),
    )
  if root is not None and state.can_append_block():
    blocks.extend(_render_blocks(root, state))
  return _finalize_render_result(_join_blocks(blocks, state.width), state)


def collect_visible_links(
  document: DocumentNode,
  *,
  width: int = 80,
  viewport_columns: int | None = None,
  session: Any = None,
) -> list[tuple[str, str]]:
  root = document.body or document.root
  if root is None:
    return []
  result = render_normal_subtree_with_metadata(
    document,
    root,
    width=width,
    viewport_columns=viewport_columns,
    link_style="none",
    text_styles=False,
    include_title=False,
    include_controls=False,
    include_control_metadata=False,
    session=session,
  )
  return visible_links_from_render_result(result)


def visible_links_from_render_result(
  result: NormalRenderResult,
) -> list[tuple[str, str]]:
  return [(_visible_link_text(entry.text, entry.href), entry.href) for entry in result.link_spans]


def find_main_content_root(
  document: DocumentNode,
  *,
  width: int = 80,
  viewport_columns: int | None = None,
  session: Any = None,
) -> ElementNode | None:
  if document.body is None:
    return None
  state = _create_render_state(document, width=width, viewport_columns=viewport_columns, session=session)
  return _find_main_content_root(document, state)


def _find_main_content_root(document: DocumentNode, state: RenderState) -> ElementNode | None:
  body = document.body
  if body is None:
    return None
  # Walk from the document root so hidden ancestors and skipped subtrees cannot
  # supply a candidate that becomes visible when rendered on its own.
  visible_nodes: list[ElementNode] = []
  pending = [(child, False) for child in reversed(document.children) if isinstance(child, ElementNode)]
  while pending:
    node, inside_body = pending.pop()
    if node.tag in SKIP_TAGS:
      continue
    properties = _child_properties(node, state, inherited_visible=True)
    if properties is not None and not properties.visible:
      continue
    inside_body = inside_body or node is body
    if inside_body:
      visible_nodes.append(node)
    pending.extend(
      (child, inside_body)
      for child in reversed(node.children)
      if isinstance(child, ElementNode)
    )
  for tag in ("main", "article"):
    for node in visible_nodes:
      if node.tag == tag:
        return node
  return _find_probable_content_root(body, visible_nodes) or body


_CONTENT_CONTAINER_TAGS = {"div", "section"}
_CONTENT_MARKERS = (
  "article",
  "body",
  "content",
  "entry",
  "main",
  "post",
  "prose",
  "story",
  "text",
)
_CHROME_MARKERS = (
  "author",
  "breadcrumb",
  "comment",
  "footer",
  "header",
  "menu",
  "meta",
  "nav",
  "related",
  "search",
  "share",
  "sidebar",
  "social",
  "tag",
  "toolbar",
)


@dataclass(frozen=True)
class _ContentStats:
  text_length: int
  blocks: int
  headings: int
  links: int


def _collect_content_stats(root: ElementNode) -> dict[int, _ContentStats]:
  stats: dict[int, _ContentStats] = {}
  pending = [(root, False)]
  while pending:
    node, visited = pending.pop()
    if not visited:
      pending.append((node, True))
      pending.extend(
        (child, False) for child in reversed(node.children)
        if isinstance(child, ElementNode)
      )
      continue
    blocks = int(node.tag in {"blockquote", "li", "p", "pre"})
    headings = int(node.tag in HEADING_TAGS)
    links = int(node.tag == "a")
    text_length = 0
    text_parts = 0
    for child in node.children:
      if isinstance(child, TextNode):
        child_length = len(" ".join(child.text.split()))
      else:
        child_stats = stats[id(child)]
        blocks += child_stats.blocks
        headings += child_stats.headings
        links += child_stats.links
        child_length = child_stats.text_length
      if child_length:
        text_length += child_length
        text_parts += 1
    text_length += max(0, text_parts - 1)
    if node.tag in {"#comment", "script", "style", "noscript"}:
      text_length = 0
    elif node.tag == "#doctype":
      text_length = len(" ".join(node.attrs.get("__text", "").split()))
    stats[id(node)] = _ContentStats(text_length, blocks, headings, links)
  return stats


def _find_probable_content_root(body: ElementNode, nodes: list[ElementNode]) -> ElementNode | None:
  stats = _collect_content_stats(body)
  best_node = None
  best_score = float("-inf")
  for node in nodes:
    if node.tag not in _CONTENT_CONTAINER_TAGS:
      continue
    score = _content_root_score(node, stats[id(node)])
    if score is not None and score > best_score:
      best_score, best_node = score, node
  return best_node


def _content_root_score(node: ElementNode, stats: _ContentStats) -> float | None:
  if stats.text_length < 160:
    return None
  if stats.blocks < 2 and stats.headings == 0:
    return None

  identity = " ".join(
    value.casefold()
    for value in (node.attrs.get("class", ""), node.attrs.get("id", ""), node.attrs.get("aria-label", ""))
    if value
  )
  content_markers = sum(marker in identity for marker in _CONTENT_MARKERS)
  chrome_markers = sum(marker in identity for marker in _CHROME_MARKERS)
  score = min(stats.text_length, 12_000) / 120
  score += min(stats.blocks, 80) * 4
  score += min(stats.headings, 12) * 8
  score += content_markers * 35
  score -= chrome_markers * 45
  score -= min(stats.links, 80) * 0.5
  return score


def render_normal_subtree(
  document: DocumentNode,
  root: ElementNode,
  *,
  width: int = 80,
  viewport_columns: int | None = None,
  link_style: str = "none",
  text_styles: bool = True,
  max_blocks: int | None = None,
  include_title: bool = True,
  include_controls: bool = True,
  include_control_metadata: bool = True,
  session: Any = None,
) -> str:
  return render_normal_subtree_with_metadata(
    document,
    root,
    width=width,
    viewport_columns=viewport_columns,
    link_style=link_style,
    text_styles=text_styles,
    max_blocks=max_blocks,
    include_title=include_title,
    include_controls=include_controls,
    include_control_metadata=include_control_metadata,
    session=session,
  ).text


def render_normal_subtree_with_metadata(
  document: DocumentNode,
  root: ElementNode,
  *,
  width: int = 80,
  viewport_columns: int | None = None,
  link_style: str = "none",
  text_styles: bool = True,
  max_blocks: int | None = None,
  include_title: bool = True,
  include_controls: bool = True,
  include_control_metadata: bool = True,
  session: Any = None,
) -> NormalRenderResult:
  state = _create_render_state(
    document,
    width=width,
    viewport_columns=viewport_columns,
    link_style=link_style,
    text_styles=text_styles,
    max_blocks=max_blocks,
    include_controls=include_controls,
    include_control_metadata=include_control_metadata,
    session=session,
  )
  return _render_normal_root(state, root, include_title=include_title)


def collect_visible_links_subtree(
  document: DocumentNode,
  root: ElementNode,
  *,
  width: int = 80,
  viewport_columns: int | None = None,
  session: Any = None,
) -> list[tuple[str, str]]:
  result = render_normal_subtree_with_metadata(
    document,
    root,
    width=width,
    viewport_columns=viewport_columns,
    link_style="none",
    text_styles=False,
    include_title=False,
    include_controls=False,
    include_control_metadata=False,
    session=session,
  )
  return visible_links_from_render_result(result)


def _visible_link_text(text: str, href: str) -> str:
  if not text:
    return href
  frame_suffix = f"] ({href})"
  if text.startswith("[frame: ") and text.endswith(frame_suffix):
    return text[len("[frame: "):-len(frame_suffix)]
  return text


def collect_two_pane_targets(
  document: DocumentNode,
  *,
  width: int = 80,
  viewport_columns: int | None = None,
  session: Any = None,
) -> list[tuple[PaneTarget, PaneTarget]]:
  # Check the renderer's static-rich policy before scanning layout hints.
  # These pages are rendered without full CSS, so CSS-based pane detection
  # would both duplicate work and disagree with their displayed layout.
  if _should_use_lightweight_style_render(document):
    LOGGER.debug("pane detection skipped reason=lightweight-render")
    return []
  if not _may_have_two_pane_targets(document):
    LOGGER.debug("pane detection skipped reason=no-layout-candidate")
    return []
  state = RenderState(
    document=document,
    width=width,
    link_style="none",
    text_styles=False,
    style_context=build_style_context(
      document, viewport_columns=viewport_columns or max(width, 160), session=session,
    ),
  )
  root = document.body or document.root
  if root is None:
    return []
  return _collect_two_pane_targets(root, state, path=())


def _may_have_two_pane_targets(document: DocumentNode) -> bool:
  root = document.body or document.root
  if root is None:
    return False
  pending = [root]
  while pending:
    node = pending.pop()
    if node.tag in SKIP_TAGS or _is_statically_hidden_layout_child(node):
      continue
    element_children = [
      child for child in node.children
      if isinstance(child, ElementNode)
      and child.tag not in SKIP_TAGS
      and not _is_statically_hidden_layout_child(child)
    ]
    pending.extend(reversed(element_children))
    if len(element_children) < 2:
      continue
    style = (node.attrs.get("style") or "").replace(" ", "").lower()
    if (
      "display:flex" in style
      or "display:grid" in style
      or "grid-template-columns" in style
      or "column-count:" in style
      or "columns:" in style
    ):
      return True
    node_tokens = " ".join(
      value.lower()
      for value in (
        node.tag,
        node.attrs.get("class", ""),
        node.attrs.get("id", ""),
        node.attrs.get("role", ""),
      )
      if value
    )
    if not any(token in node_tokens for token in ("grid", "flex", "pane", "layout", "split", "sidebar", "rail", "drawer")):
      continue
    if any(
      any(
        token in " ".join(
          value.lower()
          for value in (
            child.tag,
            child.attrs.get("class", ""),
            child.attrs.get("id", ""),
            child.attrs.get("role", ""),
          )
          if value
        )
        for token in ("main", "content", "article", "sidebar", "aside", "nav", "rail", "menu", "toc", "pane", "column")
      )
      for child in element_children
    ):
      return True
  return False


def _render_blocks(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool = True,
  properties: StyleProperties | None = None,
) -> list[RenderBlock]:
  if not state.can_append_block():
    state.truncated = True
    return []
  if node.tag in SKIP_TAGS:
    return []
  if properties is None:
    properties = _child_properties(node, state, inherited_visible)
  if properties is not None:
    if not properties.visible:
      return []
    inherited_visible = properties.visible

  if node.tag == "a" and _is_block_node(node, properties=properties):
    block_link = _render_block_link(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if block_link is not None:
      return block_link

  if node.tag in {"input", "textarea", "select", "button"}:
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks: list[RenderBlock] = []
    state.append_block(
      blocks,
      RenderBlock(text, kind="paragraph", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "img":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks: list[RenderBlock] = []
    state.append_block(
      blocks,
      RenderBlock(text, kind="paragraph", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "iframe":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks: list[RenderBlock] = []
    state.append_block(
      blocks,
      RenderBlock(text, kind="paragraph", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag in HEADING_TAGS:
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    level = int(node.tag[1])
    blocks: list[RenderBlock] = []
    state.append_block(
      blocks,
      RenderBlock(
        f'{"#" * level} {_apply_terminal_bold(text) if state.text_styles else text}',
        kind="heading",
        text_align=_text_align_value(properties),
      ),
    )
    return blocks

  if node.tag == "li":
    marker = _list_item_marker(node, state)
    if (marker != "- " and _single_nested_list_child(node) is None) or any(
      isinstance(child, ElementNode) and (child.tag in HEADING_TAGS or child.tag == "ol")
      for child in node.children
    ):
      blocks = _render_container(node, state, inherited_visible, properties)
      indent = " " * len(marker)
      return [
        replace(
          block,
          text=(marker if index == 0 else indent) + (
            re.sub(r"^#{1,6} ", "", block.text) if block.kind == "heading" else block.text
          ).replace("\n", "\n" + indent),
        )
        for index, block in enumerate(blocks)
      ]
    if compound_block := _render_compound_nested_list_item(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    ):
      return compound_block
    if _is_structural_list_wrapper_item(node):
      nested_blocks = _render_structural_list_wrapper_item(
        node,
        state,
        inherited_visible=inherited_visible,
      )
      if nested_blocks:
        return nested_blocks
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(f"{marker}{text}", kind="list_item", text_align=_text_align_value(properties)),
    )
    return blocks

  if _display_value(properties) == "list-item":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(f"- {text}", kind="list_item", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "dt":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(blocks, RenderBlock(text, kind="dt", text_align=_text_align_value(properties)))
    return blocks

  if node.tag == "dd":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(f"  {text}", kind="dd", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "summary":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(text, kind="summary", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "figcaption":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(f"  {text}", kind="figcaption", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "legend":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(text, kind="legend", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "blockquote":
    text = _render_inline(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if not text:
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(f"> {text}", kind="blockquote", text_align=_text_align_value(properties)),
    )
    return blocks

  if node.tag == "pre":
    text = _render_preformatted(
      node,
      state,
      inherited_visible=inherited_visible,
    )
    if not text.strip():
      return []
    blocks = []
    state.append_block(
      blocks,
      RenderBlock(text.rstrip("\n"), kind="preformatted"),
    )
    return blocks

  if node.tag == "table":
    return _render_table(
      node,
      state,
      inherited_visible=inherited_visible,
    )

  synthetic_button = _synthetic_clickable_button_control(state.document, node)
  if synthetic_button is not None:
    if not state.include_controls:
      return []
    text = _apply_inline_emphasis(synthetic_button.token, properties, state.text_styles)
    blocks: list[RenderBlock] = []
    state.append_block(
      blocks,
      RenderBlock(
        state.annotate_control(
          text,
          control_id=synthetic_button.control_id,
          label=synthetic_button.label,
          kind=synthetic_button.kind,
        ),
        kind="paragraph",
        text_align=_text_align_value(properties),
      ),
    )
    return blocks

  if node.tag in {"p", "div", "section", "article", "main", "header", "footer", "aside", "nav", "form"}:
    return _render_container(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )

  if node.tag in {"ul", "ol"}:
    if _is_row_flex_container(properties):
      return _render_container(
        node,
        state,
        inherited_visible=inherited_visible,
        properties=properties,
      )
    items: list[RenderBlock] = []
    for child in node.children:
      if isinstance(child, ElementNode):
        if not state.can_append_block():
          break
        child_properties = _child_properties(child, state, inherited_visible)
        if child_properties is None or child_properties.visible:
          items.extend(
            _render_blocks(
              child,
              state,
              inherited_visible=inherited_visible,
              properties=child_properties,
            )
          )
    return items

  return _render_container(
    node,
    state,
    inherited_visible=inherited_visible,
    properties=properties,
  )


def _render_block_link(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
  properties: StyleProperties | None,
) -> list[RenderBlock] | None:
  href = node.attrs.get("href", "").strip()
  if not href:
    return None
  is_javascript_control = href.casefold().startswith("javascript:")
  control_id = _ensure_control_id(state.document, node) if is_javascript_control else ""

  child_blocks = _render_container(
    node,
    state,
    inherited_visible=inherited_visible,
    properties=properties,
  )
  if child_blocks:
    rendered = _join_blocks(child_blocks, state.width)
    if rendered.strip():
      if is_javascript_control:
        label = _normalize_text(ANSI_ESCAPE_RE.sub("", rendered)) or _accessible_label(node) or control_id
        return [
          RenderBlock(
            state.annotate_control(
              rendered,
              control_id=control_id,
              label=label,
              kind="button",
            ),
            kind="grid",
          )
        ]
      return [RenderBlock(state.annotate_link(rendered, href), kind="grid")]

  label = _accessible_label(node)
  if not label:
    return None
  return [
    RenderBlock(
      state.annotate_control(
        label,
        control_id=control_id,
        label=label,
        kind="button",
      ) if is_javascript_control else state.annotate_link(label, href),
      kind="paragraph",
      text_align=_text_align_value(properties),
    )
  ]


def _collect_two_pane_targets(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool = True,
  properties: StyleProperties | None = None,
  *,
  path: tuple[int, ...],
) -> list[tuple[PaneTarget, PaneTarget]]:
  if node.tag in SKIP_TAGS:
    return []
  if properties is None:
    properties = _child_properties(node, state, inherited_visible)
  if properties is not None:
    if not properties.visible:
      return []
    inherited_visible = properties.visible

  visible_children = _visible_element_children(node, state, inherited_visible)
  child_paths = {
    id(child): path + (index,)
    for index, child in enumerate(node.children)
    if isinstance(child, ElementNode)
  }

  if _is_two_column_grid_container(properties):
    candidate_children = [child for child, _ in visible_children]
    if len(candidate_children) == 2:
      left_width, right_width = _grid_column_widths(properties, state.width)
      if left_width >= 12 and right_width >= 12:
        candidate_children = _order_two_pane_children(
          candidate_children,
          left_width=left_width,
          right_width=right_width,
        )
        return [(
          PaneTarget(path=child_paths[id(candidate_children[0])]),
          PaneTarget(path=child_paths[id(candidate_children[1])]),
        )]

  if _is_row_flex_container(properties) and _is_two_column_flex_container(node, state, inherited_visible):
    candidate_children = [child for child, _ in visible_children]
    if len(candidate_children) == 2:
      left_width, right_width = _flex_column_widths(
        visible_children[0][0],
        visible_children[0][1],
        visible_children[1][0],
        visible_children[1][1],
        state.width,
      )
      if left_width >= 12 and right_width >= 12:
        candidate_children = _order_two_pane_flex_children(
          candidate_children,
          properties=properties,
        )
        return [(
          PaneTarget(path=child_paths[id(candidate_children[0])]),
          PaneTarget(path=child_paths[id(candidate_children[1])]),
        )]

  groups: list[tuple[PaneTarget, PaneTarget]] = []
  for index, child in enumerate(node.children):
    if not isinstance(child, ElementNode):
      continue
    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue
    groups.extend(
      _collect_two_pane_targets(
        child,
        state,
        inherited_visible=inherited_visible,
        properties=child_properties,
        path=path + (index,),
      )
    )
  return groups


def _render_container(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool = True,
  properties: StyleProperties | None = None,
) -> list[RenderBlock]:
  wikipedia_heading_blocks = _render_wikipedia_heading_container(
    node,
    state,
    inherited_visible=inherited_visible,
    properties=properties,
  )
  if wikipedia_heading_blocks is not None:
    return wikipedia_heading_blocks
  blocks: list[RenderBlock] = []
  inline_parts: list[str] = []
  overlay_links: list[tuple[str, str]] = []
  text_align = _text_align_value(properties)
  row_flex = _is_row_flex_container(properties)
  two_column_grid = _is_two_column_grid_container(properties)
  two_column_flex = row_flex and _is_two_column_flex_container(
    node,
    state,
    inherited_visible=inherited_visible,
  )

  if two_column_grid:
    grid_blocks = _render_two_column_grid(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if grid_blocks is not None:
      return grid_blocks
  if two_column_flex:
    flex_blocks = _render_two_column_flex(
      node,
      state,
      inherited_visible=inherited_visible,
      properties=properties,
    )
    if flex_blocks is not None:
      return flex_blocks

  for child in node.children:
    if not state.can_append_block():
      _flush_inline_parts(blocks, inline_parts, state)
      break
    if isinstance(child, TextNode):
      text = _normalize_text(child.text)
      if text:
        inline_parts.append(text)
      continue

    if child.tag in SKIP_TAGS:
      continue

    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue

    if child.tag == "a":
      href = child.attrs.get("href", "").strip()
      label = _accessible_label(child)
      if href and label and _should_skip_empty_anchor_label(
        child,
        state,
        label,
        inherited_visible=inherited_visible,
      ):
        overlay_links.append((label, href))
        continue

    if row_flex and _can_inline_row_flex_child(
      child,
      state,
      inherited_visible=inherited_visible,
    ):
      text = _render_inline(
        child,
        state,
        inherited_visible=inherited_visible,
        properties=child_properties,
      )
      if text:
        inline_parts.append(text)
      continue

    if _is_block_node(child, properties=child_properties):
      _flush_inline_parts(blocks, inline_parts, state)
      blocks.extend(
        _render_blocks(
          child,
          state,
          inherited_visible=inherited_visible,
          properties=child_properties,
        )
      )
      continue

    text = _render_inline(
      child,
      state,
      inherited_visible=inherited_visible,
      properties=child_properties,
    )
    if text:
      inline_parts.append(text)

  if overlay_links:
    if inline_parts:
      overlay_text = _annotate_overlay_link_text(
        _join_inline_parts(inline_parts),
        overlay_links,
        state,
      )
      inline_parts.clear()
      if overlay_text:
        inline_parts.append(overlay_text)
    else:
      blocks = _annotate_overlay_link_blocks(blocks, overlay_links, state)

  _flush_inline_parts(blocks, inline_parts, state)
  blocks = _inherit_block_alignment(blocks, text_align)
  if node.tag == "p" and _has_compact_block_spacing(properties):
    blocks = [replace(block, compact_spacing=True) for block in blocks]
  return blocks


def _render_wikipedia_heading_container(
  node: ElementNode,
  state: RenderState,
  *,
  inherited_visible: bool,
  properties: StyleProperties | None,
) -> list[RenderBlock] | None:
  if node.tag != "div":
    return None
  class_tokens = {
    token.strip()
    for token in node.attrs.get("class", "").split()
    if token.strip()
  }
  if not any(token.startswith("mw-heading") for token in class_tokens):
    return None
  visible_children: list[tuple[ElementNode, StyleProperties | None]] = []
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag in SKIP_TAGS:
      continue
    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue
    visible_children.append((child, child_properties))
  if len(visible_children) != 2:
    return None
  heading_node, heading_properties = visible_children[0]
  edit_node, _ = visible_children[1]
  if heading_node.tag not in HEADING_TAGS:
    return None
  edit_classes = {
    token.strip()
    for token in edit_node.attrs.get("class", "").split()
    if token.strip()
  }
  if edit_node.tag != "span" or "mw-editsection" not in edit_classes:
    return None
  heading_text = _render_inline(
    heading_node,
    state,
    inherited_visible=inherited_visible,
    properties=heading_properties,
  )
  edit_text = _render_inline(
    edit_node,
    state,
    inherited_visible=inherited_visible,
  )
  combined = _join_inline_parts([heading_text, edit_text]).strip()
  if not combined:
    return []
  level = int(heading_node.tag[1])
  return [RenderBlock(
    f'{"#" * level} {_apply_terminal_bold(combined) if state.text_styles else combined}',
    kind="heading",
    text_align=_text_align_value(properties),
  )]


def _render_two_column_grid(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
  properties: StyleProperties | None,
) -> list[RenderBlock] | None:
  non_empty_text = [
    child for child in node.children if isinstance(child, TextNode) and _normalize_text(child.text)
  ]
  if non_empty_text:
    return None

  visible_children: list[ElementNode] = []
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag in SKIP_TAGS:
      continue
    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue
    visible_children.append(child)

  if len(visible_children) != 2:
    return None

  left_width, right_width = _grid_column_widths(properties, state.width)
  if left_width < 12 or right_width < 12:
    return None

  visible_children = _order_two_pane_children(
    visible_children,
    left_width=left_width,
    right_width=right_width,
  )
  left_text = _join_blocks(
    _render_blocks_for_column_width(visible_children[0], state, left_width, inherited_visible),
    left_width,
  )
  right_text = _join_blocks(
    _render_blocks_for_column_width(visible_children[1], state, right_width, inherited_visible),
    right_width,
  )
  if not left_text.strip():
    return _render_blocks_for_column_width(visible_children[1], state, right_width, inherited_visible)
  if not right_text.strip():
    return _render_blocks_for_column_width(visible_children[0], state, left_width, inherited_visible)
  merged = _merge_text_columns(left_text, right_text, left_width, right_width)
  if not merged.strip():
    return None
  return [RenderBlock(merged, kind="grid")]


def _render_two_column_flex(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
  properties: StyleProperties | None,
) -> list[RenderBlock] | None:
  visible_children = _visible_element_children(node, state, inherited_visible)
  if len(visible_children) != 2:
    return None

  left_width, right_width = _flex_column_widths(
    visible_children[0][0],
    visible_children[0][1],
    visible_children[1][0],
    visible_children[1][1],
    state.width,
  )
  if left_width < 12 or right_width < 12:
    return None

  ordered_children = _order_two_pane_flex_children(
    [visible_children[0][0], visible_children[1][0]],
    properties=properties,
  )
  ordered_visible_children = [
    next(entry for entry in visible_children if entry[0] is child)
    for child in ordered_children
  ]
  left_text = _join_blocks(
    _render_blocks_for_column_width(
      ordered_visible_children[0][0],
      state,
      left_width,
      inherited_visible,
      properties=ordered_visible_children[0][1],
    ),
    left_width,
  )
  right_text = _join_blocks(
    _render_blocks_for_column_width(
      ordered_visible_children[1][0],
      state,
      right_width,
      inherited_visible,
      properties=ordered_visible_children[1][1],
    ),
    right_width,
  )
  if not left_text.strip():
    return _render_blocks_for_column_width(
      ordered_visible_children[1][0],
      state,
      right_width,
      inherited_visible,
      properties=ordered_visible_children[1][1],
    )
  if not right_text.strip():
    return _render_blocks_for_column_width(
      ordered_visible_children[0][0],
      state,
      left_width,
      inherited_visible,
      properties=ordered_visible_children[0][1],
    )
  merged = _merge_text_columns(left_text, right_text, left_width, right_width)
  if not merged.strip():
    return None
  return [RenderBlock(merged, kind="grid")]


def _render_blocks_for_column_width(
  node: ElementNode,
  state: RenderState,
  width: int,
  inherited_visible: bool,
  properties: StyleProperties | None = None,
) -> list[RenderBlock]:
  if width == state.width:
    return _render_blocks(node, state, inherited_visible, properties=properties)

  original_width = state.width
  state.width = width
  try:
    return _render_blocks(node, state, inherited_visible, properties=properties)
  finally:
    state.width = original_width


def _render_table(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
) -> list[RenderBlock]:
  caption = ""
  rows = _collect_table_rows(node, state, inherited_visible, caption_ref := [""])
  caption = caption_ref[0]
  if not rows:
    return [RenderBlock(caption, kind="paragraph")] if caption else []

  column_count = max(len(row.cells) for row in rows)
  if column_count <= 0:
    return [RenderBlock(caption, kind="paragraph")] if caption else []

  normalized_rows = [
    TableRow(
      cells=row.cells + ("",) * (column_count - len(row.cells)),
      is_header=row.is_header,
    )
    for row in rows
  ]
  column_widths = _table_column_widths(normalized_rows, state.width)
  table_lines = _render_table_lines(normalized_rows, column_widths)
  if not table_lines:
    return [RenderBlock(caption, kind="paragraph")] if caption else []

  blocks: list[RenderBlock] = []
  if caption:
    state.append_block(blocks, RenderBlock(caption, kind="paragraph"))
  state.append_block(blocks, RenderBlock("\n".join(table_lines), kind="grid"))
  return blocks


def _collect_table_rows(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
  caption_ref: list[str],
  *,
  in_header_section: bool = False,
) -> list[TableRow]:
  rows: list[TableRow] = []
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag in SKIP_TAGS:
      continue
    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue
    if child.tag == "caption":
      caption_ref[0] = _render_inline(
        child,
        state,
        inherited_visible=inherited_visible,
        properties=child_properties,
      ).strip()
      continue
    if child.tag in {"thead", "tbody", "tfoot"}:
      rows.extend(
        _collect_table_rows(
          child,
          state,
          inherited_visible,
          caption_ref,
          in_header_section=(child.tag == "thead"),
        )
      )
      continue
    if child.tag != "tr":
      continue
    cells: list[str] = []
    header_flags: list[bool] = []
    for cell in child.children:
      if not isinstance(cell, ElementNode) or cell.tag not in {"th", "td"}:
        continue
      cell_properties = _child_properties(cell, state, inherited_visible)
      if cell_properties is not None and not cell_properties.visible:
        continue
      text = _render_inline(
        cell,
        state,
        inherited_visible=inherited_visible,
        properties=cell_properties,
      ).strip()
      cells.append(text)
      header_flags.append(cell.tag == "th")
    if cells:
      rows.append(
        TableRow(
          cells=tuple(cells),
          is_header=in_header_section or all(header_flags),
        )
      )
  return rows


def _table_column_widths(rows: list[TableRow], total_width: int) -> list[int]:
  column_count = len(rows[0].cells)
  gap_width = len(COLUMN_SEPARATOR) * max(0, column_count - 1)
  available_width = max(1, total_width - gap_width)
  max_widths = [
    max(3, max(_display_width(row.cells[index]) for row in rows))
    for index in range(column_count)
  ]
  if sum(max_widths) <= available_width:
    return max_widths

  min_widths = [max(3, min(width, 12)) for width in max_widths]
  min_total = sum(min_widths)
  if min_total >= available_width:
    base = max(1, available_width // column_count)
    widths = [base] * column_count
    remainder = max(0, available_width - sum(widths))
    for index in range(remainder):
      widths[index % column_count] += 1
    return widths

  widths = min_widths[:]
  remaining = available_width - min_total
  while remaining > 0:
    grew = False
    for index, max_width in enumerate(max_widths):
      if widths[index] >= max_width:
        continue
      widths[index] += 1
      remaining -= 1
      grew = True
      if remaining == 0:
        break
    if not grew:
      break
  return widths


def _render_table_lines(rows: list[TableRow], column_widths: list[int]) -> list[str]:
  rendered: list[str] = []
  for index, row in enumerate(rows):
    rendered.extend(_render_table_row(row.cells, column_widths))
    if row.is_header and index == 0:
      rendered.append(
        COLUMN_SEPARATOR.join("-" * width for width in column_widths)
      )
  return [line.rstrip() for line in rendered]


def _render_table_row(cells: tuple[str, ...], column_widths: list[int]) -> list[str]:
  wrapped_columns = [
    _wrap_table_cell(cell, width).splitlines() or [""]
    for cell, width in zip(cells, column_widths)
  ]
  row_height = max(len(lines) for lines in wrapped_columns)
  lines: list[str] = []
  for line_index in range(row_height):
    parts = []
    for column_index, width in enumerate(column_widths):
      column_lines = wrapped_columns[column_index]
      cell_line = column_lines[line_index] if line_index < len(column_lines) else ""
      parts.append(_pad_display_width(cell_line, width))
    lines.append(COLUMN_SEPARATOR.join(parts))
  return lines


def _wrap_table_cell(text: str, width: int) -> str:
  normalized = " ".join(text.split())
  if not normalized:
    return ""
  return _wrap_paragraph(normalized, width)


def _render_inline(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool = True,
  properties: StyleProperties | None = None,
) -> str:
  if node.tag in SKIP_TAGS:
    return ""
  if properties is None:
    properties = _child_properties(node, state, inherited_visible)
  if properties is not None:
    if not properties.visible:
      return ""
    inherited_visible = properties.visible

  if node.tag == "a":
    href = node.attrs.get("href", "").strip()
    text = _render_inline_children(node, state, inherited_visible=inherited_visible)
    skip_empty_overlay = False
    if not text:
      text = _accessible_label(node)
      if text and _should_skip_empty_anchor_label(
        node,
        state,
        text,
        inherited_visible=inherited_visible,
      ):
        text = ""
        skip_empty_overlay = True
    if skip_empty_overlay:
      return ""
    if not text:
      return ""
    if href.casefold().startswith("javascript:"):
      if not state.include_controls:
        return ""
      control_id = _ensure_control_id(state.document, node)
      label = text
      return state.annotate_control(
        _apply_inline_emphasis(text, properties, state.text_styles),
        control_id=control_id,
        label=label,
        kind="button",
      )
    if not href:
      return text
    if state.link_style == "none":
      return state.annotate_link(text or href, href)
    if state.link_style == "inline":
      return state.annotate_link(f"{text} ({href})" if text else href, href)
    return state.annotate_link(text or href, href)

  if node.tag == "img":
    label = _image_label(node)
    return _image_token(label)

  if node.tag == "iframe":
    src = node.attrs.get("src", "").strip()
    label = _frame_label(node)
    text = f"[frame: {label}]"
    if not src:
      return text
    if state.link_style == "inline":
      return state.annotate_link(f"{text} ({src})", src)
    return state.annotate_link(f"{text} ({src})", src)

  if node.tag == "input":
    input_type = node.attrs.get("type", "text")
    if input_type == "hidden":
      return ""
    if not state.include_controls:
      return ""
    control_id = _ensure_control_id(state.document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(state.document, node) or name or control_id
    if input_type in {"text", "search", "email", "url", "password", "number"}:
      value = node.attrs.get("value", "")
      token = _input_token(input_type, name, _display_input_value(input_type, value))
      return state.annotate_control(
        token,
        control_id=control_id,
        label=label,
        kind="text",
      )
    if input_type == "checkbox":
      token = _checkbox_token(name, "checked" in node.attrs)
      return state.annotate_control(
        token,
        control_id=control_id,
        label=label,
        kind="checkbox",
      )
    if input_type == "radio":
      value = node.attrs.get("value", "on")
      token = _radio_token(name, value, "checked" in node.attrs)
      return state.annotate_control(
        token,
        control_id=control_id,
        label=label or value,
        kind="radio",
      )
    if input_type in {"submit", "button"}:
      button_label = label or node.attrs.get("value") or input_type
      kind = "submit" if input_type == "submit" and _form_owner(state.document, node) is not None else "button"
      token = _interaction_button_token(button_label)
      return state.annotate_control(
        token,
        control_id=control_id,
        label=button_label,
        kind=kind,
      )
    return ""

  if node.tag == "textarea":
    if not state.include_controls:
      return ""
    control_id = _ensure_control_id(state.document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(state.document, node) or name or control_id
    token = _textarea_token(name, _textarea_value(node))
    return state.annotate_control(
      token,
      control_id=control_id,
      label=label,
      kind="textarea",
    )

  if node.tag == "select":
    if not state.include_controls:
      return ""
    control_id = _ensure_control_id(state.document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(state.document, node) or name or control_id
    selected = next((option for option in _select_options(node) if option.selected), None)
    selected_value = (selected.label or selected.value) if selected is not None else ""
    token = _select_token(name, selected_value)
    return state.annotate_control(
      token,
      control_id=control_id,
      label=label,
      kind="select",
    )

  if _is_tab_node(node):
    if not state.include_controls:
      return ""
    control_id = _ensure_control_id(state.document, node)
    label = _tab_label(state.document, node)
    token = _tab_token(label, _is_aria_selected(node))
    return state.annotate_control(
      _apply_inline_emphasis(token, properties, state.text_styles),
      control_id=control_id,
      label=label or control_id,
      kind="tab",
    )

  synthetic_button = _synthetic_clickable_button_control(state.document, node)
  if synthetic_button is not None:
    if not state.include_controls:
      return ""
    text = _apply_inline_emphasis(synthetic_button.token, properties, state.text_styles)
    return state.annotate_control(
      text,
      control_id=synthetic_button.control_id,
      label=synthetic_button.label,
      kind="button",
    )

  if node.tag == "button":
    if not state.include_controls:
      return ""
    control_id = _ensure_control_id(state.document, node)
    label = _tab_label(state.document, node) if _is_tab_node(node) else ""
    if not label:
      label = _render_inline_children(node, state, inherited_visible=inherited_visible)
    if not label:
      label = _accessible_label(node)
    if not label:
      label = _descendant_accessible_label(node)
    text = _apply_inline_emphasis(_interaction_button_token(label), properties, state.text_styles)
    return state.annotate_control(
      text,
      control_id=control_id,
      label=label or control_id,
      kind="submit" if _form_owner(state.document, node) is not None else "button",
    )

  if node.tag == "br":
    return "\n"

  if node.tag == "label":
    text = _render_inline_children(node, state, inherited_visible=inherited_visible)
    target = _label_target_control_metadata(state, node)
    if target is None or not text:
      return text
    control_id, label, kind = target
    return state.annotate_control(
      text,
      control_id=control_id,
      label=label,
      kind=kind,
      source_kind="label",
    )

  text = _render_inline_children(node, state, inherited_visible=inherited_visible)
  text = _apply_inline_emphasis(text, properties, state.text_styles)
  labelled_target = _labelledby_target_control_metadata(state, node)
  if labelled_target is None or not text:
    return text
  control_id, label, kind = labelled_target
  return state.annotate_control(
    text,
    control_id=control_id,
    label=label,
    kind=kind,
    source_kind="label",
  )


def _render_inline_children(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool = True,
) -> str:
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      text = _normalize_text(child.text)
      if text:
        parts.append(text)
      continue

    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue

    if _is_block_node(child, properties=child_properties):
      nested_parts = _render_blocks(
        child,
        state,
        inherited_visible=inherited_visible,
        properties=child_properties,
      )
      if nested_parts:
        nested_texts = [block.text for block in nested_parts if block.text]
        if any(block.kind == "preformatted" for block in nested_parts):
          parts.append("\n".join(nested_texts))
        else:
          parts.append(" ".join(nested_texts))
      continue

    text = _render_inline(
      child,
      state,
      inherited_visible=inherited_visible,
      properties=child_properties,
    )
    if text:
      parts.append(text)
  return _join_inline_parts(parts)


def _render_preformatted(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool = True,
) -> str:
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, TextNode):
      parts.append(child.text.replace("\r\n", "\n").replace("\r", "\n"))
      continue

    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue

    if child.tag == "br":
      parts.append("\n")
      continue

    text = _render_preformatted(
      child,
      state,
      inherited_visible=inherited_visible,
    )
    if text:
      parts.append(text)
  return _trim_preformatted_boundary_newlines("".join(parts))


def _trim_preformatted_boundary_newlines(text: str) -> str:
  if text.startswith("\n") and text != "\n":
    text = text[1:]
  if text.endswith("\n") and text != "\n":
    text = text[:-1]
  return text


def _image_label(node: ElementNode) -> str:
  return _accessible_label(node, keys=("alt", "aria-label", "title"))


def _image_token(label: str) -> str:
  return f"[{label}]" if label else "[image]"


def _button_token(label: str) -> str:
  return f"({label})" if label else "(button)"


def _frame_label(node: ElementNode) -> str:
  label = _accessible_label(node, keys=("title", "aria-label", "name"))
  if label:
    return label
  src = (node.attrs.get("src") or "").strip()
  return src or "embedded frame"


def _accessible_label(
  node: ElementNode,
  keys: tuple[str, ...] = ("aria-label", "title", "alt"),
) -> str:
  for key in keys:
    value = (node.attrs.get(key) or "").strip()
    if value:
      return value
  return ""


def _descendant_accessible_label(node: ElementNode) -> str:
  for child in node.children:
    if not isinstance(child, ElementNode):
      continue
    label = _accessible_label(child)
    if label:
      return label
    nested = _descendant_accessible_label(child)
    if nested:
      return nested
  return ""


def _should_skip_empty_anchor_label(
  node: ElementNode,
  state: RenderState,
  label: str,
  inherited_visible: bool,
) -> bool:
  if node.tag != "a" or node.children or state.style_context is None:
    return False
  parent = state.style_context.parent_map.get(id(node))
  if parent is None:
    return False
  normalized_label = _normalize_text(label)
  if not normalized_label:
    return False

  for sibling in parent.children:
    if sibling is node or not isinstance(sibling, ElementNode):
      continue
    sibling_properties = _child_properties(sibling, state, inherited_visible)
    if sibling_properties is not None and not sibling_properties.visible:
      continue
    sibling_text = _normalize_text(
      _render_inline(
        sibling,
        state,
        inherited_visible=inherited_visible,
        properties=sibling_properties,
      )
    )
    if sibling_text and normalized_label in sibling_text:
      return True
  return False


def _annotate_overlay_link_text(
  text: str,
  overlay_links: list[tuple[str, str]],
  state: RenderState,
) -> str:
  if not text:
    return text
  annotated = text
  for label, href in overlay_links:
    normalized_label = _normalize_text(label)
    if not normalized_label:
      continue
    start = annotated.find(normalized_label)
    if start < 0:
      continue
    end = start + len(normalized_label)
    annotated = (
      annotated[:start]
      + state.annotate_link(annotated[start:end], href)
      + annotated[end:]
    )
  return annotated


def _annotate_overlay_link_blocks(
  blocks: list[RenderBlock],
  overlay_links: list[tuple[str, str]],
  state: RenderState,
) -> list[RenderBlock]:
  remaining = list(overlay_links)
  annotated_blocks: list[RenderBlock] = []
  for block in blocks:
    if not remaining or not block.text:
      annotated_blocks.append(block)
      continue
    updated_text = block.text
    next_remaining: list[tuple[str, str]] = []
    for label, href in remaining:
      annotated = _annotate_overlay_link_text(updated_text, [(label, href)], state)
      if annotated == updated_text:
        next_remaining.append((label, href))
        continue
      updated_text = annotated
    annotated_blocks.append(replace(block, text=updated_text))
    remaining = next_remaining
  return annotated_blocks


def _label_target_control_metadata(
  state: RenderState,
  label_node: ElementNode,
) -> tuple[str, str, str] | None:
  for_attr = label_node.attrs.get("for", "").strip()
  target = _find_node_by_id(state, for_attr) if for_attr else _labelled_descendant_control(label_node)
  if target is None:
    return None
  return _control_metadata_for_node(state, target)


def _labelledby_target_control_metadata(
  state: RenderState,
  node: ElementNode,
) -> tuple[str, str, str] | None:
  node_id = node.attrs.get("id", "").strip()
  if not node_id:
    return None
  target = _labelledby_target(state, node_id)
  if target is None:
    return None
  return _control_metadata_for_node(state, target)


def _control_metadata_for_node(
  state: RenderState,
  node: ElementNode,
) -> tuple[str, str, str] | None:
  cache_key = id(node)
  cached = state.control_metadata_cache.get(cache_key)
  if cached is not None or cache_key in state.control_metadata_cache:
    return cached
  document = state.document
  if _is_tab_node(node):
    control_id = _ensure_control_id(document, node)
    label = _tab_label(document, node) or control_id
    result = (control_id, label, "tab")
  elif node.tag == "input":
    input_type = node.attrs.get("type", "text").strip().lower()
    if input_type == "hidden":
      result = None
    else:
      control_id = _ensure_control_id(document, node)
      name = node.attrs.get("name") or node.attrs.get("id") or control_id
      label = _control_label(document, node) or name or control_id
      if input_type in {"text", "search", "email", "url", "password", "number"}:
        result = (control_id, label, "text")
      elif input_type == "checkbox":
        result = (control_id, label, "checkbox")
      elif input_type == "radio":
        value = node.attrs.get("value", "on")
        result = (control_id, label or value, "radio")
      elif input_type == "submit":
        result = (control_id, label or node.attrs.get("value") or "submit", "submit")
      elif input_type == "button":
        result = (control_id, label or node.attrs.get("value") or "button", "button")
      else:
        result = None
  elif node.tag == "textarea":
    control_id = _ensure_control_id(document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(document, node) or name or control_id
    result = (control_id, label, "textarea")
  elif node.tag == "select":
    control_id = _ensure_control_id(document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(document, node) or name or control_id
    result = (control_id, label, "select")
  elif node.tag == "button":
    control_id = _ensure_control_id(document, node)
    label = _control_label(document, node)
    if not label:
      label = _normalize_text(node.text_content())
    if not label:
      label = _accessible_label(node)
    if not label:
      label = _descendant_accessible_label(node)
    result = (control_id, label or control_id, "submit" if _form_owner(document, node) is not None else "button")
  elif node.tag == "a":
    href = node.attrs.get("href", "").strip()
    if href.casefold().startswith("javascript:"):
      control_id = _ensure_control_id(document, node)
      label = _normalize_text(node.text_content()) or _accessible_label(node) or control_id
      result = (control_id, label, "button")
    else:
      result = None
  else:
    result = None
  state.control_metadata_cache[cache_key] = result
  return result


def _find_node_by_id(state: RenderState, target_id: str) -> ElementNode | None:
  if not target_id:
    return None
  if state.node_by_id_cache is None:
    state.node_by_id_cache = {}
    root = state.document.root
    if root is not None:
      for candidate in root.iter_nodes():
        if not isinstance(candidate, ElementNode):
          continue
        candidate_id = candidate.attrs.get("id", "").strip()
        if candidate_id and candidate_id not in state.node_by_id_cache:
          state.node_by_id_cache[candidate_id] = candidate
  return state.node_by_id_cache.get(target_id)


def _labelledby_target(state: RenderState, node_id: str) -> ElementNode | None:
  if state.labelledby_targets_cache is None:
    labelledby_targets: dict[str, ElementNode | None] = {}
    root = state.document.root
    if root is not None:
      for candidate in root.iter_nodes():
        if not isinstance(candidate, ElementNode):
          continue
        labelledby = candidate.attrs.get("aria-labelledby", "").strip().split()
        if not labelledby:
          continue
        for label_id in labelledby:
          labelledby_targets.setdefault(label_id, candidate)
    state.labelledby_targets_cache = labelledby_targets
  return state.labelledby_targets_cache.get(node_id)


def _labelled_descendant_control(node: ElementNode) -> ElementNode | None:
  for candidate in node.iter_nodes():
    if not isinstance(candidate, ElementNode) or candidate is node:
      continue
    if candidate.tag in {"input", "textarea", "select", "button"} or _is_tab_node(candidate):
      return candidate
  return None


def _flush_inline_parts(
  blocks: list[RenderBlock],
  inline_parts: list[str],
  state: RenderState,
) -> None:
  if not inline_parts:
    return
  block = _join_inline_parts(inline_parts).strip()
  inline_parts.clear()
  if block:
    state.append_block(blocks, RenderBlock(block, kind="paragraph"))


def _join_blocks(blocks: list[RenderBlock], width: int) -> str:
  rendered: list[str] = []
  previous_block: RenderBlock | None = None
  for block in blocks:
    if not block.text.strip():
      continue
    if rendered:
      rendered.append(_block_separator(previous_block, block))
    rendered.append(_render_block_text(block, width))
    previous_block = block
  return "".join(rendered)


def _render_block_text(block: RenderBlock, width: int) -> str:
  if block.kind in {"grid", "preformatted"}:
    return block.text
  wrapped = _wrap_block(block.text, width)
  return _align_block(wrapped, width, block.text_align)


def _separator(previous_kind: str | None, current_kind: str) -> str:
  if previous_kind in {"dt", "dd"} and current_kind in {"dt", "dd"}:
    return "\n"
  if previous_kind == "list_item" and current_kind == "list_item":
    return "\n"
  if previous_kind == "link" and current_kind == "link":
    return "\n"
  if previous_kind in {"summary", "legend", "figcaption"}:
    return "\n"
  if current_kind in {"summary", "legend", "figcaption"}:
    return "\n"
  return "\n\n"


def _block_separator(previous: RenderBlock | None, current: RenderBlock) -> str:
  if previous is None:
    return ""
  if previous.compact_spacing and current.compact_spacing:
    return "\n"
  return _separator(previous.kind, current.kind)


def _normalize_text(text: str) -> str:
  return " ".join(text.split())


def _wrap_block(block: str, width: int) -> str:
  if "\n" in block:
    return "\n".join(_wrap_block(line, width) if line.strip() else "" for line in block.splitlines())
  if match := re.match(r"^( *)(- |[+-]?\d+\. )(.*)$", block):
    base_indent, marker, content = match.groups()
    return _wrap_paragraph(
      content,
      width,
      initial_indent=base_indent + marker,
      subsequent_indent=base_indent + " " * len(marker),
    )
  if match := re.match(r"^( +)(.*)$", block):
    indent, content = match.groups()
    return _wrap_paragraph(
      content,
      width,
      initial_indent=indent,
      subsequent_indent=indent,
    )
  if block.startswith("> "):
    return _wrap_paragraph(
      block[2:],
      width,
      initial_indent="> ",
      subsequent_indent="> ",
    )
  return _wrap_paragraph(block, width)


def _join_inline_parts(parts: list[str]) -> str:
  if not parts:
    return ""
  joined_parts: list[str] = []
  ends_with_newline = False
  for part in parts:
    if not part:
      continue
    if part == "\n":
      while joined_parts and not joined_parts[-1]:
        joined_parts.pop()
      if joined_parts:
        joined_parts[-1] = joined_parts[-1].rstrip()
      joined_parts.append("\n")
      ends_with_newline = True
      continue
    if not joined_parts or ends_with_newline or part.startswith("\n"):
      joined_parts.append(part)
      ends_with_newline = part.endswith("\n")
      continue
    if _ends_with_opening_punctuation(joined_parts):
      joined_parts.append(part)
      ends_with_newline = part.endswith("\n")
      continue
    if part in PUNCTUATION:
      joined_parts.append(part)
      ends_with_newline = part.endswith("\n")
      continue
    joined_parts.append(" ")
    joined_parts.append(part)
    ends_with_newline = part.endswith("\n")
  return "".join(joined_parts)


def _ends_with_opening_punctuation(parts: list[str]) -> bool:
  for part in reversed(parts):
    if not part or part == "\n":
      continue
    return part.rstrip().endswith(tuple(OPENING_PUNCTUATION))
  return False


def _apply_inline_emphasis(
  text: str,
  properties: StyleProperties | None,
  text_styles: bool,
) -> str:
  if not text or properties is None:
    return text

  result = text
  if text_styles and _is_bold(properties.font_weight):
    result = _apply_terminal_bold(result)
  if text_styles and _is_italic(properties.font_style):
    result = f"_{result}_"
  if text_styles and _has_line_through(properties.text_decoration):
    result = f"~~{result}~~"
  if text_styles and _has_underline(properties.text_decoration):
    result = f"[underline: {result}]"
  return result


def _apply_terminal_bold(text: str) -> str:
  return f"{ANSI_BOLD}{text}{ANSI_BOLD_RESET}"


def _interactive_marker(marker: int, entry_id: int) -> str:
  return f"\x1b[{marker};{entry_id}m"


def _strip_custom_interactive_markers(text: str) -> str:
  return INTERACTIVE_MARKER_RE.sub("", text)


def _finalize_render_result(rendered: str, state: RenderState) -> NormalRenderResult:
  cleaned: list[str] = []
  active_spans: dict[int, int] = {}
  links: list[RenderedLinkMetadata] = []
  controls: list[RenderedControlMetadata] = []
  link_index = 0
  control_index = 0
  cursor = 0
  while cursor < len(rendered):
    marker_match = INTERACTIVE_MARKER_RE.match(rendered, cursor)
    if marker_match is not None:
      marker = int(marker_match.group("marker"))
      entry_id = int(marker_match.group("entry"))
      if marker == 9910:
        active_spans[entry_id] = len(cleaned)
      else:
        start = active_spans.pop(entry_id, None)
        if start is not None and 0 <= entry_id < len(state.interactive_entries):
          kind, payload = state.interactive_entries[entry_id]
          end = len(cleaned)
          if kind == "link" and isinstance(payload, _PendingLinkMetadata):
            links.append(
              RenderedLinkMetadata(
                start=start,
                end=end,
                text=payload.text,
                href=payload.href,
                index=link_index,
              )
            )
            link_index += 1
          elif kind == "control" and isinstance(payload, _PendingControlMetadata):
            controls.append(
              RenderedControlMetadata(
                start=start,
                end=end,
                text=payload.text,
                control_id=payload.control_id,
                label=payload.label,
                kind=payload.kind,
                index=control_index,
                source_kind=payload.source_kind,
              )
            )
            control_index += 1
      cursor = marker_match.end()
      continue
    cleaned.append(rendered[cursor])
    cursor += 1
  return NormalRenderResult(
    text="".join(cleaned),
    link_spans=tuple(links),
    control_spans=tuple(controls),
  )


def _is_bold(font_weight: str | None) -> bool:
  if font_weight is None:
    return False
  lowered = font_weight.strip().lower()
  if lowered == "bold":
    return True
  if lowered.isdigit():
    return int(lowered) >= 600
  return False


def _is_italic(font_style: str | None) -> bool:
  return font_style is not None and font_style.strip().lower() == "italic"


def _has_line_through(text_decoration: str | None) -> bool:
  if text_decoration is None:
    return False
  return "line-through" in text_decoration.strip().lower()


def _has_underline(text_decoration: str | None) -> bool:
  if text_decoration is None:
    return False
  return "underline" in text_decoration.strip().lower()


def _text_align_value(properties: StyleProperties | None) -> str | None:
  if properties is None or properties.text_align is None:
    return None
  return properties.text_align.strip().lower()


def _inherit_block_alignment(blocks: list[RenderBlock], text_align: str | None) -> list[RenderBlock]:
  if text_align is None:
    return blocks
  return [
    block if block.text_align is not None or block.kind == "grid"
    else replace(block, text_align=text_align)
    for block in blocks
  ]


def _align_block(text: str, width: int, text_align: str | None) -> str:
  if text_align != "center":
    return text
  return "\n".join(_center_line(line, width) for line in text.splitlines())


def _center_line(line: str, width: int) -> str:
  stripped = line.strip()
  if not stripped:
    return ""
  line_width = _display_width(stripped)
  if line_width >= width:
    return stripped
  padding = max(0, (width - line_width) // 2)
  return (" " * padding) + stripped


def _display_value(properties: StyleProperties | None) -> str | None:
  if properties is None or properties.display is None:
    return None
  return properties.display.strip().lower()


def _flex_direction_value(properties: StyleProperties | None) -> str:
  if properties is None or properties.flex_direction is None:
    return "row"
  return properties.flex_direction.strip().lower()


def _grid_template_columns_value(properties: StyleProperties | None) -> str | None:
  if properties is None or properties.grid_template_columns is None:
    return None
  return properties.grid_template_columns.strip().lower()


def _is_row_flex_container(properties: StyleProperties | None) -> bool:
  display = _display_value(properties)
  if display not in {"flex", "inline-flex"}:
    return False
  return not _flex_direction_value(properties).startswith("column")


def _is_two_column_grid_container(properties: StyleProperties | None) -> bool:
  display = _display_value(properties)
  if display != "grid":
    return False
  return _grid_column_count(_grid_template_columns_value(properties)) == 2


def _grid_column_count(template: str | None) -> int:
  if not template:
    return 0
  return len(_split_top_level_tokens(template))


def _grid_column_widths(properties: StyleProperties | None, total_width: int) -> tuple[int, int]:
  gap = len(COLUMN_SEPARATOR)
  usable_width = max(total_width - gap, 24)
  template = _grid_template_columns_value(properties)
  tokens = _split_top_level_tokens(template or "")
  if len(tokens) != 2:
    half = usable_width // 2
    return half, usable_width - half

  right_fixed = _token_fixed_columns(tokens[1])
  if right_fixed is not None:
    right_width = min(max(right_fixed, 16), max(16, usable_width - 20))
    return usable_width - right_width, right_width

  left_fixed = _token_fixed_columns(tokens[0])
  if left_fixed is not None:
    left_width = min(max(left_fixed, 16), max(16, usable_width - 20))
    return left_width, usable_width - left_width

  half = usable_width // 2
  return half, usable_width - half


def _is_two_column_flex_container(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
) -> bool:
  if any(isinstance(child, TextNode) and _normalize_text(child.text) for child in node.children):
    return False
  structural_children = 0
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag in SKIP_TAGS:
      continue
    if _is_statically_hidden_layout_child(child):
      continue
    structural_children += 1
    if structural_children > 2:
      return False

  visible_children = _visible_element_children(node, state, inherited_visible)
  if len(visible_children) != 2:
    return False

  return all(_is_block_node(child, properties=properties) for child, properties in visible_children)


def _can_inline_row_flex_child(
  node: ElementNode,
  state: RenderState,
  *,
  inherited_visible: bool,
) -> bool:
  if node.tag == "pre":
    return False
  for descendant in node.iter_descendants():
    if not isinstance(descendant, ElementNode) or descendant.tag in SKIP_TAGS:
      continue
    descendant_properties = _child_properties(descendant, state, inherited_visible)
    if descendant_properties is not None and not descendant_properties.visible:
      continue
    if _is_block_node(descendant, properties=descendant_properties):
      return False
  return True


def _is_statically_hidden_layout_child(node: ElementNode) -> bool:
  style = (node.attrs.get("style") or "").replace(" ", "").lower()
  if "display:none" in style or "visibility:hidden" in style:
    return True
  if node.attrs.get("hidden") is not None:
    return True
  return (node.attrs.get("aria-hidden") or "").strip().lower() == "true"


def _visible_element_children(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
) -> list[tuple[ElementNode, StyleProperties | None]]:
  visible_children: list[tuple[ElementNode, StyleProperties | None]] = []
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag in SKIP_TAGS:
      continue
    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue
    visible_children.append((child, child_properties))
  return visible_children


def _flex_column_widths(
  left_node: ElementNode,
  left_properties: StyleProperties | None,
  right_node: ElementNode,
  right_properties: StyleProperties | None,
  total_width: int,
) -> tuple[int, int]:
  gap = len(COLUMN_SEPARATOR)
  usable_width = max(total_width - gap, 24)

  left_ratio = _column_fraction(left_properties)
  right_ratio = _column_fraction(right_properties)
  if left_ratio is not None and right_ratio is not None and left_ratio + right_ratio > 0:
    left_width = max(1, round(usable_width * left_ratio / (left_ratio + right_ratio)))
    left_width = min(max(left_width, 1), usable_width - 1)
    return left_width, usable_width - left_width

  if left_ratio is not None and 0 < left_ratio < 1:
    left_width = max(1, round(usable_width * left_ratio))
    left_width = min(max(left_width, 1), usable_width - 1)
    return left_width, usable_width - left_width

  if right_ratio is not None and 0 < right_ratio < 1:
    right_width = max(1, round(usable_width * right_ratio))
    right_width = min(max(right_width, 1), usable_width - 1)
    return usable_width - right_width, right_width

  auto_sidebar = _auto_sidebar_width(
    left_node,
    left_properties,
    right_node,
    right_properties,
    usable_width,
  )
  if auto_sidebar is not None:
    return auto_sidebar

  auto_nav = _auto_nav_width(
    left_node,
    left_properties,
    right_node,
    right_properties,
    usable_width,
  )
  if auto_nav is not None:
    return auto_nav

  half = usable_width // 2
  return half, usable_width - half


def _auto_sidebar_width(
  left_node: ElementNode,
  left_properties: StyleProperties | None,
  right_node: ElementNode,
  right_properties: StyleProperties | None,
  usable_width: int,
) -> tuple[int, int] | None:
  if usable_width <= 0:
    return None

  left_fill = _is_fill_width_pane(left_properties)
  right_fill = _is_fill_width_pane(right_properties)
  left_fraction = _column_fraction(left_properties)
  right_fraction = _column_fraction(right_properties)
  left_fixed = _fixed_pane_columns(left_properties)
  right_fixed = _fixed_pane_columns(right_properties)
  preferred_sidebar = min(max(16, usable_width // 4), max(16, usable_width - 20))

  if (
    _is_primary_content_pane(left_node) and
    not _is_primary_content_pane(right_node) and
    right_fixed is not None
  ):
    right_width = min(max(right_fixed, 16), max(16, usable_width - 20))
    return usable_width - right_width, right_width

  if (
    not _is_primary_content_pane(left_node) and
    _is_primary_content_pane(right_node) and
    left_fixed is not None
  ):
    left_width = min(max(left_fixed, 16), max(16, usable_width - 20))
    return left_width, usable_width - left_width

  if (
    right_fill and
    left_fraction is None and
    not _is_primary_content_pane(left_node) and
    _is_primary_content_pane(right_node)
  ):
    return preferred_sidebar, usable_width - preferred_sidebar

  if (
    left_fill and
    right_fraction is None and
    _is_primary_content_pane(left_node) and
    not _is_primary_content_pane(right_node)
  ):
    return usable_width - preferred_sidebar, preferred_sidebar

  return None


def _is_fill_width_pane(properties: StyleProperties | None) -> bool:
  if properties is None:
    return False
  for candidate in (properties.width, properties.flex_basis):
    if candidate is None:
      continue
    if candidate.strip().lower() == "100%":
      return True
  return False


def _fixed_pane_columns(properties: StyleProperties | None) -> int | None:
  if properties is None:
    return None
  for candidate in (properties.width, properties.flex_basis):
    fixed = _token_fixed_columns(candidate or "")
    if fixed is not None:
      return fixed
  return None


def _auto_nav_width(
  left_node: ElementNode,
  left_properties: StyleProperties | None,
  right_node: ElementNode,
  right_properties: StyleProperties | None,
  usable_width: int,
) -> tuple[int, int] | None:
  if usable_width <= 0:
    return None
  if any(
    _column_fraction(properties) is not None or _is_fill_width_pane(properties)
    for properties in (left_properties, right_properties)
  ):
    return None

  brand_width = min(max(20, usable_width // 3), max(20, usable_width - 24))
  if left_node.tag != "nav" and right_node.tag == "nav":
    return brand_width, usable_width - brand_width
  if left_node.tag == "nav" and right_node.tag != "nav":
    return usable_width - brand_width, brand_width
  return None


def _column_fraction(properties: StyleProperties | None) -> float | None:
  if properties is None:
    return None

  for candidate in (properties.width, properties.flex_basis):
    fraction = _fraction_from_length(candidate)
    if fraction is not None:
      return fraction

  return _fraction_from_flex(properties.flex)


def _fraction_from_length(value: str | None) -> float | None:
  if value is None:
    return None
  cleaned = value.strip().lower()
  if cleaned.endswith("%"):
    try:
      return float(cleaned[:-1].strip()) / 100.0
    except ValueError:
      return None
  return None


def _fraction_from_flex(value: str | None) -> float | None:
  if value is None:
    return None
  tokens = _split_top_level_tokens(value.strip().lower())
  if not tokens:
    return None

  first = tokens[0]
  try:
    if first.endswith("%"):
      return float(first[:-1].strip()) / 100.0
    return float(first)
  except ValueError:
    return None


def _split_top_level_tokens(value: str) -> list[str]:
  tokens: list[str] = []
  current: list[str] = []
  depth = 0
  for char in value:
    if char == "(":
      depth += 1
    elif char == ")" and depth > 0:
      depth -= 1
    if char.isspace() and depth == 0:
      token = "".join(current).strip()
      if token:
        tokens.append(token)
      current = []
      continue
    current.append(char)

  token = "".join(current).strip()
  if token:
    tokens.append(token)
  return tokens


def _token_fixed_columns(token: str) -> int | None:
  cleaned = token.strip().lower()
  if cleaned.endswith("px"):
    raw_value = cleaned[:-2].strip()
    if raw_value.isdigit():
      return max(1, int(raw_value) // 8)
  return None


def _order_two_pane_children(
  children: list[ElementNode],
  *,
  left_width: int,
  right_width: int,
) -> list[ElementNode]:
  if len(children) != 2:
    return children
  left, right = children
  if _is_sidebar_like_pane(left) and _is_primary_content_pane(right):
    return children
  if _is_primary_content_pane(left) and _is_sidebar_like_pane(right):
    return [right, left]
  if left_width < right_width and not _is_sidebar_like_pane(left) and _is_sidebar_like_pane(right):
    return [right, left]
  return children


def _order_two_pane_flex_children(
  children: list[ElementNode],
  *,
  properties: StyleProperties | None,
) -> list[ElementNode]:
  if len(children) != 2:
    return children
  if _flex_direction_value(properties).startswith("row-reverse"):
    return [children[1], children[0]]
  return children


def _is_sidebar_like_pane(node: ElementNode) -> bool:
  values = [
    node.tag,
    node.attrs.get("class", ""),
    node.attrs.get("id", ""),
    node.attrs.get("aria-label", ""),
  ]
  haystack = " ".join(value.lower() for value in values if value)
  if node.tag in {"aside", "nav"}:
    return True
  return any(token in haystack for token in ("aside", "sidebar", "nav", "menu", "toc", "trend"))


def _is_primary_content_pane(node: ElementNode) -> bool:
  values = [
    node.tag,
    node.attrs.get("class", ""),
    node.attrs.get("id", ""),
    node.attrs.get("role", ""),
  ]
  haystack = " ".join(value.lower() for value in values if value)
  if node.tag in {"main", "article"}:
    return True
  return any(token in haystack for token in ("main", "content", "article", "body", "detail", "timeline"))


def _merge_text_columns(left_text: str, right_text: str, left_width: int, right_width: int) -> str:
  left_lines = _wrap_column_text_for_merge(left_text, left_width).splitlines() or [""]
  right_lines = _wrap_column_text_for_merge(right_text, right_width).splitlines() or [""]
  line_count = max(len(left_lines), len(right_lines))
  merged: list[str] = []
  for index in range(line_count):
    left = left_lines[index] if index < len(left_lines) else ""
    right = right_lines[index] if index < len(right_lines) else ""
    if not left and not right:
      merged.append("")
      continue
    if right and left:
      merged.append(f"{_pad_display_width(left, left_width)}{COLUMN_SEPARATOR}{right}".rstrip())
      continue
    if right:
      merged.append(f"{' ' * left_width}{COLUMN_SEPARATOR}{right}".rstrip())
      continue
    if left:
      merged.append(f"{_pad_display_width(left, left_width)}{COLUMN_SEPARATOR}".rstrip())
      continue
    merged.append(f"{' ' * left_width}{COLUMN_SEPARATOR}".rstrip())
  return "\n".join(merged).rstrip()


def _wrap_column_text_for_merge(text: str, width: int) -> str:
  if not text or width <= 0:
    return text
  lines: list[str] = []
  for line in text.splitlines():
    if _display_width(line) <= width:
      lines.append(line)
      continue
    lines.extend(_wrap_block(line, width).splitlines() or [""])
  return "\n".join(lines)


def _wrap_paragraph(
  text: str,
  width: int,
  initial_indent: str = "",
  subsequent_indent: str = "",
) -> str:
  if not text:
    return initial_indent.rstrip()

  lines: list[str] = []
  current = initial_indent
  current_indent = initial_indent
  current_width = _display_width(initial_indent)
  limit = max(width, current_width + 1)
  tokens = _tokenize_for_wrap(text)
  index = 0
  while index < len(tokens):
    token = tokens[index]
    if token == " ":
      if current.strip() and not current.endswith(" "):
        current += " "
        current_width += 1
      index += 1
      continue

    token_width = _display_width(token)
    if current_width + token_width <= limit:
      current += token
      current_width += token_width
      index += 1
      continue

    if (
      current.rstrip() != current_indent.rstrip() and
      _should_keep_wrap_token_intact(token) and
      _display_width(subsequent_indent) + token_width <= max(width, _display_width(subsequent_indent) + 1)
    ):
      lines.append(current.rstrip())
      current = subsequent_indent
      current_indent = subsequent_indent
      current_width = _display_width(subsequent_indent)
      limit = max(width, current_width + 1)

    while token:
      if current_width >= limit and current.rstrip() != current_indent.rstrip():
        lines.append(current.rstrip())
        current = subsequent_indent
        current_indent = subsequent_indent
        current_width = _display_width(subsequent_indent)
        limit = max(width, current_width + 1)
      available = max(1, limit - current_width)
      if (
        token and
        available < _char_display_width(token[0]) and
        current.rstrip() != current_indent.rstrip()
      ):
        lines.append(current.rstrip())
        current = subsequent_indent
        current_indent = subsequent_indent
        current_width = _display_width(subsequent_indent)
        limit = max(width, current_width + 1)
        continue
      head, token = _split_by_display_width(token, available)
      current += head
      current_width += _display_width(head)
      if token:
        lines.append(current.rstrip())
        current = subsequent_indent
        current_indent = subsequent_indent
        current_width = _display_width(subsequent_indent)
        limit = max(width, current_width + 1)
    index += 1

  if current.strip() or not lines:
    lines.append(current.rstrip())
  return "\n".join(lines)


def _has_compact_block_spacing(properties: StyleProperties | None) -> bool:
  if properties is None:
    return False
  top, bottom = _vertical_margin_values(properties)
  if top is None and bottom is None:
    return False
  return _is_zero_css_length(top) and _is_zero_css_length(bottom)


def _vertical_margin_values(properties: StyleProperties) -> tuple[str | None, str | None]:
  shorthand_top, shorthand_bottom = _expand_margin_shorthand(properties.margin)
  top = properties.margin_top if properties.margin_top is not None else shorthand_top
  bottom = properties.margin_bottom if properties.margin_bottom is not None else shorthand_bottom
  return top, bottom


def _expand_margin_shorthand(value: str | None) -> tuple[str | None, str | None]:
  if value is None:
    return None, None
  parts = value.split()
  if not parts:
    return None, None
  if len(parts) == 1:
    return parts[0], parts[0]
  if len(parts) == 2:
    return parts[0], parts[0]
  if len(parts) == 3:
    return parts[0], parts[2]
  return parts[0], parts[2]


def _is_zero_css_length(value: str | None) -> bool:
  if value is None:
    return False
  normalized = value.strip().lower()
  return normalized in {"0", "0px", "0rem", "0em", "0%", "0vh", "0vw"}


def _list_item_marker(node: ElementNode, state: RenderState) -> str:
  if state.list_marker_cache is None:
    state.list_marker_cache = {}
    for ordered_list in state.document.find_all("ol"):
      items = [
        child for child in ordered_list.children
        if isinstance(child, ElementNode) and child.tag == "li"
      ]
      step = -1 if "reversed" in ordered_list.attrs else 1
      number = len(items) if step == -1 else 1
      try:
        number = int(ordered_list.attrs.get("start", str(number)))
      except ValueError:
        pass
      for item in items:
        try:
          number = int(item.attrs.get("value", str(number)))
        except ValueError:
          pass
        state.list_marker_cache[id(item)] = f"{number}. "
        number += step
  return state.list_marker_cache.get(id(node), "- ")


def _is_structural_list_wrapper_item(node: ElementNode) -> bool:
  nested_list = _single_nested_list_child(node)
  if nested_list is None:
    return False
  direct_list_items = [
    child for child in nested_list.children
    if isinstance(child, ElementNode) and child.tag == "li"
  ]
  if not direct_list_items:
    return False

  return all(_looks_like_compound_list_item(child) for child in direct_list_items)


def _looks_like_compound_list_item(node: ElementNode) -> bool:
  return _single_nested_list_child(node) is not None


def _single_nested_list_child(node: ElementNode) -> ElementNode | None:
  nested_lists: list[ElementNode] = []
  for child in node.children:
    if isinstance(child, TextNode):
      if _normalize_text(child.text):
        return None
      continue
    if child.tag in {"ul", "ol"}:
      nested_lists.append(child)
      continue
    return None
  if len(nested_lists) != 1:
    return None
  return nested_lists[0]


def _render_compound_nested_list_item(
  node: ElementNode,
  state: RenderState,
  *,
  inherited_visible: bool,
  properties: StyleProperties | None,
) -> list[RenderBlock]:
  nested_list = _single_nested_list_child(node)
  if nested_list is None:
    return []

  rendered_parts: list[str] = []
  for child in nested_list.children:
    if not isinstance(child, ElementNode) or child.tag != "li":
      continue
    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue
    if _single_nested_list_child(child) is not None:
      return []
    text = _render_inline(
      child,
      state,
      inherited_visible=inherited_visible,
      properties=child_properties,
    )
    if not text:
      continue
    rendered_parts.append(text)

  if not rendered_parts:
    return []

  return [
    RenderBlock(
      f"- {' - '.join(rendered_parts)}",
      kind="list_item",
      text_align=_text_align_value(properties),
    )
  ]


def _render_structural_list_wrapper_item(
  node: ElementNode,
  state: RenderState,
  *,
  inherited_visible: bool,
) -> list[RenderBlock]:
  nested_blocks: list[RenderBlock] = []
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag not in {"ul", "ol"}:
      continue
    child_properties = _child_properties(child, state, inherited_visible)
    if child_properties is not None and not child_properties.visible:
      continue
    nested_blocks.extend(
      _render_blocks(
        child,
        state,
        inherited_visible=inherited_visible,
        properties=child_properties,
      )
    )

  indented_blocks: list[RenderBlock] = []
  for block in nested_blocks:
    indented_blocks.append(
      RenderBlock(
        f"  {block.text}" if block.text else block.text,
        kind=block.kind,
        text_align=block.text_align,
        compact_spacing=block.compact_spacing,
      )
    )
  return indented_blocks


def _tokenize_for_wrap(text: str) -> list[str]:
  tokens: list[str] = []
  current: list[str] = []
  current_kind: str | None = None
  index = 0
  while index < len(text):
    if match := ANSI_ESCAPE_RE.match(text, index):
      if current:
        tokens.append("".join(current))
        current = []
        current_kind = None
      tokens.append(match.group(0))
      index = match.end()
      continue
    char = text[index]
    if char.isspace():
      if current:
        tokens.append("".join(current))
        current = []
        current_kind = None
      tokens.append(" ")
      index += 1
      continue
    kind = "ascii" if _is_ascii_wrap_character(char) else "other"
    if current and current_kind != kind:
      tokens.append("".join(current))
      current = []
    current.append(char)
    current_kind = kind
    index += 1
  if current:
    tokens.append("".join(current))
  return tokens


def _is_ascii_wrap_character(char: str) -> bool:
  return ord(char) < 128 and (char.isalnum() or char in ".+/_-")


def _should_keep_wrap_token_intact(token: str) -> bool:
  return all(_is_ascii_wrap_character(char) for char in token)


def _split_by_display_width(text: str, limit: int) -> tuple[str, str]:
  width = 0
  index = 0
  visible_boundaries: list[int] = []
  while index < len(text):
    if match := ANSI_ESCAPE_RE.match(text, index):
      index = match.end()
      continue
    char_width = _char_display_width(text[index])
    if width + char_width > limit:
      break
    width += char_width
    index += 1
    visible_boundaries.append(index)
  if index == 0:
    index = 1
  elif visible_boundaries:
    index = _adjust_split_index_for_forbidden_line_start(text, index, visible_boundaries)
  return text[:index], text[index:]


def _adjust_split_index_for_forbidden_line_start(
  text: str,
  index: int,
  visible_boundaries: list[int],
) -> int:
  adjusted_boundaries = visible_boundaries[:]
  while len(adjusted_boundaries) > 1:
    next_char = _first_visible_char(text, index)
    if next_char is None or next_char not in FORBIDDEN_LINE_START_PUNCTUATION:
      break
    adjusted_boundaries.pop()
    index = adjusted_boundaries[-1]
  return index


def _first_visible_char(text: str, start: int) -> str | None:
  index = start
  while index < len(text):
    if match := ANSI_ESCAPE_RE.match(text, index):
      index = match.end()
      continue
    return text[index]
  return None


def _pad_display_width(text: str, width: int) -> str:
  padding = max(0, width - _display_width(text))
  return text + (" " * padding)


def _display_width(text: str) -> int:
  width = 0
  index = 0
  while index < len(text):
    if match := ANSI_ESCAPE_RE.match(text, index):
      index = match.end()
      continue
    width += _char_display_width(text[index])
    index += 1
  return width


def _char_display_width(char: str) -> int:
  if unicodedata.combining(char):
    return 0
  if unicodedata.east_asian_width(char) in {"F", "W"}:
    return 2
  return 1


def _is_block_node(
  node: ElementNode,
  properties: StyleProperties | None = None,
) -> bool:
  if node.tag == "table":
    return True
  display = _display_value(properties)
  if display == "inline-block":
    return node.tag in BLOCK_TAGS or node.tag in HEADING_TAGS
  if display in {"inline", "inline-flex"}:
    return False
  if display in {"block", "list-item", "flex"}:
    return True
  return node.tag in BLOCK_TAGS or node.tag in HEADING_TAGS


def _child_properties(
  node: ElementNode,
  state: RenderState,
  inherited_visible: bool,
) -> StyleProperties | None:
  cache_key = (id(node), inherited_visible)
  cached = state.child_properties_cache.get(cache_key)
  if cached is not None or cache_key in state.child_properties_cache:
    return cached
  if state.style_context is not None:
    properties = state.style_context.properties(node, inherited_visible=inherited_visible)
  elif state.lightweight_style_only:
    properties = _inline_style_properties(node, inherited_visible=inherited_visible)
  else:
    properties = None
  state.child_properties_cache[cache_key] = properties
  return properties


def _inline_style_properties(
  node: ElementNode,
  *,
  inherited_visible: bool,
) -> StyleProperties:
  declarations = _parse_declarations(node.attrs.get("style", ""))
  return style_properties_from_declarations(node, declarations, inherited_visible)


def _should_use_lightweight_style_render(document: DocumentNode) -> bool:
  source = (document.source or "").strip().lower()
  if not source.startswith(("http://", "https://")):
    return False
  body = document.body
  if body is None:
    return False
  main = body.find_first("main") or body
  body_preview = _collect_inline_visible_text(body, character_limit=4096).strip()
  main_preview = _collect_inline_visible_text(main, character_limit=4096).strip()
  if len(body_preview) < 4000 or len(main_preview) < 3000:
    return False
  if _looks_like_client_failure_text(body_preview) or _looks_like_client_failure_text(main_preview):
    return False
  raw_body_len = len(_normalize_text(body.text_content()))
  if raw_body_len < 5000:
    return False
  link_count = 0
  stylesheet_count = 0
  root = document.root
  if root is None:
    return False
  for candidate in root.iter_nodes():
    if not isinstance(candidate, ElementNode):
      continue
    if candidate.tag == "a" and candidate.attrs.get("href", "").strip():
      link_count += 1
    if candidate.tag == "link":
      rel_tokens = {
        token.strip().lower()
        for token in candidate.attrs.get("rel", "").split()
        if token.strip()
      }
      if "stylesheet" in rel_tokens:
        stylesheet_count += 1
    if link_count >= 400 and stylesheet_count >= 2:
      return True
  return False


def _collect_inline_visible_text(node: ElementNode, *, character_limit: int) -> str:
  parts: list[str] = []
  total_chars = 0

  def walk(current: ElementNode) -> bool:
    nonlocal total_chars
    if current.tag in SKIP_TAGS or _is_statically_hidden_layout_child(current):
      return False
    for child in current.children:
      if isinstance(child, TextNode):
        text = _normalize_text(child.text)
        if text:
          parts.append(text)
          total_chars += len(text)
          if total_chars >= character_limit:
            return True
        continue
      if walk(child):
        return True
    return False

  walk(node)
  return " ".join(parts)[:character_limit]


def _looks_like_client_failure_text(text: str) -> bool:
  lowered = text.lower()
  return any(
    needle in lowered
    for needle in (
      "enable javascript",
      "javascript is disabled",
      "please wait while we load",
      "loading...",
    )
  )
