from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urljoin
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .dom import DocumentNode, ElementNode


TEXT_INPUT_TYPES = {"text", "search", "email", "url", "password", "number"}
ButtonClickPolicy = Literal["off", "dom-only", "network"]


@dataclass(frozen=True)
class FormOption:
  value: str
  label: str
  selected: bool


@dataclass(frozen=True)
class FormControl:
  control_id: str
  kind: str
  name: str
  label: str
  token: str
  value: str = ""
  checked: bool = False
  options: tuple[FormOption, ...] = ()
  input_type: str = ""
  disabled: bool = False
  readonly: bool = False


@dataclass(frozen=True)
class FormSubmission:
  method: str
  action: str
  enctype: str
  params: tuple[tuple[str, str], ...]

  def url(self) -> str:
    parsed = urlsplit(self.action)
    merged = parse_qsl(parsed.query, keep_blank_values=True) + list(self.params)
    return urlunsplit(
      (
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(merged),
        parsed.fragment,
      )
    )

  def form_data(self) -> list[tuple[str, str]]:
    return list(self.params)


@dataclass(frozen=True)
class ButtonNetworkRequest:
  method: str
  url: str
  blocked: bool = False


@dataclass(frozen=True)
class ButtonClickResult:
  clicked: bool
  dom_changed: bool
  policy: ButtonClickPolicy
  navigation_target: str | None = None
  network_requests: tuple[ButtonNetworkRequest, ...] = ()
  blocked_by_policy: bool = False

  @property
  def classification(self) -> str:
    if self.blocked_by_policy and not self.clicked:
      return "blocked_by_policy"
    if self.navigation_target is not None:
      return "navigation_requested"
    if self.network_requests:
      return "network_requested"
    if self.dom_changed:
      return "dom_updated"
    if self.clicked:
      return "javascript_required"
    return "unsupported"


@dataclass(frozen=True)
class ControlSubmissionPreview:
  method: str
  action: str
  enctype: str
  url: str
  form_data: tuple[tuple[str, str], ...]

  def to_dict(self) -> dict[str, object]:
    return asdict(self)


@dataclass(frozen=True)
class ControlDebugInfo:
  control_id: str
  tag: str
  kind: str
  name: str
  label: str
  value: str = ""
  checked: bool = False
  input_type: str = ""
  disabled: bool = False
  readonly: bool = False
  form_action: str | None = None
  form_method: str | None = None
  form_enctype: str | None = None
  submit_preview: ControlSubmissionPreview | None = None
  click_hint: str | None = None
  controlled_target: str | None = None
  navigation_target: str | None = None

  def to_dict(self) -> dict[str, object]:
    return asdict(self)


def sync_interactive_document(document: DocumentNode) -> None:
  _invalidate_interaction_lookup_caches(document)
  for node in _iter_elements(document):
    if node.tag == "input" and _input_type(node) == "checkbox":
      _sync_checkbox_visibility(node)
    if node.tag == "select":
      _sync_select_defaults(node)


def collect_form_controls(document: DocumentNode) -> list[FormControl]:
  controls: list[FormControl] = []
  for node in _iter_elements(document):
    controls.extend(_synthetic_form_controls(document, node))
    control = _node_to_form_control(document, node)
    if control is not None:
      controls.append(control)
  return controls


def collect_checkbox_controls(document: DocumentNode) -> list[FormControl]:
  return [control for control in collect_form_controls(document) if control.kind == "checkbox"]


def toggle_checkbox_control(document: DocumentNode, control_id: str) -> bool:
  node = _find_control_node(document, control_id)
  if node is None or node.tag != "input" or _input_type(node) != "checkbox":
    return False
  if "checked" in node.attrs:
    node.attrs.pop("checked", None)
  else:
    node.attrs["checked"] = ""
  _sync_checkbox_visibility(node)
  return True


def select_radio_control(document: DocumentNode, control_id: str) -> bool:
  node = _find_control_node(document, control_id)
  if node is None or node.tag != "input" or _input_type(node) != "radio":
    return False
  name = node.attrs.get("name", "")
  form = _nearest_form(node)
  container = form if form is not None else document.root
  if container is None:
    return False
  for candidate in _iter_descendants_inclusive(container):
    if candidate.tag == "input" and _input_type(candidate) == "radio" and candidate.attrs.get("name", "") == name:
      candidate.attrs.pop("checked", None)
  node.attrs["checked"] = ""
  return True


def activate_tab_control(document: DocumentNode, control_id: str) -> bool:
  node = _find_control_node(document, control_id)
  if node is None or not _is_tab_node(node):
    return False
  group = _tab_group_container(node)
  if group is None:
    return False
  tabs = [candidate for candidate in _iter_descendants_inclusive(group) if _is_tab_node(candidate)]
  if not tabs:
    return False
  for candidate in tabs:
    is_active = candidate is node
    _set_tab_selected_state(candidate, is_active)
    panel_id = candidate.attrs.get("aria-controls", "").strip()
    if not panel_id:
      continue
    panel = _find_element_by_id(document, panel_id)
    if panel is not None:
      _set_tab_panel_visibility(panel, is_active)
  return True


def activate_disclosure_control(document: DocumentNode, control_id: str) -> bool:
  node = _find_control_node(document, control_id)
  if node is None or node.tag not in {"button", "a"}:
    return False
  content = _controlled_button_content(node)
  if content is None:
    return False
  previous_style_key = "data-tweb-disclosure-prev-style"
  previous_hidden_key = "data-tweb-disclosure-was-hidden"
  if previous_hidden_key in content.attrs:
    content.attrs.pop(previous_hidden_key, None)
    content.attrs["data-tweb-collapsed"] = "1"
    content.attrs["hidden"] = ""
    node.attrs["aria-expanded"] = "false"
    return True
  if "hidden" in content.attrs:
    content.attrs[previous_hidden_key] = "1"
    content.attrs.pop("data-tweb-collapsed", None)
    content.attrs.pop("hidden", None)
    node.attrs["aria-expanded"] = "true"
    return True
  if previous_style_key in content.attrs:
    previous_style = content.attrs.pop(previous_style_key)
    if previous_style == "__none__":
      content.attrs.pop("style", None)
    else:
      content.attrs["style"] = previous_style
    content.attrs["data-tweb-collapsed"] = "1"
    node.attrs["aria-expanded"] = "false"
    return True
  previous_style = content.attrs.get("style")
  content.attrs[previous_style_key] = previous_style if previous_style is not None else "__none__"
  content.attrs["style"] = _merge_inline_style(previous_style, {"height": "auto", "overflow": "visible"})
  content.attrs.pop("data-tweb-collapsed", None)
  node.attrs["aria-expanded"] = "true"
  return True


