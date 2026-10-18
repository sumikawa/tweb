from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace
import importlib.resources
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from time import monotonic
from typing import Callable
from rich.text import Text
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual import events
from textual.worker import Worker, WorkerState, get_current_worker
from textual.widgets import Input, Label, Static, TextArea

from .api import Link, TWebDocument
from .dom import ElementNode
from .fetcher import FetchCancelled, FetchError, Resource, create_session, fetch_resource, normalize_target
from .interactions import ButtonClickPolicy, ButtonClickResult, FormControl, is_button_control, is_submit_control, is_text_entry_control
from .js_runtime import JavaScriptRuntimeError
from .parser import parse_document
from .renderers.dom import render_dom
from .renderers.normal import (
  ANSI_ESCAPE_RE,
  PaneTarget,
  RenderedControlMetadata,
  RenderedLinkMetadata,
  _display_width,
  collect_two_pane_targets,
  render_normal,
  render_normal_subtree,
  render_normal_subtree_with_metadata,
  render_normal_with_metadata,
  visible_links_from_render_result,
)

LINK_BASE_STYLE = "underline cyan"
CONTROL_BASE_STYLE = "bold magenta"
BLOCK_DEBUG_BACKGROUND_STYLES = (
  "on #1f3b4d",
  "on #3f2f4d",
  "on #3a4a1f",
  "on #4d3520",
  "on #2f4d46",
  "on #4d1f2f",
)
WELCOME_PAGE_TARGET = str(Path(importlib.resources.files("tweb").joinpath("data", "welcome.html")).resolve())
LOGGER = logging.getLogger("tweb")
DEFAULT_HISTORY_PATH = Path("~/.config/tw/history.json").expanduser()
BUILTIN_HISTORY_EXCLUDED_TARGETS = frozenset((str(Path(WELCOME_PAGE_TARGET).resolve()),))


@dataclass(frozen=True)
class LinkSpan:
  start: int
  end: int
  href: str
  text: str
  index: int


@dataclass(frozen=True)
class ControlSpan:
  start: int
  end: int
  control_id: str
  text: str
  label: str
  kind: str
  source_kind: str = "token"


@dataclass(frozen=True)
class InteractiveSpan:
  start: int
  end: int
  key: str


@dataclass(frozen=True)
class BlockRegion:
  start: int
  start_line: int
  end_line: int
  start_column: int
  end_column: int | None = None
  line_columns: tuple[tuple[int, int, int | None], ...] = ()

  def contains(self, line_index: int, column: int) -> bool:
    if self.line_columns:
      for entry_line, entry_start, entry_end in self.line_columns:
        if entry_line != line_index:
          continue
        if column < entry_start:
          return False
        if entry_end is not None and column >= entry_end:
          return False
        return True
      return False
    if not (self.start_line <= line_index <= self.end_line):
      return False
    if column < self.start_column:
      return False
    if self.end_column is not None and column >= self.end_column:
      return False
    return True


@dataclass(frozen=True)
class RenderedBuffer:
  text: str
  visible_positions: list[int]
  line_starts: list[int]
  line_visible_ends: list[int]
  block_starts: list[int]
  block_regions: list[BlockRegion]
  link_spans: list[LinkSpan]
  control_spans: list[ControlSpan]
  visible_position_indexes: dict[int, int]
  interactive_spans_cache: list[InteractiveSpan]
  interactive_keys_cache: list[str]
  interactive_cursor_by_key: dict[str, int]
  control_cursor_by_id: dict[str, int]
  link_starts: list[int]
  control_starts: list[int]

  def first_cursor_index(self) -> int:
    return self.visible_positions[0] if self.visible_positions else 0

  def move_char(self, cursor_index: int, delta: int) -> int:
    if not self.visible_positions:
      return 0
    position = self.visible_position_indexes.get(cursor_index)
    if position is None:
      return self.first_cursor_index()
    next_position = max(0, min(len(self.visible_positions) - 1, position + delta))
    return self.visible_positions[next_position]

  def line_col(self, cursor_index: int) -> tuple[int, int]:
    if not self.line_starts:
      return (0, 0)
    line_index = max(0, bisect_right(self.line_starts, cursor_index) - 1)
    return (line_index, max(0, cursor_index - self.line_starts[line_index]))

  def move_line(self, cursor_index: int, delta: int) -> int:
    if not self.visible_positions:
      return 0
    line_index, column = self.line_col(cursor_index)
    target_line = max(0, min(len(self.line_starts) - 1, line_index + delta))
    step = 1 if delta >= 0 else -1
    while 0 <= target_line < len(self.line_starts):
      target_start, target_end = self._line_visible_bounds(target_line)
      if target_end > target_start:
        return min(target_start + column, target_end - 1)
      target_line += step
    return cursor_index

  def line_start(self, cursor_index: int) -> int:
    line_index, _ = self.line_col(cursor_index)
    start, end = self._line_visible_bounds(line_index)
    return start if end > start else cursor_index

  def line_end(self, cursor_index: int) -> int:
    line_index, _ = self.line_col(cursor_index)
    start, end = self._line_visible_bounds(line_index)
    return max(start, end - 1) if end > start else cursor_index

  def link_at(self, cursor_index: int) -> LinkSpan | None:
    return _interactive_span_at(self, self.link_spans, self.link_starts, cursor_index, lambda span: span.text)

  def next_link_cursor(self, cursor_index: int, reverse: bool = False) -> int:
    if not self.interactive_keys_cache:
      return cursor_index
    current_key = None
    current_control = self.control_at(cursor_index)
    current_link = self.link_at(cursor_index)
    if current_control is not None:
      current_key = f"control:{current_control.control_id}"
    elif current_link is not None:
      current_key = f"link:{current_link.index}"
    if current_key is not None:
      current_index = self.interactive_keys_cache.index(current_key)
      next_index = (current_index - 1 if reverse else current_index + 1) % len(self.interactive_keys_cache)
      return self.interactive_cursor_by_key[self.interactive_keys_cache[next_index]]
    ordered_keys = list(reversed(self.interactive_keys_cache)) if reverse else self.interactive_keys_cache
    for key in ordered_keys:
      interactive_cursor = self.interactive_cursor_by_key[key]
      if reverse:
        if interactive_cursor < cursor_index:
          return interactive_cursor
      else:
        if interactive_cursor > cursor_index:
          return interactive_cursor
    edge_key = ordered_keys[0]
    return self.interactive_cursor_by_key[edge_key]

  def last_cursor_index(self) -> int:
    return self.visible_positions[-1] if self.visible_positions else 0

  def control_at(self, cursor_index: int) -> ControlSpan | None:
    return _interactive_span_at(self, self.control_spans, self.control_starts, cursor_index, lambda span: span.text)

  def first_control_cursor(self, control_id: str) -> int | None:
    return self.control_cursor_by_id.get(control_id)

  def interactive_spans(self) -> list[InteractiveSpan]:
    return self.interactive_spans_cache

  def move_block(self, cursor_index: int, delta: int) -> int:
    if not self.block_starts or delta == 0:
      return cursor_index
    line_index, column = self.line_col(cursor_index)
    current_block_index = None
    for index, region in enumerate(self.block_regions):
      if region.contains(line_index, column):
        current_block_index = index
        break
    if current_block_index is None:
      current_block_index = 0
      for index, start in enumerate(self.block_starts):
        if start > cursor_index:
          break
        current_block_index = index
    target_index = max(0, min(len(self.block_starts) - 1, current_block_index + delta))
    return self.block_starts[target_index]

  def _line_visible_bounds(self, line_index: int) -> tuple[int, int]:
    start = self.line_starts[line_index]
    end = self.line_visible_ends[line_index]
    visible_positions = [
      position for position in range(start, end)
      if position in self.visible_position_indexes
    ]
    if not visible_positions:
      return (start, start)
    return (visible_positions[0], visible_positions[-1] + 1)


@dataclass
class BrowserPage:
  resource: Resource
  document: TWebDocument
  rendered: str
  links: list[Link]
  controls: list[FormControl]
  buffer: RenderedBuffer
  is_partial: bool = False
  source_rendered: str | None = None
  source_links: list[Link] | None = None
  source_link_metadata: tuple[RenderedLinkMetadata, ...] = ()
  source_control_metadata: tuple[RenderedControlMetadata, ...] = ()
  source_buffer: RenderedBuffer | None = None
  source_pane_groups: list[tuple[PaneTarget, PaneTarget]] | None = None


@dataclass(frozen=True)
class LoadResult:
  request: "LoadRequest"
  push_navigation: bool
  page: BrowserPage


@dataclass(frozen=True)
class BackgroundRenderResult:
  document: TWebDocument
  rendered: str
  links: list[Link]
  controls: list[FormControl]
  link_metadata: tuple[RenderedLinkMetadata, ...] = ()
  control_metadata: tuple[RenderedControlMetadata, ...] = ()


@dataclass(frozen=True)
class CursorRestoreContext:
  line_snippet: str
  region_column: int
  fallback_line: int
  fallback_column: int


@dataclass(frozen=True)
class ViewRenderResult:
  document: TWebDocument
  page: BrowserPage
  restore_context: CursorRestoreContext
  display_mode: str
  pane_focus_target_path: tuple[int, ...] | None
  content_width: int


@dataclass(frozen=True)
class LoadRequest:
  target: str
  method: str = "get"
  form_data: tuple[tuple[str, str], ...] = ()
  skip_embedded_scripts: bool = False
  title: str | None = field(default=None, compare=False)


class EditControlScreen(ModalScreen[str | None]):
  AUTO_FOCUS = "#edit-input"
  CSS = """
  EditControlScreen {
    align: center middle;
  }

  #edit-dialog {
    width: 80%;
    max-width: 80;
    height: auto;
    border: round $warning;
    background: $surface;
    padding: 1 2;
  }

  #edit-title {
    text-style: bold;
    margin-bottom: 1;
  }

  #edit-input {
    min-height: 3;
    max-height: 12;
  }

  #edit-help {
    margin-top: 1;
    color: $text-muted;
  }
  """

  def __init__(self, control: FormControl) -> None:
    super().__init__()
    self.control = control

  def compose(self) -> ComposeResult:
    with Vertical(id="edit-dialog"):
      yield Label(f"Edit: {self.control.label or self.control.name}", id="edit-title")
      if self.control.input_type == "password":
        yield PasswordInput(self.control.value, password=True, id="edit-input", compact=True)
      else:
        yield EditTextArea(
          self.control.value,
          id="edit-input",
          soft_wrap=True,
          tab_behavior="indent",
          compact=self.control.kind != "textarea",
          submit_on_enter=self.control.kind != "textarea",
        )
      if self.control.kind == "textarea":
        yield Static("Enter: newline  Ctrl-S: save  Esc/Ctrl-G: cancel  Ctrl-C: quit", id="edit-help")
      else:
        yield Static("Enter: save  Esc/Ctrl-G: cancel  Ctrl-C: quit", id="edit-help")


