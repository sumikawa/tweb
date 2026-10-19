from __future__ import annotations

import re
from typing import Callable

import quickjs


class JavaScriptRuntimeError(RuntimeError):
  pass


_WEBPACK_JSONP_RE = re.compile(
  r"^\s*\(window\.webpackJsonp=window\.webpackJsonp\|\|\[\]\)\.push\(",
)
_JS_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_JS_CODE_WORD_RE = re.compile(r"[\w$]+")
_JS_REGEX_LITERAL_RE = re.compile(r"/(?:\\.|[^/\\\[\n]|\[(?:\\.|[^\]\\])*\])+/[a-z]*")
_NULLISH_STRING_RECEIVER_ERROR_RE = re.compile(
  r"cannot read property '(?P<method>[A-Za-z_$][A-Za-z0-9_$]*)' of (?:undefined|null)",
  re.IGNORECASE,
)
_SAFE_STRING_RECEIVER_METHODS = ("charAt", "indexOf", "slice", "toLowerCase")
_SAFE_STRING_RECEIVER_RE = re.compile(
  r"(?P<receiver>"
  r"(?<![A-Za-z0-9_$])(?:this|[A-Za-z_$][A-Za-z0-9_$]*)"
  r"(?:\s*(?:\.\s*[A-Za-z_$][A-Za-z0-9_$]*|\[\s*(?:[A-Za-z_$][A-Za-z0-9_$]*|\d+|\"[^\"]*\"|'[^']*')\s*\]))*"
  r")\s*\.\s*(?P<method>charAt|indexOf|slice|toLowerCase)\s*\(",
)
_IMPORT_META_RE = re.compile(r"\bimport\.meta\b")
_EXPORT_NAMED_BLOCK_RE = re.compile(r"\bexport\s*\{[^}]*\}\s*;?")
_EXPORT_DEFAULT_RE = re.compile(r"\bexport\s+default\s+")
_EXPORT_DECL_RE = re.compile(r"\bexport\s+(?=(?:async\s+)?(?:function|class)\b|(?:const|let|var)\b)")
_EXPORT_FUNCTION_RE = re.compile(r"\bexport\s+((?:async\s+)?)function\s+([A-Za-z_$][A-Za-z0-9_$]*)")
_EXPORT_CLASS_RE = re.compile(r"\bexport\s+class\s+([A-Za-z_$][A-Za-z0-9_$]*)")
_EXPORT_VAR_RE = re.compile(r"\bexport\s+(const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)")
_DYNAMIC_IMPORT_LITERAL_RE = re.compile(
  r'\bimport\s*\(\s*(?P<quote>["\'])(?P<spec>[^"\']+)(?P=quote)\s*\)'
)
_JS_METHOD_KEYWORDS = {
  "if",
  "for",
  "while",
  "switch",
  "catch",
  "function",
  "return",
  "typeof",
  "delete",
  "new",
  "class",
  "do",
  "else",
  "try",
}


def _normalize_js_exception(error: quickjs.JSException) -> JavaScriptRuntimeError:
  message = str(error)
  if "InternalError: interrupted" in message:
    return JavaScriptRuntimeError("JavaScript execution interrupted")
  if "InternalError: out of memory" in message:
    return JavaScriptRuntimeError("JavaScript memory limit exceeded")
  return JavaScriptRuntimeError(message)


def _should_reset_runtime_after_js_error(error: JavaScriptRuntimeError) -> bool:
  message = str(error).strip().lower()
  return message in {"", "null", "undefined"}


