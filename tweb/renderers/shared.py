from __future__ import annotations

from ..dom import ElementNode, TextNode


def iter_child_lines(
  children: list[ElementNode | TextNode],
  depth: int,
) -> list[str]:
  lines: list[str] = []
  for child in children:
    indent = "  " * depth
    if isinstance(child, TextNode):
      text = " ".join(child.text.split())
      if text:
        lines.append(f'{indent}"{text}"')
      continue

    attrs = ""
    if child.attrs:
      attrs = " " + " ".join(f'{key}="{value}"' for key, value in child.attrs.items())
    lines.append(f"{indent}<{child.tag}{attrs}>")
    lines.extend(iter_child_lines(child.children, depth + 1))
  return lines