class SearchScreen(ModalScreen[str | None]):
  AUTO_FOCUS = "#search-input"
  CSS = """
  SearchScreen {
    align: center middle;
  }

  #search-dialog {
    width: 80%;
    max-width: 80;
    height: auto;
    border: round $accent;
    background: $surface;
    padding: 1 2;
  }

  #search-title {
    text-style: bold;
    margin-bottom: 1;
  }

  #search-input {
    min-height: 3;
    max-height: 3;
  }

  #search-help {
    margin-top: 1;
    color: $text-muted;
  }
  """

  BINDINGS = [
    Binding("escape,ctrl+g", "cancel_search", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  def __init__(self, initial_value: str = "") -> None:
    super().__init__()
    self.initial_value = initial_value

  def compose(self) -> ComposeResult:
    with Vertical(id="search-dialog"):
      yield Label("Find in page", id="search-title")
      yield SearchTextArea(
        self.initial_value,
        id="search-input",
        soft_wrap=False,
        tab_behavior="indent",
        compact=True,
      )
      yield Static("Enter: find next match  Esc/Ctrl-G: cancel  Ctrl-C: quit", id="search-help")

  def action_cancel_search(self) -> None:
    self._cancel_search()

  def action_quit_app(self) -> None:
    self.app.action_quit()

  def _submit_search(self) -> None:
    self.app._finish_search(self.query_one("#search-input", SearchTextArea).text)
    self.dismiss(None)

  def _cancel_search(self) -> None:
    self.app._finish_search(None)
    self.dismiss(None)


class EditTextArea(TextArea):
  BINDINGS = [
    Binding("enter", "submit_or_newline", "Save", show=False, priority=True),
    Binding("ctrl+s", "save", "Save", show=False, priority=True),
    Binding("escape,ctrl+g", "cancel", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  def __init__(self, *args, submit_on_enter: bool, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self.submit_on_enter = submit_on_enter

  def action_submit_or_newline(self) -> None:
    if self.submit_on_enter:
      self._dismiss_with_value()
      return
    self.insert("\n")

  def action_save(self) -> None:
    self._dismiss_with_value()

  def action_cancel(self) -> None:
    if isinstance(self.screen, EditControlScreen):
      self.screen.dismiss(None)

  def action_quit_app(self) -> None:
    self.app.action_quit()

  def _dismiss_with_value(self) -> None:
    if isinstance(self.screen, EditControlScreen):
      self.screen.dismiss(self.text)


class SearchTextArea(TextArea):
  BINDINGS = [
    Binding("right,ctrl+f", "cursor_right", "Cursor Right", show=False, priority=True),
    Binding("left,ctrl+b", "cursor_left", "Cursor Left", show=False, priority=True),
    Binding("up,ctrl+p", "cursor_up", "Cursor Up", show=False, priority=True),
    Binding("down,ctrl+n", "cursor_down", "Cursor Down", show=False, priority=True),
    Binding("home,ctrl+a", "cursor_line_start", "Line Start", show=False, priority=True),
    Binding("end,ctrl+e", "cursor_line_end", "Line End", show=False, priority=True),
    Binding("enter", "submit_search", "Search", show=False, priority=True),
    Binding("escape,ctrl+g", "cancel_search", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  def on_key(self, event: events.Key) -> None:
    if event.key == "enter":
      event.prevent_default()
      event.stop()
      self.action_submit_search()
      return
    if event.key == "escape":
      event.prevent_default()
      event.stop()
      self.action_cancel_search()
      return

  def action_submit_search(self) -> None:
    if isinstance(self.screen, SearchScreen):
      self.screen._submit_search()

  def action_cancel_search(self) -> None:
    if isinstance(self.screen, SearchScreen):
      self.screen._cancel_search()

  def action_quit_app(self) -> None:
    self.app.action_quit()


class OpenLocationTextArea(TextArea):
  BINDINGS = [
    Binding("right,ctrl+f", "cursor_right", "Cursor Right", show=False, priority=True),
    Binding("left,ctrl+b", "cursor_left", "Cursor Left", show=False, priority=True),
    Binding("up,ctrl+p", "cursor_up", "Cursor Up", show=False, priority=True),
    Binding("down,ctrl+n", "cursor_down", "Cursor Down", show=False, priority=True),
    Binding("home,ctrl+a", "cursor_line_start", "Line Start", show=False, priority=True),
    Binding("end,ctrl+e", "cursor_line_end", "Line End", show=False, priority=True),
    Binding("enter", "submit_location", "Open", show=False, priority=True),
    Binding("escape,ctrl+g", "cancel_location", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  def on_key(self, event: events.Key) -> None:
    if event.key == "enter":
      event.prevent_default()
      event.stop()
      self.action_submit_location()
      return
    if event.key == "escape":
      event.prevent_default()
      event.stop()
      self.action_cancel_location()
      return

  def action_submit_location(self) -> None:
    if isinstance(self.screen, OpenLocationScreen):
      self.screen._submit_location()

  def action_cancel_location(self) -> None:
    if isinstance(self.screen, OpenLocationScreen):
      self.screen._cancel_location()

  def action_quit_app(self) -> None:
    self.app.action_quit()


class OpenLocationScreen(ModalScreen[str | None]):
  AUTO_FOCUS = "#open-location-input"
  CSS = """
  OpenLocationScreen {
    align: center middle;
  }

  #open-location-dialog {
    width: 80%;
    max-width: 100;
    height: auto;
    border: round $accent;
    background: $surface;
    padding: 1 2;
  }

  #open-location-title {
    text-style: bold;
    margin-bottom: 1;
  }

  #open-location-input {
    min-height: 3;
    max-height: 3;
  }

  #open-location-help {
    margin-top: 1;
    color: $text-muted;
  }
  """

  BINDINGS = [
    Binding("right,ctrl+f", "cursor_right", "Cursor Right", show=False, priority=True),
    Binding("left,ctrl+b", "cursor_left", "Cursor Left", show=False, priority=True),
    Binding("up,ctrl+p", "cursor_up", "Cursor Up", show=False, priority=True),
    Binding("down,ctrl+n", "cursor_down", "Cursor Down", show=False, priority=True),
    Binding("home,ctrl+a", "cursor_line_start", "Line Start", show=False, priority=True),
    Binding("end,ctrl+e", "cursor_line_end", "Line End", show=False, priority=True),
    Binding("escape,ctrl+g", "cancel_location", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  def __init__(self, initial_value: str = "") -> None:
    super().__init__()
    self.initial_value = initial_value

  def compose(self) -> ComposeResult:
    with Vertical(id="open-location-dialog"):
      yield Label("Open URL or path", id="open-location-title")
      yield OpenLocationTextArea(
        self.initial_value,
        id="open-location-input",
        soft_wrap=False,
        tab_behavior="indent",
        compact=True,
      )
      yield Static("Enter: open  Esc/Ctrl-G: cancel  Ctrl-C: quit", id="open-location-help")

  def on_mount(self) -> None:
    self._focus_input()
    self.call_after_refresh(self._debug_initial_focus_state)

  def _watch_focused(self) -> None:
    super()._watch_focused()
    if self.focused is None:
      self._focus_input()

  def on_key(self, event: events.Key) -> None:
    if event.key == "enter":
      event.prevent_default()
      event.stop()
      self._submit_location()
      return
    if event.key == "escape":
      event.prevent_default()
      event.stop()
      self._cancel_location()
      return
    self._handle_cursor_key(event)

  def action_cancel_location(self) -> None:
    self._cancel_location()

  def action_cursor_right(self) -> None:
    self._focus_input().action_cursor_right()

  def action_cursor_left(self) -> None:
    self._focus_input().action_cursor_left()

  def action_cursor_up(self) -> None:
    self._focus_input().action_cursor_up()

  def action_cursor_down(self) -> None:
    self._focus_input().action_cursor_down()

  def action_cursor_line_start(self) -> None:
    self._focus_input().action_cursor_line_start()

  def action_cursor_line_end(self) -> None:
    self._focus_input().action_cursor_line_end()

  def action_quit_app(self) -> None:
    self.app.action_quit()

  def _submit_location(self) -> None:
    value = self.query_one("#open-location-input", OpenLocationTextArea).text
    self.app._finish_open_location(value)
    self.dismiss(None)

  def _cancel_location(self) -> None:
    self.app._finish_open_location(None)
    self.dismiss(None)

  def _debug_initial_focus_state(self) -> None:
    expected = self.query_one("#open-location-input", OpenLocationTextArea)
    focused = self.focused
    LOGGER.debug(
      "open-location popup focus expected_id=%s focused_id=%s focused_type=%s initial_chars=%d",
      expected.id,
      getattr(focused, "id", None),
      type(focused).__name__ if focused is not None else None,
      len(expected.text),
    )
    if focused is expected:
      return
    LOGGER.debug(
      "open-location popup focus mismatch recovering expected_id=%s focused_id=%s",
      expected.id,
      getattr(focused, "id", None),
    )
    self.set_focus(expected)

  def _focus_input(self) -> OpenLocationTextArea:
    expected = self.query_one("#open-location-input", OpenLocationTextArea)
    focused = self.focused
    if focused is not expected:
      LOGGER.debug(
        "open-location popup refocusing input expected_id=%s focused_id=%s focused_type=%s",
        expected.id,
        getattr(focused, "id", None),
        type(focused).__name__ if focused is not None else None,
      )
      self.set_focus(expected)
    return expected

  def _handle_cursor_key(self, event: events.Key) -> bool:
    action_name = {
      "right": "action_cursor_right",
      "ctrl+f": "action_cursor_right",
      "left": "action_cursor_left",
      "ctrl+b": "action_cursor_left",
      "up": "action_cursor_up",
      "ctrl+p": "action_cursor_up",
      "down": "action_cursor_down",
      "ctrl+n": "action_cursor_down",
      "home": "action_cursor_line_start",
      "ctrl+a": "action_cursor_line_start",
      "end": "action_cursor_line_end",
      "ctrl+e": "action_cursor_line_end",
    }.get(event.key)
    if action_name is None:
      return False
    event.prevent_default()
    event.stop()
    getattr(self, action_name)()
    return True


class HistoryScreen(ModalScreen[int | None]):
  CSS = """
  HistoryScreen {
    align: center middle;
  }

  #history-dialog {
    width: 88%;
    max-width: 120;
    height: auto;
    border: round $accent;
    background: $surface;
    padding: 1 2;
  }

  #history-title {
    text-style: bold;
    margin-bottom: 1;
  }

  #history-body {
    margin-bottom: 1;
  }

  #history-help {
    color: $text-muted;
  }
  """

  BINDINGS = [
    Binding("up,ctrl+p", "cursor_up", "Previous", show=False, priority=True),
    Binding("down,ctrl+n", "cursor_down", "Next", show=False, priority=True),
    Binding("enter", "submit_history", "Open", show=False, priority=True),
    Binding("escape,ctrl+g", "cancel_history", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  def __init__(self, history: list["LoadRequest"], current_index: int | None) -> None:
    super().__init__()
    self.history = list(history)
    self.current_index = current_index
    self.selected_row = 0 if not history or current_index is None else max(0, len(history) - 1 - current_index)

  def compose(self) -> ComposeResult:
    with Vertical(id="history-dialog"):
      yield Label("History", id="history-title")
      yield Static("", id="history-body")
      yield Static(
        "Up/Down: select  Enter: open selected  Esc/Ctrl-G: cancel  * current page",
        id="history-help",
      )

  def on_mount(self) -> None:
    body = self.query_one("#history-body", Static)
    body.styles.text_wrap = "nowrap"
    body.styles.text_overflow = "ellipsis"
    self._refresh_entries()

  def on_resize(self, event: events.Resize) -> None:
    del event
    self._refresh_entries()

  def action_cursor_up(self) -> None:
    if not self.history or self.selected_row <= 0:
      return
    self.selected_row -= 1
    self._refresh_entries()

  def action_cursor_down(self) -> None:
    if not self.history or self.selected_row >= len(self.history) - 1:
      return
    self.selected_row += 1
    self._refresh_entries()

  def action_submit_history(self) -> None:
    if not self.history:
      self.dismiss(None)
      return
    self.dismiss(self._selected_history_index())

  def action_cancel_history(self) -> None:
    self.dismiss(None)

  def action_quit_app(self) -> None:
    self.app.action_quit()

  def _refresh_entries(self) -> None:
    title = self.query_one("#history-title", Label)
    body = self.query_one("#history-body", Static)
    if not self.history:
      title.update("History")
      body.update("No history entries")
      return
    visible_count = max(1, self.size.height - 8)
    start = min(max(0, self.selected_row - (visible_count // 2)), max(0, len(self.history) - visible_count))
    end = min(len(self.history), start + visible_count)
    entry_width = self._entry_width(body)
    lines: list[str] = []
    for row in range(start, end):
      history_index = len(self.history) - 1 - row
      request = self.history[history_index]
      selected = ">" if row == self.selected_row else " "
      current = "*" if history_index == self.current_index else " "
      label = self._entry_label(request, width=entry_width)
      lines.append(f"{selected}{current} {label}")
    title.update(f"History {self._selected_history_index() + 1}/{len(self.history)}")
    body.update(Text("\n".join(lines), no_wrap=True, overflow="ellipsis", end=""))

  def _selected_history_index(self) -> int:
    return len(self.history) - 1 - self.selected_row

  def _entry_width(self, body: Static) -> int:
    if body.size.width > 0:
      return max(20, body.size.width - 2)
    dialog = self.query_one("#history-dialog", Vertical)
    if dialog.size.width > 0:
      return max(20, dialog.size.width - 8)
    return max(20, self.size.width - 12)

  def _entry_label(self, request: "LoadRequest", *, width: int) -> str:
    prefix = "" if request.method == "get" else f"{request.method.upper()} "
    parsed = urlparse(request.target)
    tail = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
    if not tail:
      tail = parsed.netloc if parsed.scheme else Path(request.target).name
    title = " ".join((request.title or "").split())
    left = title or tail
    label = f"{prefix}{left} | {request.target}" if left and left != request.target else f"{prefix}{request.target}"
    if _display_width(label) <= width:
      return label
    if width <= 3:
      return self._truncate_display_width(label, width)
    return f"{self._truncate_display_width(label, width - 3).rstrip()}..."

  def _truncate_display_width(self, text: str, width: int) -> str:
    if width <= 0:
      return ""
    truncated: list[str] = []
    current_width = 0
    for char in text:
      char_width = _display_width(char)
      if current_width + char_width > width:
        break
      truncated.append(char)
      current_width += char_width
    return "".join(truncated)


class SavePageInput(Input):
  BINDINGS = Input.BINDINGS + [
    Binding("ctrl+s", "save", "Save", show=False, priority=True),
    Binding("escape,ctrl+g", "cancel", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  async def action_submit(self) -> None:
    self._dismiss_with_value()

  def action_save(self) -> None:
    self._dismiss_with_value()

  def action_cancel(self) -> None:
    if isinstance(self.screen, SavePageScreen):
      self.screen.dismiss(None)

  def action_quit_app(self) -> None:
    self.app.action_quit()

  def _dismiss_with_value(self) -> None:
    if isinstance(self.screen, SavePageScreen):
      self.screen.dismiss(self.value)


class SavePageScreen(ModalScreen[str | None]):
  AUTO_FOCUS = "#save-page-input"
  CSS = """
  SavePageScreen {
    align: center middle;
  }

  #save-page-dialog {
    width: 80%;
    max-width: 100;
    height: auto;
    border: round $accent;
    background: $surface;
    padding: 1 2;
  }

  #save-page-title {
    text-style: bold;
    margin-bottom: 1;
  }

  #save-page-input {
    min-height: 3;
    max-height: 3;
  }

  #save-page-help {
    margin-top: 1;
    color: $text-muted;
  }
  """

  BINDINGS = [
    Binding("escape,ctrl+g", "cancel_save_page", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  def __init__(self, initial_value: str = "") -> None:
    super().__init__()
    self.initial_value = initial_value

  def compose(self) -> ComposeResult:
    with Vertical(id="save-page-dialog"):
      yield Label("Save visible page to", id="save-page-title")
      yield SavePageInput(
        self.initial_value,
        id="save-page-input",
      )
      yield Static("Enter: save  Esc/Ctrl-G: cancel  Ctrl-C: quit", id="save-page-help")

  def action_cancel_save_page(self) -> None:
    self.dismiss(None)

  def action_quit_app(self) -> None:
    self.app.action_quit()


class PasswordInput(Input):
  BINDINGS = Input.BINDINGS + [
    Binding("ctrl+s", "save", "Save", show=False, priority=True),
    Binding("escape,ctrl+g", "cancel", "Cancel", show=False, priority=True),
    Binding("ctrl+c", "quit_app", "Quit", show=False, priority=True),
  ]

  async def action_submit(self) -> None:
    self._dismiss_with_value()

  def action_save(self) -> None:
    self._dismiss_with_value()

  def action_cancel(self) -> None:
    if isinstance(self.screen, EditControlScreen):
      self.screen.dismiss(None)

  def action_quit_app(self) -> None:
    self.app.action_quit()

  def _dismiss_with_value(self) -> None:
    if isinstance(self.screen, EditControlScreen):
      self.screen.dismiss(self.value)


class ShortcutHelpScreen(ModalScreen[None]):
  CSS = """
  ShortcutHelpScreen {
    align: center middle;
  }

  #shortcuts-dialog {
    width: 80%;
    max-width: 84;
    height: auto;
    border: round $accent;
    background: $surface;
    padding: 1 2;
  }

  #shortcuts-title {
    text-style: bold;
    margin-bottom: 1;
  }

  #shortcuts-body {
    margin-bottom: 1;
  }

  #shortcuts-help {
    color: $text-muted;
  }
  """

  BINDINGS = [
    Binding("escape,question_mark", "close_help", "Close", show=False, priority=True),
  ]

  def compose(self) -> ComposeResult:
    with Vertical(id="shortcuts-dialog"):
      yield Label("Keyboard shortcuts", id="shortcuts-title")
      yield Static(
        "\n".join(
          [
            "Tab / Shift-Tab: next or previous link or control",
            "Enter: open link or activate control",
            "o: open URL or path",
            "h: show history",
            "c: copy visible page",
            "s: save visible page",
            "/: find in page",
            "b: back",
            "f: forward",
            "x: toggle normal or DOM view",
            "v: remove other panes or restore all panes",
            "Arrow keys / Ctrl-F / Ctrl-B / Ctrl-N / Ctrl-P: move cursor",
            "Shift-Arrow: move to next or previous block",
            "Ctrl-A / Ctrl-E: start or end of line",
            "Ctrl-L: redraw and center cursor line",
            "Ctrl-V / Alt-V: page down or page up",
            "Esc then <: start of document",
            "Esc then >: end of document",
            "Esc: cancel loading or start Esc prefix",
            "Ctrl-C: quit",
            "?: show this help",
          ]
        ),
        id="shortcuts-body",
      )
      yield Static("Esc or ? closes this dialog.", id="shortcuts-help")

  def action_close_help(self) -> None:
    self.dismiss(None)


class TwebBrowserApp(App[None]):
  CSS = """
  Screen {
    layout: vertical;
  }

  #content-pane {
    height: 1fr;
  }

  #content {
    width: 1fr;
    height: 1fr;
  }

  #content-title {
    padding: 0 1;
    background: $panel-darken-1;
    color: $text;
    text-style: bold;
  }

  #content-title.editing {
    background: $warning;
    color: $text;
    text-style: bold reverse;
  }

  #content-title.chrome-rendered {
    background: $success-darken-2;
    color: $text;
  }

  #status {
    height: 1;
    padding: 0 1;
    background: $panel;
  }
  """

  BINDINGS = [
    Binding("ctrl+c", "quit", "Quit"),
    Binding("question_mark", "show_shortcuts", "Help", show=False, priority=True),
    Binding("o", "open_location", "Open URL", priority=True),
    Binding("h", "show_history", "History", priority=True),
    Binding("c", "copy_page", "Copy Page", priority=True),
    Binding("s", "save_page", "Save Page", priority=True),
    Binding("slash", "search_page", "Search", show=False, priority=True),
    Binding("n", "search_next_match", "Next Match", show=False, priority=True),
    Binding("p", "search_previous_match", "Previous Match", show=False, priority=True),
    Binding("x", "toggle_dom_mode", "Toggle DOM", priority=True),
    Binding("v", "toggle_pane_visibility", "Toggle Pane", priority=True),
    Binding("r", "toggle_render_mode", "Toggle Render", priority=True),
    Binding("tab", "next_link", "Next Link", priority=True),
    Binding("shift+tab,backtab", "previous_link", "Previous Link", show=False, priority=True),
    Binding("enter", "open_link", "Open Link", priority=True),
    Binding("b", "back", "Back", priority=True),
    Binding("f", "forward", "Forward", priority=True),
    Binding("right,ctrl+f", "cursor_right", "Cursor Right", show=False, priority=True),
    Binding("left,ctrl+b", "cursor_left", "Backward", show=False, priority=True),
    Binding("down,ctrl+n", "cursor_down", "Next Line", show=False, priority=True),
    Binding("up,ctrl+p", "cursor_up", "Previous Line", show=False, priority=True),
    Binding("shift+right,shift+down", "next_block", "Next Block", show=False, priority=True),
    Binding("shift+left,shift+up", "previous_block", "Previous Block", show=False, priority=True),
    Binding("home,ctrl+a", "cursor_line_start", "Line Start", show=False, priority=True),
    Binding("end,ctrl+e", "cursor_line_end", "Line End", show=False, priority=True),
    Binding("ctrl+l", "redraw_center_cursor", "Redraw", show=False, priority=True),
    Binding("pagedown,ctrl+v", "page_down", "Page Down", show=False, priority=True),
    Binding("pageup,alt+v", "page_up", "Page Up", show=False, priority=True),
  ]

  def __init__(
    self,
    target: str,
    *,
    encoding: str | None = None,
    width: int = 80,
    scripts: list[str] | None = None,
    session: requests.Session | None = None,
    browser_render_policy: str = "never",
    button_click_policy: ButtonClickPolicy = "network",
    use_script_cache: bool = True,
    debug_block_colors: bool = False,
    history_path: Path | None = None,
  ) -> None:
    super().__init__()
    self.initial_target = target
    self.encoding = encoding
    self.viewport_columns = width
    self.pending_scripts = list(scripts or [])
    self.session = session or create_session()
    self.browser_render_policy = browser_render_policy
    self.button_click_policy = button_click_policy
    self.use_script_cache = use_script_cache
    self.debug_block_colors = debug_block_colors
    self.current_page: BrowserPage | None = None
    self.display_mode = "normal"
    self.history: list[LoadRequest] = []
    self.navigation_history: list[LoadRequest] = []
    self.navigation_index = -1
    self.history_path = history_path
    self.cursor_index = 0
    self.cursor_trailing_columns = 0
    self.viewport_line = 0
    self.loading_worker: Worker[LoadResult] | None = None
    self.view_render_worker: Worker[ViewRenderResult] | None = None
    self.background_render_worker: Worker[BackgroundRenderResult] | None = None
    self.loading_started_at: float | None = None
    self.view_render_started_at: float | None = None
    self.background_render_started_at: float | None = None
    self.active_loading_message: str | None = None
    self.pending_meta_prefix = False
    self.editing_control_id: str | None = None
    self.search_query = ""
    self.pane_focus_target_path: tuple[int, ...] | None = None

  def compose(self) -> ComposeResult:
    with Vertical(id="content-pane"):
      yield Label("", id="content-title")
      yield Static("", id="content", markup=False)
    yield Static("", id="status")

  def on_mount(self) -> None:
    self._sync_viewport_columns()
    self._load_persistent_history()
    self.set_interval(1.0, self._refresh_active_status)
    self._start_load_target(self.initial_target, push_history=True, scripts=self.pending_scripts)
    self.pending_scripts = []

  def on_resize(self, event: events.Resize) -> None:
    previous_width = self.viewport_columns
    self._sync_viewport_columns(event.size.width)
    if self.current_page is None or event.size.width == previous_width or self._is_loading():
      return
    self._start_current_page_rerender()

  def action_focus_next(self) -> None:
    self.action_next_link()

  def action_focus_previous(self) -> None:
    self.action_previous_link()

  def action_quit(self) -> None:
    self._sync_current_request_title()
    self._save_persistent_history()
    self.exit()

  def on_key(self, event: events.Key) -> None:
    if self._is_search_popup_open():
      if event.key == "enter":
        event.prevent_default()
        event.stop()
        self.screen._submit_search()
        return
      if event.key == "escape":
        event.prevent_default()
        event.stop()
        self.screen.action_cancel_search()
        return
      search_input = self.screen.query_one("#search-input", SearchTextArea)
      if self._handle_text_input_cursor_key(event, search_input):
        return
      return
    if self._is_open_location_popup_open():
      if event.key == "enter":
        event.prevent_default()
        event.stop()
        self.screen._submit_location()
        return
      if event.key == "escape":
        event.prevent_default()
        event.stop()
        self.screen.action_cancel_location()
        return
      location_input = self.screen.query_one("#open-location-input", OpenLocationTextArea)
      if self._handle_text_input_cursor_key(event, location_input):
        return
      return
    if self._is_history_popup_open():
      if event.key == "enter":
        event.prevent_default()
        event.stop()
        self.screen.action_submit_history()
        return
      if event.key == "escape":
        event.prevent_default()
        event.stop()
        self.screen.action_cancel_history()
        return
      if event.key in {"up", "ctrl+p"}:
        event.prevent_default()
        event.stop()
        self.screen.action_cursor_up()
        return
      if event.key in {"down", "ctrl+n"}:
        event.prevent_default()
        event.stop()
        self.screen.action_cursor_down()
        return
      return
    if self._is_save_page_popup_open():
      if event.key == "enter":
        event.prevent_default()
        event.stop()
        save_input = self.screen.query_one("#save-page-input", SavePageInput)
        self.screen.dismiss(save_input.value)
        return
      if event.key == "escape":
        event.prevent_default()
        event.stop()
        self.screen.dismiss(None)
        return
      return
    if self._is_edit_popup_open():
      return
    if self.pending_meta_prefix:
      if event.key in {"left_shift", "right_shift", "shift"}:
        event.prevent_default()
        event.stop()
        return
      self.pending_meta_prefix = False
      if event.key.lower() == "v" or event.character == "v":
        event.prevent_default()
        event.stop()
        self.action_page_up()
        return
      if event.key in {"<", ",", "comma", "shift+comma", "less_than_sign"} or event.character in {"<", ","}:
        event.prevent_default()
        event.stop()
        self.action_cursor_document_start()
        return
      if event.key in {">", ".", "full_stop", "period", "shift+period", "greater_than_sign"} or event.character in {">", "."}:
        event.prevent_default()
        event.stop()
        self.action_cursor_document_end()
        return
      self._set_status(f"Esc prefix key={event.key!r} char={event.character!r}")
      return

    if event.key in {"alt+v", "meta+v", "escape+v"} or event.character == "√":
      event.prevent_default()
      event.stop()
      self.action_page_up()
      return

    if event.key == "question_mark" or event.character == "?":
      event.prevent_default()
      event.stop()
      self.action_show_shortcuts()
      return

    if event.key == "tab":
      event.prevent_default()
      event.stop()
      self.action_next_link()
      return
    if event.key in {"shift+tab", "backtab"}:
      event.prevent_default()
      event.stop()
      self.action_previous_link()
      return
    if event.key == "escape":
      event.prevent_default()
      event.stop()
      if self._is_loading():
        self.action_cancel_loading()
      elif self._is_view_rerendering() or self._is_background_rendering():
        self.action_cancel_rendering()
      else:
        self.pending_meta_prefix = True
      return

  def on_paste(self, event: events.Paste) -> None:
    return

  def action_next_link(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.next_link_cursor(self.cursor_index))
    self._sync_cursor()

  def action_previous_link(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.next_link_cursor(self.cursor_index, reverse=True))
    self._sync_cursor()

  def action_open_link(self) -> None:
    if self._is_history_popup_open():
      self.screen.action_submit_history()
      return
    if self._is_search_popup_open():
      self.screen._submit_search()
      return
    if self._is_open_location_popup_open():
      self.screen._submit_location()
      return
    if self._is_save_page_popup_open():
      save_input = self.screen.query_one("#save-page-input", SavePageInput)
      self.screen.dismiss(save_input.value)
      return
    if self._is_edit_popup_open():
      edit_input = self.screen.query_one("#edit-input")
      if isinstance(edit_input, EditTextArea):
        edit_input.action_submit_or_newline()
      elif isinstance(edit_input, PasswordInput):
        self.screen.dismiss(edit_input.value)
      return
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading():
      return
    if self.editing_control_id is not None:
      self.editing_control_id = None
      self._update_content_title()
      self._sync_cursor()
      return
    control_span = self.current_page.buffer.control_at(self.cursor_index)
    if control_span is not None:
      self._activate_form_control(control_span.control_id)
      return
    link_span = self.current_page.buffer.link_at(self.cursor_index)
    if link_span is None:
      self._set_status(f"{self.current_page.resource.source} | cursor not on a link")
      return
    target = _resolve_target(self.current_page.resource.source, link_span.href)
    if self._navigate_same_document_fragment(target, push_history=True):
      return
    self._start_load_target(target, push_history=True)

  def action_open_location(self) -> None:
    LOGGER.debug(
      "open-location requested source=%s loading=%s editing=%s popup_open=%s",
      None if self.current_page is None else self.current_page.resource.source,
      self._is_loading(),
      self.editing_control_id is not None,
      self._is_open_location_popup_open(),
    )
    if self._is_loading() or self.editing_control_id is not None:
      return
    self._interrupt_background_render_for_interaction()
    if self._is_open_location_popup_open():
      return
    initial_value = self._open_location_initial_value()
    self.push_screen(OpenLocationScreen(initial_value))

  def action_save_page(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    if self._is_save_page_popup_open():
      return
    self.push_screen(SavePageScreen(self._default_save_path()), self._finish_save_page)

  def action_show_history(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    if self._is_history_popup_open():
      self.screen.dismiss(None)
      return
    self.push_screen(HistoryScreen(self.history, self._current_history_entry_index()), self._finish_history_selection)

  def action_copy_page(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    try:
      # Rendering normally stays plain in the TUI, but keep terminal styling
      # escapes out of the clipboard if a future rendering path adds them.
      clipboard_text = ANSI_ESCAPE_RE.sub("", self.current_page.rendered)
      subprocess.run(
        ["pbcopy"],
        input=clipboard_text,
        text=True,
        check=True,
      )
    except (OSError, subprocess.CalledProcessError) as error:
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | copy failed: {error}")
      return
    self._sync_cursor()
    self._set_status(f"{self.query_one('#status', Static).content} | copied to macOS clipboard")

  def action_toggle_dom_mode(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._clear_pane_focus()
    self.display_mode = "dom" if self.display_mode == "normal" else "normal"
    self._render_current_page()

  def action_toggle_pane_visibility(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    if self.pane_focus_target_path is not None:
      self._clear_pane_focus()
      self._rebuild_current_page_view()
      self._set_status(
        f"{self._status_base_message(*self.current_page.buffer.line_col(self.cursor_index))} | restored all panes"
      )
      return
    pane_target = self._current_pane_target()
    if pane_target is None:
      fallback_target_path = self._current_content_focus_target_path()
      if fallback_target_path is None:
        self._set_status(
          f"{self._status_base_message(*self.current_page.buffer.line_col(self.cursor_index))} | current block is not part of a multi-pane layout"
        )
        return
      self.pane_focus_target_path = fallback_target_path
    else:
      self.pane_focus_target_path = self._focused_pane_target_path(pane_target)
    self._rebuild_current_page_view()
    self._set_status(
      f"{self._status_base_message(*self.current_page.buffer.line_col(self.cursor_index))} | focused current pane"
    )

  def action_toggle_render_mode(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    if self.current_page.document.browser_rendered_via_chrome:
      self.browser_render_policy = "never"
    else:
      self.browser_render_policy = "always"
    renderer = "Chrome manual retry" if self.browser_render_policy == "always" else "QuickJS only"
    request = self._current_load_request()
    self._set_loading_status(f"Manual retry: reloading {request.target} in {renderer} mode...")
    self._start_load_target(request, push_history=False)

  def action_back(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self._is_loading() or self.editing_control_id is not None:
      return
    if self.navigation_index <= 0:
      self._set_status("No previous page")
      return
    self.navigation_index -= 1
    self._start_load_target(self.navigation_history[self.navigation_index], push_history=False)

  def action_forward(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self._is_loading() or self.editing_control_id is not None:
      return
    if self.navigation_index >= len(self.navigation_history) - 1:
      self._set_status("No next page")
      return
    self.navigation_index += 1
    self._start_load_target(self.navigation_history[self.navigation_index], push_history=False)

  def action_cancel_loading(self) -> None:
    if not self._is_loading() or self.loading_worker is None:
      return
    self.loading_worker.cancel()
    self._set_status("Loading cancelled")

  def action_cancel_rendering(self) -> None:
    if self._is_view_rerendering():
      self._cancel_view_rerender()
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | rendering cancelled")
      return
    if not self._is_background_rendering():
      return
    self._cancel_background_render(mark_partial_complete=True)
    self._sync_cursor()
    self._set_status(f"{self.query_one('#status', Static).content} | rendering cancelled")

  def action_cursor_right(self) -> None:
    if self._is_search_popup_open():
      self.screen.action_cursor_right()
      return
    if self._is_open_location_popup_open():
      self.screen.action_cursor_right()
      return
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    line_end = self.current_page.buffer.line_end(self.cursor_index)
    _, content_column = self.current_page.buffer.line_col(self.cursor_index)
    visual_column = content_column + self.cursor_trailing_columns
    if self.cursor_index == line_end and visual_column < self._max_cursor_column():
      self.cursor_trailing_columns += 1
      self._sync_cursor()
      return
    self._set_cursor_position(self.current_page.buffer.move_char(self.cursor_index, 1))
    self._sync_cursor()

  def action_cursor_left(self) -> None:
    if self._is_search_popup_open():
      self.screen.action_cursor_left()
      return
    if self._is_open_location_popup_open():
      self.screen.action_cursor_left()
      return
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    if self.cursor_trailing_columns > 0:
      self.cursor_trailing_columns -= 1
      self._sync_cursor()
      return
    self._set_cursor_position(self.current_page.buffer.move_char(self.cursor_index, -1))
    self._sync_cursor()

  def action_cursor_down(self) -> None:
    if self._is_search_popup_open():
      self.screen.action_cursor_down()
      return
    if self._is_open_location_popup_open():
      self.screen.action_cursor_down()
      return
    if self._is_history_popup_open():
      self.screen.action_cursor_down()
      return
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._move_cursor_to_line(1)
    self._sync_cursor()

  def action_cursor_up(self) -> None:
    if self._is_search_popup_open():
      self.screen.action_cursor_up()
      return
    if self._is_open_location_popup_open():
      self.screen.action_cursor_up()
      return
    if self._is_history_popup_open():
      self.screen.action_cursor_up()
      return
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._move_cursor_to_line(-1)
    self._sync_cursor()

  def action_next_block(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.move_block(self.cursor_index, 1))
    self._sync_cursor()

  def action_previous_block(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.move_block(self.cursor_index, -1))
    self._sync_cursor()

  def action_cursor_line_start(self) -> None:
    if self._is_search_popup_open():
      self.screen.action_cursor_line_start()
      return
    if self._is_open_location_popup_open():
      self.screen.action_cursor_line_start()
      return
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.line_start(self.cursor_index))
    self._sync_cursor()

  def action_cursor_line_end(self) -> None:
    if self._is_search_popup_open():
      self.screen.action_cursor_line_end()
      return
    if self._is_open_location_popup_open():
      self.screen.action_cursor_line_end()
      return
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.line_end(self.cursor_index))
    self._sync_cursor()

  def action_redraw_center_cursor(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._center_cursor_in_viewport()
    self.refresh(repaint=True, layout=True)
    self._sync_cursor()

  def action_cursor_document_start(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.first_cursor_index())
    self._sync_cursor()

  def action_cursor_document_end(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    self._set_cursor_position(self.current_page.buffer.last_cursor_index())
    self._sync_cursor()

  def action_page_down(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    current_line, _ = self.current_page.buffer.line_col(self.cursor_index)
    target_line = min(
      len(self.current_page.buffer.line_starts) - 1,
      current_line + self._viewport_height(),
    )
    self._jump_viewport_to_line(target_line)

  def action_page_up(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    current_line, _ = self.current_page.buffer.line_col(self.cursor_index)
    target_line = max(0, current_line - self._viewport_height())
    self._jump_viewport_to_line(target_line)

  def action_show_shortcuts(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self._is_edit_popup_open():
      return
    if self._is_shortcuts_popup_open():
      self.screen.dismiss(None)
      return
    self.push_screen(ShortcutHelpScreen())

  def action_search_page(self) -> None:
    self._interrupt_background_render_for_interaction()
    if self.current_page is None or self._is_loading() or self.editing_control_id is not None:
      return
    if self._is_open_location_popup_open():
      self.screen.query_one("#open-location-input", OpenLocationTextArea).insert("/")
      return
    if self._is_search_popup_open():
      return
    self.push_screen(SearchScreen(self.search_query))

  def action_search_next_match(self) -> None:
    self._interrupt_background_render_for_interaction()
    self._repeat_search(reverse=False)

  def action_search_previous_match(self) -> None:
    self._interrupt_background_render_for_interaction()
    self._repeat_search(reverse=True)

  def _build_page(
    self,
    request: LoadRequest,
    *,
    initial_block_budget: int | None = None,
    scripts: list[str] | None = None,
  ) -> BrowserPage:
    worker = get_current_worker()
    resource = fetch_resource(
      request.target,
      encoding=self.encoding,
      cancelled_event=worker.cancelled_event,
      on_status=self._notify_loading_status,
      session=self.session,
      method=request.method,
      form_data=list(request.form_data),
    )
    self._notify_loading_status(f"Parsing {resource.source}...")
    document = TWebDocument(parse_document(resource))
    if not request.skip_embedded_scripts:
      self._notify_loading_status(f"Running embedded scripts...")
      document.execute_embedded_scripts(
        ignore_errors=True,
        session=self.session,
        browser_render_policy=self.browser_render_policy,
        use_script_cache=self.use_script_cache,
      )
    if document.reloaded_resource is not None:
      resource = document.reloaded_resource
    pending_scripts = scripts or []
    for index, script in enumerate(pending_scripts, start=1):
      if worker.cancelled_event.is_set():
        raise FetchCancelled(f"cancelled fetch for {request.target}")
      self._notify_loading_status(f"Running script {index}/{len(pending_scripts)}...")
      document.execute_script(script, session=self.session)
    self._notify_loading_status(f"Rendering {resource.source}...")
    rendered, links, controls, link_metadata, control_metadata = self._render_document(
      document,
      max_blocks=initial_block_budget,
    )
    return self._build_browser_page(
      resource=resource,
      document=document,
      rendered=rendered,
      links=links,
      controls=controls,
      link_metadata=link_metadata,
      control_metadata=control_metadata,
      is_partial=initial_block_budget is not None and self.display_mode == "normal",
    )

  def _start_load_target(
    self,
    target: str | LoadRequest,
    *,
    push_history: bool,
    scripts: list[str] | None = None,
    method: str = "get",
    form_data: tuple[tuple[str, str], ...] | None = None,
  ) -> None:
    scripts = list(scripts or [])
    request = target if isinstance(target, LoadRequest) else LoadRequest(
      target=target,
      method=method,
      form_data=tuple(form_data or ()),
    )
    if self.loading_worker is not None and not self.loading_worker.is_finished:
      self.loading_worker.cancel()
    self._cancel_view_rerender()
    self._cancel_background_render(mark_partial_complete=False)
    self.loading_started_at = monotonic()
    self.active_loading_message = f"Connecting {request.target}..."
    self._set_loading_status(f"Connecting {request.target}...")
    initial_block_budget = self._initial_render_block_budget()
    if urlparse(request.target).fragment:
      initial_block_budget = None
    self.loading_worker = self.run_worker(
      lambda: LoadResult(
        request=request,
        push_navigation=push_history,
        page=self._build_page(
          request,
          initial_block_budget=initial_block_budget,
          scripts=scripts,
        ),
      ),
      name="load-page",
      group="navigation",
      description=request.target,
      exit_on_error=False,
      exclusive=True,
      thread=True,
    )

  def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
    if self.view_render_worker is not None and event.worker is self.view_render_worker:
      self._handle_view_render_state(event)
      return
    if self.background_render_worker is not None and event.worker is self.background_render_worker:
      self._handle_background_render_state(event)
      return
    if self.loading_worker is None or event.worker is not self.loading_worker:
      return
    if event.state == WorkerState.CANCELLED:
      self.loading_started_at = None
      self.active_loading_message = None
      self._set_status("Loading cancelled")
      self.loading_worker = None
      return
    if event.state == WorkerState.ERROR:
      error = event.worker.error
      if isinstance(error, FetchCancelled):
        self._set_status("Loading cancelled")
      else:
        self._set_status(f"Error: {error}")
      self.loading_started_at = None
      self.active_loading_message = None
      self.loading_worker = None
      return
    if event.state != WorkerState.SUCCESS:
      return
    result = event.worker.result
    self.loading_started_at = None
    self.active_loading_message = None
    self.loading_worker = None
    if result is None:
      return
    history_request = replace(
      result.request,
      title=self._history_title_for_document(result.page.document),
    )
    self._clear_pane_focus()
    self.current_page = result.page
    if urlparse(result.request.target).fragment:
      self.current_page.document.document.source = result.request.target
      self.current_page.resource.source = result.request.target
    track_visit_history = (
      history_request.target.strip()
      and (
        self.history_path is None
        or self._should_track_history_request(history_request)
      )
    )
    if result.push_navigation:
      self.navigation_history = self.navigation_history[: self.navigation_index + 1]
      self.navigation_history.append(history_request)
      self.navigation_index = len(self.navigation_history) - 1
    elif (
      0 <= self.navigation_index < len(self.navigation_history)
      and self.navigation_history[self.navigation_index] == history_request
    ):
      self.navigation_history[self.navigation_index] = history_request
    if track_visit_history:
      self.history = self._dedupe_history_requests(self.history, incoming=history_request)
      self.history.append(history_request)
      self._save_persistent_history()
    target_cursor = _fragment_cursor_for_target(result.page, result.request.target)
    if target_cursor is None:
      self._set_cursor_position(result.page.buffer.first_cursor_index())
      self.viewport_line = 0
    else:
      target_line, _target_column = result.page.buffer.line_col(target_cursor)
      self._set_cursor_position(target_cursor)
      self.viewport_line = target_line
    self._update_content_title()
    self._sync_cursor()
    if result.page.is_partial:
      self._start_background_render(result.page.document)

  def _handle_view_render_state(self, event: Worker.StateChanged) -> None:
    if self.view_render_worker is None or event.worker is not self.view_render_worker:
      return
    if event.state in {WorkerState.CANCELLED, WorkerState.ERROR}:
      self.view_render_started_at = None
      self.view_render_worker = None
      self._sync_cursor()
      return
    if event.state != WorkerState.SUCCESS:
      return
    result = event.worker.result
    self.view_render_started_at = None
    self.view_render_worker = None
    if result is None or self.current_page is None:
      return
    if self.current_page.document is not result.document:
      return
    if self.display_mode != result.display_mode:
      return
    if self.pane_focus_target_path != result.pane_focus_target_path:
      return
    self.current_page = result.page
    self._set_cursor_position(self._cursor_for_line_context(
      result.restore_context.line_snippet,
      result.restore_context.region_column,
      fallback_line=result.restore_context.fallback_line,
      fallback_column=result.restore_context.fallback_column,
    ))
    self._update_content_title()
    self._sync_cursor()
    if result.page.is_partial:
      self._start_background_render(result.page.document)

  def _handle_background_render_state(self, event: Worker.StateChanged) -> None:
    if self.background_render_worker is None or event.worker is not self.background_render_worker:
      return
    if event.state in {WorkerState.CANCELLED, WorkerState.ERROR}:
      self.background_render_started_at = None
      self.background_render_worker = None
      self._sync_cursor()
      return
    if event.state != WorkerState.SUCCESS:
      return
    result = event.worker.result
    self.background_render_started_at = None
    self.background_render_worker = None
    if result is None or self.current_page is None:
      return
    if self.current_page.document is not result.document:
      return
    self.current_page = self._build_browser_page(
      resource=self.current_page.resource,
      document=self.current_page.document,
      rendered=result.rendered,
      links=result.links,
      controls=result.controls,
      link_metadata=result.link_metadata,
      control_metadata=result.control_metadata,
      is_partial=False,
    )
    self._set_cursor_position(min(
      self.cursor_index,
      self.current_page.buffer.last_cursor_index(),
    ))
    self._sync_current_request_title()
    self._sync_cursor()

  def _start_background_render(self, document: TWebDocument) -> None:
    self._cancel_background_render(mark_partial_complete=False)
    self.background_render_worker = self.run_worker(
      lambda: self._build_background_render_result(document),
      name="render-page-background",
      group="render",
      description=document.title or document.document.source,
      exit_on_error=False,
      exclusive=True,
      thread=True,
    )
    self.background_render_started_at = monotonic()

  def _cancel_background_render(self, *, mark_partial_complete: bool = True) -> None:
    if self.background_render_worker is None or self.background_render_worker.is_finished:
      return
    self.background_render_worker.cancel()
    self.background_render_worker = None
    self.background_render_started_at = None
    if mark_partial_complete and self.current_page is not None and self.current_page.is_partial:
      self.current_page = replace(self.current_page, is_partial=False)

  def _build_background_render_result(
    self,
    document: TWebDocument,
  ) -> BackgroundRenderResult:
    worker = get_current_worker()
    rendered, links, controls, link_metadata, control_metadata = self._render_document(document)
    if worker.cancelled_event.is_set():
      raise FetchCancelled(f"cancelled background render for {document.document.source}")
    return BackgroundRenderResult(
      document=document,
      rendered=rendered,
      links=links,
      controls=controls,
      link_metadata=link_metadata,
      control_metadata=control_metadata,
    )

  def _start_current_page_rerender(self, *, control_id: str | None = None) -> None:
    if self.current_page is None:
      return
    restore_context = self._capture_cursor_restore_context()
    document = self.current_page.document
    resource = self.current_page.resource
    display_mode = self.display_mode
    pane_focus_target_path = self.pane_focus_target_path
    content_width = self._content_width()
    initial_block_budget = max(24, self._viewport_height() * 4) if display_mode == "normal" else None
    self._cancel_view_rerender()
    self._cancel_background_render(mark_partial_complete=False)
    self.view_render_started_at = monotonic()
    self._set_status(f"Rendering {resource.source}... Esc to cancel")
    self.view_render_worker = self.run_worker(
      lambda: self._build_view_render_result(
        document=document,
        resource=resource,
        restore_context=restore_context,
        display_mode=display_mode,
        pane_focus_target_path=pane_focus_target_path,
        content_width=content_width,
        initial_block_budget=initial_block_budget,
        control_id=control_id,
      ),
      name="render-page-view",
      group="render",
      description=document.title or document.document.source,
      exit_on_error=False,
      exclusive=True,
      thread=True,
    )

  def _cancel_view_rerender(self) -> None:
    if self.view_render_worker is None or self.view_render_worker.is_finished:
      return
    self.view_render_worker.cancel()
    self.view_render_worker = None
    self.view_render_started_at = None

  def _render_current_page(self) -> None:
    if self.current_page is None:
      return
    self._cancel_view_rerender()
    self._cancel_background_render(mark_partial_complete=False)
    rendered, links, controls, link_metadata, control_metadata = self._render_document(self.current_page.document)
    self.current_page = self._build_browser_page(
      resource=self.current_page.resource,
      document=self.current_page.document,
      rendered=rendered,
      links=links,
      controls=controls,
      link_metadata=link_metadata,
      control_metadata=control_metadata,
      is_partial=False,
    )
    self._set_cursor_position(
      self.current_page.buffer.first_cursor_index() if not self.current_page.buffer.visible_positions else min(
        self.cursor_index,
        self.current_page.buffer.visible_positions[-1],
      )
    )
    self._update_content_title()
    self._sync_cursor()

  def _sync_cursor(self) -> None:
    if self.current_page is None:
      return
    self._ensure_cursor_visible()
    self._render_viewport()
    self._set_status(self._compose_current_status_message())

  def _status_base_message(self, line_index: int, column: int) -> str:
    if self.current_page is None:
      return ""
    base = f"{self.current_page.resource.source} | line {line_index + 1} col {column + 1}"
    if self._is_view_rerendering():
      return f"{base} | rerendering... ({self._elapsed_label(self.view_render_started_at)})"
    if self.current_page.is_partial or (
      self.background_render_worker is not None and not self.background_render_worker.is_finished
    ):
      return f"{base} | rendering more... ({self._elapsed_label(self.background_render_started_at)})"
    return base

  def _compose_current_status_message(self) -> str:
    if self.current_page is None:
      return str(self.query_one("#status", Static).content)
    line_index, column = self._cursor_line_col()
    link_span = self.current_page.buffer.link_at(self.cursor_index)
    control_span = self.current_page.buffer.control_at(self.cursor_index)
    base = self._status_base_message(line_index, column)
    if self.editing_control_id is not None:
      return f'{base} | editing {self._editing_control_label()} value="{self._editing_control_value()}"'
    if link_span is not None:
      return f"{base} | {self._resolved_link_status_target(link_span.href)}"
    if control_span is not None:
      return f"{base} | {self._control_status_label(control_span)}"
    return base

  def _cursor_line_col(self) -> tuple[int, int]:
    if self.current_page is None:
      return (0, 0)
    line_index, column = self.current_page.buffer.line_col(self.cursor_index)
    return (line_index, column + self.cursor_trailing_columns)

  def _set_cursor_position(self, cursor_index: int, *, trailing_columns: int = 0) -> None:
    self.cursor_index = cursor_index
    self.cursor_trailing_columns = max(0, trailing_columns)

  def _max_cursor_column(self) -> int:
    return max(0, self._content_width() - 1)

  def _move_cursor_to_line(self, delta: int) -> None:
    if self.current_page is None:
      return
    buffer = self.current_page.buffer
    current_line, current_visual_column = self._cursor_line_col()
    target_visual_column = min(current_visual_column, self._max_cursor_column())
    current_region = _block_region_at(buffer, current_line, current_visual_column)
    target_line = max(0, min(len(buffer.line_starts) - 1, current_line + delta))
    if current_region is not None:
      next_position = _cursor_position_in_region_line(
        buffer,
        current_region,
        source_line=current_line,
        source_column=current_visual_column,
        target_line=target_line,
        max_column=self._max_cursor_column(),
      )
      if next_position is not None:
        next_index, trailing_columns = next_position
        self._set_cursor_position(next_index, trailing_columns=trailing_columns)
        return
    next_index = buffer.move_line(self.cursor_index, delta)
    self._set_cursor_position(next_index)
    line_end_column = buffer.line_col(buffer.line_end(self.cursor_index))[1]
    if self.cursor_index == buffer.line_end(self.cursor_index) and target_visual_column > line_end_column:
      self.cursor_trailing_columns = min(
        target_visual_column - line_end_column,
        self._max_cursor_column() - line_end_column,
      )

  def _ensure_cursor_visible(self) -> None:
    if self.current_page is None:
      return
    line_index, _ = self._cursor_line_col()
    viewport_height = self._viewport_height()
    if line_index < self.viewport_line:
      self.viewport_line = line_index
      return
    if line_index >= self.viewport_line + viewport_height:
      self.viewport_line = max(0, line_index - viewport_height + 1)

  def _center_cursor_in_viewport(self) -> None:
    if self.current_page is None:
      return
    line_index, _ = self._cursor_line_col()
    viewport_height = self._viewport_height()
    max_viewport_line = max(0, len(self.current_page.buffer.line_starts) - viewport_height)
    self.viewport_line = min(max(0, line_index - (viewport_height // 2)), max_viewport_line)

  def _set_status(self, message: str) -> None:
    self.query_one("#status", Static).update(message)

  def _set_loading_status(self, message: str) -> None:
    self.active_loading_message = message
    self._set_status(f"{message} ({self._elapsed_label(self.loading_started_at)}) Esc to cancel")

  def _set_active_loading_status(self, message: str) -> None:
    if not self._is_loading():
      return
    self._set_loading_status(message)

  def _notify_loading_status(self, message: str) -> None:
    self.call_from_thread(self._set_active_loading_status, message)

  def _elapsed_label(self, started_at: float | None) -> str:
    if started_at is None:
      return "0s"
    return f"{max(0, int(monotonic() - started_at))}s"

  def _refresh_active_status(self) -> None:
    if self._is_loading():
      if self.active_loading_message is not None:
        self._set_loading_status(self.active_loading_message)
      return
    if self.current_page is None:
      return
    if self._is_view_rerendering() or self._is_background_rendering():
      self._set_status(self._compose_current_status_message())

  def _update_content_title(self) -> None:
    title = self.query_one("#content-title", Label)
    if self.editing_control_id is not None:
      title.update(f"Editing: {self._editing_control_label()}")
      title.add_class("editing")
      title.remove_class("chrome-rendered")
      title.display = True
      return
    if self.current_page is None:
      title.update("Loading...")
      title.remove_class("editing")
      title.remove_class("chrome-rendered")
      title.display = True
      return
    self._sync_current_request_title()
    renderer = self._current_renderer_label()
    label = self.current_page.document.title or self.current_page.resource.source
    if self.display_mode == "dom":
      label = f"{label} (DOM)"
    title.update(Text(f"{label} [{renderer}]"))
    title.remove_class("editing")
    if self.current_page.document.browser_rendered_via_chrome:
      title.add_class("chrome-rendered")
    else:
      title.remove_class("chrome-rendered")
    title.display = True

  def _current_renderer_label(self) -> str:
    if self.current_page is None:
      return "QuickJS"
    if self.current_page.document.browser_rendered_via_chrome:
      if self.browser_render_policy == "always":
        return "Chrome manual retry"
      return "Chrome auto fallback"
    if self.browser_render_policy == "always":
      return "QuickJS (Chrome retry available)"
    return "QuickJS"

  def _render_document(
    self,
    document: TWebDocument,
    *,
    max_blocks: int | None = None,
    content_width: int | None = None,
    display_mode: str | None = None,
  ) -> tuple[str, list[Link], list[FormControl], tuple[RenderedLinkMetadata, ...], tuple[RenderedControlMetadata, ...]]:
    resolved_width = self._content_width() if content_width is None else max(content_width, 40)
    resolved_display_mode = self.display_mode if display_mode is None else display_mode
    if resolved_display_mode == "dom":
      return (
        render_dom(
          document.document,
          variant="summary",
          viewport_columns=max(resolved_width, 160),
          session=self.session,
        ),
        [],
        [],
        (),
        (),
      )
    result = render_normal_with_metadata(
      document.document,
      width=resolved_width,
      link_style="none",
      text_styles=False,
      max_blocks=max_blocks,
      session=self.session,
    )
    return (
      result.text,
      [
        Link(text=text, href=href)
        for text, href in visible_links_from_render_result(result)
      ],
      document.form_controls(),
      result.link_spans,
      result.control_spans,
    )

  def _is_loading(self) -> bool:
    return self.loading_worker is not None and not self.loading_worker.is_finished

  def _is_background_rendering(self) -> bool:
    return self.background_render_worker is not None and not self.background_render_worker.is_finished

  def _is_view_rerendering(self) -> bool:
    return self.view_render_worker is not None and not self.view_render_worker.is_finished

  def _interrupt_background_render_for_interaction(self) -> None:
    if self.current_page is None or not self._is_background_rendering():
      return
    self._cancel_background_render(mark_partial_complete=True)

  def _is_edit_popup_open(self) -> bool:
    return isinstance(self.screen, EditControlScreen)

  def _is_shortcuts_popup_open(self) -> bool:
    return isinstance(self.screen, ShortcutHelpScreen)

  def _is_search_popup_open(self) -> bool:
    return isinstance(self.screen, SearchScreen)

  def _is_open_location_popup_open(self) -> bool:
    return isinstance(self.screen, OpenLocationScreen)

  def _is_save_page_popup_open(self) -> bool:
    return isinstance(self.screen, SavePageScreen)

  def _is_history_popup_open(self) -> bool:
    return isinstance(self.screen, HistoryScreen)

  def _content_width(self) -> int:
    try:
      content_width = self.query_one("#content", Static).size.width
    except Exception:
      content_width = 0
    if content_width > 0:
      return max(content_width, 40)
    return max(self.viewport_columns - 2, 40)

  def _sync_viewport_columns(self, width: int | None = None) -> None:
    width = self.size.width if width is None else width
    if width > 0:
      self.viewport_columns = width

  def _initial_render_block_budget(self) -> int | None:
    if self.display_mode != "normal":
      return None
    return max(24, self._viewport_height() * 4)

  def _viewport_height(self) -> int:
    content = self.query_one("#content", Static)
    return max(1, content.size.height)

  def _render_viewport(self) -> None:
    if self.current_page is None:
      return
    content = self.query_one("#content", Static)
    cursor_line, cursor_column = self._cursor_line_col()
    content.update(
      _build_content_text(
        self.current_page.buffer,
        self.cursor_index,
        self.viewport_line,
        self._viewport_height(),
        self.editing_control_id,
        self.debug_block_colors,
        viewport_width=self._content_width(),
        cursor_line=cursor_line,
        cursor_column=cursor_column,
      )
    )

  def _jump_viewport_to_line(self, target_line: int) -> None:
    if self.current_page is None:
      return
    self.viewport_line = max(0, min(target_line, len(self.current_page.buffer.line_starts) - 1))
    line_start = self.current_page.buffer.line_starts[self.viewport_line]
    line_end = self.current_page.buffer.line_visible_ends[self.viewport_line]
    self._set_cursor_position(line_start if line_end > line_start else self.current_page.buffer.move_line(line_start, 1))
    self._render_viewport()
    line_index, column = self._cursor_line_col()
    link_span = self.current_page.buffer.link_at(self.cursor_index)
    control_span = self.current_page.buffer.control_at(self.cursor_index)
    base = f"{self.current_page.resource.source} | line {line_index + 1} col {column + 1}"
    if self.editing_control_id is not None:
      self._set_status(f'{base} | editing {self._editing_control_label()} value="{self._editing_control_value()}"')
      return
    if link_span is not None:
      self._set_status(f"{base} | {self._resolved_link_status_target(link_span.href)}")
      return
    if control_span is not None:
      self._set_status(f"{base} | {self._control_status_label(control_span)}")
      return
    self._set_status(base)

  def _activate_form_control(self, control_id: str) -> None:
    if self.current_page is None:
      return
    control = next((item for item in self.current_page.controls if item.control_id == control_id), None)
    if control is None:
      return
    if control.kind == "checkbox":
      if self.current_page.document.toggle_checkbox(control_id):
        self._rerender_after_control_change(control_id)
      return
    if control.kind == "radio":
      if self.current_page.document.select_radio_control(control_id):
        self._rerender_after_control_change(control_id)
      return
    if control.kind == "select":
      if self.current_page.document.cycle_select_control(control_id):
        self._rerender_after_control_change(control_id)
      return
    if is_text_entry_control(control):
      self.editing_control_id = control_id
      self._update_content_title()
      self._sync_cursor()
      self.push_screen(
        EditControlScreen(control),
        lambda value, control_id=control_id: self._finish_popup_edit(control_id, value),
      )
      return
    if is_submit_control(control):
      submission = self.current_page.document.submit_form_control(control_id, self.current_page.resource.source)
      if submission is None:
        self._set_status(f"{self.current_page.resource.source} | form submit unsupported")
        return
      if submission.method == "get":
        target = _resolve_target(self.current_page.resource.source, submission.url())
        self._start_load_target(target, push_history=True)
        return
      target = _resolve_target(self.current_page.resource.source, submission.action)
      self._start_load_target(
        target,
        push_history=True,
        method=submission.method,
        form_data=submission.params,
      )
      return
    if is_button_control(control):
      try:
        result = self.current_page.document.click_button_control(
          control_id,
          session=self.session,
          policy=self.button_click_policy,
        )
      except JavaScriptRuntimeError as error:
        self._set_status(f"{self.current_page.resource.source} | JavaScript error: {error}")
        return
      if not result.clicked and result.classification != "blocked_by_policy":
        self._set_status(f"{self.current_page.resource.source} | button click unsupported")
        return
      if result.navigation_target is not None and not result.blocked_by_policy:
        target = _resolve_target(self.current_page.resource.source, result.navigation_target)
        request = LoadRequest(
          target=target,
          skip_embedded_scripts=control.kind == "tab",
        )
        self._start_load_target(request, push_history=True)
        return
      if result.dom_changed or result.network_requests or result.navigation_target is not None:
        self._rerender_after_control_change(control_id)
      self._set_status(
        f"{self.current_page.resource.source} | {self._button_click_status_message(result)}"
      )
      return

  def _rerender_after_control_change(self, control_id: str) -> None:
    self._render_current_page()
    control_cursor = self.current_page.buffer.first_control_cursor(control_id) if self.current_page is not None else None
    if control_cursor is not None:
      self._set_cursor_position(control_cursor)
    self._sync_cursor()

  def _finish_popup_edit(self, control_id: str, value: str | None) -> None:
    if self.current_page is None:
      return
    control = next((item for item in self.current_page.controls if item.control_id == control_id), None)
    self.editing_control_id = None
    self._update_content_title()
    if value is None:
      self._set_status(f"{self.current_page.resource.source} | edit cancelled")
      self._sync_cursor()
      return
    if control is not None and control.kind == "text":
      value = " ".join(value.splitlines())
    if self.current_page.document.set_text_control(control_id, value):
      self._rerender_after_control_change(control_id)
      return
    self._sync_cursor()

  def _editing_control_label(self) -> str:
    if self.current_page is None or self.editing_control_id is None:
      return ""
    control = next((item for item in self.current_page.controls if item.control_id == self.editing_control_id), None)
    if control is None:
      return self.editing_control_id
    return control.label or control.name or control.control_id

  def _editing_control_value(self) -> str:
    if self.current_page is None or self.editing_control_id is None:
      return ""
    control = next((item for item in self.current_page.controls if item.control_id == self.editing_control_id), None)
    if control is None:
      return ""
    if control.input_type == "password" and control.value:
      return "*" * len(control.value)
    return control.value

  def _control_status_label(self, control_span: ControlSpan) -> str:
    if control_span.kind in {"checkbox", "radio"}:
      return f"toggle {control_span.label}"
    if control_span.kind == "select":
      return f"select {control_span.label}"
    if control_span.kind in {"text", "textarea"}:
      return f"edit {control_span.label}"
    if control_span.kind == "submit":
      return self._submit_status_label(control_span)
    if control_span.kind == "tab":
      return f"activate tab {control_span.label} (JS control, policy {self.button_click_policy})"
    if control_span.kind == "button":
      return f"click {control_span.label} (JS button, policy {self.button_click_policy})"
    return control_span.label

  def _submit_status_label(self, control_span: ControlSpan) -> str:
    if self.current_page is None:
      return f"submit {control_span.label}"
    submission = self.current_page.document.submit_form_control(
      control_span.control_id,
      self.current_page.resource.source,
    )
    if submission is None:
      return f"submit {control_span.label}"
    target = submission.url() if submission.method == "get" else submission.action
    return f"submit {control_span.label} -> {submission.method.upper()} {target} ({submission.enctype})"

  def _resolved_link_status_target(self, href: str) -> str:
    if self.current_page is None:
      return href
    return _resolve_target(self.current_page.resource.source, href)

  def _button_click_status_message(self, result: ButtonClickResult) -> str:
    if result.classification == "blocked_by_policy":
      return f"button click blocked by {result.policy} policy"
    if result.classification == "navigation_requested":
      suffix = f"button requested navigation to {result.navigation_target}"
      if result.blocked_by_policy:
        return f"{suffix} (blocked by {result.policy} policy)"
      return suffix
    if result.classification == "network_requested":
      request = result.network_requests[-1]
      suffix = f"button requested network {request.method} {request.url}"
      if request.blocked:
        if result.dom_changed:
          return f"button updated DOM; skipped network {request.method} {request.url} under {result.policy} policy"
        return f"{suffix} (not sent under {result.policy} policy)"
      if result.dom_changed:
        return f"{suffix} and updated DOM"
      return suffix
    if result.classification == "dom_updated":
      return "button updated DOM"
    if result.classification == "javascript_required":
      return "button click finished without visible DOM change"
    return "button click unsupported"

  def _finish_search(self, query: str | None) -> None:
    if self.current_page is None:
      return
    if query is None:
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | search cancelled")
      return
    normalized_query = " ".join(query.splitlines()).strip()
    self.search_query = normalized_query
    if not normalized_query:
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | search query is empty")
      return
    match = self._find_next_match(normalized_query)
    if match is None:
      self._sync_cursor()
      self._set_status(f'{self.query_one("#status", Static).content} | no match for "{normalized_query}"')
      return
    cursor_index, wrapped = match
    self._set_cursor_position(cursor_index)
    self._sync_cursor()
    if wrapped:
      self._set_status(f'{self.query_one("#status", Static).content} | wrapped search "{normalized_query}"')

  def _finish_open_location(self, value: str | None) -> None:
    if value is None:
      if self.current_page is not None:
        self._sync_cursor()
        self._set_status(f"{self.query_one('#status', Static).content} | open cancelled")
      return
    target = normalize_target(value)
    if not target.strip():
      if self.current_page is not None:
        self._sync_cursor()
        self._set_status(f"{self.query_one('#status', Static).content} | open target is empty")
      return
    if self._navigate_same_document_fragment(target, push_history=True):
      return
    self._start_load_target(target, push_history=True)

  def _navigate_same_document_fragment(self, target: str, *, push_history: bool) -> bool:
    if self.current_page is None:
      return False
    parsed_target = urlparse(target)
    fragment = parsed_target.fragment
    if not fragment:
      return False
    current_source = self.current_page.resource.source
    if _without_fragment(target) != _without_fragment(current_source):
      return False
    cursor_index = _fragment_cursor_for_target(self.current_page, target)
    if cursor_index is None:
      return False
    self.current_page.document.document.source = target
    self.current_page.resource.source = target
    history_request = LoadRequest(
      target=target,
      title=self._history_title_for_document(self.current_page.document),
    )
    track_visit_history = (
      history_request.target.strip()
      and (
        self.history_path is None
        or self._should_track_history_request(history_request)
      )
    )
    if push_history:
      self.navigation_history = self.navigation_history[: self.navigation_index + 1]
      self.navigation_history.append(history_request)
      self.navigation_index = len(self.navigation_history) - 1
    elif (
      0 <= self.navigation_index < len(self.navigation_history)
      and self.navigation_history[self.navigation_index] == history_request
    ):
      self.navigation_history[self.navigation_index] = history_request
    if track_visit_history:
      self.history = self._dedupe_history_requests(self.history, incoming=history_request)
      self.history.append(history_request)
      self._save_persistent_history()
    target_line, _target_column = self.current_page.buffer.line_col(cursor_index)
    self._set_cursor_position(cursor_index)
    self.viewport_line = target_line
    self._sync_cursor()
    return True

  def _finish_history_selection(self, index: int | None) -> None:
    if self.current_page is None:
      return
    if index is None:
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | history cancelled")
      return
    if not (0 <= index < len(self.history)):
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | history selection out of range")
      return
    if index == self._current_history_entry_index():
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | already on selected history entry")
      return
    self._start_load_target(self.history[index], push_history=True)

  def _open_location_initial_value(self) -> str:
    if self.current_page is not None and self._is_welcome_page_source(self.current_page.resource.source):
      return ""
    if self.current_page is not None:
      return self.current_page.resource.source
    if self._is_welcome_page_source(self.initial_target):
      return ""
    return self.initial_target

  def _is_welcome_page_source(self, source: str) -> bool:
    return self._resolved_local_history_target(source) == Path(WELCOME_PAGE_TARGET)

  def _finish_save_page(self, value: str | None) -> None:
    if self.current_page is None:
      return
    if value is None:
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | save cancelled")
      return
    target_text = value.strip()
    if not target_text:
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | save path is empty")
      return
    target = Path(target_text).expanduser()
    # Keep saved text as portable as copied text when a rendering path has
    # terminal styling enabled.
    content = ANSI_ESCAPE_RE.sub("", self.current_page.rendered)
    if content and not content.endswith("\n"):
      content = f"{content}\n"
    try:
      target.write_text(content, encoding="utf-8")
    except OSError as error:
      self._sync_cursor()
      self._set_status(f"{self.query_one('#status', Static).content} | save failed: {error}")
      return
    self._sync_cursor()
    self._set_status(f"{self.query_one('#status', Static).content} | saved to {target}")

  def _default_save_path(self) -> str:
    if self.current_page is None:
      return "page.txt"
    source = self.current_page.resource.source
    parsed = urlparse(source)
    label = self.current_page.document.title
    if not label:
      if parsed.scheme in {"http", "https"}:
        label = Path(parsed.path).stem or parsed.netloc
      else:
        label = Path(source).stem or Path(source).name
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", label or "page").strip(".-")
    if not slug:
      slug = "page"
    suffixes: list[str] = []
    if self.display_mode == "dom":
      suffixes.append("dom")
    if self.pane_focus_target_path is not None:
      suffixes.append("pane")
    if suffixes:
      slug = f"{slug}-{'-'.join(suffixes)}"
    return f"{slug}.txt"

  def _current_load_request(self) -> LoadRequest:
    if 0 <= self.navigation_index < len(self.navigation_history):
      return self.navigation_history[self.navigation_index]
    if self.current_page is not None:
      return LoadRequest(target=self.current_page.resource.source)
    return LoadRequest(target=self.initial_target)

  def _current_history_entry_index(self) -> int | None:
    if self.current_page is None:
      return None
    current_target = self.current_page.resource.source
    for index in range(len(self.history) - 1, -1, -1):
      if self.history[index].target == current_target:
        return index
    return None

  def _sync_current_request_title(self) -> None:
    if self.current_page is None:
      return
    current_target = self.current_page.resource.source
    title = self._history_title_for_document(self.current_page.document)
    history_index = self._current_history_entry_index()
    if history_index is not None:
      request = self.history[history_index]
      if request.title != title:
        self.history[history_index] = replace(request, title=title)
    if 0 <= self.navigation_index < len(self.navigation_history):
      request = self.navigation_history[self.navigation_index]
      if request.target == current_target and request.title != title:
        self.navigation_history[self.navigation_index] = replace(request, title=title)

  def _load_persistent_history(self) -> None:
    if self.history_path is None:
      return
    requests = self._read_persistent_history_requests()
    if not requests:
      return
    self.history = self._dedupe_history_requests(
      [
        request
        for request in requests
        if self._should_track_history_request(request)
      ]
    )

  def _save_persistent_history(self) -> None:
    if self.history_path is None:
      return
    current_requests = [
      request
      for request in self.history
      if request.target.strip() and self._should_track_history_request(request)
    ]
    try:
      self.history_path.parent.mkdir(parents=True, exist_ok=True)
      persisted_requests = [
        request
        for request in self._read_persistent_history_requests()
        if self._should_track_history_request(request)
      ]
      merged_requests = [
        *persisted_requests,
        *current_requests,
      ]
      merged_entries = [
        self._serialize_persistent_history_request(request)
        for request in self._dedupe_history_requests(merged_requests)
      ]
      content = "".join(f"{entry}\n" for entry in merged_entries)
      temp_path: Path | None = None
      try:
        with tempfile.NamedTemporaryFile(
          "w",
          encoding="utf-8",
          dir=self.history_path.parent,
          delete=False,
        ) as temp_file:
          temp_file.write(content)
          temp_path = Path(temp_file.name)
        temp_path.replace(self.history_path)
      finally:
        if temp_path is not None and temp_path.exists():
          temp_path.unlink()
    except OSError:
      return

  def _read_persistent_history_requests(self) -> list[LoadRequest]:
    if self.history_path is None:
      return []
    try:
      return [
        self._deserialize_persistent_history_entry(line)
        for line in self.history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
      ]
    except FileNotFoundError:
      return []
    except OSError:
      return []

  def _deserialize_persistent_history_entry(self, entry: str) -> LoadRequest:
    stripped = entry.strip()
    if not stripped:
      return LoadRequest(target="")
    if stripped.startswith("{"):
      try:
        payload = json.loads(stripped)
      except json.JSONDecodeError:
        return LoadRequest(target=stripped)
      if isinstance(payload, dict):
        target = str(payload.get("target") or "").strip()
        title = payload.get("title")
        normalized_title = " ".join(str(title).split()) if isinstance(title, str) and title.strip() else None
        if target:
          return LoadRequest(target=target, title=normalized_title)
    return LoadRequest(target=stripped)

  def _serialize_persistent_history_request(self, request: LoadRequest) -> str:
    payload = {"target": request.target}
    if request.title:
      payload["title"] = request.title
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

  def _history_title_for_document(self, document: TWebDocument) -> str | None:
    title = " ".join(document.title.split())
    return title or None

  def _should_track_history_request(self, request: LoadRequest) -> bool:
    local_target = self._resolved_local_history_target(request.target)
    if local_target is None:
      return True
    return str(local_target) not in BUILTIN_HISTORY_EXCLUDED_TARGETS

  def _resolved_local_history_target(self, target: str) -> Path | None:
    parsed = urlparse(target)
    if parsed.scheme:
      return None
    try:
      return Path(target).expanduser().resolve()
    except OSError:
      return None

  def _dedupe_history_requests(
    self,
    requests: list[LoadRequest],
    *,
    incoming: LoadRequest | None = None,
  ) -> list[LoadRequest]:
    duplicate_target = incoming.target if incoming is not None else None
    deduped: list[LoadRequest] = []
    seen_targets: set[str] = set()
    for request in reversed(requests):
      if duplicate_target is not None:
        if request.target == duplicate_target:
          continue
      elif request.target in seen_targets:
        continue
      seen_targets.add(request.target)
      deduped.append(request)
    deduped.reverse()
    return deduped

  def _handle_text_input_cursor_key(self, event: events.Key, text_input: TextArea) -> bool:
    action_name = {
      "right": "action_cursor_right",
      "ctrl+f": "action_cursor_right",
      "left": "action_cursor_left",
      "ctrl+b": "action_cursor_left",
      "up": "action_cursor_up",
      "ctrl+p": "action_cursor_up",
      "down": "action_cursor_down",
      "ctrl+n": "action_cursor_down",
      "home": "action_cursor_line_start",
      "ctrl+a": "action_cursor_line_start",
      "end": "action_cursor_line_end",
      "ctrl+e": "action_cursor_line_end",
    }.get(event.key)
    if action_name is None:
      return False
    event.prevent_default()
    event.stop()
    getattr(text_input, action_name)()
    return True

  def _find_next_match(self, query: str) -> tuple[int, bool] | None:
    return self._find_match(query, reverse=False)

  def _find_previous_match(self, query: str) -> tuple[int, bool] | None:
    return self._find_match(query, reverse=True)

  def _repeat_search(self, *, reverse: bool) -> None:
    if (
      self.current_page is None
      or self._is_loading()
      or self.editing_control_id is not None
      or not self.search_query
    ):
      return
    match = self._find_previous_match(self.search_query) if reverse else self._find_next_match(self.search_query)
    if match is None:
      self._sync_cursor()
      self._set_status(f'{self.query_one("#status", Static).content} | no match for "{self.search_query}"')
      return
    cursor_index, wrapped = match
    self._set_cursor_position(cursor_index)
    self._sync_cursor()
    if wrapped:
      self._set_status(f'{self.query_one("#status", Static).content} | wrapped search "{self.search_query}"')

  def _find_match(self, query: str, *, reverse: bool) -> tuple[int, bool] | None:
    if self.current_page is None:
      return None
    rendered = self.current_page.buffer.text.casefold()
    target = query.casefold()
    if not target:
      return None
    wrapped = False
    if reverse:
      search_end = max(0, min(len(rendered), self.cursor_index))
      found_at = rendered.rfind(target, 0, search_end)
      if found_at == -1 and search_end < len(rendered):
        found_at = rendered.rfind(target)
        wrapped = found_at != -1
    else:
      search_start = min(len(rendered), self.cursor_index + 1)
      found_at = rendered.find(target, search_start)
      if found_at == -1 and search_start > 0:
        found_at = rendered.find(target)
        wrapped = found_at != -1
    if found_at == -1:
      return None
    cursor_index = self._match_cursor_index(found_at, found_at + len(target))
    return (cursor_index, wrapped)

  def _match_cursor_index(self, start: int, end: int) -> int:
    if self.current_page is None:
      return 0
    for position in self.current_page.buffer.visible_positions:
      if start <= position < end:
        return position
    for position in self.current_page.buffer.visible_positions:
      if position >= start:
        return position
    return self.current_page.buffer.last_cursor_index()

  def _build_browser_page(
    self,
    *,
    resource: Resource,
    document: TWebDocument,
    rendered: str,
    links: list[Link],
    controls: list[FormControl],
    is_partial: bool,
    link_metadata: tuple[RenderedLinkMetadata, ...] = (),
    control_metadata: tuple[RenderedControlMetadata, ...] = (),
    content_width: int | None = None,
    pane_focus_target_path: tuple[int, ...] | None = None,
  ) -> BrowserPage:
    resolved_width = self._content_width() if content_width is None else max(content_width, 40)
    resolved_pane_focus_target_path = self.pane_focus_target_path if pane_focus_target_path is None else pane_focus_target_path
    interactive_keys = _interactive_order_keys(document, links, controls)
    source_link_metadata = link_metadata
    source_control_metadata = control_metadata
    source_buffer = _build_render_buffer(
      rendered,
      links,
      controls,
      interactive_keys,
      link_metadata=source_link_metadata,
      control_metadata=source_control_metadata,
    )
    source_pane_groups = collect_two_pane_targets(
      document.document,
      width=resolved_width,
      session=self.session,
    )
    display_rendered = rendered
    display_links = links
    display_link_metadata = source_link_metadata
    display_control_metadata = source_control_metadata
    if resolved_pane_focus_target_path is not None:
      pane_node = _element_node_at_path(
        document.document.body or document.document.root,
        resolved_pane_focus_target_path,
      )
      if pane_node is not None:
        subtree_result = render_normal_subtree_with_metadata(
          document.document,
          pane_node,
          width=resolved_width,
          link_style="none",
          text_styles=False,
          include_title=False,
          session=self.session,
        )
        display_rendered = subtree_result.text
        display_links = [
          Link(text=text, href=href)
          for text, href in visible_links_from_render_result(subtree_result)
        ]
        display_link_metadata = subtree_result.link_spans
        display_control_metadata = subtree_result.control_spans
    # Initial full-page rendering is the common path.  Its display buffer is
    # exactly the source buffer, so avoid rebuilding every position/span map.
    # Keep a distinct buffer only when focusing a pane changes the rendered
    # text and metadata.
    buffer = source_buffer
    if resolved_pane_focus_target_path is not None:
      buffer = _build_render_buffer(
        display_rendered,
        display_links,
        controls,
        interactive_keys,
        link_metadata=display_link_metadata,
        control_metadata=display_control_metadata,
      )
    if source_pane_groups and resolved_pane_focus_target_path is None:
      buffer = _merge_regions_by_pane_target(
        document.document,
        buffer,
        list(source_pane_groups),
        width=resolved_width,
        session=self.session,
      )
    if resolved_pane_focus_target_path is not None:
      buffer = _replace_buffer_block_regions(
        buffer,
        [_build_single_content_block_region(display_rendered, buffer.line_starts, buffer.line_visible_ends)],
      )
    return BrowserPage(
      resource=resource,
      document=document,
      rendered=display_rendered,
      links=display_links,
      controls=controls,
      buffer=buffer,
      is_partial=is_partial,
      source_rendered=rendered,
      source_links=links,
      source_link_metadata=source_link_metadata,
      source_control_metadata=source_control_metadata,
      source_buffer=source_buffer,
      source_pane_groups=source_pane_groups,
    )

  def _capture_cursor_restore_context(self) -> CursorRestoreContext:
    if self.current_page is None:
      return CursorRestoreContext("", 0, 0, 0)
    previous_line, previous_column = self.current_page.buffer.line_col(self.cursor_index)
    line_snippet, region_column = _current_region_line_context(
      self.current_page.buffer,
      previous_line,
      previous_column,
    )
    return CursorRestoreContext(
      line_snippet=line_snippet,
      region_column=region_column,
      fallback_line=previous_line,
      fallback_column=previous_column,
    )

  def _build_view_render_result(
    self,
    *,
    document: TWebDocument,
    resource: Resource,
    restore_context: CursorRestoreContext,
    display_mode: str,
    pane_focus_target_path: tuple[int, ...] | None,
    content_width: int,
    initial_block_budget: int | None,
    control_id: str | None,
  ) -> ViewRenderResult:
    rendered, links, controls, link_metadata, control_metadata = self._render_document(
      document,
      max_blocks=initial_block_budget,
      content_width=content_width,
      display_mode=display_mode,
    )
    page = self._build_browser_page(
      resource=resource,
      document=document,
      rendered=rendered,
      links=links,
      controls=controls,
      link_metadata=link_metadata,
      control_metadata=control_metadata,
      is_partial=initial_block_budget is not None and display_mode == "normal",
      content_width=content_width,
      pane_focus_target_path=pane_focus_target_path,
    )
    if control_id is not None:
      control_cursor = page.buffer.first_control_cursor(control_id)
      if control_cursor is not None:
        fallback_line, fallback_column = page.buffer.line_col(control_cursor)
        restore_context = CursorRestoreContext(
          line_snippet="",
          region_column=0,
          fallback_line=fallback_line,
          fallback_column=fallback_column,
        )
    return ViewRenderResult(
      document=document,
      page=page,
      restore_context=restore_context,
      display_mode=display_mode,
      pane_focus_target_path=pane_focus_target_path,
      content_width=content_width,
    )

  def _rebuild_current_page_view(self) -> None:
    if self.current_page is None:
      return
    previous_line, previous_column = self.current_page.buffer.line_col(self.cursor_index)
    line_snippet, region_column = _current_region_line_context(
      self.current_page.buffer,
      previous_line,
      previous_column,
    )
    rendered = self.current_page.source_rendered or self.current_page.rendered
    self.current_page = self._build_browser_page(
      resource=self.current_page.resource,
      document=self.current_page.document,
      rendered=rendered,
      links=self.current_page.source_links or self.current_page.links,
      controls=self.current_page.controls,
      link_metadata=self.current_page.source_link_metadata,
      control_metadata=self.current_page.source_control_metadata,
      is_partial=self.current_page.is_partial,
    )
    self._set_cursor_position(self._cursor_for_line_context(
      line_snippet,
      region_column,
      fallback_line=previous_line,
      fallback_column=previous_column,
    ))
    LOGGER.debug(
      "pane view rebuilt target_path=%s snippet=%r region_column=%d cursor_line_col=%s rendered_lines=%d",
      self.pane_focus_target_path,
      line_snippet,
      region_column,
      self.current_page.buffer.line_col(self.cursor_index),
      len(self.current_page.rendered.splitlines()),
    )
    self._update_content_title()
    self._sync_cursor()

  def _clear_pane_focus(self) -> None:
    self.pane_focus_target_path = None

  def _cursor_for_line_col(self, line_index: int, column: int) -> int:
    if self.current_page is None or not self.current_page.buffer.visible_positions:
      return 0
    target_line = max(0, min(line_index, len(self.current_page.buffer.line_starts) - 1))
    while target_line < len(self.current_page.buffer.line_starts):
      start, end = self.current_page.buffer._line_visible_bounds(target_line)
      if end > start:
        return min(start + column, end - 1)
      target_line += 1
    return self.current_page.buffer.last_cursor_index()

  def _cursor_for_line_context(
    self,
    line_snippet: str,
    column: int,
    *,
    fallback_line: int,
    fallback_column: int,
  ) -> int:
    if self.current_page is None or not self.current_page.buffer.visible_positions:
      return 0
    normalized_snippet = _normalize_pane_match_text(line_snippet)
    if not normalized_snippet:
      return self._cursor_for_line_col(fallback_line, fallback_column)
    candidates: list[tuple[int, int]] = []
    for line_index, raw_line in enumerate(self.current_page.buffer.text.splitlines()):
      match_column = raw_line.find(line_snippet)
      if match_column != -1:
        candidates.append((abs(line_index - fallback_line), self.current_page.buffer.line_starts[line_index] + match_column))
        continue
      normalized_line = _normalize_pane_match_text(raw_line)
      if normalized_snippet not in normalized_line:
        continue
      candidates.append((abs(line_index - fallback_line), self.current_page.buffer.line_starts[line_index]))
    if not candidates:
      return self._cursor_for_line_col(fallback_line, fallback_column)
    _, line_start = min(candidates, key=lambda item: item[0])
    target = line_start + column
    line_index, _ = self.current_page.buffer.line_col(min(target, self.current_page.buffer.last_cursor_index()))
    start, end = self.current_page.buffer._line_visible_bounds(line_index)
    if end <= start:
      return self._cursor_for_line_col(fallback_line, fallback_column)
    return min(target, end - 1)

  def _current_pane_target(self) -> PaneTarget | None:
    if self.current_page is None:
      return None
    source_buffer = self.current_page.source_buffer or self.current_page.buffer
    pane_groups = self.current_page.source_pane_groups or []
    line_index, column = source_buffer.line_col(self.cursor_index)
    line_snippet = _current_region_line_snippet(source_buffer, line_index, column)
    if line_snippet:
      matched_target = self._pane_target_for_line_snippet(line_snippet)
      if matched_target is not None:
        return matched_target
    multi_region_groups: list[list[BlockRegion]] = []
    current_group: list[BlockRegion] = []
    current_key: tuple[int, int] | None = None
    for region in source_buffer.block_regions:
      group_key = _block_region_group_key(region)
      if group_key != current_key:
        if len(current_group) > 1:
          multi_region_groups.append(current_group)
        current_group = [region]
        current_key = group_key
      else:
        current_group.append(region)
    if len(current_group) > 1:
      multi_region_groups.append(current_group)
    for group_index, regions in enumerate(multi_region_groups):
      if group_index >= len(pane_groups):
        break
      for pane_index, region in enumerate(regions):
        if pane_index >= len(pane_groups[group_index]):
          break
        if not region.contains(line_index, column):
          continue
        return pane_groups[group_index][pane_index]
    return None

  def _pane_target_for_line_snippet(self, line_snippet: str) -> PaneTarget | None:
    if self.current_page is None:
      return None
    document = self.current_page.document
    root = document.document.body or document.document.root
    if root is None:
      return None
    normalized_snippet = _normalize_pane_match_text(line_snippet)
    if not normalized_snippet:
      return None
    matching_targets: list[PaneTarget] = []
    for pane_group in self.current_page.source_pane_groups or []:
      for pane_target in pane_group:
        pane_node = _element_node_at_path(root, pane_target.path)
        if pane_node is None:
          continue
        rendered = render_normal_subtree(
          document.document,
          pane_node,
          width=self._content_width(),
          link_style="none",
          text_styles=False,
          include_title=False,
          session=self.session,
        )
        if normalized_snippet not in _normalize_pane_match_text(rendered):
          continue
        matching_targets.append(pane_target)
    if len(matching_targets) == 1:
      return matching_targets[0]
    return None

  def _focused_pane_target_path(self, pane_target: PaneTarget) -> tuple[int, ...]:
    if self.current_page is None:
      return pane_target.path
    source_buffer = self.current_page.source_buffer or self.current_page.buffer
    line_index, column = source_buffer.line_col(self.cursor_index)
    line_snippet = _current_region_line_snippet(source_buffer, line_index, column)
    if not line_snippet:
      return pane_target.path
    document = self.current_page.document
    root = document.document.body or document.document.root
    if root is None:
      return pane_target.path
    pane_node = _element_node_at_path(root, pane_target.path)
    if pane_node is None:
      return pane_target.path
    deepest_match = _deepest_matching_descendant_path(
      document.document,
      pane_node,
      pane_target.path,
      line_snippet,
      width=self._content_width(),
      session=self.session,
    )
    if deepest_match is None:
      return pane_target.path
    promoted_path = _promote_heading_match_path(
      document.document,
      root,
      deepest_match,
      line_snippet,
      width=self._content_width(),
      session=self.session,
    )
    return _promote_leading_metadata_match_path(
      document.document,
      root,
      promoted_path,
      line_snippet,
      minimum_path=pane_target.path,
      width=self._content_width(),
      session=self.session,
    )

  def _current_content_focus_target_path(self) -> tuple[int, ...] | None:
    if self.current_page is None:
      return None
    source_buffer = self.current_page.source_buffer or self.current_page.buffer
    line_index, column = source_buffer.line_col(self.cursor_index)
    line_snippet = _current_region_line_snippet(source_buffer, line_index, column)
    if not line_snippet:
      return None
    document = self.current_page.document
    root = document.document.body or document.document.root
    if root is None:
      return None
    deepest_match = _deepest_matching_descendant_path(
      document.document,
      root,
      (),
      line_snippet,
      width=self._content_width(),
      session=self.session,
    )
    if deepest_match is None or not deepest_match:
      return None
    promoted_path = _promote_heading_match_path(
      document.document,
      root,
      deepest_match,
      line_snippet,
      width=self._content_width(),
      session=self.session,
    )
    if not promoted_path:
      return None
    if not _path_has_textual_sibling_context(
      document.document,
      root,
      promoted_path,
      width=self._content_width(),
      session=self.session,
    ):
      return None
    return promoted_path


def run_tui_browser(
  target: str,
  *,
  encoding: str | None = None,
  width: int | None = None,
  scripts: list[str] | None = None,
  session: requests.Session | None = None,
  browser_render_policy: str = "never",
  button_click_policy: ButtonClickPolicy = "network",
  use_script_cache: bool = True,
  debug_block_colors: bool = False,
) -> int:
  app = TwebBrowserApp(
    target,
    encoding=encoding,
    width=_resolve_width(width),
    scripts=scripts,
    session=session,
    browser_render_policy=browser_render_policy,
    button_click_policy=button_click_policy,
    use_script_cache=use_script_cache,
    debug_block_colors=debug_block_colors,
    history_path=DEFAULT_HISTORY_PATH,
  )
  try:
    app.run()
    return 0
  except KeyboardInterrupt:
    app.action_quit()
    return 130
  finally:
    app.session.close()


def _resolve_width(width: int | None) -> int:
  if width is not None:
    return width
  return shutil.get_terminal_size(fallback=(80, 24)).columns


def _resolve_target(current_source: str, href: str) -> str:
  parsed = urlparse(href)
  if parsed.scheme in {"http", "https"}:
    return href
  if current_source.startswith(("http://", "https://")):
    return urljoin(current_source, href)
  current_path = Path(current_source).resolve()
  if href.startswith("/"):
    return str(Path(href))
  return str((current_path.parent / href).resolve())


def _without_fragment(target: str) -> str:
  parsed = urlparse(target)
  return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def _fragment_cursor_for_target(page: BrowserPage, target: str) -> int | None:
  fragment = urlparse(target).fragment
  if not fragment:
    return None
  element = page.document.find(attrs={"id": fragment})
  if element is None:
    return None
  return _cursor_index_for_fragment_target(page.buffer, element.node)


def _cursor_index_for_fragment_target(buffer: RenderedBuffer, node: ElementNode) -> int | None:
  for snippet in _fragment_target_snippets(node):
    exact_match = buffer.text.find(snippet)
    if exact_match >= 0 and exact_match in buffer.visible_position_indexes:
      return exact_match
    normalized_snippet = _normalize_fragment_snippet(snippet)
    if not normalized_snippet:
      continue
    for line_index, line_start in enumerate(buffer.line_starts):
      line_end = buffer.line_visible_ends[line_index]
      line_text = buffer.text[line_start:line_end]
      if normalized_snippet in _normalize_fragment_snippet(line_text):
        return line_start
  return None


def _fragment_target_snippets(node: ElementNode) -> tuple[str, ...]:
  snippets: list[str] = []
  current: ElementNode | None = node
  while current is not None:
    text = " ".join(current.text_content().split()).strip()
    if text and text not in snippets:
      snippets.append(text)
    current = getattr(current, "_tweb_parent", None)
  return tuple(snippets)


def _normalize_fragment_snippet(text: str) -> str:
  return " ".join(text.split()).strip()


def _block_region_group_key(region: BlockRegion) -> tuple[int, int]:
  return (region.start_line, region.end_line)


def _block_region_at(buffer: RenderedBuffer, line_index: int, column: int) -> BlockRegion | None:
  for region in buffer.block_regions:
    if region.contains(line_index, column):
      return region
  return None


def _region_line_bounds(
  buffer: RenderedBuffer,
  region: BlockRegion,
  line_index: int,
) -> tuple[int, int | None, int, int] | None:
  line_start = buffer.line_starts[line_index]
  line_end = buffer.line_visible_ends[line_index]
  if region.line_columns:
    for entry_line, start_column, end_column in region.line_columns:
      if entry_line != line_index:
        continue
      start_index = min(line_end, line_start + start_column)
      end_index = line_end if end_column is None else min(line_end, line_start + end_column)
      return (start_column, end_column, start_index, end_index)
    return None
  if not (region.start_line <= line_index <= region.end_line):
    return None
  start_index = min(line_end, line_start + region.start_column)
  end_index = line_end if region.end_column is None else min(line_end, line_start + region.end_column)
  return (region.start_column, region.end_column, start_index, end_index)


def _cursor_position_in_region_line(
  buffer: RenderedBuffer,
  region: BlockRegion,
  *,
  source_line: int,
  source_column: int,
  target_line: int,
  max_column: int,
) -> tuple[int, int] | None:
  source_bounds = _region_line_bounds(buffer, region, source_line)
  target_bounds = _region_line_bounds(buffer, region, target_line)
  if source_bounds is None or target_bounds is None:
    return None
  source_start_column, _source_end_column, _source_start_index, _source_end_index = source_bounds
  target_start_column, target_end_column, target_start_index, target_end_index = target_bounds
  relative_column = max(0, source_column - source_start_column)
  desired_column = min(max_column, target_start_column + relative_column)
  if target_end_column is not None:
    desired_column = min(desired_column, max(target_start_column, target_end_column - 1))
  if target_end_index > target_start_index:
    return (min(target_start_index + relative_column, target_end_index - 1), 0)
  fallback_index = max(buffer.line_starts[target_line], buffer.line_visible_ends[target_line] - 1)
  fallback_column = buffer.line_col(fallback_index)[1]
  return (fallback_index, max(0, desired_column - fallback_column))


def _current_region_line_snippet(buffer: RenderedBuffer, line_index: int, column: int) -> str:
  return _current_region_line_context(buffer, line_index, column)[0]


def _current_region_line_context(buffer: RenderedBuffer, line_index: int, column: int) -> tuple[str, int]:
  for region in buffer.block_regions:
    if not region.contains(line_index, column):
      continue
    if region.line_columns:
      for entry_line, start_column, end_column in region.line_columns:
        if entry_line != line_index:
          continue
        line_start = buffer.line_starts[line_index]
        line_end = buffer.line_visible_ends[line_index]
        start = min(line_end, line_start + start_column)
        visible_end = line_end if end_column is None else min(line_end, line_start + end_column)
        snippet = _sanitize_region_line_snippet(buffer.text[start:visible_end].strip())
        relative_column = max(0, column - start_column)
        return snippet, min(relative_column, max(0, len(snippet) - 1))
    line_start = buffer.line_starts[line_index]
    line_end = buffer.line_visible_ends[line_index]
    snippet = _sanitize_region_line_snippet(buffer.text[line_start:line_end].strip())
    return snippet, min(max(0, column), max(0, len(snippet) - 1))
  line_start = buffer.line_starts[line_index]
  line_end = buffer.line_visible_ends[line_index]
  snippet = _sanitize_region_line_snippet(buffer.text[line_start:line_end].strip())
  return snippet, min(max(0, column), max(0, len(snippet) - 1))


def _sanitize_region_line_snippet(snippet: str) -> str:
  snippet = snippet.strip()
  if snippet.startswith("|"):
    snippet = snippet[1:].lstrip()
  if snippet.endswith("|"):
    snippet = snippet[:-1].rstrip()
  return snippet


def _replace_buffer_block_regions(
  buffer: RenderedBuffer,
  block_regions: list[BlockRegion],
) -> RenderedBuffer:
  return replace(
    buffer,
    block_regions=block_regions,
    block_starts=[region.start for region in block_regions],
  )


def _build_single_content_block_region(
  rendered: str,
  line_starts: list[int],
  line_visible_ends: list[int],
) -> BlockRegion:
  first_non_empty_line: int | None = None
  last_non_empty_line: int | None = None
  for line_index, line_start in enumerate(line_starts):
    line_end = line_visible_ends[line_index]
    if not rendered[line_start:line_end].strip():
      continue
    if first_non_empty_line is None:
      first_non_empty_line = line_index
    last_non_empty_line = line_index
  if first_non_empty_line is None or last_non_empty_line is None:
    return BlockRegion(start=0, start_line=0, end_line=0, start_column=0)
  return BlockRegion(
    start=_line_first_content_position(
      rendered,
      line_starts[first_non_empty_line],
      line_visible_ends[first_non_empty_line],
    ),
    start_line=first_non_empty_line,
    end_line=last_non_empty_line,
    start_column=0,
  )


def _multi_region_groups(block_regions: list[BlockRegion]) -> list[list[BlockRegion]]:
  multi_region_groups: list[list[BlockRegion]] = []
  current_group: list[BlockRegion] = []
  current_key: tuple[int, int] | None = None
  for region in block_regions:
    group_key = _block_region_group_key(region)
    if group_key != current_key:
      if len(current_group) > 1:
        multi_region_groups.append(current_group)
      current_group = [region]
      current_key = group_key
    else:
      current_group.append(region)
  if len(current_group) > 1:
    multi_region_groups.append(current_group)
  return multi_region_groups


def _merge_regions_by_pane_target(
  document,
  buffer: RenderedBuffer,
  source_pane_groups: list[tuple[PaneTarget, PaneTarget]],
  *,
  width: int,
  session: requests.Session | None,
) -> RenderedBuffer:
  root = document.body or document.root
  if root is None or not buffer.block_regions:
    return buffer

  pane_targets = [pane_target for pane_group in source_pane_groups for pane_target in pane_group]
  if not pane_targets:
    return buffer

  normalized_by_path: dict[tuple[int, ...], str] = {}
  for pane_target in pane_targets:
    pane_node = _element_node_at_path(root, pane_target.path)
    if pane_node is None:
      continue
    normalized_by_path[pane_target.path] = _normalize_pane_match_text(
      render_normal_subtree(
        document,
        pane_node,
        width=width,
        link_style="none",
        text_styles=False,
        include_title=False,
        session=session,
      )
    )

  if not normalized_by_path:
    return buffer

  merged_regions: list[BlockRegion] = []
  pending_region: BlockRegion | None = None
  pending_path: tuple[int, ...] | None = None

  for region in buffer.block_regions:
    region_path = _pane_target_path_for_region(buffer, region, normalized_by_path)
    if pending_region is None:
      pending_region = region
      pending_path = region_path
      continue
    if pending_path is not None and region_path == pending_path:
      pending_region = _merge_block_region_pair(pending_region, region)
      continue
    merged_regions.append(pending_region)
    pending_region = region
    pending_path = region_path

  if pending_region is not None:
    merged_regions.append(pending_region)

  return _replace_buffer_block_regions(buffer, merged_regions)


def _pane_target_path_for_region(
  buffer: RenderedBuffer,
  region: BlockRegion,
  normalized_by_path: dict[tuple[int, ...], str],
) -> tuple[int, ...] | None:
  line_index, column = buffer.line_col(region.start)
  snippet, _ = _current_region_line_context(buffer, line_index, column)
  normalized_snippet = _normalize_pane_match_text(snippet)
  if not normalized_snippet:
    return None
  matching_paths = [
    path
    for path, normalized_rendered in normalized_by_path.items()
    if normalized_snippet in normalized_rendered
  ]
  if len(matching_paths) == 1:
    return matching_paths[0]
  return None


def _merge_block_region_pair(first: BlockRegion, second: BlockRegion) -> BlockRegion:
  return BlockRegion(
    start=first.start,
    start_line=first.start_line,
    end_line=second.end_line,
    start_column=first.start_column,
  )


def _normalize_pane_match_text(text: str) -> str:
  return " ".join(text.split())


def _deepest_matching_descendant_path(
  document,
  node: ElementNode,
  base_path: tuple[int, ...],
  line_snippet: str,
  *,
  width: int,
  session: requests.Session | None,
) -> tuple[int, ...] | None:
  normalized_snippet = _normalize_pane_match_text(line_snippet)
  if not normalized_snippet:
    return None

  best_path: tuple[int, ...] | None = None
  best_score: tuple[int, int, int] | None = None

  def visit(current: ElementNode, current_path: tuple[int, ...]) -> None:
    nonlocal best_path, best_score
    rendered = render_normal_subtree(
      document,
      current,
      width=width,
      link_style="none",
      text_styles=False,
      include_title=False,
      session=session,
    )
    normalized_rendered = _normalize_pane_match_text(rendered)
    if normalized_snippet not in normalized_rendered:
      return
    has_only_snippet = int(normalized_rendered == normalized_snippet)
    has_multiple_blocks = int("\n\n" not in rendered)
    has_element_children = int(not any(isinstance(child, ElementNode) for child in current.children))
    score = (has_only_snippet, has_multiple_blocks, has_element_children, len(normalized_rendered), -len(current_path))
    if best_score is None or score < best_score:
      best_path = current_path
      best_score = score
    for index, child in enumerate(current.children):
      if isinstance(child, ElementNode):
        visit(child, current_path + (index,))

  visit(node, base_path)
  return best_path


def _promote_heading_match_path(
  document,
  root: ElementNode,
  path: tuple[int, ...],
  line_snippet: str,
  *,
  width: int,
  session: requests.Session | None,
) -> tuple[int, ...]:
  normalized_snippet = _normalize_pane_match_text(line_snippet)
  current_path = path
  while current_path:
    node = _element_node_at_path(root, current_path)
    parent = _element_node_at_path(root, current_path[:-1])
    if node is None or parent is None:
      break
    if not _has_heading_descendant_match(node, normalized_snippet):
      break
    sibling_texts = [
      render_normal_subtree(
        document,
        sibling,
        width=width,
        link_style="none",
        text_styles=False,
        include_title=False,
        session=session,
      )
      for sibling in parent.children[current_path[-1] + 1:]
      if isinstance(sibling, ElementNode)
    ]
    if not any(_normalize_pane_match_text(text) for text in sibling_texts):
      break
    parent_rendered = render_normal_subtree(
      document,
      parent,
      width=width,
      link_style="none",
      text_styles=False,
      include_title=False,
      session=session,
    )
    if normalized_snippet not in _normalize_pane_match_text(parent_rendered):
      break
    current_path = current_path[:-1]
  return current_path


def _promote_leading_metadata_match_path(
  document,
  root: ElementNode,
  path: tuple[int, ...],
  line_snippet: str,
  *,
  minimum_path: tuple[int, ...] = (),
  width: int,
  session: requests.Session | None,
) -> tuple[int, ...]:
  normalized_snippet = _normalize_pane_match_text(line_snippet)
  candidate_path = path
  while candidate_path:
    node = _element_node_at_path(root, candidate_path)
    parent = _element_node_at_path(root, candidate_path[:-1])
    if node is None or parent is None:
      break
    if _has_heading_descendant_match(node, normalized_snippet):
      break
    element_child_indexes = [
      index for index, child in enumerate(parent.children)
      if isinstance(child, ElementNode)
    ]
    if not element_child_indexes or candidate_path[-1] != element_child_indexes[0]:
      candidate_path = candidate_path[:-1]
      continue
    following_siblings = [
      parent.children[index]
      for index in element_child_indexes[1:]
    ]
    if following_siblings and any(_has_any_heading_descendant(sibling) for sibling in following_siblings):
      parent_rendered = render_normal_subtree(
        document,
        parent,
        width=width,
        link_style="none",
        text_styles=False,
        include_title=False,
        session=session,
      )
      parent_path = candidate_path[:-1]
      if (
        len(parent_path) >= len(minimum_path)
        and parent_path[:len(minimum_path)] == minimum_path
        and normalized_snippet in _normalize_pane_match_text(parent_rendered)
      ):
        return candidate_path[:-1]
    candidate_path = candidate_path[:-1]
  return path


def _has_heading_descendant_match(node: ElementNode, normalized_snippet: str) -> bool:
  heading_snippet = normalized_snippet.lstrip("# ").strip()
  if not heading_snippet:
    return False
  for descendant in node.iter_nodes():
    if not isinstance(descendant, ElementNode):
      continue
    if descendant.tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
      continue
    if heading_snippet in _normalize_pane_match_text(descendant.text_content()):
      return True
  return False


def _has_any_heading_descendant(node: ElementNode) -> bool:
  for descendant in node.iter_nodes():
    if isinstance(descendant, ElementNode) and descendant.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
      return True
  return False


def _element_node_at_path(root: ElementNode | None, path: tuple[int, ...]) -> ElementNode | None:
  if root is None:
    return None
  node = root
  for index in path:
    if index < 0 or index >= len(node.children):
      return None
    child = node.children[index]
    if not isinstance(child, ElementNode):
      return None
    node = child
  return node


def _path_has_textual_sibling_context(
  document,
  root: ElementNode,
  path: tuple[int, ...],
  *,
  width: int,
  session: requests.Session | None,
) -> bool:
  current_path = path
  while current_path:
    parent = _element_node_at_path(root, current_path[:-1])
    if parent is None:
      break
    sibling_nodes = [
      sibling
      for index, sibling in enumerate(parent.children)
      if index != current_path[-1] and isinstance(sibling, ElementNode)
    ]
    for sibling in sibling_nodes:
      rendered = render_normal_subtree(
        document,
        sibling,
        width=width,
        link_style="none",
        text_styles=False,
        include_title=False,
        session=session,
      )
      if _normalize_pane_match_text(rendered):
        return True
    current_path = current_path[:-1]
  return False


def _build_render_buffer(
  rendered: str,
  links: list[Link],
  controls: list[FormControl],
  interactive_keys: list[str] | None = None,
  *,
  link_metadata: tuple[RenderedLinkMetadata, ...] = (),
  control_metadata: tuple[RenderedControlMetadata, ...] = (),
) -> RenderedBuffer:
  visible_positions = [
    index for index, char in enumerate(rendered)
    if char != "\n"
  ]
  visible_position_indexes = {
    position: index for index, position in enumerate(visible_positions)
  }
  line_starts: list[int] = []
  line_visible_ends: list[int] = []
  offset = 0
  for line in rendered.splitlines(keepends=True) or [""]:
    line_starts.append(offset)
    line_visible_ends.append(offset + len(line.rstrip("\n")))
    offset += len(line)
  if not line_starts:
    line_starts = [0]
    line_visible_ends = [0]
  link_spans = _link_spans_from_renderer_metadata(link_metadata, links)
  control_spans = _control_spans_from_renderer_metadata(control_metadata)
  block_regions = _build_block_regions(rendered, line_starts, line_visible_ends)
  interactive_spans = [InteractiveSpan(start=span.start, end=span.end, key=f"link:{span.index}") for span in link_spans]
  interactive_spans.extend(
    InteractiveSpan(
      start=span.start,
      end=span.end,
      key=f"control:{span.control_id}",
    )
    for span in control_spans
  )
  interactive_spans.sort(key=lambda span: span.start)
  interactive_keys_cache = _interactive_keys_cache(interactive_spans, interactive_keys)
  control_cursor_by_id = _control_cursor_by_id(control_spans)
  return RenderedBuffer(
    text=rendered,
    visible_positions=visible_positions,
    line_starts=line_starts,
    line_visible_ends=line_visible_ends,
    block_starts=[region.start for region in block_regions],
    block_regions=block_regions,
    link_spans=link_spans,
    control_spans=control_spans,
    visible_position_indexes=visible_position_indexes,
    interactive_spans_cache=interactive_spans,
    interactive_keys_cache=interactive_keys_cache,
    interactive_cursor_by_key=_interactive_cursor_by_key(interactive_spans, control_cursor_by_id),
    control_cursor_by_id=control_cursor_by_id,
    link_starts=[span.start for span in link_spans],
    control_starts=[span.start for span in control_spans],
  )


def _link_spans_from_renderer_metadata(
  metadata: tuple[RenderedLinkMetadata, ...],
  links: list[Link],
) -> list[LinkSpan]:
  spans: list[LinkSpan] = []
  link_cursor = 0
  for fallback_index, entry in enumerate(metadata):
    matched_index = _match_renderer_metadata_link_index(entry, links, start=link_cursor)
    if matched_index is not None:
      link_cursor = matched_index + 1
    spans.append(
      LinkSpan(
        start=entry.start,
        end=entry.end,
        href=entry.href,
        text=entry.text,
        index=matched_index if matched_index is not None else (
          entry.index if entry.index < len(links) else fallback_index
        ),
      )
    )
  spans.sort(key=lambda span: span.start)
  return spans


def _match_renderer_metadata_link_index(
  entry: RenderedLinkMetadata,
  links: list[Link],
  *,
  start: int,
) -> int | None:
  for matcher in (
    lambda link: link.href == entry.href and (link.text or link.href).strip() == entry.text,
    lambda link: link.href == entry.href,
    lambda link: (link.text or link.href).strip() == entry.text,
  ):
    for index in range(start, len(links)):
      if matcher(links[index]):
        return index
  return None


def _control_spans_from_renderer_metadata(
  metadata: tuple[RenderedControlMetadata, ...],
) -> list[ControlSpan]:
  spans: list[ControlSpan] = []
  for entry in metadata:
    spans.append(
      ControlSpan(
        start=entry.start,
        end=entry.end,
        control_id=entry.control_id,
        text=entry.text,
        label=entry.label,
        kind=entry.kind,
        source_kind=entry.source_kind,
      )
    )
  spans.sort(key=lambda span: span.start)
  return spans


def _build_block_regions(
  rendered: str,
  line_starts: list[int],
  line_visible_ends: list[int],
) -> list[BlockRegion]:
  block_regions: list[BlockRegion] = []
  block_start_line: int | None = None
  for line_index, line_start in enumerate(line_starts):
    line_end = line_visible_ends[line_index]
    line_text = rendered[line_start:line_end]
    if not line_text.strip():
      if block_start_line is not None:
        block_regions.extend(
          _build_regions_for_line_range(
            rendered,
            line_starts,
            line_visible_ends,
            block_start_line,
            line_index - 1,
          )
        )
        block_start_line = None
      continue
    if block_start_line is None:
      block_start_line = line_index
  if block_start_line is not None:
    block_regions.extend(
      _build_regions_for_line_range(
        rendered,
        line_starts,
        line_visible_ends,
        block_start_line,
        len(line_starts) - 1,
      )
    )
  if not block_regions:
    return [BlockRegion(start=0, start_line=0, end_line=0, start_column=0)]
  return _merge_adjacent_plain_block_regions(block_regions)


def _merge_adjacent_plain_block_regions(block_regions: list[BlockRegion]) -> list[BlockRegion]:
  merged_regions: list[BlockRegion] = []
  pending_region: BlockRegion | None = None
  for region in block_regions:
    if pending_region is None:
      pending_region = region
      continue
    if not pending_region.line_columns and not region.line_columns:
      pending_region = BlockRegion(
        start=pending_region.start,
        start_line=pending_region.start_line,
        end_line=region.end_line,
        start_column=pending_region.start_column,
      )
      continue
    merged_regions.append(pending_region)
    pending_region = region
  if pending_region is not None:
    merged_regions.append(pending_region)
  return merged_regions


def _build_regions_for_line_range(
  rendered: str,
  line_starts: list[int],
  line_visible_ends: list[int],
  start_line: int,
  end_line: int,
) -> list[BlockRegion]:
  grid_regions = _build_grid_regions_for_line_range(
    rendered,
    line_starts,
    line_visible_ends,
    start_line,
    end_line,
  )
  if grid_regions is not None:
    return grid_regions
  return [
    BlockRegion(
      start=_line_first_content_position(
        rendered,
        line_starts[start_line],
        line_visible_ends[start_line],
      ),
      start_line=start_line,
      end_line=end_line,
      start_column=0,
    )
  ]


def _build_grid_regions_for_line_range(
  rendered: str,
  line_starts: list[int],
  line_visible_ends: list[int],
  start_line: int,
  end_line: int,
) -> list[BlockRegion] | None:
  separator_candidates: set[int] | None = None
  separator_indexes_by_line: list[dict[int, int]] = []
  for line_index in range(start_line, end_line + 1):
    line_text = rendered[line_starts[line_index]:line_visible_ends[line_index]]
    pipe_columns: dict[int, int] = {}
    for separator_index, char in enumerate(line_text):
      if char != "|":
        continue
      pipe_columns[_display_width(line_text[:separator_index])] = separator_index
    if not pipe_columns:
      return None
    current_columns = set(pipe_columns)
    if separator_candidates is None:
      separator_candidates = current_columns
    else:
      separator_candidates &= current_columns
    if not separator_candidates:
      return None
    separator_indexes_by_line.append(pipe_columns)

  if not separator_candidates:
    return None
  viable_candidates: list[tuple[int, int]] = []
  for separator_column in sorted(separator_candidates):
    if separator_column < 8:
      continue
    empty_side_count = 0
    for line_index, pipe_columns in zip(range(start_line, end_line + 1), separator_indexes_by_line):
      separator_index = pipe_columns[separator_column]
      line_text = rendered[line_starts[line_index]:line_visible_ends[line_index]]
      left_text = line_text[:separator_index].strip()
      right_text = line_text[separator_index + 1:].strip()
      if not left_text or not right_text:
        empty_side_count += 1
    if empty_side_count > 0:
      viable_candidates.append((empty_side_count, separator_column))
  if viable_candidates:
    _, separator_column = max(viable_candidates)
  else:
    if start_line == end_line:
      separator_column = max(separator_candidates)
    else:
      if len(separator_candidates) != 1:
        return None
      separator_column = next(iter(separator_candidates))
  separator_indexes = [
    (line_index, separator_indexes_by_line[offset][separator_column])
    for offset, line_index in enumerate(range(start_line, end_line + 1))
  ]
  left_bounds = tuple((line_index, 0, separator_index) for line_index, separator_index in separator_indexes)
  right_bounds = tuple(
    (
      line_index,
      separator_index + 1,
      None,
    )
    for line_index, separator_index in separator_indexes
  )
  left_start = _first_content_position_in_line_bounds(rendered, line_starts, line_visible_ends, left_bounds)
  right_start = _first_content_position_in_line_bounds(rendered, line_starts, line_visible_ends, right_bounds)
  if left_start is None or right_start is None:
    return None
  return [
    BlockRegion(
      start=left_start,
      start_line=start_line,
      end_line=end_line,
      start_column=0,
      line_columns=left_bounds,
    ),
    BlockRegion(
      start=right_start,
      start_line=start_line,
      end_line=end_line,
      start_column=0,
      line_columns=right_bounds,
    ),
  ]


def _line_first_content_position(rendered: str, line_start: int, line_end: int) -> int:
  for index in range(line_start, line_end):
    if not rendered[index].isspace():
      return index
  return line_start


def _first_content_position_in_line_bounds(
  rendered: str,
  line_starts: list[int],
  line_visible_ends: list[int],
  line_bounds: tuple[tuple[int, int, int | None], ...],
) -> int | None:
  for line_index, start_column, end_column in line_bounds:
    line_start = line_starts[line_index]
    line_end = line_visible_ends[line_index]
    visible_end = line_end if end_column is None else min(line_end, line_start + end_column)
    start = min(line_end, line_start + start_column)
    for index in range(start, visible_end):
      if not rendered[index].isspace():
        return index
  return None


def _build_link_spans(
  links: list[Link],
  occurrences_by_text: dict[str, list[int]],
  rendered: str,
  *,
  indexes: list[int] | None = None,
  occupied_ranges: set[tuple[int, int]] | None = None,
) -> list[LinkSpan]:
  link_spans: list[LinkSpan] = []
  consumed_counts: dict[str, int] = {}
  target_indexes = indexes if indexes is not None else list(range(len(links)))
  occupied = set() if occupied_ranges is None else set(occupied_ranges)
  for index in target_indexes:
    link = links[index]
    match = _find_link_span_start(
      link,
      occurrences_by_text,
      rendered,
      consumed_counts,
      occupied,
    )
    if match is None:
      continue
    start, target = match
    end = start + len(target)
    link_spans.append(
      LinkSpan(
        start=start,
        end=end,
        href=link.href,
        text=target,
        index=index,
      )
    )
    occupied.add((start, end))
  link_spans.sort(key=lambda span: span.start)
  return link_spans


def _find_link_span_start(
  link: Link,
  occurrences_by_text: dict[str, list[int]],
  rendered: str,
  consumed_counts: dict[str, int],
  occupied_ranges: set[tuple[int, int]],
) -> tuple[int, str] | None:
  for target in _link_text_candidates(link):
    occurrences = occurrences_by_text.get(target, [])
    occurrence_index = consumed_counts.get(target, 0)
    while occurrence_index < len(occurrences):
      candidate = occurrences[occurrence_index]
      occurrence_index += 1
      if not _should_map_link_text_at(rendered, candidate, target):
        continue
      span = (candidate, candidate + len(target))
      if any(_ranges_overlap(span, occupied) for occupied in occupied_ranges):
        continue
      consumed_counts[target] = occurrence_index
      return (candidate, target)
    consumed_counts[target] = occurrence_index
  return None


def _link_text_candidates(link: Link) -> tuple[str, ...]:
  target = (link.text or link.href).strip()
  if not target:
    return ()
  candidates = [target]
  if " " in target:
    first_token = target.split()[0].strip()
    if first_token and first_token not in candidates:
      candidates.append(first_token)
  return tuple(candidates)


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
  return left[0] < right[1] and right[0] < left[1]


def _should_map_link_text_at(rendered: str, start: int, target: str) -> bool:
  if len(target) != 1:
    return True
  end = start + 1
  before = rendered[start - 1] if start > 0 else ""
  after = rendered[end] if end < len(rendered) else ""
  return not _is_wordish_character(before) and not _is_wordish_character(after)


def _is_wordish_character(value: str) -> bool:
  return bool(value) and (value.isalnum() or value == "_")


def _control_cursor_by_id(control_spans: list[ControlSpan]) -> dict[str, int]:
  cursor_by_id: dict[str, int] = {}
  for span in control_spans:
    previous = cursor_by_id.get(span.control_id)
    if previous is None:
      cursor_by_id[span.control_id] = span.start
      continue
    if span.source_kind == "token":
      token_span = next(
        (candidate for candidate in control_spans if candidate.control_id == span.control_id and candidate.start == previous),
        None,
      )
      if token_span is None or token_span.source_kind != "token":
        cursor_by_id[span.control_id] = span.start
  return cursor_by_id


def _interactive_cursor_by_key(
  interactive_spans: list[InteractiveSpan],
  control_cursor_by_id: dict[str, int],
) -> dict[str, int]:
  cursor_by_key: dict[str, int] = {}
  for span in interactive_spans:
    if span.key.startswith("control:"):
      cursor_by_key.setdefault(span.key, control_cursor_by_id.get(span.key.removeprefix("control:"), span.start))
      continue
    cursor_by_key.setdefault(span.key, span.start)
  return cursor_by_key


def _interactive_keys_cache(
  interactive_spans: list[InteractiveSpan],
  interactive_keys: list[str] | None,
) -> list[str]:
  keys_by_visual_order = [span.key for span in interactive_spans]
  if interactive_keys is None:
    return keys_by_visual_order
  known_keys = set(keys_by_visual_order)
  ordered_keys: list[str] = []
  for key in interactive_keys:
    if key in known_keys and key not in ordered_keys:
      ordered_keys.append(key)
  for key in keys_by_visual_order:
    if key not in ordered_keys:
      ordered_keys.append(key)
  return ordered_keys


def _interactive_order_keys(
  document: TWebDocument,
  links: list[Link],
  controls: list[FormControl],
) -> list[str]:
  root = document.document.root
  if root is None:
    return []
  control_ids = {control.control_id for control in controls}
  ordered_keys: list[str] = []
  link_index = 0
  for node in _iter_element_nodes(root):
    if node.tag == "a":
      href = node.attrs.get("href", "").strip()
      if href:
        if link_index < len(links):
          ordered_keys.append(f"link:{link_index}")
        link_index += 1
    control_key = _interactive_control_key(node, control_ids)
    if control_key is not None:
      ordered_keys.append(control_key)
  return ordered_keys


def _iter_element_nodes(node: ElementNode):
  yield node
  for child in node.children:
    if isinstance(child, ElementNode):
      yield from _iter_element_nodes(child)


def _interactive_control_key(node: ElementNode, control_ids: set[str]) -> str | None:
  if node.tag == "input" and node.attrs.get("type", "text").strip().lower() == "hidden":
    return None
  if (
    node.tag not in {"input", "textarea", "select", "button"} and
    "tab" not in node.attrs.get("role", "").strip().lower().split()
  ):
    return None
  control_id = getattr(node, "_tweb_control_id", None) or node.attrs.get("id", "").strip()
  if not control_id or control_id not in control_ids:
    return None
  return f"control:{control_id}"


def _span_at[T](
  spans: list[T],
  starts: list[int],
  cursor_index: int,
) -> T | None:
  if not starts:
    return None
  span_index = bisect_right(starts, cursor_index) - 1
  if span_index < 0:
    return None
  span = spans[span_index]
  if span.start <= cursor_index < span.end:
    return span
  return None


def _interactive_span_at[T](
  buffer: RenderedBuffer,
  spans: list[T],
  starts: list[int],
  cursor_index: int,
  span_text: Callable[[T], str | None],
) -> T | None:
  if not starts:
    return None
  span_index = bisect_right(starts, cursor_index) - 1
  while span_index >= 0:
    span = spans[span_index]
    if span.start > cursor_index:
      span_index -= 1
      continue
    if span.end <= cursor_index:
      break
    if _interactive_span_contains_cursor(buffer, span.start, span.end, cursor_index, span_text(span)):
      return span
    span_index -= 1
  return None


def _interactive_span_contains_cursor(
  buffer: RenderedBuffer,
  span_start: int,
  span_end: int,
  cursor_index: int,
  span_text: str | None,
) -> bool:
  if span_end <= span_start or not (span_start <= cursor_index < span_end):
    return False
  line_index, _ = buffer.line_col(cursor_index)
  line_start = buffer.line_starts[line_index]
  line_end = buffer.line_visible_ends[line_index]
  visible_start = max(span_start, line_start)
  visible_end = min(span_end, line_end)
  if visible_end <= visible_start:
    return False
  segment_start_offset, segment_end_offset = _best_matching_span_segment_offsets(
    buffer.text[visible_start:visible_end],
    span_text,
    require_match=bool(span_text),
  )
  if segment_end_offset <= segment_start_offset:
    return False
  matched_start = visible_start + segment_start_offset
  matched_end = visible_start + segment_end_offset
  return matched_start <= cursor_index < matched_end


def _build_content_text(
  buffer: RenderedBuffer,
  cursor_index: int,
  viewport_line: int = 0,
  viewport_height: int | None = None,
  editing_control_id: str | None = None,
  debug_block_colors: bool = False,
  viewport_width: int | None = None,
  cursor_line: int | None = None,
  cursor_column: int | None = None,
) -> Text:
  if viewport_height is None:
    viewport_height = len(buffer.line_starts)
  start_line = max(0, min(viewport_line, len(buffer.line_starts) - 1 if buffer.line_starts else 0))
  end_line = min(len(buffer.line_starts), start_line + max(1, viewport_height))
  raw_lines = [
    buffer.text[buffer.line_starts[line_index]:buffer.line_visible_ends[line_index]]
    for line_index in range(start_line, end_line)
  ]
  if viewport_width is not None and viewport_width > 0:
    display_lines = [
      _pad_display_line(line_text, viewport_width)
      for line_text in raw_lines
    ]
  else:
    display_lines = raw_lines
  display_line_starts = _display_line_starts(display_lines)
  display_line_widths = [len(line) for line in display_lines]
  text = Text("\n".join(display_lines))
  if debug_block_colors:
    _stylize_block_debug_backgrounds(
      text,
      buffer,
      display_line_starts=display_line_starts,
      display_line_widths=display_line_widths,
      start_line=start_line,
      end_line=end_line,
    )
  for span in buffer.link_spans:
    local_segments = _local_display_span_segments(
      buffer,
      display_line_starts,
      start_line,
      end_line,
      span.start,
      span.end,
      span_text=span.text,
    )
    for local_start, local_end in local_segments:
      text.stylize(LINK_BASE_STYLE, local_start, local_end)
  for span in buffer.control_spans:
    local_segments = _local_display_span_segments(
      buffer,
      display_line_starts,
      start_line,
      end_line,
      span.start,
      span.end,
    )
    for local_start, local_end in local_segments:
      text.stylize(CONTROL_BASE_STYLE, local_start, local_end)
  if not buffer.visible_positions:
    return text
  actual_cursor_line, actual_cursor_column = buffer.line_col(cursor_index)
  if cursor_line is None:
    cursor_line = actual_cursor_line
  if cursor_column is None:
    cursor_column = actual_cursor_column
  if not (start_line <= cursor_line < end_line):
    return text
  link_span = buffer.link_at(cursor_index) if (cursor_line, cursor_column) == (actual_cursor_line, actual_cursor_column) else None
  control_span = buffer.control_at(cursor_index) if (cursor_line, cursor_column) == (actual_cursor_line, actual_cursor_column) else None
  if editing_control_id is not None and control_span is not None and control_span.control_id == editing_control_id:
    local_start = _local_display_index(buffer, display_line_starts, start_line, end_line, control_span.start)
    if local_start is not None:
      local_end = min(len(text.plain), local_start + (control_span.end - control_span.start))
    else:
      local_end = None
    if local_start is not None and local_end is not None and local_end > local_start:
      text.stylize("bold black on yellow", local_start, local_end)
  style = "black on white"
  if link_span is not None or control_span is not None:
    style = "bold white on blue"
  if editing_control_id is not None and control_span is not None and control_span.control_id == editing_control_id:
    style = "bold white on red"
  line_width = display_line_widths[cursor_line - start_line] if display_line_widths else 0
  local_index = display_line_starts[cursor_line - start_line] + min(cursor_column, max(0, line_width - 1))
  text.stylize(style, local_index, local_index + 1)
  return text


def _stylize_block_debug_backgrounds(
  text: Text,
  buffer: RenderedBuffer,
  *,
  display_line_starts: list[int],
  display_line_widths: list[int],
  start_line: int,
  end_line: int,
) -> None:
  for index, region in enumerate(buffer.block_regions):
    if region.end_line < start_line or region.start_line >= end_line:
      continue
    style = BLOCK_DEBUG_BACKGROUND_STYLES[index % len(BLOCK_DEBUG_BACKGROUND_STYLES)]
    if region.line_columns:
      for line_index, start_column, end_column in region.line_columns:
        if not (start_line <= line_index < end_line):
          continue
        _stylize_line_slice(
          text,
          display_line_starts,
          display_line_widths,
          line_offset=line_index - start_line,
          start_column=start_column,
          end_column=end_column,
          style=style,
        )
      continue
    for line_index in range(max(start_line, region.start_line), min(end_line, region.end_line + 1)):
      _stylize_line_slice(
        text,
        display_line_starts,
        display_line_widths,
        line_offset=line_index - start_line,
        start_column=0,
        end_column=None,
        style=style,
      )


def _stylize_line_slice(
  text: Text,
  display_line_starts: list[int],
  display_line_widths: list[int],
  *,
  line_offset: int,
  start_column: int,
  end_column: int | None,
  style: str,
) -> None:
  if line_offset < 0 or line_offset >= len(display_line_starts) or line_offset >= len(display_line_widths):
    return
  line_width = display_line_widths[line_offset]
  start = display_line_starts[line_offset] + min(start_column, line_width)
  visible_end = display_line_starts[line_offset] + (line_width if end_column is None else min(end_column, line_width))
  if visible_end <= start:
    return
  text.stylize(style, start, visible_end)


def _pad_display_line(line_text: str, viewport_width: int) -> str:
  return f"{line_text}{' ' * max(0, viewport_width - _display_width(line_text))}"


def _display_line_starts(lines: list[str]) -> list[int]:
  starts: list[int] = []
  offset = 0
  for index, line in enumerate(lines):
    starts.append(offset)
    offset += len(line)
    if index < len(lines) - 1:
      offset += 1
  return starts


def _local_display_index(
  buffer: RenderedBuffer,
  display_line_starts: list[int],
  start_line: int,
  end_line: int,
  buffer_index: int,
) -> int | None:
  line_index, column = buffer.line_col(buffer_index)
  if not (start_line <= line_index < end_line):
    return None
  return display_line_starts[line_index - start_line] + column


def _local_display_span_segments(
  buffer: RenderedBuffer,
  display_line_starts: list[int],
  start_line: int,
  end_line: int,
  span_start: int,
  span_end: int,
  span_text: str | None = None,
) -> list[tuple[int, int]]:
  if span_end <= span_start:
    return []
  segments: list[tuple[int, int]] = []
  for line_index in range(start_line, end_line):
    line_start = buffer.line_starts[line_index]
    line_end = buffer.line_visible_ends[line_index]
    visible_start = max(span_start, line_start)
    visible_end = min(span_end, line_end)
    segment_start_offset, segment_end_offset = _best_matching_span_segment_offsets(
      buffer.text[visible_start:visible_end],
      span_text,
    )
    visible_start += segment_start_offset
    visible_end = visible_start + max(0, segment_end_offset - segment_start_offset)
    if visible_end <= visible_start:
      continue
    local_start = _local_display_index(buffer, display_line_starts, start_line, end_line, visible_start)
    local_last = _local_display_index(buffer, display_line_starts, start_line, end_line, visible_end - 1)
    if local_start is None or local_last is None:
      continue
    segments.append((local_start, local_last + 1))
  return segments


def _best_matching_span_segment_offsets(
  segment_text: str,
  span_text: str | None,
  *,
  require_match: bool = False,
) -> tuple[int, int]:
  start = 0
  end = len(segment_text)
  while start < end and segment_text[start].isspace():
    start += 1
  while end > start and segment_text[end - 1].isspace():
    end -= 1
  if not span_text:
    return (start, end)
  best: tuple[int, int] | None = None
  for candidate_start in range(start, end):
    for candidate_end in range(end, candidate_start, -1):
      candidate = segment_text[candidate_start:candidate_end]
      if not candidate.strip():
        continue
      if candidate in span_text:
        if best is None or (candidate_end - candidate_start) > (best[1] - best[0]):
          best = (candidate_start, candidate_end)
        break
  if best is not None:
    return best
  if require_match and span_text:
    return (0, 0)
  return (start, end)
