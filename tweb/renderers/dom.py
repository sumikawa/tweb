from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..css import StyleContext, build_style_context
from ..dom import DocumentNode, ElementNode, TextNode

SKIP_TEXT_TAGS = {"script", "style"}
SUMMARY_ATTRS = ("id", "class", "name", "href", "src", "type", "role", "aria-label")


@dataclass
class DomRenderOptions:
  variant: str = "summary"
  max_depth: int | None = None
  skip_script_like: bool = True
  viewport_columns: int = 160
  session: Any = None


def render_dom(
  document: DocumentNode,
  max_depth: int | None = None,
  skip_script_like: bool = True,
  variant: str = "summary",
  viewport_columns: int | None = None,
  session: Any = None,
) -> str:
  effective_viewport_columns = viewport_columns or 160
  options = DomRenderOptions(
    variant=variant,
    max_depth=max_depth,
    skip_script_like=skip_script_like,
    viewport_columns=effective_viewport_columns,
    session=session,
  )
  if options.variant == "ai":
    return _render_dom_ai(document, options)
  return _render_dom_summary(document, options)


def _render_dom_summary(document: DocumentNode, options: DomRenderOptions) -> str:
  lines = [f"#document source={document.source}"]
  if document.title:
    lines.append(f'title="{_escape(document.title)}"')
  style_context = build_style_context(
    document,
    viewport_columns=options.viewport_columns,
    session=options.session,
  )

  for child in document.children:
    lines.extend(
      _render_summary_node(
        child,
        depth=0,
        options=options,
        parent_tag=None,
        style_context=style_context,
        inherited_visible=True,
      )
    )
  return "\n".join(lines)


def _render_summary_node(
  node: ElementNode | TextNode,
  depth: int,
  options: DomRenderOptions,
  parent_tag: str | None,
  style_context: StyleContext,
  inherited_visible: bool,
) -> list[str]:
  indent = "  " * depth

  if isinstance(node, TextNode):
    if parent_tag in SKIP_TEXT_TAGS:
      return []
    text = _normalize_text(node.text)
    if not text:
      return []
    return [f'{indent}- text "{_escape(text)}"']

  if options.skip_script_like and node.tag in {"script", "style"}:
    return [f"{indent}- <{node.tag}> ..."]

  properties = style_context.properties(node, inherited_visible=inherited_visible)

  line = f"{indent}- <{node.tag}{_format_summary_attrs(node)}>"
  summary = _inline_text_summary(node, skip_script_like=options.skip_script_like)
  if summary:
    line += f' text="{_escape(summary)}"'
  if not properties.visible:
    line += f" visible=false reason={properties.hidden_reason}"

  lines = [line]
  if options.max_depth is not None and depth >= options.max_depth:
    child_count = len(node.children)
    if child_count:
      lines.append(f"{indent}  ... {child_count} child nodes")
    return lines

  for child in node.children:
    lines.extend(
      _render_summary_node(
        child,
        depth=depth + 1,
        options=options,
        parent_tag=node.tag,
        style_context=style_context,
        inherited_visible=properties.visible,
      )
    )
  return lines


def _render_dom_ai(document: DocumentNode, options: DomRenderOptions) -> str:
  lines = [f"#document source={document.source}"]
  if document.title:
    lines.append(f'title="{document.title}"')

  counter = {"value": 0}
  style_context = build_style_context(
    document,
    viewport_columns=options.viewport_columns,
    session=options.session,
  )
  for child in document.children:
    lines.extend(
      _render_ai_node(
        child,
        depth=0,
        options=options,
        parent_tag=None,
        parent_id="document",
        counter=counter,
        style_context=style_context,
        inherited_visible=True,
      )
    )
  return "\n".join(lines)