def tab_control_navigation_target(
  document: DocumentNode,
  control_id: str,
  current_source: str,
) -> str | None:
  node = _find_control_node(document, control_id)
  if node is None or not _is_tab_node(node):
    return None
  classes = _class_tokens(node)
  query = dict(parse_qsl(urlsplit(current_source).query, keep_blank_values=True))
  if "ek-dw-select" in classes:
    query["dw"] = node.attrs.get("data-dw", "").strip()
    query.pop("dt", None)
    return _replace_query(current_source, query)
  if "ek-list-select" in classes:
    query["view"] = "list"
    return _replace_query(current_source, query)
  if "ek-pocket-select" in classes:
    query.pop("view", None)
    return _replace_query(current_source, query)
  return None


def append_text_control(document: DocumentNode, control_id: str, text: str) -> bool:
  node = _find_control_node(document, control_id)
  if node is None:
    return False
  if node.tag == "input" and _input_type(node) in TEXT_INPUT_TYPES:
    for target in _mirrored_text_controls(document, node):
      target.attrs["value"] = target.attrs.get("value", "") + text
    return True
  if node.tag == "textarea":
    for target in _mirrored_text_controls(document, node):
      target.set_text_content(_textarea_value(target) + text)
    return True
  return False


def set_text_control(document: DocumentNode, control_id: str, value: str) -> bool:
  node = _find_control_node(document, control_id)
  if node is None:
    return False
  if node.tag == "input" and _input_type(node) in TEXT_INPUT_TYPES:
    for target in _mirrored_text_controls(document, node):
      target.attrs["value"] = value
    return True
  if node.tag == "textarea":
    for target in _mirrored_text_controls(document, node):
      target.set_text_content(value)
    return True
  return False


def backspace_text_control(document: DocumentNode, control_id: str) -> bool:
  node = _find_control_node(document, control_id)
  if node is None:
    return False
  if node.tag == "input" and _input_type(node) in TEXT_INPUT_TYPES:
    for target in _mirrored_text_controls(document, node):
      target.attrs["value"] = target.attrs.get("value", "")[:-1]
    return True
  if node.tag == "textarea":
    for target in _mirrored_text_controls(document, node):
      target.set_text_content(_textarea_value(target)[:-1])
    return True
  return False


def cycle_select_control(document: DocumentNode, control_id: str, reverse: bool = False) -> bool:
  node = _find_control_node(document, control_id)
  if node is None or node.tag != "select":
    return False
  options = [child for child in node.children if isinstance(child, ElementNode) and child.tag == "option"]
  if not options:
    return False
  current_index = 0
  for index, option in enumerate(options):
    if "selected" in option.attrs:
      current_index = index
      break
  next_index = (current_index - 1 if reverse else current_index + 1) % len(options)
  for option in options:
    option.attrs.pop("selected", None)
  options[next_index].attrs["selected"] = ""
  return True


def submit_form_control(document: DocumentNode, control_id: str, current_source: str) -> FormSubmission | None:
  node = find_control_node(document, control_id)
  if node is None:
    return None
  form = _form_owner(document, node)
  if form is None:
    return None
  method = form.attrs.get("method", "get").strip().lower() or "get"
  enctype = form.attrs.get("enctype", "").strip().lower() or "application/x-www-form-urlencoded"
  action = _resolve_form_action(current_source, form.attrs.get("action", "").strip() or current_source)
  params = tuple(_serialize_form(form, submitter=node))
  return FormSubmission(method=method, action=action, enctype=enctype, params=params)


def register_parents_for_interactions(document: DocumentNode) -> None:
  root = document.root
  if root is None:
    return
  _invalidate_interaction_lookup_caches(document)
  _register_parents(root, None)


def is_text_entry_control(control: FormControl) -> bool:
  return control.kind in {"text", "textarea"}


def is_submit_control(control: FormControl) -> bool:
  return control.kind == "submit"


def is_button_control(control: FormControl) -> bool:
  return control.kind in {"button", "tab", "picker"}


def find_control_node(document: DocumentNode, control_id: str) -> ElementNode | None:
  return _find_control_node(document, control_id)


def describe_controls(document: DocumentNode, current_source: str) -> list[ControlDebugInfo]:
  descriptions: list[ControlDebugInfo] = []
  for control in collect_form_controls(document):
    info = describe_control(document, control.control_id, current_source)
    if info is not None:
      descriptions.append(info)
  return descriptions


def describe_control(document: DocumentNode, control_id: str, current_source: str) -> ControlDebugInfo | None:
  node = _find_control_node(document, control_id)
  if node is None:
    return None
  control = next((item for item in collect_form_controls(document) if item.control_id == control_id), None)
  if control is None:
    return None
  form = _form_owner(document, node)
  form_action = None
  form_method = None
  form_enctype = None
  submit_preview = None
  if form is not None:
    form_method = form.attrs.get("method", "get").strip().lower() or "get"
    form_enctype = form.attrs.get("enctype", "").strip().lower() or "application/x-www-form-urlencoded"
    form_action = _resolve_form_action(current_source, form.attrs.get("action", "").strip() or current_source)
  if control.kind == "submit":
    submission = submit_form_control(document, control_id, current_source)
    if submission is not None:
      submit_preview = ControlSubmissionPreview(
        method=submission.method,
        action=submission.action,
        enctype=submission.enctype,
        url=submission.url(),
        form_data=tuple(submission.form_data()),
      )
  controlled_target = _controlled_target_id(node)
  navigation_target = None
  click_hint = None
  if control.kind == "submit":
    click_hint = "submit"
  elif control.kind == "tab":
    navigation_target = tab_control_navigation_target(document, control_id, current_source)
    if navigation_target is not None:
      click_hint = "navigation"
    elif _is_tab_node(node):
      click_hint = "tab_activation"
    else:
      click_hint = "javascript"
  elif control.kind in {"button", "picker"}:
    if _controlled_button_content(node) is not None:
      click_hint = "disclosure_toggle"
    else:
      click_hint = "javascript"
  return ControlDebugInfo(
    control_id=control.control_id,
    tag=node.tag,
    kind=control.kind,
    name=control.name,
    label=control.label,
    value=control.value,
    checked=control.checked,
    input_type=control.input_type,
    disabled="disabled" in node.attrs,
    readonly="readonly" in node.attrs,
    form_action=form_action,
    form_method=form_method,
    form_enctype=form_enctype,
    submit_preview=submit_preview,
    click_hint=click_hint,
    controlled_target=controlled_target,
    navigation_target=navigation_target,
  )