def _js_code_tokens(source: str):
  """Yield code tokens, excluding comments and literal contents (but visiting ${...})."""
  index = 0
  previous = ""
  template = False
  template_expressions: list[int] = []
  braces = 0
  while index < len(source):
    char = source[index]
    if template:
      if char == "\\":
        index += 2
        continue
      if char == "`":
        template = False
        previous = "literal"
      elif source.startswith("${", index):
        template_expressions.append(braces)
        braces += 1
        yield ("{", index + 1, index + 2)
        previous = "{"
        template = False
        index += 2
        continue
      index += 1
      continue
    if char.isspace():
      index += 1
      continue
    if source.startswith("//", index):
      end = source.find("\n", index + 2)
      index = len(source) if end < 0 else end + 1
      continue
    if source.startswith("/*", index):
      end = source.find("*/", index + 2)
      index = len(source) if end < 0 else end + 2
      continue
    if char in {"'", '"'}:
      quote = char
      index += 1
      while index < len(source):
        if source[index] == "\\":
          index += 2
        elif source[index] == quote:
          index += 1
          break
        else:
          index += 1
      previous = "literal"
      continue
    if char == "`":
      template = True
      index += 1
      continue
    if char == "/" and _can_start_js_regex(previous):
      match = _JS_REGEX_LITERAL_RE.match(source, index)
      if match:
        index = match.end()
        previous = "literal"
        continue
    match = _JS_CODE_WORD_RE.match(source, index) if char.isalnum() or char in {"_", "$"} else None
    end = match.end() if match else index + 1
    token = source[index:end]
    if token == "{":
      braces += 1
    elif token == "}":
      braces -= 1
      if template_expressions and braces == template_expressions[-1]:
        template_expressions.pop()
        template = True
    yield (token, index, end)
    previous = token
    index = end


def _rewrite_class_static_blocks(source: str) -> str:
  # Private static field initializers preserve ordering, lexical this/super, and
  # visibility without adding public properties to the class constructor.
  if re.search(r"\bstatic(?:\s|/\*.*?\*/|//[^\n]*(?:\n|$))*\{", source, re.DOTALL) is None:
    return source
  tokens = list(_js_code_tokens(source))
  stack: list[str] = []
  pending_classes: list[int] = []
  edits: list[tuple[int, int, str]] = []
  serial = 0
  for index, (token, start, end) in enumerate(tokens):
    following = tokens[index + 1][0] if index + 1 < len(tokens) else ""
    if token == "class" and (following in {"{", "extends"} or following.isidentifier() or _JS_IDENTIFIER_RE.fullmatch(following)):
      pending_classes.append(len(stack))
    if token == "static" and following == "{" and stack and stack[-1] == "class":
      opening = tokens[index + 1]
      try:
        closing = _find_matching_js_pair_lenient(source, opening[1], "{", "}")
      except ValueError:
        return source
      while f"__twebStaticBlock{serial}" in source:
        serial += 1
      name = f"__twebStaticBlock{serial}"
      serial += 1
      edits.append((start, opening[2], f"static #{name} = (() => {{"))
      edits.append((closing + 1, closing + 1, ")();"))
    if token in {"{", "(", "["}:
      is_class = token == "{" and pending_classes and pending_classes[-1] == len(stack)
      if is_class:
        pending_classes.pop()
      stack.append("class" if is_class else token)
    elif token in {"}", ")", "]"} and stack:
      stack.pop()
  for start, end, text in sorted(edits, reverse=True):
    source = source[:start] + text + source[end:]
  return source


def _find_matching_js_delimiter(
  source: str,
  start: int,
  open_char: str,
  close_char: str,
) -> int:
  if source[start] != open_char:
    raise ValueError(f"expected {open_char!r} at {start}")
  depth = 0
  state = "default"
  escape = False
  template_stack: list[int] = []
  regex_char_class = False
  previous_token = ""
  current_identifier = ""
  index = start
  while index < len(source):
    char = source[index]
    next_char = source[index + 1] if index + 1 < len(source) else ""
    is_identifier_char = char.isalnum() or char in {"_", "$"}
    if state == "default" and is_identifier_char:
      current_identifier += char
      index += 1
      continue
    if state == "default" and current_identifier:
      previous_token = current_identifier
      current_identifier = ""
    if state == "single":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "'":
        state = "default"
    elif state == "double":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == '"':
        state = "default"
    elif state == "template":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "`":
        state = "default"
      elif char == "$" and next_char == "{":
        template_stack.append(depth)
        depth += 1
        state = "default"
        index += 1
    elif state == "line_comment":
      if char == "\n":
        state = "default"
    elif state == "block_comment":
      if char == "*" and next_char == "/":
        state = "default"
        index += 1
    elif state == "regex":
      if escape:
        escape = False
      elif regex_char_class:
        if char == "]":
          regex_char_class = False
      elif char == "\\":
        escape = True
      elif char == "[":
        regex_char_class = True
      elif char == "/":
        state = "default"
        previous_token = "/"
    else:
      if char == "'":
        state = "single"
      elif char == '"':
        state = "double"
      elif char == "`":
        state = "template"
      elif char == "/" and next_char == "/":
        state = "line_comment"
        index += 1
      elif char == "/" and next_char == "*":
        state = "block_comment"
        index += 1
      elif char == "/" and _can_start_js_regex(previous_token):
        state = "regex"
      elif char == open_char:
        depth += 1
      elif char == close_char:
        depth -= 1
        if template_stack and depth == template_stack[-1]:
          template_stack.pop()
          state = "template"
        elif depth == 0:
          return index
      elif char in "([{":
        depth += 1
      elif char in ")]}":
        depth -= 1
        if template_stack and depth == template_stack[-1]:
          template_stack.pop()
          state = "template"
      if not char.isspace() and state == "default":
        previous_token = char
    index += 1
  raise ValueError(f"unmatched {open_char!r}")


