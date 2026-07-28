from __future__ import annotations

from dataclasses import dataclass

from .dom import DocumentNode, ElementNode, TextNode


@dataclass(frozen=True)
class HydrationLink:
  text: str
  href: str


@dataclass(frozen=True)
class HydrationSection:
  title: str
  items: tuple[tuple[str, str | None], ...]
  role: str | None = None


def merge_hydration_sections(
  preferred: list[HydrationSection],
  fallback: list[HydrationSection],
) -> list[HydrationSection]:
  merged: list[HydrationSection] = []
  seen: set[str] = set()
  for section in [*preferred, *fallback]:
    key = section.title.strip().lower()
    if not key or key in seen:
      continue
    seen.add(key)
    merged.append(section)
  return merged


def populate_disclosure_sections(
  document: DocumentNode,
  sections: list[HydrationSection],
) -> set[str]:
  root = document.root
  if root is None:
    return set()
  sections_by_title = {
    _normalize_heading(section.title): section
    for section in sections
    if _normalize_heading(section.title)
  }
  populated: set[str] = set()
  for node in _iter_descendants_inclusive(root):
    if node.tag != "button":
      continue
    title = _button_heading_text(node)
    if not title:
      continue
    section = sections_by_title.get(title)
    if section is None:
      continue
    content = _disclosure_content_for_button(document, node)
    if content is None or not _is_disclosure_content_candidate(content):
      continue
    first_item = section.items[0][0] if section.items else ""
    if first_item and first_item in content.text_content():
      populated.add(section.title)
      continue
    listing = ElementNode(
      tag="ul",
      attrs={
        "data-tweb-hydration": "1",
        "data-tweb-hydration-role": "section-items",
      },
    )
    for item_text, item_href in section.items[:12]:
      child = ElementNode(tag="li")
      if item_href:
        anchor = ElementNode(tag="a", attrs={"href": item_href})
        anchor.append_child(TextNode(text=item_text))
        child.append_child(anchor)
      else:
        child.append_child(TextNode(text=item_text))
      listing.append_child(child)
    content.children = [listing]
    content.attrs["data-tweb-disclosure-content"] = "1"
    content.attrs["data-tweb-collapsed"] = "1"
    content.attrs["hidden"] = ""
    node.attrs["data-tweb-disclosure-button"] = "1"
    node.attrs["aria-expanded"] = "false"
    populated.add(section.title)
  return populated


def _normalize_heading(value: str) -> str:
  return " ".join(value.split())


def _button_heading_text(button: ElementNode) -> str:
  for candidate in _iter_descendants_inclusive(button):
    if candidate.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
      text = _normalize_heading(candidate.text_content())
      if text:
        return text
  return _normalize_heading(button.text_content())


def _disclosure_content_for_button(
  document: DocumentNode,
  button: ElementNode,
) -> ElementNode | None:
  controlled_id = button.attrs.get("aria-controls", "").strip()
  if controlled_id:
    content = _find_element_by_id(document, controlled_id)
    if content is not None:
      return content
  parent = getattr(button, "_tweb_parent", None)
  if parent is None:
    return None
  found_button = False
  for child in parent.children:
    if child is button:
      found_button = True
      continue
    if not found_button or not isinstance(child, ElementNode):
      continue
    return child
  return None


def _find_element_by_id(document: DocumentNode, element_id: str) -> ElementNode | None:
  root = document.root
  if root is None:
    return None
  for node in _iter_descendants_inclusive(root):
    if node.attrs.get("id", "").strip() == element_id:
      return node
  return None


def _is_disclosure_content_candidate(node: ElementNode) -> bool:
  attrs = node.attrs
  classes = set(attrs.get("class", "").split())
  if attrs.get("data-tweb-disclosure-content") == "1":
    return True
  if "hidden" in attrs:
    return True
  if attrs.get("aria-hidden", "").strip().lower() == "true":
    return True
  if attrs.get("data-collapsed", "").strip() in {"1", "true"}:
    return True
  class_text = " ".join(sorted(classes)).lower()
  return any(
    token in class_text
    for token in ("accordion", "disclosure", "collapse", "collapsed", "contents", "panel")
  )


def _iter_descendants_inclusive(node: ElementNode):
  yield node
  for child in node.children:
    if isinstance(child, ElementNode):
      yield from _iter_descendants_inclusive(child)
