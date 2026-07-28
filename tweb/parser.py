from __future__ import annotations

from html.parser import HTMLParser
from html import unescape

from .dom import DocumentNode, ElementNode, TextNode
from .fetcher import Resource

VOID_TAGS = {
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr",
}


class _DocumentParser(HTMLParser):
  def __init__(self, source: str):
    super().__init__(convert_charrefs=True)
    self.document = DocumentNode(source=source)
    self._stack: list[DocumentNode | ElementNode] = [self.document]
    self._title_parts: list[str] = []
    self._in_title = False

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    node = ElementNode(
      tag=tag,
      attrs={key: value or "" for key, value in attrs},
    )
    self._current_parent().append_child(node)
    if tag not in VOID_TAGS:
      self._stack.append(node)
    if tag == "title":
      self._in_title = True

  def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    node = ElementNode(
      tag=tag,
      attrs={key: value or "" for key, value in attrs},
    )
    self._current_parent().append_child(node)

  def handle_endtag(self, tag: str) -> None:
    if not any(
      isinstance(node, ElementNode) and node.tag == tag
      for node in self._stack[1:]
    ):
      return
    while len(self._stack) > 1:
      node = self._stack.pop()
      if isinstance(node, ElementNode) and node.tag == tag:
        break
    if tag == "title":
      self._in_title = False
      self.document.title = "".join(self._title_parts).strip()

  def handle_data(self, data: str) -> None:
    if not data:
      return
    text = TextNode(text=data)
    self._current_parent().append_child(text)
    if self._in_title:
      self._title_parts.append(data)

  def handle_comment(self, data: str) -> None:
    self._current_parent().append_child(
      ElementNode(tag="#comment", attrs={"__text": data})
    )

  def handle_decl(self, decl: str) -> None:
    text = decl.strip()
    lowered = text.lower()
    if lowered.startswith("doctype"):
      name = text[7:].strip() or "html"
      self._current_parent().append_child(
        ElementNode(tag="#doctype", attrs={"name": name, "__text": text})
      )
      return
    super().handle_decl(decl)

  def handle_entityref(self, name: str) -> None:
    self.handle_data(unescape(f"&{name};"))

  def handle_charref(self, name: str) -> None:
    self.handle_data(unescape(f"&#{name};"))

  def _current_parent(self) -> DocumentNode | ElementNode:
    return self._stack[-1]


def parse_document(resource: Resource) -> DocumentNode:
  parser = _DocumentParser(resource.source)
  parser.feed(resource.content)
  parser.close()
  return parser.document


def parse_fragment(source: str, html: str) -> list[ElementNode | TextNode]:
  container = ElementNode(tag="fragment")
  parser = _DocumentParser(source)
  parser._stack = [container]
  parser.document.children = []
  parser.feed(html)
  parser.close()
  return container.children