def _find_matching_js_pair_lenient(
  source: str,
  start: int,
  open_char: str,
  close_char: str,
) -> int:
  if source[start] != open_char:
    raise ValueError(f"expected {open_char!r} at {start}")
  pairs = {"(": ")", "[": "]", "{": "}"}
  group_stack: list[str] = [open_char]
  state = "default"
  escape = False
  template_expr_stack: list[int] = []
  regex_char_class = False
  previous_token = ""
  current_identifier = ""
  index = start + 1
  while index < len(source):
    char = source[index]
    next_char = source[index + 1] if index + 1 < len(source) else ""
    is_identifier_char = char.isalnum() or char in {"_", "$"}
    if state == "default" and is_identifier_char:
      current_identifier += char
      index += 1
      continue
    if state == "default" and current_identifier:
      previous_token = current_identifier
      current_identifier = ""
    if state == "single":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "'":
        state = "default"
    elif state == "double":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == '"':
        state = "default"
    elif state == "template":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "`":
        state = "default"
      elif char == "$" and next_char == "{":
        template_expr_stack.append(len(group_stack))
        group_stack.append("{")
        state = "default"
        index += 1
    elif state == "line_comment":
      if char == "\n":
        state = "default"
    elif state == "block_comment":
      if char == "*" and next_char == "/":
        state = "default"
        index += 1
    elif state == "regex":
      if escape:
        escape = False
      elif regex_char_class:
        if char == "]":
          regex_char_class = False
      elif char == "\\":
        escape = True
      elif char == "[":
        regex_char_class = True
      elif char == "/":
        state = "default"
        previous_token = "/"
    else:
      if char == "'":
        state = "single"
      elif char == '"':
        state = "double"
      elif char == "`":
        state = "template"
      elif char == "/" and next_char == "/":
        state = "line_comment"
        index += 1
      elif char == "/" and next_char == "*":
        state = "block_comment"
        index += 1
      elif char == "/" and _can_start_js_regex(previous_token):
        state = "regex"
      elif char in pairs:
        group_stack.append(char)
      elif char in ")]}":
        if group_stack and pairs.get(group_stack[-1]) == char:
          group_stack.pop()
          if template_expr_stack and len(group_stack) == template_expr_stack[-1]:
            template_expr_stack.pop()
            state = "template"
          elif not group_stack:
            return index
      if not char.isspace() and state == "default":
        previous_token = char
    index += 1
  raise ValueError(f"unmatched {open_char!r}")


def _find_matching_js_brace_lenient(source: str, start: int) -> int:
  return _find_matching_js_pair_lenient(source, start, "{", "}")


