from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Iterator


@dataclass
class TextNode:
  text: str


@dataclass
class ElementNode:
  tag: str
  attrs: dict[str, str] = field(default_factory=dict)
  children: list["ElementNode | TextNode"] = field(default_factory=list)

  def append_child(self, child: "ElementNode | TextNode") -> None:
    self.children.append(child)

  def iter_nodes(self) -> Iterator["ElementNode | TextNode"]:
    yield self
    for child in self.children:
      yield child
      if isinstance(child, ElementNode):
        yield from child.iter_descendants()

  def iter_descendants(self) -> Iterator["ElementNode | TextNode"]:
    for child in self.children:
      yield child
      if isinstance(child, ElementNode):
        yield from child.iter_descendants()

  def find_first(self, tag: str) -> "ElementNode | None":
    if self.tag == tag:
      return self
    for child in self.children:
      if isinstance(child, ElementNode):
        found = child.find_first(tag)
        if found is not None:
          return found
    return None

  def find_all(self, tag: str) -> list["ElementNode"]:
    matches: list[ElementNode] = []
    if self.tag == tag:
      matches.append(self)
    for child in self.children:
      if isinstance(child, ElementNode):
        matches.extend(child.find_all(tag))
    return matches

  def text_content(self) -> str:
    if self.tag == "#comment":
      return ""
    if self.tag == "#doctype":
      return self.attrs.get("__text", "")
    if self.tag in {"script", "style", "noscript"}:
      return ""
    parts: list[str] = []
    for child in self.children:
      if isinstance(child, TextNode):
        text = " ".join(child.text.split())
        if text:
          parts.append(text)
        continue
      nested = child.text_content()
      if nested:
        parts.append(nested)
    return " ".join(parts)

  def set_text_content(self, text: str) -> None:
    if self.tag in {"#comment", "#doctype"}:
      self.attrs["__text"] = text
      return
    self.children = [TextNode(text=text)]

  def set_children(self, children: list["ElementNode | TextNode"]) -> None:
    self.children = children

  def inner_html(self) -> str:
    return "".join(_serialize_node(child) for child in self.children)


@dataclass
class DocumentNode:
  source: str
  title: str = ""
  children: list[ElementNode | TextNode] = field(default_factory=list)

  def append_child(self, child: ElementNode | TextNode) -> None:
    self.children.append(child)

  @property
  def root(self) -> ElementNode | None:
    for child in self.children:
      if isinstance(child, ElementNode) and not child.tag.startswith("#"):
        return child
    return None

  @property
  def html(self) -> ElementNode | None:
    return self.find_first("html")

  @property
  def doctype(self) -> ElementNode | None:
    for child in self.children:
      if isinstance(child, ElementNode) and child.tag == "#doctype":
        return child
    return None

  @property
  def body(self) -> ElementNode | None:
    return self.find_first("body")

  def find_first(self, tag: str) -> ElementNode | None:
    for child in self.children:
      if isinstance(child, ElementNode):
        found = child.find_first(tag)
        if found is not None:
          return found
    return None

  def find_all(self, tag: str) -> list[ElementNode]:
    matches: list[ElementNode] = []
    for child in self.children:
      if isinstance(child, ElementNode):
        matches.extend(child.find_all(tag))
    return matches

  def sync_title(self) -> None:
    title = self.find_first("title")
    self.title = "" if title is None else title.text_content().strip()


def _serialize_node(node: ElementNode | TextNode) -> str:
  if isinstance(node, TextNode):
    return escape(node.text)
  if node.tag == "#comment":
    return f"<!--{escape(node.attrs.get('__text', ''))}-->"
  if node.tag == "#doctype":
    name = node.attrs.get("name", "html") or "html"
    return f"<!DOCTYPE {escape(name)}>"
  if node.tag == "fragment":
    return "".join(_serialize_node(child) for child in node.children)
  # Attributes use double quotes, so apostrophes remain literal as in browser
  # outerHTML. Template compilers may treat encoded apostrophes as JS syntax.
  escaped_attrs = (
    (key, escape(value, quote=False).replace('"', "&quot;"))
    for key, value in node.attrs.items()
  )
  attrs = "".join(f' {key}="{value}"' for key, value in escaped_attrs)
  if not node.children:
    return f"<{node.tag}{attrs}></{node.tag}>"
  children = "".join(_serialize_node(child) for child in node.children)
  return f"<{node.tag}{attrs}>{children}</{node.tag}>"
