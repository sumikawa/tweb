from __future__ import annotations

from itertools import islice
import re

from .dom import ElementNode, TextNode
from .hydration import HydrationSection


_CONTENT_ROLES = {"main", "article", "feed", "tabpanel"}
_NAV_ROLES = {"navigation", "menu", "menubar", "tree"}
_CONTROL_TAGS = {"input", "select", "textarea", "button", "form", "iframe"}
_CONTROL_ROLES = {
  "textbox", "combobox", "searchbox", "form", "button", "checkbox", "radio",
  "switch", "slider", "spinbutton", "listbox", "option", "link", "menuitem", "treeitem",
}


def element_roles(node: ElementNode) -> set[str]:
  return set(node.attrs.get("role", "").lower().split())


def iter_elements(node: ElementNode):
  yield node
  for child in node.children:
    if isinstance(child, ElementNode):
      yield from iter_elements(child)


def is_hidden_region(node: ElementNode) -> bool:
  return (
    "hidden" in node.attrs
    or node.attrs.get("aria-hidden", "").lower() == "true"
    or bool(re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", node.attrs.get("style", ""), re.I))
  )


def _region_metrics(node: ElementNode) -> tuple[int, int, int, bool, bool, bool]:
  # Bound structural probes even when a page contains a very large article tree.
  text_chars = link_chars = links = 0
  has_controls = has_articles = False
  truncated = False
  pending = [(node, False)]
  steps = 0
  while pending and steps < 256:
    child, in_link = pending.pop()
    steps += 1
    if isinstance(child, TextNode):
      length = len(" ".join(child.text.split()))
      text_chars += length
      if in_link:
        link_chars += length
      continue
    if child.tag in {"script", "style", "template", "noscript"} or is_hidden_region(child):
      continue
    roles = element_roles(child)
    has_controls |= (
      child.tag in _CONTROL_TAGS
      or bool(roles & _CONTROL_ROLES)
      or child.attrs.get("contenteditable", "false").lower() != "false"
    )
    has_articles |= child.tag in {"article", "p", "blockquote", "pre"} or bool(roles & {"article", "feed"})
    is_link = child.tag == "a" and bool(child.attrs.get("href"))
    links += int(is_link)
    truncated |= len(child.children) > 64
    pending.extend((item, in_link or is_link) for item in reversed(list(islice(child.children, 64))))
  return text_chars, link_chars, links, has_controls, has_articles, not pending and not truncated


def is_navigation_container(node: ElementNode) -> bool:
  roles = element_roles(node)
  if roles & _NAV_ROLES:
    return True
  if roles & (_CONTENT_ROLES | {"form", "search"}):
    return False
  if node.tag == "nav":
    return True
  if node.tag not in {"aside", "div", "section", "ul", "ol"}:
    return False
  has_list = node.tag in {"ul", "ol"} or any(
    isinstance(child, ElementNode) and (child.tag in {"ul", "ol"} or "list" in element_roles(child))
    for child in islice(node.children, 64)
  )
  if node.tag != "aside" and "complementary" not in roles and not has_list:
    return False
  text, linked, count, controls, articles, complete = _region_metrics(node)
  if not complete or controls or articles:
    return False
  if count >= 2 and linked >= max(1, int(text * 0.6)):
    return True
  if node.tag == "aside" or "complementary" in roles:
    nodes = list(islice(iter_elements(node), 128))
    return (
      sum(child.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for child in nodes) >= 3
      and sum(child.tag in {"ul", "ol"} for child in nodes) >= 3
    )
  return False


def is_content_container(node: ElementNode) -> bool:
  roles = element_roles(node)
  if roles & _NAV_ROLES or node.tag in {"nav", "aside", "header", "footer"}:
    return False
  if roles & _CONTENT_ROLES or node.tag in {"main", "article"}:
    return True
  if "region" in roles and (node.attrs.get("aria-label") or node.attrs.get("aria-labelledby")):
    return not is_navigation_container(node)
  if node.tag not in {"div", "section"}:
    return False
  text, linked, _links, controls, _articles, complete = _region_metrics(node)
  return complete and text >= 160 and linked <= text * 0.3 and not controls


def is_empty_body_target(node: ElementNode) -> bool:
  if node.tag not in {"div", "section", "article", "main"} or is_hidden_region(node):
    return False
  text, _linked, links, controls, _articles, complete = _region_metrics(node)
  return complete and text <= 40 and not links and not controls


def find_main_region(body: ElementNode) -> ElementNode | None:
  pending = [body]
  while pending:
    node = pending.pop()
    if is_hidden_region(node):
      continue
    if node.tag == "main" or "main" in element_roles(node):
      return node
    pending.extend(child for child in reversed(node.children) if isinstance(child, ElementNode))
  return None


def is_navigation_section(
  section: HydrationSection,
  target: ElementNode | None = None,
  *,
  root: ElementNode | None = None,
) -> bool:
  if section.role is not None:
    return section.role == "nav"
  if target is None or len(section.items) < 2:
    return False
  title = " ".join(section.title.split()).casefold()
  labels = [target.attrs.get("aria-label", "")]
  label_ids = set(target.attrs.get("aria-labelledby", "").split())
  if label_ids and root is not None:
    labels.extend(node.text_content() for node in iter_elements(root) if node.attrs.get("id") in label_ids)
  labels.extend(
    node.text_content()
    for node in iter_elements(target)
    if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
  )
  if title and any(title == " ".join(label.split()).casefold() for label in labels if label):
    return True
  # Reuse observed navigation membership, never a site's URL naming convention.
  existing = {" ".join(node.text_content().split()) for node in iter_elements(target) if node.tag == "a"}
  items = [" ".join(text.split()) for text, _href in section.items if text.strip()]
  return len(items) >= 2 and sum(text in existing for text in items) >= max(2, len(items) * 0.8)