def _split_top_level_js_items(source: str) -> list[str]:
  items: list[str] = []
  start = 0
  depth = 0
  state = "default"
  escape = False
  template_stack: list[int] = []
  regex_char_class = False
  previous_token = ""
  current_identifier = ""
  index = 0
  while index < len(source):
    char = source[index]
    next_char = source[index + 1] if index + 1 < len(source) else ""
    is_identifier_char = char.isalnum() or char in {"_", "$"}
    if state == "default" and is_identifier_char:
      current_identifier += char
      index += 1
      continue
    if state == "default" and current_identifier:
      previous_token = current_identifier
      current_identifier = ""
    if state == "single":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "'":
        state = "default"
    elif state == "double":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == '"':
        state = "default"
    elif state == "template":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "`":
        state = "default"
      elif char == "$" and next_char == "{":
        template_stack.append(depth)
        depth += 1
        state = "default"
        index += 1
    elif state == "line_comment":
      if char == "\n":
        state = "default"
    elif state == "block_comment":
      if char == "*" and next_char == "/":
        state = "default"
        index += 1
    elif state == "regex":
      if escape:
        escape = False
      elif regex_char_class:
        if char == "]":
          regex_char_class = False
      elif char == "\\":
        escape = True
      elif char == "[":
        regex_char_class = True
      elif char == "/":
        state = "default"
        previous_token = "/"
    else:
      if char == "'":
        state = "single"
      elif char == '"':
        state = "double"
      elif char == "`":
        state = "template"
      elif char == "/" and next_char == "/":
        state = "line_comment"
        index += 1
      elif char == "/" and next_char == "*":
        state = "block_comment"
        index += 1
      elif char == "/" and _can_start_js_regex(previous_token):
        state = "regex"
      elif char in "([{":
        depth += 1
      elif char in ")]}":
        depth -= 1
        if template_stack and depth == template_stack[-1]:
          template_stack.pop()
          state = "template"
      elif char == "," and depth == 0:
        items.append(source[start:index])
        start = index + 1
      if not char.isspace() and state == "default":
        previous_token = char
    index += 1
  items.append(source[start:])
  return items


def _split_webpack_jsonp_array_modules(modules_expr: str) -> list[str]:
  if not modules_expr.startswith("["):
    raise ValueError("webpackJsonp array modules must start with '['")
  if not modules_expr.endswith("]"):
    raise ValueError("webpackJsonp array modules must end with ']'")
  body = modules_expr[1:-1]
  fallback_items = _split_top_level_js_items(body)
  items: list[str] = []
  cursor = 0
  expect_item = True
  while cursor < len(body):
    if body[cursor].isspace():
      cursor += 1
      continue
    if body[cursor] == ",":
      if expect_item:
        items.append("")
      expect_item = True
      cursor += 1
      continue
    start = cursor
    if body.startswith("function", cursor):
      brace_index = body.find("{", cursor)
      if brace_index < 0:
        raise ValueError("webpackJsonp module function body not found")
      try:
        module_end = _find_matching_js_brace_lenient(body, brace_index)
      except ValueError:
        return fallback_items
      items.append(body[start : module_end + 1])
      cursor = module_end + 1
      expect_item = False
      continue
    remainder = _split_top_level_js_items(body[cursor:])
    if not remainder:
      break
    items.append(remainder[0])
    cursor += len(remainder[0])
    expect_item = False
  return items


def _extract_webpack_jsonp_array_modules(source: str, start: int) -> tuple[str, int, list[str]]:
  if source[start] != "[":
    raise ValueError("webpackJsonp array modules must start with '['")
  array_end = _find_matching_js_pair_lenient(source, start, "[", "]")
  modules_expr = source[start : array_end + 1]
  return (modules_expr, array_end, _split_webpack_jsonp_array_modules(modules_expr))