def _render_ai_node(
  node: ElementNode | TextNode,
  depth: int,
  options: DomRenderOptions,
  parent_tag: str | None,
  parent_id: str,
  counter: dict[str, int],
  style_context: StyleContext,
  inherited_visible: bool,
) -> list[str]:
  indent = "  " * depth
  node_id = _next_node_id(counter)

  if isinstance(node, TextNode):
    if parent_tag in SKIP_TEXT_TAGS and options.skip_script_like:
      return []
    text = _normalize_text(node.text)
    if not text:
      return []
    lines = [
      f'{indent}- node id={node_id} type=text parent={parent_id} text="{_escape(text)}"'
    ]
    return lines

  if options.skip_script_like and node.tag in {"script", "style"}:
    return [
      f"{indent}- node id={node_id} type=element tag={node.tag} parent={parent_id} skipped=true"
    ]

  properties = style_context.properties(node, inherited_visible=inherited_visible)
  attrs = _format_ai_attrs(node.attrs)
  line = f"{indent}- node id={node_id} type=element tag={node.tag} parent={parent_id}"
  if attrs:
    line += f" attrs={attrs}"
  line += f" visible={'true' if properties.visible else 'false'}"
  if properties.hidden_reason is not None:
    line += f" hidden_reason={properties.hidden_reason}"
  if properties.display is not None:
    line += f' display="{_escape(properties.display)}"'
  if properties.flex_direction is not None:
    line += f' flex_direction="{_escape(properties.flex_direction)}"'
  if properties.grid_template_columns is not None:
    line += f' grid_template_columns="{_escape(properties.grid_template_columns)}"'
  if properties.visibility is not None:
    line += f' visibility="{_escape(properties.visibility)}"'
  if properties.font_weight is not None:
    line += f' font_weight="{_escape(properties.font_weight)}"'
  if properties.font_style is not None:
    line += f' font_style="{_escape(properties.font_style)}"'
  if properties.text_decoration is not None:
    line += f' text_decoration="{_escape(properties.text_decoration)}"'
  lines = [line]

  if options.max_depth is not None and depth >= options.max_depth:
    child_count = len(node.children)
    lines.append(f"{indent}  - truncated child_count={child_count}")
    return lines

  for child in node.children:
    lines.extend(
      _render_ai_node(
        child,
        depth=depth + 1,
        options=options,
        parent_tag=node.tag,
        parent_id=node_id,
        counter=counter,
        style_context=style_context,
        inherited_visible=properties.visible,
      )
    )
  return lines


def _format_summary_attrs(node: ElementNode) -> str:
  parts: list[str] = []
  for key in SUMMARY_ATTRS:
    value = node.attrs.get(key)
    if value:
      parts.append(f'{key}="{_escape(" ".join(value.split()))}"')
  if not parts and node.attrs:
    first_key = sorted(node.attrs)[0]
    value = node.attrs[first_key]
    if value:
      parts.append(f'{first_key}="{_escape(" ".join(value.split()))}"')
  return (" " + " ".join(parts)) if parts else ""


def _format_ai_attrs(attrs: dict[str, str]) -> str:
  if not attrs:
    return "{}"
  ordered = sorted(attrs.items())
  formatted = ", ".join(f'"{key}": "{_escape(value)}"' for key, value in ordered)
  return "{" + formatted + "}"


def _inline_text_summary(node: ElementNode, skip_script_like: bool) -> str:
  parts: list[str] = []
  _collect_inline_text_summary_parts(node, parts, skip_script_like=skip_script_like)
  return " ".join(parts)


def _collect_inline_text_summary_parts(
  node: ElementNode,
  parts: list[str],
  *,
  skip_script_like: bool,
) -> None:
  for child in node.children:
    if isinstance(child, TextNode):
      text = _normalize_text(child.text)
      if text:
        parts.append(text)
      continue
    if skip_script_like and child.tag in SKIP_TEXT_TAGS:
      continue
    _collect_inline_text_summary_parts(
      child,
      parts,
      skip_script_like=skip_script_like,
    )


def _normalize_text(text: str) -> str:
  return " ".join(text.split())
def _escape(text: str) -> str:
  return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _next_node_id(counter: dict[str, int]) -> str:
  counter["value"] += 1
  return f"n{counter['value']}"