def _register_parents(node: ElementNode, parent: ElementNode | None) -> None:
  setattr(node, "_tweb_parent", parent)
  for child in node.children:
    if isinstance(child, ElementNode):
      _register_parents(child, node)


def _iter_elements(document: DocumentNode) -> list[ElementNode]:
  root = document.root
  if root is None:
    return []
  return list(_iter_descendants_inclusive(root))


def _iter_descendants_inclusive(node: ElementNode):
  yield node
  for child in node.children:
    if isinstance(child, ElementNode):
      yield from _iter_descendants_inclusive(child)


def _node_to_form_control(document: DocumentNode, node: ElementNode) -> FormControl | None:
  if _is_tab_node(node):
    control_id = _ensure_control_id(document, node)
    label = _tab_label(document, node)
    selected = _is_aria_selected(node)
    return FormControl(
      control_id=control_id,
      kind="tab",
      name=node.attrs.get("name") or node.attrs.get("id") or control_id,
      label=label,
      token=_tab_token(label, selected),
      value=node.attrs.get("aria-controls", ""),
      checked=selected,
      disabled="disabled" in node.attrs,
      readonly="readonly" in node.attrs,
    )

  if node.tag == "input":
    input_type = _input_type(node)
    if input_type == "hidden":
      return None
    control_id = _ensure_control_id(document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(document, node)
    if input_type in TEXT_INPUT_TYPES:
      value = node.attrs.get("value", "")
      return FormControl(
        control_id=control_id,
        kind="text",
        name=name,
        label=label,
        token=_input_token(input_type, name, _display_input_value(input_type, value)),
        value=value,
        input_type=input_type,
        disabled="disabled" in node.attrs,
        readonly="readonly" in node.attrs,
      )
    if input_type == "checkbox":
      checked = "checked" in node.attrs
      return FormControl(
        control_id=control_id,
        kind="checkbox",
        name=name,
        label=label,
        token=_checkbox_token(name, checked),
        checked=checked,
        disabled="disabled" in node.attrs,
        readonly="readonly" in node.attrs,
      )
    if input_type == "radio":
      checked = "checked" in node.attrs
      value = node.attrs.get("value", "on")
      return FormControl(
        control_id=control_id,
        kind="radio",
        name=name,
        label=label or value,
        token=_radio_token(name, value, checked),
        value=value,
        checked=checked,
        disabled="disabled" in node.attrs,
        readonly="readonly" in node.attrs,
      )
    if input_type in {"submit", "button"}:
      value = node.attrs.get("value", "")
      label_text = label or value or input_type
      form = _form_owner(document, node) if input_type == "submit" else None
      return FormControl(
        control_id=control_id,
        kind="submit" if form is not None else "button",
        name=name,
        label=label_text,
        token=_button_token(label_text),
        value=value,
        disabled="disabled" in node.attrs,
        readonly="readonly" in node.attrs,
      )
    return None

  if node.tag == "textarea":
    control_id = _ensure_control_id(document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(document, node)
    value = _textarea_value(node)
    return FormControl(
      control_id=control_id,
      kind="textarea",
      name=name,
      label=label,
      token=_textarea_token(name, value),
      value=value,
      disabled="disabled" in node.attrs,
      readonly="readonly" in node.attrs,
    )

  if node.tag == "select":
    control_id = _ensure_control_id(document, node)
    name = node.attrs.get("name") or node.attrs.get("id") or control_id
    label = _control_label(document, node)
    options = tuple(_select_options(node))
    selected = next((option for option in options if option.selected), options[0] if options else FormOption("", "", False))
    return FormControl(
      control_id=control_id,
      kind="select",
      name=name,
      label=label or selected.label,
      token=_select_token(name, selected.label or selected.value),
      value=selected.value,
      options=options,
      disabled="disabled" in node.attrs,
      readonly="readonly" in node.attrs,
    )

  if node.tag == "button":
    control_id = _ensure_control_id(document, node)
    button_type = node.attrs.get("type", "submit").strip().lower() or "submit"
    label = _button_label(document, node)
    form = _form_owner(document, node) if button_type == "submit" else None
    kind = "submit" if form is not None else "button"
    token = _button_token(label)
    if _looks_like_select_launcher(node, label):
      kind = "select"
      token = _select_token(node.attrs.get("name") or node.attrs.get("id") or control_id, label)
    elif _looks_like_picker_launcher(node, label):
      kind = "picker"
      token = _picker_token(label)
    return FormControl(
      control_id=control_id,
      kind=kind,
      name=node.attrs.get("name") or node.attrs.get("id") or control_id,
      label=label,
      token=token,
      value=node.attrs.get("value", label),
      options=(FormOption(value=node.attrs.get("value", label), label=label, selected=True),) if kind == "select" else (),
      disabled="disabled" in node.attrs,
      readonly="readonly" in node.attrs,
    )

  return None


def _synthetic_form_controls(document: DocumentNode, node: ElementNode) -> list[FormControl]:
  class_tokens = _class_tokens(node)
  is_google_cse_placeholder = (
    node.tag == "gcse:searchbox-only" or
    "gcse-searchbox-only" in class_tokens
  )
  controls: list[FormControl] = []
  if is_google_cse_placeholder:
    base_id = _ensure_control_id(document, node)
    results_url = (node.attrs.get("resultsurl") or "").strip() or "/"
    search_name = "q"
    return [
      FormControl(
        control_id=f"{base_id}:search",
        kind="text",
        name=search_name,
        label="Google Custom Search",
        token=_input_token("search", search_name, ""),
        value="",
        input_type="search",
      ),
      FormControl(
        control_id=f"{base_id}:submit",
        kind="submit",
        name="search",
        label="Search",
        token=_button_token("Search"),
        value=results_url,
      ),
    ]
  controls.extend(_synthetic_search_shell_controls(document, node))
  location_search_control = _synthetic_location_search_control(document, node)
  if location_search_control is not None:
    controls.append(location_search_control)
  hidden_input_control = _synthetic_hidden_input_shell_control(document, node)
  if hidden_input_control is not None:
    controls.append(hidden_input_control)
  pagination_control = _synthetic_pagination_dot_control(document, node)
  if pagination_control is not None:
    controls.append(pagination_control)
  picker_control = _synthetic_clickable_picker_control(document, node)
  if picker_control is not None:
    controls.append(picker_control)
  clickable_button_control = _synthetic_clickable_button_control(document, node)
  if clickable_button_control is not None:
    controls.append(clickable_button_control)
  javascript_link_control = _synthetic_javascript_link_control(document, node)
  if javascript_link_control is not None:
    controls.append(javascript_link_control)
  return controls


def _synthetic_search_shell_controls(document: DocumentNode, node: ElementNode) -> list[FormControl]:
  if node.tag not in {"div", "section", "aside"} and "-" not in node.tag:
    return []
  search_descriptor = _search_shell_descriptor(node)
  if search_descriptor is None:
    return []
  if _node_contains_form_like_descendants(node):
    return []
  control_id = _ensure_control_id(document, node)
  label = _search_shell_label(node)
  name_prefix = search_descriptor
  return [
    FormControl(
      control_id=f"{control_id}:search",
      kind="text",
      name=f"{name_prefix}-search",
      label=label,
      token=_input_token("search", f"{name_prefix}-search", ""),
      value="",
      input_type="search",
    ),
    FormControl(
      control_id=f"{control_id}:submit",
      kind="submit",
      name=f"{name_prefix}-submit",
      label=label,
      token=_button_token(label),
      value="",
    ),
  ]


def _synthetic_location_search_control(document: DocumentNode, node: ElementNode) -> FormControl | None:
  if node.tag not in {"div", "section", "aside"}:
    return None
  descriptor = _location_shell_descriptor(node)
  if descriptor is None:
    return None
  if _node_contains_form_like_descendants(node):
    return None
  control_id = _ensure_control_id(document, node)
  return FormControl(
    control_id=f"{control_id}:location-search",
    kind="text",
    name=f"{descriptor}-search",
    label=_location_shell_label(node),
    token=_input_token("text", f"{descriptor}-search", ""),
    value="",
    input_type="text",
  )


def _input_type(node: ElementNode) -> str:
  return node.attrs.get("type", "text").strip().lower()


def _role_tokens(node: ElementNode) -> set[str]:
  return {token for token in node.attrs.get("role", "").strip().lower().split() if token}


def _is_tab_node(node: ElementNode) -> bool:
  if "tab" in _role_tokens(node):
    return True
  if node.tag != "button":
    return False
  if _looks_like_tab_button(node):
    return True
  parent = getattr(node, "_tweb_parent", None)
  return parent is not None and _looks_like_tab_container(parent)


def _is_aria_selected(node: ElementNode) -> bool:
  return (
    node.attrs.get("aria-selected", "").strip().lower() == "true" or
    bool(_class_tokens(node) & {"active", "current", "selected"})
  )


def _class_tokens(node: ElementNode) -> set[str]:
  return {token for token in node.attrs.get("class", "").strip().lower().split() if token}


def _class_token_parts(tokens: set[str]) -> set[str]:
  parts: set[str] = set()
  for token in tokens:
    parts.update(part for part in token.replace("_", "-").split("-") if part)
  return parts


def _search_shell_descriptor(node: ElementNode) -> str | None:
  is_custom_element = "-" in node.tag
  values = [
    node.tag,
    node.attrs.get("id", ""),
    node.attrs.get("class", ""),
    node.attrs.get("name", ""),
    node.attrs.get("aria-label", ""),
    node.attrs.get("placeholder", ""),
    node.attrs.get("title", ""),
    node.attrs.get("role", ""),
  ]
  haystack = " ".join(value.casefold() for value in values if value)
  if "search" not in haystack and "検索" not in haystack:
    return None
  if "research" in haystack:
    return None
  if "search-box" in haystack or "searchbox" in haystack or "search field" in haystack:
    return "search"
  if is_custom_element and ("search-bar" in haystack or "site-search" in haystack):
    return "search"
  return None


def _location_shell_descriptor(node: ElementNode) -> str | None:
  values = [
    node.tag,
    node.attrs.get("id", ""),
    node.attrs.get("class", ""),
    node.attrs.get("name", ""),
    node.attrs.get("aria-label", ""),
    node.attrs.get("data-name", ""),
    node.attrs.get("data-testid", ""),
  ]
  haystack = " ".join(value.casefold() for value in values if value)
  if "store selector" in haystack or "store-selector" in haystack:
    return "store"
  if "pickup-address" in haystack or "location selector" in haystack:
    return "location"
  return None


def _node_contains_form_like_descendants(node: ElementNode) -> bool:
  for child in node.iter_descendants():
    if not isinstance(child, ElementNode):
      continue
    if child.tag in {"form", "input", "select", "textarea", "button"}:
      return True
  return False


def _search_shell_label(node: ElementNode) -> str:
  current: ElementNode | None = node
  while current is not None:
    attrs = current.attrs
    combined = " ".join(
      value for value in (
        attrs.get("aria-label", "").strip(),
        attrs.get("title", "").strip(),
        attrs.get("placeholder", "").strip(),
      )
      if value
    )
    if "検索" in combined:
      return "検索"
    if "search" in combined.casefold():
      return "Search"
    current = getattr(current, "_tweb_parent", None)
  return "Search"


def _location_shell_label(node: ElementNode) -> str:
  current: ElementNode | None = node
  while current is not None:
    attrs = current.attrs
    combined = " ".join(
      value for value in (
        attrs.get("aria-label", "").strip(),
        attrs.get("title", "").strip(),
        attrs.get("placeholder", "").strip(),
        attrs.get("data-name", "").strip(),
      )
      if value
    )
    normalized = combined.casefold()
    if "store" in normalized:
      return "Store search"
    if "location" in normalized:
      return "Location search"
    current = getattr(current, "_tweb_parent", None)
  return "Location search"


def _looks_like_tab_button(node: ElementNode) -> bool:
  classes = _class_tokens(node)
  parts = _class_token_parts(classes)
  return "tab" in parts or "tabs" in parts or any(token.startswith("select-type-") for token in classes)


def _looks_like_tab_container(node: ElementNode) -> bool:
  classes = _class_tokens(node)
  parts = _class_token_parts(classes)
  if node.attrs.get("role", "").strip().lower() == "tablist":
    return True
  if "tab" in parts or "tabs" in parts:
    return True
  return "select-type" in classes


def _looks_like_picker_button(node: ElementNode, label: str) -> bool:
  if node.attrs.get("type", "submit").strip().lower() not in {"button", ""}:
    return False
  return _looks_like_picker_launcher(node, label)


def _looks_like_select_launcher(node: ElementNode, label: str) -> bool:
  normalized = " ".join(label.split())
  if not normalized or len(normalized) > 40:
    return False
  if _looks_like_command_label(normalized):
    return False
  role_tokens = _role_tokens(node)
  aria_haspopup = node.attrs.get("aria-haspopup", "").strip().lower()
  aria_controls = node.attrs.get("aria-controls", "").strip().lower()
  if "combobox" in role_tokens:
    return True
  if aria_haspopup == "listbox":
    return True
  return any(token in aria_controls for token in ("scope", "category", "genre", "sort"))


def _looks_like_picker_launcher(node: ElementNode, label: str) -> bool:
  normalized = " ".join(label.split())
  if not normalized or len(normalized) > 40:
    return False
  if _looks_like_command_label(normalized):
    return False
  classes = _class_tokens(node)
  parts = _class_token_parts(classes)
  aria_haspopup = node.attrs.get("aria-haspopup", "").strip().lower()
  aria_controls = node.attrs.get("aria-controls", "").strip().lower()
  if aria_haspopup in {"true", "dialog", "grid", "listbox", "menu", "tree"}:
    return True
  if any(token in aria_controls for token in ("date", "calendar", "picker", "scope", "filter")):
    return True
  if "justify-between" in classes:
    return True
  if "picker" in parts or "counter" in parts:
    return True
  return bool({"dropdown", "calendar", "date"} & parts)


def _looks_like_command_label(label: str) -> bool:
  normalized = label.casefold()
  command_fragments = (
    "search",
    "検索",
    "詳しく",
    "help",
    "ヘルプ",
    "次へ",
    "前へ",
    "戻る",
    "進む",
    "top",
    "画面上",
    "open",
    "close",
    "開く",
    "閉じる",
  )
  return any(fragment in normalized for fragment in command_fragments)


def _tab_group_container(node: ElementNode) -> ElementNode | None:
  current = getattr(node, "_tweb_parent", None)
  while current is not None:
    if _looks_like_tab_container(current):
      return current
    current = getattr(current, "_tweb_parent", None)
  return getattr(node, "_tweb_parent", None)


def _set_tab_selected_state(node: ElementNode, selected: bool) -> None:
  if "tab" in _role_tokens(node):
    node.attrs["aria-selected"] = "true" if selected else "false"
  classes = _class_tokens(node)
  token_parts = _class_token_parts(classes)
  if {"active", "current", "selected"} & classes or {"tab", "tabs"} & token_parts or any(
    token.startswith("select-type-") for token in classes
  ):
    _set_class_token(node, "active", selected)
    if "selected" in classes:
      _set_class_token(node, "selected", selected)
    if "current" in classes:
      _set_class_token(node, "current", selected)


def _set_tab_panel_visibility(node: ElementNode, visible: bool) -> None:
  if visible:
    node.attrs.pop("hidden", None)
  else:
    node.attrs["hidden"] = ""
  classes = _class_tokens(node)
  if "active" in classes:
    _set_class_token(node, "active", visible)
  if "current" in classes:
    _set_class_token(node, "current", visible)
  if "selected" in classes:
    _set_class_token(node, "selected", visible)


def _set_class_token(node: ElementNode, token: str, enabled: bool) -> None:
  classes = node.attrs.get("class", "").split()
  filtered = [value for value in classes if value != token]
  if enabled:
    filtered.append(token)
  if filtered:
    node.attrs["class"] = " ".join(filtered)
  else:
    node.attrs.pop("class", None)


def _control_label(document: DocumentNode, node: ElementNode) -> str:
  control_id = node.attrs.get("id", "").strip()
  if control_id:
    label = _label_targets_by_for(document).get(control_id)
    if label is not None:
      text = label.text_content().strip()
      if text:
        return text
  labelledby = _aria_labelledby_text(document, node)
  if labelledby:
    return labelledby
  aria_label = node.attrs.get("aria-label", "").strip()
  if aria_label:
    return aria_label
  return node.attrs.get("title", "").strip()


def _tab_label(document: DocumentNode, node: ElementNode) -> str:
  label = _control_label(document, node)
  if label:
    return label
  text = " ".join(node.text_content().split())
  if text:
    return text
  return node.attrs.get("aria-controls", "").strip()


def _button_label(document: DocumentNode, node: ElementNode) -> str:
  label = _control_label(document, node)
  if label:
    return label
  text = " ".join(node.text_content().split())
  if text:
    return text
  descendant_label = _descendant_accessible_label(node)
  if descendant_label:
    return descendant_label
  return node.attrs.get("value", "") or "button"


def _synthetic_hidden_input_shell_control(document: DocumentNode, node: ElementNode) -> FormControl | None:
  if node.tag != "label":
    return None
  hidden_input: ElementNode | None = None
  for child in node.children:
    if not isinstance(child, ElementNode) or child.tag != "input":
      continue
    input_type = _input_type(child)
    if input_type not in {"checkbox", "radio"}:
      continue
    if "hidden" not in _class_tokens(child) and child.attrs.get("type", "").strip().lower() != "hidden":
      continue
    hidden_input = child
    break
  if hidden_input is None:
    return None
  label = " ".join(node.text_content().split())
  if not label or len(label) > 60:
    return None
  control_id = _ensure_control_id(document, node)
  return FormControl(
    control_id=control_id,
    kind="picker",
    name=hidden_input.attrs.get("name") or hidden_input.attrs.get("id") or control_id,
    label=label,
    token=_picker_token(label),
    value=hidden_input.attrs.get("value", ""),
    checked="checked" in hidden_input.attrs,
    disabled="disabled" in hidden_input.attrs,
    readonly="readonly" in hidden_input.attrs,
  )


def _synthetic_pagination_dot_control(document: DocumentNode, node: ElementNode) -> FormControl | None:
  if node.tag != "li":
    return None
  if _has_clickable_ancestor(node):
    return None
  if " ".join(node.text_content().split()):
    return None
  classes = _class_tokens(node)
  if "cursor-pointer" not in classes or "rounded-full" not in classes:
    return None
  parent = getattr(node, "_tweb_parent", None)
  if parent is None or parent.tag not in {"ul", "ol", "div"}:
    return None
  siblings = [
    child for child in parent.children
    if isinstance(child, ElementNode)
    and child.tag == node.tag
    and "cursor-pointer" in _class_tokens(child)
    and "rounded-full" in _class_tokens(child)
  ]
  if len(siblings) < 3:
    return None
  index = next((position for position, sibling in enumerate(siblings, start=1) if sibling is node), 1)
  control_id = _ensure_control_id(document, node)
  label = f"carousel page {index}"
  checked = bool(_class_tokens(node) & {"active", "current", "selected"}) or "opacity-visible" in classes
  return FormControl(
    control_id=control_id,
    kind="picker",
    name=f"{_ensure_control_id(document, parent)}-pagination",
    label=label,
    token=_picker_token(label),
    value=str(index),
    checked=checked,
  )


def _synthetic_clickable_picker_control(document: DocumentNode, node: ElementNode) -> FormControl | None:
  if node.tag not in {"div", "label", "span"}:
    return None
  if node.tag == "label" and _synthetic_hidden_input_shell_control(document, node) is not None:
    return None
  if _has_clickable_ancestor(node):
    return None
  classes = _class_tokens(node)
  parts = _class_token_parts(classes)
  if "cursor-pointer" not in classes and "data-gaclickid" not in node.attrs:
    return None
  label = " ".join(node.text_content().split())
  if not label or len(label) > 60 or _looks_like_command_label(label):
    return None
  if not (
    "counter" in parts
    or "appearance-none" in classes
    or "rounded-full" in classes
    or "data-gaclickid" in node.attrs
  ):
    return None
  control_id = _ensure_control_id(document, node)
  return FormControl(
    control_id=control_id,
    kind="picker",
    name=node.attrs.get("name") or node.attrs.get("id") or control_id,
    label=label,
    token=_picker_token(label),
    value=node.attrs.get("data-gaclickid", ""),
    disabled="disabled" in node.attrs,
    readonly="readonly" in node.attrs,
  )


def _synthetic_javascript_link_control(document: DocumentNode, node: ElementNode) -> FormControl | None:
  if node.tag != "a":
    return None
  href = node.attrs.get("href", "").strip()
  if not href.casefold().startswith("javascript:"):
    return None
  label = " ".join(node.text_content().split())
  if not label or len(label) > 60:
    return None
  control_id = _ensure_control_id(document, node)
  return FormControl(
    control_id=control_id,
    kind="button",
    name=node.attrs.get("name") or node.attrs.get("id") or control_id,
    label=label,
    token=_button_token(label),
    value=href,
    disabled="disabled" in node.attrs,
    readonly="readonly" in node.attrs,
  )


def _synthetic_clickable_button_control(document: DocumentNode, node: ElementNode) -> FormControl | None:
  if node.tag not in {"div", "span", "a"}:
    return None
  if _is_tab_node(node):
    return None
  if node.tag == "a" and node.attrs.get("href", "").strip():
    return None
  if _has_clickable_ancestor(node):
    return None
  role_tokens = _role_tokens(node)
  attr_label = _control_label(document, node)
  descendant_label = _descendant_accessible_label(node)
  classes = _class_tokens(node)
  interactive_signal = (
    "button" in role_tokens
    or "aria-controls" in node.attrs
    or "aria-expanded" in node.attrs
    or "aria-haspopup" in node.attrs
    or "onclick" in node.attrs
  )
  if not interactive_signal and not ((attr_label or descendant_label) and "cursor-pointer" in classes):
    return None
  label = attr_label or " ".join(node.text_content().split()) or descendant_label
  if not label or len(label) > 60:
    return None
  if _looks_like_select_launcher(node, label):
    control_id = _ensure_control_id(document, node)
    return FormControl(
      control_id=control_id,
      kind="select",
      name=node.attrs.get("name") or node.attrs.get("id") or control_id,
      label=label,
      token=_select_token(node.attrs.get("name") or node.attrs.get("id") or control_id, label),
      value=node.attrs.get("aria-controls", "") or label,
      options=(FormOption(value=node.attrs.get("aria-controls", "") or label, label=label, selected=True),),
      disabled="disabled" in node.attrs,
      readonly="readonly" in node.attrs,
    )
  if _looks_like_picker_launcher(node, label):
    control_id = _ensure_control_id(document, node)
    return FormControl(
      control_id=control_id,
      kind="picker",
      name=node.attrs.get("name") or node.attrs.get("id") or control_id,
      label=label,
      token=_picker_token(label),
      value=node.attrs.get("aria-controls", "") or label,
      disabled="disabled" in node.attrs,
      readonly="readonly" in node.attrs,
    )
  control_id = _ensure_control_id(document, node)
  return FormControl(
    control_id=control_id,
    kind="button",
    name=node.attrs.get("name") or node.attrs.get("id") or control_id,
    label=label,
    token=_button_token(label),
    value=node.attrs.get("aria-controls", "") or label,
    disabled="disabled" in node.attrs,
    readonly="readonly" in node.attrs,
  )


def _has_clickable_ancestor(node: ElementNode) -> bool:
  current = getattr(node, "_tweb_parent", None)
  while current is not None:
    if current.tag in {"a", "button", "label"}:
      return True
    current = getattr(current, "_tweb_parent", None)
  return False


def _descendant_accessible_label(node: ElementNode) -> str:
  for child in node.children:
    if not isinstance(child, ElementNode):
      continue
    label = child.attrs.get("aria-label", "").strip() or child.attrs.get("title", "").strip()
    if label:
      return label
    nested = _descendant_accessible_label(child)
    if nested:
      return nested
  return ""


def _ensure_control_id(document: DocumentNode, node: ElementNode) -> str:
  existing = getattr(node, "_tweb_control_id", None)
  if existing:
    return existing
  control_id = node.attrs.get("id", "").strip()
  if control_id:
    setattr(node, "_tweb_control_id", control_id)
    cached_nodes = getattr(document, "_tweb_control_nodes_by_id", None)
    if cached_nodes is not None:
      cached_nodes.setdefault(control_id, node)
    return control_id
  tag_prefix = node.tag
  counters = getattr(document, "_tweb_generated_control_id_counters", None)
  if counters is None:
    counters = {}
    setattr(document, "_tweb_generated_control_id_counters", counters)
  counter = counters.get(tag_prefix, 1)
  control_nodes_by_id = _control_nodes_by_id(document)
  while True:
    candidate = f"tweb-{tag_prefix}-{counter}"
    if candidate not in control_nodes_by_id:
      setattr(node, "_tweb_control_id", candidate)
      control_nodes_by_id[candidate] = node
      counters[tag_prefix] = counter + 1
      return candidate
    counter += 1


def _control_id_in_tree(node: ElementNode, candidate: str) -> bool:
  document = node if isinstance(node, DocumentNode) else None
  if document is None:
    current = node
    while current is not None:
      parent = getattr(current, "_tweb_parent", None)
      if isinstance(parent, DocumentNode):
        document = parent
        break
      current = parent
  if document is not None:
    return candidate in _control_nodes_by_id(document)
  for descendant in _iter_descendants_inclusive(node):
    if descendant.attrs.get("id") == candidate or getattr(descendant, "_tweb_control_id", None) == candidate:
      return True
  return False


def _find_control_node(document: DocumentNode, control_id: str) -> ElementNode | None:
  return _control_nodes_by_id(document).get(control_id)


def _find_element_by_id(document: DocumentNode, element_id: str) -> ElementNode | None:
  return _elements_by_id(document).get(element_id)


def _aria_labelledby_text(document: DocumentNode, node: ElementNode) -> str:
  labelledby = node.attrs.get("aria-labelledby", "").strip()
  if not labelledby:
    return ""
  parts: list[str] = []
  for element_id in labelledby.split():
    target = _find_element_by_id(document, element_id)
    if target is None:
      continue
    text = " ".join(target.text_content().split())
    if text:
      parts.append(text)
  return " ".join(parts).strip()


def _invalidate_interaction_lookup_caches(document: DocumentNode) -> None:
  for attr_name in (
    "_tweb_labels_by_for",
    "_tweb_elements_by_id",
    "_tweb_control_nodes_by_id",
    "_tweb_generated_control_id_counters",
  ):
    if hasattr(document, attr_name):
      delattr(document, attr_name)


def _label_targets_by_for(document: DocumentNode) -> dict[str, ElementNode]:
  cached = getattr(document, "_tweb_labels_by_for", None)
  if cached is not None:
    return cached
  labels_by_for: dict[str, ElementNode] = {}
  for node in _iter_elements(document):
    if node.tag != "label":
      continue
    control_id = node.attrs.get("for", "").strip()
    if control_id and control_id not in labels_by_for:
      labels_by_for[control_id] = node
  setattr(document, "_tweb_labels_by_for", labels_by_for)
  return labels_by_for


def _elements_by_id(document: DocumentNode) -> dict[str, ElementNode]:
  cached = getattr(document, "_tweb_elements_by_id", None)
  if cached is not None:
    return cached
  elements_by_id: dict[str, ElementNode] = {}
  for node in _iter_elements(document):
    element_id = node.attrs.get("id", "").strip()
    if element_id and element_id not in elements_by_id:
      elements_by_id[element_id] = node
  setattr(document, "_tweb_elements_by_id", elements_by_id)
  return elements_by_id


def _control_nodes_by_id(document: DocumentNode) -> dict[str, ElementNode]:
  cached = getattr(document, "_tweb_control_nodes_by_id", None)
  if cached is not None:
    return cached
  nodes_by_id = dict(_elements_by_id(document))
  for node in _iter_elements(document):
    control_id = getattr(node, "_tweb_control_id", None)
    if control_id and control_id not in nodes_by_id:
      nodes_by_id[control_id] = node
  setattr(document, "_tweb_control_nodes_by_id", nodes_by_id)
  return nodes_by_id


def _nearest_form(node: ElementNode) -> ElementNode | None:
  current = getattr(node, "_tweb_parent", None)
  while current is not None:
    if current.tag == "form":
      return current
    current = getattr(current, "_tweb_parent", None)
  return None


def _form_owner(document: DocumentNode, node: ElementNode) -> ElementNode | None:
  form_id = node.attrs.get("form", "").strip()
  if form_id:
    root = document.root
    if root is not None:
      for candidate in _iter_descendants_inclusive(root):
        if candidate.tag == "form" and candidate.attrs.get("id", "").strip() == form_id:
          return candidate
  return _nearest_form(node)


def _serialize_form(form: ElementNode, submitter: ElementNode) -> list[tuple[str, str]]:
  params: list[tuple[str, str]] = []
  submitter_in_form = False
  for node in _iter_descendants_inclusive(form):
    if node is submitter:
      submitter_in_form = True
    name = node.attrs.get("name", "")
    if not name:
      continue
    if node.tag == "input":
      input_type = _input_type(node)
      if input_type in TEXT_INPUT_TYPES | {"hidden"}:
        params.append((name, node.attrs.get("value", "")))
      elif input_type == "checkbox" and "checked" in node.attrs:
        params.append((name, node.attrs.get("value", "on")))
      elif input_type == "radio" and "checked" in node.attrs:
        params.append((name, node.attrs.get("value", "on")))
      elif input_type == "submit" and node is submitter:
        params.append((name, node.attrs.get("value", "")))
    elif node.tag == "textarea":
      params.append((name, _textarea_value(node)))
    elif node.tag == "select":
      selected = next((option for option in _select_options(node) if option.selected), None)
      if selected is not None:
        params.append((name, selected.value))
    elif node.tag == "button" and node is submitter:
      params.append((name, node.attrs.get("value", node.text_content().strip())))
  if not submitter_in_form:
    submitter_name = submitter.attrs.get("name", "")
    if submitter_name:
      if submitter.tag == "input":
        params.append((submitter_name, submitter.attrs.get("value", "")))
      elif submitter.tag == "button":
        params.append((submitter_name, submitter.attrs.get("value", submitter.text_content().strip())))
  return params


def _sync_select_defaults(node: ElementNode) -> None:
  options = [child for child in node.children if isinstance(child, ElementNode) and child.tag == "option"]
  if not options:
    return
  if any("selected" in option.attrs for option in options):
    return
  options[0].attrs["selected"] = ""


def _select_options(node: ElementNode) -> list[FormOption]:
  options: list[FormOption] = []
  for child in node.children:
    if isinstance(child, ElementNode) and child.tag == "option":
      label = child.text_content().strip()
      value = child.attrs.get("value", label)
      options.append(FormOption(value=value, label=label, selected="selected" in child.attrs))
  return options


def _sync_checkbox_visibility(checkbox: ElementNode) -> None:
  content = _controlled_dropdown_content(checkbox)
  if content is None:
    return
  if "checked" in checkbox.attrs:
    content.attrs.pop("data-tweb-collapsed", None)
    content.attrs.pop("hidden", None)
    return
  content.attrs["data-tweb-collapsed"] = "1"
  content.attrs["hidden"] = ""


def _resolve_form_action(current_source: str, action: str) -> str:
  parsed = urlsplit(action)
  if parsed.scheme in {"http", "https"}:
    return action
  if current_source.startswith(("http://", "https://")):
    return urljoin(current_source, action)
  current_path = Path(current_source).resolve()
  if action.startswith("/"):
    return str(Path(action))
  return str((current_path.parent / action).resolve())


def _replace_query(current_source: str, query: dict[str, str]) -> str:
  parsed = urlsplit(current_source)
  return urlunsplit(
    (
      parsed.scheme,
      parsed.netloc,
      parsed.path,
      urlencode(query),
      parsed.fragment,
    )
  )


def _mirrored_text_controls(document: DocumentNode, node: ElementNode) -> list[ElementNode]:
  name = node.attrs.get("name", "")
  if not name:
    return [node]
  if node.tag == "input":
    input_type = _input_type(node)
    return [
      candidate
      for candidate in _iter_elements(document)
      if candidate.tag == "input"
      and _input_type(candidate) == input_type
      and candidate.attrs.get("name", "") == name
    ] or [node]
  if node.tag == "textarea":
    return [
      candidate
      for candidate in _iter_elements(document)
      if candidate.tag == "textarea"
      and candidate.attrs.get("name", "") == name
    ] or [node]
  return [node]


def _controlled_dropdown_content(checkbox: ElementNode) -> ElementNode | None:
  parent = getattr(checkbox, "_tweb_parent", None)
  if parent is None:
    return None
  for child in parent.children:
    if isinstance(child, ElementNode):
      classes = set(child.attrs.get("class", "").split())
      if "vector-dropdown-content" in classes:
        return child
  return None


def _controlled_button_content(button: ElementNode) -> ElementNode | None:
  controlled_id = _controlled_target_id(button)
  if controlled_id:
    root = _document_root_element(button)
    if root is not None:
      for node in _iter_descendants_inclusive(root):
        if node.attrs.get("id", "").strip() == controlled_id:
          return node
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
    if child.attrs.get("data-tweb-disclosure-content") == "1":
      return child
    classes = set(child.attrs.get("class", "").split())
    if "WorkTocAccordion_contents__6nJhY" in classes:
      return child
  return None


def _controlled_target_id(node: ElementNode) -> str | None:
  controlled_id = node.attrs.get("aria-controls", "").strip()
  if controlled_id:
    return controlled_id
  node_id = node.attrs.get("id", "").strip()
  if not node_id:
    return None
  match = re.fullmatch(r"(.+?)-(?:open|toggle)", node_id, re.IGNORECASE)
  if not match:
    return None
  candidate = match.group(1)
  root = _document_root_element(node)
  if root is None:
    return None
  for descendant in _iter_descendants_inclusive(root):
    if descendant.attrs.get("id", "").strip() == candidate:
      return candidate
  return None


def _merge_inline_style(style: str | None, updates: dict[str, str]) -> str:
  declarations: dict[str, str] = {}
  if style:
    for part in style.split(";"):
      key, _, value = part.partition(":")
      if not key.strip():
        continue
      declarations[key.strip().lower()] = value.strip()
  declarations.update(updates)
  return "; ".join(f"{key}: {value}" for key, value in declarations.items())


def _document_root_element(node: ElementNode) -> ElementNode | None:
  current: ElementNode | None = node
  while current is not None:
    parent = getattr(current, "_tweb_parent", None)
    if parent is None:
      return current
    current = parent
  return None


def _input_token(input_type: str, name: str, value: str) -> str:
  if value:
    return f"[input:{input_type} {name}={value}]"
  return f"[input:{input_type} {name}]"


def _display_input_value(input_type: str, value: str) -> str:
  if input_type == "password" and value:
    return "*" * len(value)
  return value


def _checkbox_token(name: str, checked: bool) -> str:
  suffix = " checked" if checked else ""
  return f"[input:checkbox {name}{suffix}]"


def _radio_token(name: str, value: str, checked: bool) -> str:
  suffix = " checked" if checked else ""
  return f"[input:radio {name}={value}{suffix}]"


def _textarea_token(name: str, value: str) -> str:
  if value:
    return f"[textarea {name}={value}]"
  return f"[textarea {name}]"


def _select_token(name: str, value: str) -> str:
  if value:
    return f"[select {name}={value}]"
  return f"[select {name}]"


def _button_token(label: str) -> str:
  return f"({label})" if label else "(button)"


def _picker_token(label: str) -> str:
  return f"[picker {label}]" if label else "[picker]"


def _tab_token(label: str, selected: bool) -> str:
  suffix = " selected" if selected else ""
  return f"[tab: {label}{suffix}]" if label else f"[tab{suffix}]"


def _textarea_value(node: ElementNode) -> str:
  parts: list[str] = []
  for child in node.children:
    if isinstance(child, ElementNode):
      parts.append(_textarea_value(child))
    else:
      parts.append(child.text)
  return "".join(parts)