def _find_top_level_js_character(source: str, target: str) -> int:
  depth = 0
  state = "default"
  escape = False
  template_stack: list[int] = []
  regex_char_class = False
  previous_token = ""
  current_identifier = ""
  index = 0
  while index < len(source):
    char = source[index]
    next_char = source[index + 1] if index + 1 < len(source) else ""
    is_identifier_char = char.isalnum() or char in {"_", "$"}
    if state == "default" and is_identifier_char:
      current_identifier += char
      index += 1
      continue
    if state == "default" and current_identifier:
      previous_token = current_identifier
      current_identifier = ""
    if state == "single":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "'":
        state = "default"
    elif state == "double":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == '"':
        state = "default"
    elif state == "template":
      if escape:
        escape = False
      elif char == "\\":
        escape = True
      elif char == "`":
        state = "default"
      elif char == "$" and next_char == "{":
        template_stack.append(depth)
        depth += 1
        state = "default"
        index += 1
    elif state == "line_comment":
      if char == "\n":
        state = "default"
    elif state == "block_comment":
      if char == "*" and next_char == "/":
        state = "default"
        index += 1
    elif state == "regex":
      if escape:
        escape = False
      elif regex_char_class:
        if char == "]":
          regex_char_class = False
      elif char == "\\":
        escape = True
      elif char == "[":
        regex_char_class = True
      elif char == "/":
        state = "default"
        previous_token = "/"
    else:
      if char == "'":
        state = "single"
      elif char == '"':
        state = "double"
      elif char == "`":
        state = "template"
      elif char == "/" and next_char == "/":
        state = "line_comment"
        index += 1
      elif char == "/" and next_char == "*":
        state = "block_comment"
        index += 1
      elif char == "/" and _can_start_js_regex(previous_token):
        state = "regex"
      elif char == target and depth == 0:
        return index
      elif char in "([{":
        depth += 1
      elif char in ")]}":
        depth -= 1
        if template_stack and depth == template_stack[-1]:
          template_stack.pop()
          state = "template"
      if not char.isspace() and state == "default":
        previous_token = char
    index += 1
  return -1


def _find_top_level_js_colon(source: str) -> int:
  return _find_top_level_js_character(source, ":")


def _find_top_level_js_paren(source: str) -> int:
  return _find_top_level_js_character(source, "(")


def _previous_significant_token(source: str, index: int) -> str:
  cursor = index - 1
  while cursor >= 0 and source[cursor].isspace():
    cursor -= 1
  if cursor < 0:
    return ""
  if cursor > 0 and source[cursor - 1 : cursor + 1] == "=>":
    return "=>"
  if source[cursor].isalnum() or source[cursor] in {"_", "$"}:
    end = cursor + 1
    while cursor >= 0 and (source[cursor].isalnum() or source[cursor] in {"_", "$"}):
      cursor -= 1
    return source[cursor + 1 : end]
  return source[cursor]


def _looks_like_js_object_literal(source: str, index: int) -> bool:
  token = _previous_significant_token(source, index)
  return token in {
    "",
    "=",
    "(",
    "[",
    "{",
    ",",
    ":",
    "?",
    ";",
    "return",
    "case",
  }


def _rewrite_js_object_entry_method(entry: str) -> str:
  leading_length = len(entry) - len(entry.lstrip())
  trailing_length = len(entry) - len(entry.rstrip())
  leading = entry[:leading_length]
  trailing = entry[len(entry) - trailing_length :] if trailing_length else ""
  core = entry[leading_length : len(entry) - trailing_length if trailing_length else len(entry)]
  if not core:
    return entry
  colon_index = _find_top_level_js_colon(core)
  paren_index = _find_top_level_js_paren(core)
  if paren_index <= 0 or (colon_index >= 0 and colon_index < paren_index):
    return entry
  key = core[:paren_index].strip()
  async_prefix = ""
  if key.startswith("async "):
    async_prefix = "async "
    key = key[6:].strip()
  if not key or key.startswith("*") or key in _JS_METHOD_KEYWORDS:
    return entry
  if not (
    _JS_IDENTIFIER_RE.match(key) or
    key.startswith("[") and key.endswith("]") or
    key.startswith("'") and key.endswith("'") or
    key.startswith('"') and key.endswith('"') or
    key.isdigit()
  ):
    return entry
  return f"{leading}{key}:{async_prefix}function{core[paren_index:]}{trailing}"


def _rewrite_js_object_literal_methods(source: str) -> str:
  parts: list[str] = []
  cursor = 0
  while cursor < len(source):
    brace_index = source.find("{", cursor)
    if brace_index < 0:
      parts.append(source[cursor:])
      break
    parts.append(source[cursor:brace_index])
    if not _looks_like_js_object_literal(source, brace_index):
      parts.append("{")
      cursor = brace_index + 1
      continue
    try:
      brace_end = _find_matching_js_delimiter(source, brace_index, "{", "}")
    except ValueError:
      parts.append(source[brace_index:])
      break
    body = source[brace_index + 1 : brace_end]
    rewritten_items = [
      _rewrite_js_object_entry_method(_rewrite_js_object_literal_methods(item))
      for item in _split_top_level_js_items(body)
    ]
    parts.append("{")
    parts.append(",".join(rewritten_items))
    parts.append("}")
    cursor = brace_end + 1
  return "".join(parts)


def _compile_js_module_expression(source: str) -> None:
  quickjs.Context().eval(f"({source})")


def _neutralize_js_object_entry(entry: str) -> str:
  paren_index = _find_top_level_js_paren(entry)
  if paren_index <= 0:
    return entry
  key = entry[:paren_index].strip()
  if key.startswith("async "):
    key = key[6:].strip()
  return f"{key}:function(){{return Promise.resolve();}}"


def _patch_js_module_stack_underflow(
  source: str,
  *,
  compile_checker: Callable[[str], None] | None = None,
) -> str:
  checker = _compile_js_module_expression if compile_checker is None else compile_checker
  patched = source
  cursor = 0
  while True:
    marker_index = patched.find("={", cursor)
    if marker_index < 0:
      return patched
    brace_start = marker_index + 1
    try:
      brace_end = _find_matching_js_delimiter(patched, brace_start, "{", "}")
    except ValueError:
      return patched
    body = patched[brace_start + 1 : brace_end]
    items = _split_top_level_js_items(body)
    changed = False
    for index, entry in enumerate(items):
      candidate = entry.strip()
      if not candidate:
        continue
      try:
        checker(f"function(){{return {{{candidate}}};}}")
      except (JavaScriptRuntimeError, quickjs.JSException) as exc:
        if "stack underflow" not in str(exc):
          continue
        neutralized = _neutralize_js_object_entry(entry)
        if neutralized != entry:
          items[index] = neutralized
          changed = True
    if changed:
      patched = patched[: brace_start + 1] + ",".join(items) + patched[brace_end:]
      cursor = brace_start + 1
    else:
      cursor = brace_end + 1


def _can_start_js_regex(previous_token: str) -> bool:
  return previous_token in {
    "",
    "(",
    "[",
    "{",
    "=",
    ":",
    ",",
    ";",
    "!",
    "?",
    "+",
    "-",
    "*",
    "%",
    "&",
    "|",
    "^",
    "~",
    "<",
    ">",
    "return",
    "case",
    "throw",
    "delete",
    "typeof",
    "void",
    "new",
    "do",
    "else",
    "in",
    "instanceof",
  }


def _extract_nullish_string_receiver_method(message: str) -> str | None:
  match = _NULLISH_STRING_RECEIVER_ERROR_RE.search(message)
  if match is None:
    return None
  method = match.group("method")
  if method not in _SAFE_STRING_RECEIVER_METHODS:
    return None
  return method


def _safeguard_string_method_receivers(
  source: str,
  methods: set[str] | None = None,
) -> str:
  active_methods = set(_SAFE_STRING_RECEIVER_METHODS if methods is None else methods)
  if not active_methods:
    return source

  def replace(match: re.Match[str]) -> str:
    method = match.group("method")
    if method not in active_methods:
      return match.group(0)
    receiver = match.group("receiver")
    return f"__twebStringReceiver({receiver}).{method}("

  return _SAFE_STRING_RECEIVER_RE.sub(replace, source)


def _patch_import_meta(source: str, *, source_url: str) -> str:
  replacement = f'({{ url: "{source_url}", env: {{}} }})'
  return _IMPORT_META_RE.sub(replacement, source)


def _patch_esm_exports(source: str) -> str:
  patched = _EXPORT_NAMED_BLOCK_RE.sub("", source)
  patched = _EXPORT_DEFAULT_RE.sub("", patched)
  patched = _EXPORT_DECL_RE.sub("", patched)
  return patched


def _rewrite_esm_to_classic(
  source: str,
  *,
  source_url: str,
  resolve_specifier: Callable[[str], str],
) -> tuple[str, tuple[str, ...]]:
  source = _patch_import_meta(source, source_url=source_url)
  dependencies: list[str] = []

  def remember_dependency(specifier: str) -> str:
    resolved = resolve_specifier(specifier)
    if resolved not in dependencies:
      dependencies.append(resolved)
    return resolved

  source = _rewrite_leading_imports(
    source,
    remember_dependency=remember_dependency,
  )
  source = _DYNAMIC_IMPORT_LITERAL_RE.sub(
    lambda match: f'__twebDynamicImport("{resolve_specifier(match.group("spec"))}")',
    source,
  )

  exports: list[tuple[str, str]] = []

  def replace_export_block(match: re.Match[str]) -> str:
    for local_name, exported_name in _parse_export_specifiers(match.group(0)):
      exports.append((exported_name, local_name))
    return ""

  source = _EXPORT_NAMED_BLOCK_RE.sub(replace_export_block, source)
  if _EXPORT_DEFAULT_RE.search(source):
    source = _EXPORT_DEFAULT_RE.sub("const __tweb_default__ = ", source, count=1)
    exports.append(("default", "__tweb_default__"))

  def replace_export_function(match: re.Match[str]) -> str:
    exports.append((match.group(2), match.group(2)))
    return f"{match.group(1)}function {match.group(2)}"

  def replace_export_class(match: re.Match[str]) -> str:
    exports.append((match.group(1), match.group(1)))
    return f"class {match.group(1)}"

  def replace_export_var(match: re.Match[str]) -> str:
    exports.append((match.group(2), match.group(2)))
    return f"{match.group(1)} {match.group(2)}"

  source = _EXPORT_FUNCTION_RE.sub(replace_export_function, source)
  source = _EXPORT_CLASS_RE.sub(replace_export_class, source)
  source = _EXPORT_VAR_RE.sub(replace_export_var, source)

  prelude_lines: list[str] = []
  for index, marker in enumerate(_extract_module_import_markers(source)):
    prelude_lines.extend(_build_module_import_bindings(marker["url"], marker["clause"], index=index))
  source = _strip_module_import_markers(source)

  export_lines = [
    f'__tweb_module_exports[{exported_name!r}] = {local_name};'
    for exported_name, local_name in exports
  ]
  rewritten = "\n".join(
    [
      "(function() {",
      "const __tweb_module_exports = Object.create(null);",
      *prelude_lines,
      source,
      *export_lines,
      f'window.__twebModules[{source_url!r}] = __tweb_module_exports;',
      "})();",
    ]
  )
  return rewritten, tuple(dependencies)


def _module_import_marker(url: str, clause: str) -> str:
  return f'__TWEB_IMPORT__({url!r},{clause!r});'


def _rewrite_leading_imports(
  source: str,
  *,
  remember_dependency: Callable[[str], str],
) -> str:
  cursor = 0
  markers: list[str] = []
  while True:
    start = _skip_js_whitespace_and_comments(source, cursor)
    if not source.startswith("import", start):
      break
    clause_start = start + len("import")
    while clause_start < len(source) and source[clause_start].isspace():
      clause_start += 1
    if clause_start < len(source) and source[clause_start] == "(":
      break
    statement_end = _find_top_level_js_character(source[start:], ";")
    if statement_end < 0:
      break
    statement = source[start : start + statement_end + 1]
    marker = _rewrite_import_statement(
      statement,
      remember_dependency=remember_dependency,
    )
    if marker is None:
      break
    markers.append(source[cursor:start])
    markers.append(marker)
    cursor = start + statement_end + 1
  if not markers:
    return source
  markers.append(source[cursor:])
  return "".join(markers)


def _skip_js_whitespace_and_comments(source: str, start: int) -> int:
  cursor = start
  while cursor < len(source):
    if source[cursor].isspace():
      cursor += 1
      continue
    if source.startswith("//", cursor):
      newline = source.find("\n", cursor + 2)
      if newline < 0:
        return len(source)
      cursor = newline + 1
      continue
    if source.startswith("/*", cursor):
      comment_end = source.find("*/", cursor + 2)
      if comment_end < 0:
        return len(source)
      cursor = comment_end + 2
      continue
    break
  return cursor


def _rewrite_import_statement(
  statement: str,
  *,
  remember_dependency: Callable[[str], str],
) -> str | None:
  normalized = statement.strip()
  if normalized.endswith(";"):
    normalized = normalized[:-1].rstrip()
  if not normalized.startswith("import"):
    return None
  body = normalized[len("import") :].strip()
  bare_match = re.fullmatch(r'(?P<quote>["\'])(?P<spec>[^"\']+)(?P=quote)', body)
  if bare_match is not None:
    return _module_import_marker(remember_dependency(bare_match.group("spec")), "")
  from_match = re.fullmatch(
    r'(?P<clause>.*?)\s*from\s*(?P<quote>["\'])(?P<spec>[^"\']+)(?P=quote)',
    body,
    re.DOTALL,
  )
  if from_match is None:
    return None
  return _module_import_marker(
    remember_dependency(from_match.group("spec")),
    from_match.group("clause"),
  )


def _extract_module_import_markers(source: str) -> list[dict[str, str]]:
  markers: list[dict[str, str]] = []
  pattern = re.compile(r"__TWEB_IMPORT__\((?P<url>'[^']*'|\"[^\"]*\"),(?P<clause>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")\);")
  for match in pattern.finditer(source):
    markers.append(
      {
        "url": _unquote_js_string(match.group("url")),
        "clause": _unquote_js_string(match.group("clause")),
      }
    )
  return markers


def _strip_module_import_markers(source: str) -> str:
  pattern = re.compile(r"__TWEB_IMPORT__\((?:'[^']*'|\"[^\"]*\"),(?:'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")\);")
  return pattern.sub("", source)


def _unquote_js_string(value: str) -> str:
  return value[1:-1].encode("utf-8").decode("unicode_escape")


def _build_module_import_bindings(url: str, clause: str, *, index: int) -> list[str]:
  normalized_clause = clause.strip()
  if not normalized_clause:
    return [f"window.__twebModules[{url!r}] = window.__twebModules[{url!r}] || Object.create(null);"]
  module_var = f"__tweb_import_module_{index}__"
  lines = [f"const {module_var} = window.__twebModules[{url!r}] || Object.create(null);"]
  default_clause, named_clause = _split_import_clause(normalized_clause)
  if default_clause:
    if default_clause.startswith("* as "):
      namespace_name = default_clause[5:].strip()
      lines.append(f"const {namespace_name} = {module_var};")
    else:
      lines.append(
        f'const {default_clause} = Object.prototype.hasOwnProperty.call({module_var}, "default") ? {module_var}.default : {module_var};'
      )
  if named_clause:
    lines.append(f"const {_rewrite_named_import_clause(named_clause)} = {module_var};")
  return lines


def _split_import_clause(clause: str) -> tuple[str, str]:
  depth = 0
  for index, char in enumerate(clause):
    if char == "{":
      depth += 1
    elif char == "}":
      depth -= 1
    elif char == "," and depth == 0:
      return clause[:index].strip(), clause[index + 1 :].strip()
  if clause.startswith("{"):
    return "", clause
  return clause, ""


def _rewrite_named_import_clause(clause: str) -> str:
  body = clause.strip()
  if body.startswith("{") and body.endswith("}"):
    body = body[1:-1]
  parts: list[str] = []
  for entry in body.split(","):
    normalized = entry.strip()
    if not normalized:
      continue
    if " as " in normalized:
      imported, local = [part.strip() for part in normalized.split(" as ", 1)]
      parts.append(f"{imported}: {local}")
    else:
      parts.append(normalized)
  return "{ " + ", ".join(parts) + " }"


def _parse_export_specifiers(source: str) -> list[tuple[str, str]]:
  brace_start = source.find("{")
  brace_end = source.rfind("}")
  if brace_start < 0 or brace_end < 0 or brace_end <= brace_start:
    return []
  specifiers = source[brace_start + 1 : brace_end]
  parsed: list[tuple[str, str]] = []
  for entry in specifiers.split(","):
    normalized = entry.strip()
    if not normalized:
      continue
    if " as " in normalized:
      local, exported = [part.strip() for part in normalized.split(" as ", 1)]
      parsed.append((local, exported))
    else:
      parsed.append((normalized, normalized))
  return parsed
