from __future__ import annotations

from asyncio import sleep as async_sleep
from dataclasses import replace
import os
from pathlib import Path
import re
import tempfile
from time import sleep
import unittest
from unittest.mock import Mock, patch

from rich.text import Text
from textual import events
from textual.widgets import Footer, Input, Label, Static, TextArea

from tweb import parse_document
from tweb.api import Link, TWebDocument
from tweb.dom import ElementNode
from tweb.interactions import FormControl
from tweb.fetcher import FetchCancelled, Resource
from tweb.renderers.normal import (
  RenderedControlMetadata,
  RenderedLinkMetadata,
  collect_visible_links,
  render_normal,
  render_normal_subtree,
  render_normal_with_metadata,
)
from tweb.tui import (
  BrowserPage,
  HistoryScreen,
  LinkSpan,
  LoadRequest,
  OpenLocationScreen,
  SavePageScreen,
  ShortcutHelpScreen,
  TwebBrowserApp,
  _build_content_text,
  _build_render_buffer,
  _element_node_at_path,
  _interactive_order_keys,
  _promote_leading_metadata_match_path,
  _resolve_width,
  run_tui_browser,
)


ROOT = Path(__file__).resolve().parents[1]
TUI_ROOT = ROOT / "tests" / "fixtures" / "tui_root.html"
TUI_LONG = ROOT / "tests" / "fixtures" / "tui_long.html"
CSS_EXTERNAL_GRID = ROOT / "tests" / "fixtures" / "css_external_grid.html"
DROPDOWN = ROOT / "tests" / "fixtures" / "dropdown.html"
FORM = ROOT / "tests" / "fixtures" / "form.html"
PASSWORD_FORM = ROOT / "tests" / "fixtures" / "form_password.html"
BUTTON_CLICK = ROOT / "tests" / "fixtures" / "button_click.html"
BUTTON_CLICK_FETCH = ROOT / "tests" / "fixtures" / "button_click_fetch.html"
BUTTON_CLICK_NAVIGATION = ROOT / "tests" / "fixtures" / "button_click_navigation.html"
WELCOME_PAGE = ROOT / "tweb" / "data" / "welcome.html"


class TuiTest(unittest.IsolatedAsyncioTestCase):
  def _freebsd_fragment_source(self) -> Resource:
    return Resource(
      source="https://example.com/freebsd",
      content="""
      <html>
        <body>
          <h1>FreeBSD</h1>
          <p>Introductory paragraph with a citation <sup><a href="#cite_note-8">8</a></sup>.</p>
          <p>Line 1 filler content for scrolling.</p>
          <p>Line 2 filler content for scrolling.</p>
          <p>Line 3 filler content for scrolling.</p>
          <p>Line 4 filler content for scrolling.</p>
          <p>Line 5 filler content for scrolling.</p>
          <p>Line 6 filler content for scrolling.</p>
          <p>Line 7 filler content for scrolling.</p>
          <p>Line 8 filler content for scrolling.</p>
          <p>Line 9 filler content for scrolling.</p>
          <p>Line 10 filler content for scrolling.</p>
          <h2>References</h2>
          <ol>
            <li id="cite_note-8">Footnote target line with FreeBSD release details.</li>
          </ol>
        </body>
      </html>
      """,
    )

  def _metadata_links(
    self,
    rendered: str,
    links: list[Link],
  ) -> tuple[RenderedLinkMetadata, ...]:
    spans: list[RenderedLinkMetadata] = []
    for index, link in enumerate(links):
      start = rendered.index(link.text)
      spans.append(
        RenderedLinkMetadata(
          start=start,
          end=start + len(link.text),
          text=link.text,
          href=link.href,
          index=index,
        )
      )
    return tuple(spans)

  def _metadata_controls(
    self,
    rendered: str,
    controls: list[FormControl],
  ) -> tuple[RenderedControlMetadata, ...]:
    spans: list[RenderedControlMetadata] = []
    for control_index, control in enumerate(controls):
      token = control.token
      if not token:
        continue
      search_from = 0
      while True:
        start = rendered.find(token, search_from)
        if start < 0:
          break
        spans.append(
          RenderedControlMetadata(
            start=start,
            end=start + len(token),
            text=token,
            control_id=control.control_id,
            label=control.label or control.control_id,
            kind=control.kind,
            index=control_index,
          )
        )
        search_from = start + len(token)
    return tuple(spans)

  def _write_history_test_pages(self, tmpdir: str) -> tuple[Path, Path]:
    root_page = (Path(tmpdir) / "root.html").resolve()
    page2 = (Path(tmpdir) / "page2.html").resolve()
    root_page.write_text(
      """
      <html><head><title>Root</title></head><body><h1>Root</h1><a href="page2.html">Page 2</a></body></html>
      """,
      encoding="utf-8",
    )
    page2.write_text("<html><head><title>Page 2</title></head><body><h1>Page 2</h1></body></html>", encoding="utf-8")
    return (root_page, page2)

  async def test_renders_initial_page_and_status(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test() as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      status = app.query_one("#status", Static)
      self.assertIn("TUI Root", str(content.content))
      self.assertEqual(str(app.query_one("#content-title", Label).render()), "TUI Root [QuickJS]")
      self.assertEqual(len(app.query(Footer)), 0)
      self.assertIn("line 1 col 1", str(status.content))

  async def test_status_shows_resolved_link_target(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, _page2 = self._write_history_test_pages(tmpdir)
      app = TwebBrowserApp(str(root_page), width=80)

      async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        status = str(app.query_one("#status", Static).content)
        self.assertIn(str((root_page.parent / "page2.html").resolve()), status)

  async def test_x_toggles_between_normal_and_dom_views(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test() as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      self.assertIn("TUI Root", content.content.plain)

      await pilot.press("x")
      await pilot.pause()
      self.assertIn("#document source=", content.content.plain)
      self.assertEqual(str(app.query_one("#content-title", Label).render()), "TUI Root (DOM) [QuickJS]")

      await pilot.press("x")
      await pilot.pause()
      self.assertIn("TUI Root", content.content.plain)
      self.assertEqual(str(app.query_one("#content-title", Label).render()), "TUI Root [QuickJS]")

  async def test_tab_enter_back_and_forward_navigate_history(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test() as pilot:
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      self.assertIn("tests/fixtures/sample.html", str(app.query_one("#status", Static).content))
      await pilot.press("tab")
      await pilot.pause()
      self.assertIn("tui_page2.html", str(app.query_one("#status", Static).content))
      await pilot.press("enter")
      await pilot.pause()
      self.assertEqual(app.current_page.document.title, "TUI Page 2")
      self.assertIn("tests/fixtures/tui_page2.html", app.current_page.resource.source)

      await pilot.press("b")
      await pilot.pause()
      self.assertEqual(app.current_page.document.title, "TUI Root")
      self.assertIn("tests/fixtures/tui_root.html", app.current_page.resource.source)

      await pilot.press("f")
      await pilot.pause()
      self.assertEqual(app.current_page.document.title, "TUI Page 2")

  async def test_mount_syncs_viewport_width_to_actual_terminal_width(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=30)

    async with app.run_test(size=(90, 20)) as pilot:
      await pilot.pause()
      self.assertEqual(app.viewport_columns, 90)
      self.assertEqual(app._content_width(), 90)

  async def test_resize_updates_viewport_width_to_actual_terminal_width(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=30)

    async with app.run_test(size=(90, 20)) as pilot:
      await pilot.pause()
      await pilot.resize_terminal(110, 20)
      await pilot.pause()
      self.assertEqual(app.viewport_columns, 110)
      self.assertEqual(app._content_width(), 110)

  async def test_resize_rerenders_in_background(self) -> None:
    class SlowResizeRenderApp(TwebBrowserApp):
      def _build_view_render_result(self, *args, **kwargs):
        sleep(0.2)
        return super()._build_view_render_result(*args, **kwargs)

    app = SlowResizeRenderApp(str(TUI_ROOT), width=30)

    async with app.run_test(size=(90, 20)) as pilot:
      await pilot.pause()
      await pilot.resize_terminal(110, 20)
      await pilot.pause()
      self.assertIsNotNone(app.view_render_worker)
      self.assertIn("Rendering", str(app.query_one("#status", Static).content))
      self.assertIn("Esc to cancel", str(app.query_one("#status", Static).content))

      await async_sleep(0.25)
      await pilot.pause()
      self.assertFalse(app._is_view_rerendering())
      self.assertIn("line 1 col 1", str(app.query_one("#status", Static).content))
      self.assertEqual(app._content_width(), 110)

  async def test_content_width_matches_actual_content_pane_width(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=30)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      self.assertEqual(app._content_width(), content.size.width)

  async def test_v_toggles_current_multi_pane_focus(self) -> None:
    app = TwebBrowserApp(str(CSS_EXTERNAL_GRID), width=40)

    async with app.run_test(size=(40, 20)) as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      self.assertIn("Main content", content.content.plain)
      self.assertIn("line.", content.content.plain)
      self.assertIn("Sidebar top.", content.content.plain)
      self.assertIn("|", content.content.plain)

      app.cursor_index = app.current_page.rendered.index("Main content")
      app._sync_cursor()
      line_col_before_focus = app.current_page.buffer.line_col(app.cursor_index)
      await pilot.press("v")
      await pilot.pause()

      self.assertIn("Main content", content.content.plain)
      self.assertIn("Second content", content.content.plain)
      self.assertNotIn("Sidebar top.", content.content.plain)
      self.assertNotIn("|", content.content.plain)
      focused_line_index, _ = app.current_page.buffer.line_col(app.cursor_index)
      focused_line = app.current_page.buffer.text.splitlines()[focused_line_index]
      self.assertIn("Main content", focused_line)
      self.assertIn("focused current pane", str(app.query_one("#status", Static).content))

      line_col_before_restore = app.current_page.buffer.line_col(app.cursor_index)
      await pilot.press("v")
      await pilot.pause()

      self.assertIn("Main content", content.content.plain)
      self.assertIn("Sidebar top.", content.content.plain)
      self.assertIn("|", content.content.plain)
      self.assertEqual(app.current_page.buffer.line_col(app.cursor_index)[0], line_col_before_restore[0])
      self.assertIn("restored all panes", str(app.query_one("#status", Static).content))

  async def test_v_restore_keeps_full_page_links(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=40)
    resource = Resource(
      source="grid-links",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div><a href="/left">Left link</a></div>
            <div><a href="/right">Right link</a></div>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(40, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      result = render_normal_with_metadata(document.document, width=40, link_style="none", text_styles=False)
      rendered = result.text
      links = [Link(text=text, href=href) for text, href in collect_visible_links(document.document, width=40)]
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=links,
        controls=[],
        is_partial=False,
        link_metadata=result.link_spans,
      )
      app.cursor_index = rendered.index("Left link")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()
      await pilot.press("v")
      await pilot.pause()

      self.assertEqual(len(app.current_page.links), 2)
      self.assertEqual(app.current_page.buffer.link_at(app.current_page.rendered.index("Left link")).href, "/left")
      self.assertEqual(app.current_page.buffer.link_at(app.current_page.rendered.index("Right link")).href, "/right")

  async def test_v_handles_literal_pipe_inside_left_pane_text(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=50)
    resource = Resource(
      source="grid-pipe-text",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>
              <p>Delete article | close</p>
              <p>Left note.</p>
            </div>
            <div>
              <h2>Heading</h2>
              <p>Main content line one.</p>
              <p>Main content line two.</p>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(50, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=50, link_style="none", text_styles=False)
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      app.cursor_index = app.current_page.rendered.index("Delete article")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()

      content = app.query_one("#content", Static)
      self.assertIn("Delete article | close", content.content.plain)
      self.assertNotIn("Main content line one.", content.content.plain)
      self.assertIn("focused current pane", str(app.query_one("#status", Static).content))

  async def test_v_on_qiita_like_tag_line_keeps_article_body(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=70)
    resource = Resource(
      source="qiita-tag-line",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>
              <p>(Like)</p>
              <p>(Post)</p>
              <p>(more_horiz)</p>
            </div>
            <main>
              <article>
                <div>
                  <p>Author Name</p>
                  <h1>AWS Microcredentialsを全部取得したので勉強方法と難易度をまとめてみた</h1>
                  <p>AWS 合格体験記 AWS認定資格 SkillBuilder</p>
                  <p>Last updated at 2026-07-07</p>
                </div>
                <section>
                  <h2>はじめに</h2>
                  <p>本文がここに続きます。</p>
                </section>
              </article>
            </main>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(70, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(
        document.document,
        width=app._content_width(),
        link_style="none",
        text_styles=False,
      )
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      self.assertIsNotNone(app.current_page.source_pane_groups)
      pane_target = app.current_page.source_pane_groups[0][1]
      root = document.document.body or document.document.root
      pane_node = _element_node_at_path(root, pane_target.path)
      self.assertIsNotNone(pane_node)
      article_path = pane_target.path
      article_node = pane_node
      if pane_node.tag == "main":
        article_index = next(index for index, child in enumerate(pane_node.children) if isinstance(child, ElementNode))
        article_path = pane_target.path + (article_index,)
        article_node = pane_node.children[article_index]
      header_index = next(index for index, child in enumerate(article_node.children) if isinstance(child, ElementNode))
      header_path = article_path + (header_index,)
      line_snippet = "AWS 合格体験記 AWS認定資格 SkillBuilder"
      focused_path = _promote_leading_metadata_match_path(
        document.document,
        root,
        header_path,
        line_snippet,
        minimum_path=article_path,
        width=app._content_width(),
        session=app.session,
      )
      self.assertEqual(focused_path, article_path)
      focused_node = _element_node_at_path(root, focused_path)
      focused_rendered = render_normal_subtree(
        document.document,
        focused_node,
        width=app._content_width(),
        link_style="none",
        text_styles=False,
        include_title=False,
        session=app.session,
      )
      self.assertIn("AWS 合格体験記 AWS認定資格 SkillBuilder", focused_rendered)
      self.assertIn("## はじめに", focused_rendered)
      self.assertIn("本文がここに続きます。", focused_rendered)
      self.assertNotIn("(Like)", focused_rendered)
      self.assertNotIn("|", focused_rendered)

  async def test_v_uses_matching_right_pane_when_multi_pane_sections_run_together(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="stacked-grid",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>Left header</div>
            <div>Right header</div>
          </div>
          <div style="display:flex">
            <div>
              <p>Left rail</p>
              <p>Left rail detail</p>
            </div>
            <div>
              <h2>Main heading</h2>
              <p>Main body line one.</p>
              <p>Main body line two.</p>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=60, link_style="none", text_styles=False)
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      app.cursor_index = app.current_page.rendered.index("Main heading")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()

      content = app.query_one("#content", Static)
      self.assertIn("Main heading", content.content.plain)
      self.assertIn("Main body line one.", content.content.plain)
      self.assertNotIn("Right header", content.content.plain)
      self.assertNotIn("Left rail", content.content.plain)
      self.assertIn("focused current pane", str(app.query_one("#status", Static).content))

  async def test_v_hides_top_meta_when_cursor_is_in_deeper_right_pane_content(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="nested-right-pane",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>
              <p>Left rail</p>
            </div>
            <div>
              <article>
                <div>Info banner</div>
                <div>Author block</div>
                <section>
                  <h2>Main heading</h2>
                  <p>Main body line one.</p>
                  <p>Main body line two.</p>
                </section>
              </article>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=60, link_style="none", text_styles=False)
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      app.cursor_index = app.current_page.rendered.index("Main heading")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()

      content = app.query_one("#content", Static)
      self.assertTrue(content.content.plain.startswith("## Main heading"))
      self.assertIn("Main heading", content.content.plain)
      self.assertIn("Main body line one.", content.content.plain)
      self.assertNotIn("Info banner", content.content.plain)
      self.assertNotIn("Author block", content.content.plain)
      self.assertNotIn("Left rail", content.content.plain)

  async def test_v_title_line_ignores_document_title_when_finding_pane(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="title-match-pane",
      content="""
      <html>
        <head>
          <title>Article Focus Title</title>
        </head>
        <body>
          <div style="display:flex">
            <div>
              <p>Site nav</p>
            </div>
            <div>
              <p>search</p>
              <p>Login</p>
            </div>
          </div>
          <div style="display:flex">
            <div>
              <p>Share links</p>
            </div>
            <div>
              <article>
                <div>
                  <h1>Article Focus Title</h1>
                  <p>Tag row</p>
                </div>
                <section>
                  <p>Main body line one.</p>
                  <p>Main body line two.</p>
                </section>
              </article>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=60, link_style="none", text_styles=False)
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      app.cursor_index = rendered.rindex("Article Focus Title")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()

      content = app.query_one("#content", Static)
      self.assertIn("Article Focus Title", content.content.plain)
      self.assertIn("Main body line one.", content.content.plain)
      self.assertNotIn("search", content.content.plain)
      self.assertNotIn("Login", content.content.plain)
      self.assertNotIn("Share links", content.content.plain)

  async def test_v_keeps_neighboring_body_content_when_cursor_is_on_paragraph(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="nested-right-pane-paragraph",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>
              <p>Left rail</p>
            </div>
            <div>
              <article>
                <div>Info banner</div>
                <section>
                  <h2>Main heading</h2>
                  <p>Main body line one.</p>
                  <p>Main body line two.</p>
                </section>
              </article>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=60, link_style="none", text_styles=False)
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      app.cursor_index = app.current_page.rendered.index("Main body line one.")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()

      content = app.query_one("#content", Static)
      self.assertIn("Main heading", content.content.plain)
      self.assertIn("Main body line one.", content.content.plain)
      self.assertIn("Main body line two.", content.content.plain)
      self.assertNotIn("Info banner", content.content.plain)
      self.assertNotIn("Left rail", content.content.plain)
      self.assertEqual(len(app.current_page.buffer.block_regions), 1)

  async def test_v_collapses_focused_body_even_with_nested_two_column_content(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="nested-right-pane-with-nested-grid",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>
              <p>Left rail</p>
            </div>
            <div>
              <article>
                <section>
                  <h2>Main heading</h2>
                  <p>Main body line one.</p>
                  <div style="display:grid; grid-template-columns: minmax(0, 1fr) 16ch; gap: 1ch;">
                    <div>
                      <p>Main body line two.</p>
                      <p>Main body line three.</p>
                    </div>
                    <aside>
                      <p>Nested side note</p>
                    </aside>
                  </div>
                  <p>Main body line four.</p>
                </section>
              </article>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=60, link_style="none", text_styles=False)
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      app.cursor_index = app.current_page.rendered.index("Main body line one.")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()

      content = app.query_one("#content", Static)
      self.assertIn("Main body line one.", content.content.plain)
      self.assertIn("Main body line two.", content.content.plain)
      self.assertIn("Main body line three.", content.content.plain)
      self.assertIn("Main body line four.", content.content.plain)
      self.assertNotIn("Left rail", content.content.plain)
      self.assertEqual(len(app.current_page.buffer.block_regions), 1)

  async def test_v_can_focus_article_body_below_top_menu(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="menu-above-article-body",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>
              <p>Main menu</p>
            </div>
            <div>
              <p>Tools</p>
            </div>
          </div>
          <article>
            <h2>Antioxidants</h2>
            <p>生物化学的観点に立つと、</p>
            <p>本文の続きです。</p>
          </article>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=60, link_style="none", text_styles=False)
      app.current_page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )
      app.cursor_index = app.current_page.rendered.index("生物化学的観点に立つと、")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("v")
      await pilot.pause()

      content = app.query_one("#content", Static)
      self.assertTrue(content.content.plain.startswith("## Antioxidants"))
      self.assertIn("生物化学的観点に立つと、", content.content.plain)
      self.assertIn("本文の続きです。", content.content.plain)
      self.assertNotIn("Main menu", content.content.plain)
      self.assertNotIn("Tools", content.content.plain)
      self.assertIn("focused current pane", str(app.query_one("#status", Static).content))

  async def test_full_page_merges_following_prose_into_same_pane_block(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="pane-aware-full-page-blocks",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <aside>
              <p>Left rail</p>
            </aside>
            <article>
              <h2>Main heading</h2>
              <p>Main body line one.</p>
              <p>Main body line two.</p>
              <p>Main body line three.</p>
            </article>
          </div>
        </body>
      </html>
      """,
    )

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      document = TWebDocument(parse_document(resource))
      rendered = render_normal(document.document, width=60, link_style="none", text_styles=False)
      page = app._build_browser_page(
        resource=resource,
        document=document,
        rendered=rendered,
        links=[],
        controls=[],
        is_partial=False,
      )

      self.assertEqual(
        page.buffer.block_starts,
        [
          page.rendered.index("Left rail"),
          page.rendered.index("## Main heading"),
        ],
      )
      self.assertEqual(
        page.buffer.move_block(page.rendered.index("Main body line three."), -1),
        page.rendered.index("Left rail"),
      )

  async def test_build_browser_page_reuses_source_buffer_without_pane_focus(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=60)
    resource = Resource(
      source="https://example.com/article",
      content="<html><body><main><h1>Article</h1><p>Body text.</p></main></body></html>",
    )
    document = TWebDocument(parse_document(resource))
    rendered = "# Article\n\nBody text."

    async with app.run_test(size=(60, 20)) as pilot:
      await pilot.pause()
      with patch("tweb.tui._build_render_buffer", wraps=_build_render_buffer) as build_buffer:
        page = app._build_browser_page(
          resource=resource,
          document=document,
          rendered=rendered,
          links=[],
          controls=[],
          is_partial=False,
        )

    self.assertEqual(build_buffer.call_count, 1)
    self.assertIs(page.buffer, page.source_buffer)

  async def test_title_marks_chrome_rendered_pages(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test() as pilot:
      await pilot.pause()
      app.current_page.document.browser_rendered_via_chrome = True
      app._update_content_title()
      await pilot.pause()
      title = app.query_one("#content-title", Label)
      self.assertEqual(str(title.render()), "TUI Root [Chrome auto fallback]")
      self.assertTrue(title.has_class("chrome-rendered"))

  async def test_r_toggles_render_mode_and_reloads_without_pushing_history(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test() as pilot:
      await pilot.pause()
      self.assertEqual(app.browser_render_policy, "never")
      self.assertEqual(len(app.history), 1)

      with patch.object(app, "_start_load_target") as mock_start_load_target:
        await pilot.press("r")
        await pilot.pause()

      self.assertEqual(app.browser_render_policy, "always")
      mock_start_load_target.assert_called_once_with(app.history[0], push_history=False)
      self.assertIn(
        "Manual retry: reloading",
        str(app.query_one("#status", Static).content),
      )

      app.current_page.document.browser_rendered_via_chrome = True
      with patch.object(app, "_start_load_target") as mock_start_load_target:
        await pilot.press("r")
        await pilot.pause()

      self.assertEqual(app.browser_render_policy, "never")
      mock_start_load_target.assert_called_once_with(app.history[0], push_history=False)

  async def test_r_from_auto_chrome_rendered_page_switches_to_quickjs_in_one_press(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80, browser_render_policy="auto")

    async with app.run_test() as pilot:
      await pilot.pause()
      app.current_page.document.browser_rendered_via_chrome = True
      app._update_content_title()

      with patch.object(app, "_start_load_target") as mock_start_load_target:
        await pilot.press("r")
        await pilot.pause()

      self.assertEqual(app.browser_render_policy, "never")
      mock_start_load_target.assert_called_once_with(app.history[0], push_history=False)

  async def test_r_from_auto_quickjs_page_switches_to_chrome_in_one_press(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80, browser_render_policy="auto")

    async with app.run_test() as pilot:
      await pilot.pause()
      self.assertFalse(app.current_page.document.browser_rendered_via_chrome)

      with patch.object(app, "_start_load_target") as mock_start_load_target:
        await pilot.press("r")
        await pilot.pause()

      self.assertEqual(app.browser_render_policy, "always")
      mock_start_load_target.assert_called_once_with(app.history[0], push_history=False)

  async def test_title_labels_manual_retry_chrome_page(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80, browser_render_policy="always")

    async with app.run_test() as pilot:
      await pilot.pause()
      app.current_page.document.browser_rendered_via_chrome = True
      app._update_content_title()
      await pilot.pause()
      title = app.query_one("#content-title", Label)
      self.assertEqual(str(title.render()), "TUI Root [Chrome manual retry]")

  async def test_no_images_survives_rerender_and_pane_focus(self) -> None:
    target = Path(__file__).parent / "fixtures" / "no_images.html"
    app = TwebBrowserApp(str(target), width=80, include_images=False)
    async with app.run_test() as pilot:
      await pilot.pause()
      self.assertNotIn("photo", app.current_page.rendered)
      self.assertNotIn("[image]", app.current_page.rendered)
      self.assertNotIn("Caption", app.current_page.rendered)
      app._render_current_page()
      self.assertNotIn("photo", app.current_page.rendered)
      # Focus the main subtree, using the same path used by pane navigation.
      root = app.current_page.document.document.body
      main_index = next(i for i, node in enumerate(root.children) if getattr(node, "tag", None) == "main")
      app.pane_focus_target_path = (main_index,)
      app._render_current_page()
      self.assertNotIn("photo", app.current_page.rendered)
      self.assertNotIn("Caption", app.current_page.rendered)
      self.assertEqual([link.href for link in app.current_page.links], ["/mixed"])

  async def test_tui_render_matches_normal_mode_without_links(self) -> None:
    app = TwebBrowserApp(str(CSS_EXTERNAL_GRID), width=30)

    async with app.run_test(size=(160, 20)) as pilot:
      await pilot.pause()
      expected = render_normal(
        app.current_page.document.document,
        width=app._content_width(),
        link_style="none",
        text_styles=False,
      )
      self.assertEqual(app.current_page.rendered, expected)

  async def test_cursor_moves_across_text_and_tab_jumps_links(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test() as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      first_span = next(span for span in content.content.spans if "on white" in str(span.style))
      self.assertEqual(content.content.plain[first_span.start:first_span.end], "T")

      await pilot.press("right")
      await pilot.pause()
      content = app.query_one("#content", Static)
      span = next(span for span in content.content.spans if "on white" in str(span.style))
      self.assertEqual(content.content.plain[span.start:span.end], "U")

      await pilot.press("tab")
      await pilot.pause()
      content = app.query_one("#content", Static)
      span = next(span for span in content.content.spans if "on blue" in str(span.style))
      self.assertEqual(content.content.plain[span.start:span.end], "O")
      self.assertIn("tests/fixtures/sample.html", str(app.query_one("#status", Static).content))

  async def test_cursor_can_move_into_trailing_viewport_space(self) -> None:
    rendered = "Main heading          | Sidebar\n"
    app = TwebBrowserApp(str(TUI_ROOT), width=40)

    async with app.run_test(size=(40, 8)) as pilot:
      await pilot.pause()
      app.current_page = BrowserPage(
        resource=Resource(source="grid", content=""),
        document=TWebDocument(parse_document(Resource(source="grid", content="<html><body></body></html>"))),
        rendered=rendered,
        links=[],
        controls=[],
        buffer=_build_render_buffer(rendered, [], []),
      )
      app.cursor_index = app.current_page.buffer.text.index("Sidebar") + len("Sidebar") - 1
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("right")
      await pilot.pause()

      content = app.query_one("#content", Static)
      cursor_span = next(span for span in content.content.spans if "on white" in str(span.style))
      self.assertEqual(content.content.plain[cursor_span.start:cursor_span.end], " ")
      self.assertIn("line 1 col 32", str(app.query_one("#status", Static).content))

  def test_build_render_buffer_prefers_dom_order_for_tab_navigation(self) -> None:
    rendered = "Second link\nFirst link\n"
    links = [
      Link(text="First link", href="first.html"),
      Link(text="Second link", href="second.html"),
    ]

    buffer = _build_render_buffer(
      rendered,
      links,
      [],
      interactive_keys=["link:0", "link:1"],
      link_metadata=self._metadata_links(rendered, links),
    )

    self.assertEqual(buffer.next_link_cursor(0), rendered.index("First link"))
    self.assertEqual(
      buffer.next_link_cursor(rendered.index("First link")),
      rendered.index("Second link"),
    )

  def test_build_render_buffer_tracks_current_link_with_visual_ordered_spans(self) -> None:
    rendered = "Sidebar\nMain one\nMain two\n"
    links = [
      Link(text="Main one", href="main-1.html"),
      Link(text="Main two", href="main-2.html"),
      Link(text="Sidebar", href="sidebar.html"),
    ]

    buffer = _build_render_buffer(
      rendered,
      links,
      [],
      interactive_keys=["link:0", "link:1", "link:2"],
      link_metadata=self._metadata_links(rendered, links),
    )

    self.assertEqual(buffer.link_at(rendered.index("Main one")).href, "main-1.html")
    self.assertEqual(
      buffer.next_link_cursor(rendered.index("Main one")),
      rendered.index("Main two"),
    )
    self.assertEqual(buffer.next_link_cursor(0), rendered.index("Main one"))

  def test_build_render_buffer_uses_next_interactive_after_cursor_position(self) -> None:
    rendered = "Main one\nplain text\nMain two\nSidebar\n"
    links = [
      Link(text="Main one", href="main-1.html"),
      Link(text="Main two", href="main-2.html"),
      Link(text="Sidebar", href="sidebar.html"),
    ]

    buffer = _build_render_buffer(
      rendered,
      links,
      [],
      interactive_keys=["link:0", "link:1", "link:2"],
      link_metadata=self._metadata_links(rendered, links),
    )

    self.assertEqual(
      buffer.next_link_cursor(rendered.index("plain text")),
      rendered.index("Main two"),
    )
    self.assertEqual(
      buffer.next_link_cursor(rendered.index("plain text"), reverse=True),
      rendered.index("Main one"),
    )

  def test_interactive_order_keys_includes_role_tab_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/tabs",
          content="""
          <html>
            <body>
              <div role="tablist">
                <div role="tab" id="weekday" aria-selected="true">平日</div>
                <div role="tab" id="holiday">休日</div>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()

    self.assertEqual(
      _interactive_order_keys(document, [], controls),
      ["control:weekday", "control:holiday"],
    )

  def test_build_render_buffer_tracks_links_with_css_hidden_anchor_text(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            .eyebrow { display: none; }
          </style>
        </head>
        <body>
          <nav>
            <a href="/prev"><span class="eyebrow">Previous</span><span>&laquo; prev</span></a>
            <a href="/next"><span class="eyebrow">Next</span><span>next &raquo;</span></a>
          </nav>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    result = render_normal_with_metadata(document.document, width=80, link_style="none", text_styles=False)
    rendered = result.text
    links = [Link(text=text, href=href) for text, href in collect_visible_links(document.document, width=80)]

    buffer = _build_render_buffer(
      rendered,
      links,
      [],
      interactive_keys=_interactive_order_keys(document, links, []),
      link_metadata=result.link_spans,
    )

    self.assertEqual(buffer.link_at(rendered.index("« prev")).href, "/prev")
    self.assertEqual(buffer.link_at(rendered.index("next »")).href, "/next")

  def test_build_render_buffer_tracks_overlay_card_link_by_accessible_label(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <a href="https://example.com/post" aria-label="Card title"></a>
            <div>
              <h3>Card title</h3>
              <p>Author name</p>
            </div>
          </div>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    result = render_normal_with_metadata(document.document, width=80, link_style="none", text_styles=False)
    rendered = result.text
    links = [Link(text=text, href=href) for text, href in collect_visible_links(document.document, width=80)]

    buffer = _build_render_buffer(
      rendered,
      links,
      [],
      interactive_keys=_interactive_order_keys(document, links, []),
      link_metadata=result.link_spans,
    )

    self.assertEqual(buffer.link_at(rendered.index("Card title")).href, "https://example.com/post")

  def test_build_render_buffer_uses_partial_renderer_metadata_when_link_counts_differ(self) -> None:
    rendered = "日本語\n1,503,000+ 記事\n\n- 日本語\n"
    links = [
      Link(text="Donate", href="/donate"),
      Link(text="日本語 1,503,000+ 記事", href="/ja-top"),
      Link(text="日本語", href="/ja"),
    ]

    buffer = _build_render_buffer(
      rendered,
      links,
      [],
      interactive_keys=["link:1", "link:2"],
      link_metadata=(
        RenderedLinkMetadata(
          start=0,
          end=len("日本語"),
          text="日本語",
          href="/ja-top",
          index=0,
        ),
        RenderedLinkMetadata(
          start=rendered.rindex("日本語"),
          end=rendered.rindex("日本語") + len("日本語"),
          text="日本語",
          href="/ja",
          index=1,
        ),
      ),
    )

    self.assertEqual(buffer.link_at(rendered.index("日本語")).href, "/ja-top")
    self.assertEqual(buffer.link_at(rendered.rindex("日本語")).href, "/ja")
    self.assertEqual([span.href for span in buffer.link_spans], ["/ja-top", "/ja"])

  def test_block_anchor_renderer_metadata_covers_split_lines(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            a.link-box { display: block; text-align: center; }
            a.link-box strong, a.link-box small { display: block; }
          </style>
        </head>
        <body>
          <a href="/ja" class="link-box">
            <strong>日本語</strong>
            <small>1,503,000+ 記事</small>
          </a>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    result = render_normal_with_metadata(document.document, width=80, link_style="none", text_styles=False)
    links = [Link(text=text, href=href) for text, href in collect_visible_links(document.document, width=80)]

    self.assertEqual(len(result.link_spans), len(links))

    buffer = _build_render_buffer(
      result.text,
      links,
      [],
      interactive_keys=_interactive_order_keys(document, links, []),
      link_metadata=result.link_spans,
    )

    self.assertEqual(buffer.link_at(result.text.index("日本語")).href, "/ja")
    self.assertEqual(buffer.link_at(result.text.index("1,503,000+ 記事")).href, "/ja")

  async def test_vertical_movement_updates_cursor_line(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test() as pilot:
      await pilot.pause()
      app.action_cursor_down()
      self.assertIn("line 2", str(app.query_one("#status", Static).content))

  async def test_vertical_movement_keeps_right_pane_column_across_heading_boundary(self) -> None:
    rendered = (
      "### テクノロジー          |   最強プロンプト10選【上級者編】知らないと1年分の時\n"
      "                          |   間を損しています\n"
      "- 科学・テクノロジー      | - 変わってしまう『君』に、いつでも涙する\n"
      "- コンピュータ・IT        | - 【保存版】AIをチャット画面でしか使わない会社員へ。\n"
      "- AI・機械学習            |   Xで話題の「ループエンジニアリング」実務完全ガイド\n"
      "- プログラミング          | - 【コピペOK】ChatGPTで作る雑貨風イラスト｜国旗カラ\n"
      "- ガジェット              |   ー別プロンプト\n"
      "### エンタメ              |\n"
      "                          | ### Claude\n"
      "- エンタメ全般            |\n"
      "- マンガ                  | - [保存版]Fable\n"
    )
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      app.current_page = BrowserPage(
        resource=Resource(source="note-heading-boundary", content=""),
        document=TWebDocument(parse_document(Resource(source="note-heading-boundary", content="<html><body></body></html>"))),
        rendered=rendered,
        links=[],
        controls=[],
        buffer=_build_render_buffer(rendered, [], []),
      )
      app.cursor_index = rendered.index("ー別プロンプト")
      app.viewport_line = 0
      app._sync_cursor()
      separator_column = rendered.splitlines()[7].index("|")

      await pilot.press("down")
      self.assertEqual(app._cursor_line_col()[0], 7)
      self.assertGreater(app._cursor_line_col()[1], separator_column)

      await pilot.press("down")
      self.assertEqual(app._cursor_line_col()[0], 8)
      self.assertGreater(app._cursor_line_col()[1], separator_column)
      self.assertIn("### Claude", app.current_page.rendered.splitlines()[8])
      self.assertGreaterEqual(app.current_page.buffer.line_col(app.cursor_index)[1], rendered.splitlines()[8].index("### Claude"))

  async def test_page_scroll_moves_cursor_to_top_left_of_new_view(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      initial_view = content.content.plain
      initial_status = str(app.query_one("#status", Static).content)
      app.action_page_down()
      await pilot.pause()
      self.assertNotEqual(content.content.plain, initial_view)
      self.assertNotEqual(str(app.query_one("#status", Static).content), initial_status)
      self.assertIn("line 7 col 1", str(app.query_one("#status", Static).content))
      self.assertIn("col 1", str(app.query_one("#status", Static).content))
      first_span = content.content.spans[0]
      self.assertEqual(first_span.start, 0)
      app.action_page_up()
      await pilot.pause()
      self.assertIn("line 1 col 1", str(app.query_one("#status", Static).content))
      self.assertIn("# TUI Long", content.content.plain)

  async def test_ctrl_l_redraws_and_centers_cursor_line(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      await pilot.press("/")
      await pilot.pause()
      search_input = app.screen.query_one("#search-input", TextArea)
      search_input.load_text("Line thirty")
      await pilot.press("enter")
      await pilot.pause()
      cursor_line, _ = app.current_page.buffer.line_col(app.cursor_index)
      viewport_height = app._viewport_height()
      max_viewport_line = max(0, len(app.current_page.buffer.line_starts) - viewport_height)
      expected_viewport_line = min(max(0, cursor_line - (viewport_height // 2)), max_viewport_line)

      await pilot.press("ctrl+l")
      await pilot.pause()

      self.assertEqual(app.viewport_line, expected_viewport_line)
      self.assertIn(
        f"line {cursor_line + 1} col 1",
        str(app.query_one("#status", Static).content),
      )
      self.assertIn("Line thirty for scrolling.", app.query_one("#content", Static).content.plain)

  async def test_escape_v_triggers_meta_page_up(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      app.action_page_down()
      await pilot.pause()
      self.assertIn("line 7 col 1", str(app.query_one("#status", Static).content))
      app.on_key(events.Key("escape", None))
      app.on_key(events.Key("v", "v"))
      self.assertIn("line 1 col 1", str(app.query_one("#status", Static).content))
      self.assertIn("# TUI Long", content.content.plain)

  async def test_option_v_character_triggers_page_up(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      app.action_page_down()
      await pilot.pause()
      self.assertIn("line 7 col 1", str(app.query_one("#status", Static).content))
      app.on_key(events.Key("√", "√"))
      self.assertIn("line 1 col 1", str(app.query_one("#status", Static).content))
      self.assertIn("# TUI Long", content.content.plain)

  async def test_escape_angle_brackets_jump_to_top_and_bottom(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 9)) as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      initial_view = content.content.plain
      last_line = len(app.current_page.buffer.line_starts)
      app.on_key(events.Key("escape", None))
      app.on_key(events.Key(">", ">"))
      self.assertIn(f"line {last_line}", str(app.query_one("#status", Static).content))
      self.assertNotEqual(content.content.plain, initial_view)
      self.assertIn("Line thirty for scrolling.", content.content.plain)
      app.on_key(events.Key("escape", None))
      app.on_key(events.Key("<", "<"))
      self.assertIn("line 1 col 1", str(app.query_one("#status", Static).content))
      self.assertEqual(content.content.plain, initial_view)

  async def test_escape_shift_comma_and_period_are_supported(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 9)) as pilot:
      await pilot.pause()
      content = app.query_one("#content", Static)
      initial_view = content.content.plain
      last_line = len(app.current_page.buffer.line_starts)
      app.on_key(events.Key("escape", None))
      app.on_key(events.Key("left_shift", None))
      app.on_key(events.Key(".", "."))
      self.assertIn(f"line {last_line}", str(app.query_one("#status", Static).content))
      self.assertNotEqual(content.content.plain, initial_view)
      self.assertIn("Line thirty for scrolling.", content.content.plain)
      app.on_key(events.Key("escape", None))
      app.on_key(events.Key("left_shift", None))
      app.on_key(events.Key(",", ","))
      self.assertIn("line 1 col 1", str(app.query_one("#status", Static).content))
      self.assertTrue(content.content.plain.startswith("TUI Long"))

  async def test_escape_cancels_loading(self) -> None:
    class SlowLoadApp(TwebBrowserApp):
      def _build_page(
        self,
        request,
        *,
        initial_block_budget: int | None = None,
        scripts: list[str] | None = None,
      ):
        worker = self.loading_worker
        for _ in range(50):
          sleep(0.01)
          if worker is not None and worker.cancelled_event.is_set():
            raise FetchCancelled("cancelled in test")
        return super()._build_page(
          request,
          initial_block_budget=initial_block_budget,
          scripts=scripts,
        )

    app = SlowLoadApp(str(TUI_ROOT), width=80)
    app.pending_scripts = []

    async with app.run_test() as pilot:
      app._start_load_target(str(TUI_ROOT), push_history=True)
      await pilot.pause()
      await pilot.press("escape")
      await pilot.pause()
      self.assertIn("Loading cancelled", str(app.query_one("#status", Static).content))

  async def test_status_shows_loading_phase_updates(self) -> None:
    class DeferredLoadApp(TwebBrowserApp):
      def on_mount(self) -> None:
        return

    app = DeferredLoadApp(str(TUI_ROOT), width=80)

    def fake_fetch_resource(
      target: str,
      encoding: str | None = None,
      cancelled_event=None,
      on_status=None,
      session=None,
      method: str = "get",
      form_data=None,
    ) -> Resource:
      del encoding
      del cancelled_event
      del session
      del method
      del form_data
      if on_status is not None:
        on_status(f"Connecting {target}...")
      sleep(0.03)
      if on_status is not None:
        on_status(f"Downloading {target}... 128 bytes")
      sleep(0.03)
      return Resource(source=target, content=TUI_ROOT.read_text())

    with patch("tweb.tui.fetch_resource", side_effect=fake_fetch_resource):
      async with app.run_test() as pilot:
        app._start_load_target(str(TUI_ROOT), push_history=True)
        interim_status = str(app.query_one("#status", Static).content)
        self.assertIn("Connecting", interim_status)
        self.assertRegex(interim_status, r"\(\d+s\) Esc to cancel")
        self.assertIn("Esc to cancel", interim_status)
        for _ in range(150):
          await async_sleep(0.03)
          await pilot.pause()
          status = str(app.query_one("#status", Static).content)
          if (
            app.loading_worker is None
            and app.background_render_worker is None
            and "line 1 col 1" in status
          ):
            break
        self.assertIsNone(app.loading_worker)
        self.assertIsNone(app.background_render_worker)
        await pilot.pause()
        self.assertIn("line 1 col 1", str(app.query_one("#status", Static).content))

  async def test_initial_partial_render_is_replaced_by_full_content(self) -> None:
    class PartialRenderApp(TwebBrowserApp):
      def _initial_render_block_budget(self) -> int | None:
        return 2

      def _build_background_render_result(self, document):
        sleep(0.2)
        return super()._build_background_render_result(document)

    app = PartialRenderApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      self.assertTrue(app.current_page.is_partial)
      self.assertNotIn("Line thirty for scrolling.", app.current_page.rendered)
      self.assertRegex(str(app.query_one("#status", Static).content), r"rendering more\.\.\. \(\d+s\)")

      await async_sleep(0.25)
      await pilot.pause()
      self.assertFalse(app.current_page.is_partial)
      self.assertIn("Line thirty for scrolling.", app.current_page.rendered)

  async def test_escape_cancels_background_rendering(self) -> None:
    class PartialRenderApp(TwebBrowserApp):
      def _initial_render_block_budget(self) -> int | None:
        return 2

      def _build_background_render_result(self, document):
        sleep(0.2)
        return super()._build_background_render_result(document)

    app = PartialRenderApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      self.assertTrue(app.current_page.is_partial)
      self.assertRegex(str(app.query_one("#status", Static).content), r"rendering more\.\.\. \(\d+s\)")

      await pilot.press("escape")
      await pilot.pause()
      self.assertFalse(app.current_page.is_partial)
      self.assertNotIn("Line thirty for scrolling.", app.current_page.rendered)
      self.assertIn("rendering cancelled", str(app.query_one("#status", Static).content))

  async def test_navigation_key_cancels_background_rendering(self) -> None:
    class PartialRenderApp(TwebBrowserApp):
      def _initial_render_block_budget(self) -> int | None:
        return 2

      def _build_background_render_result(self, document):
        sleep(0.2)
        return super()._build_background_render_result(document)

    app = PartialRenderApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      self.assertTrue(app.current_page.is_partial)
      self.assertRegex(str(app.query_one("#status", Static).content), r"rendering more\.\.\. \(\d+s\)")

      await pilot.press("down")
      await pilot.pause()
      self.assertIsNone(app.background_render_worker)
      self.assertFalse(app.current_page.is_partial)
      self.assertEqual(app._cursor_line_col()[0], 1)
      self.assertNotIn("Line thirty for scrolling.", app.current_page.rendered)
      self.assertNotIn("rendering more...", str(app.query_one("#status", Static).content))

      await async_sleep(0.25)
      await pilot.pause()
      self.assertNotIn("Line thirty for scrolling.", app.current_page.rendered)

  async def test_cookie_challenge_reload_updates_tui_resource_and_body(self) -> None:
    target = "https://example.com/news"
    challenge = Resource(source=target, status_code=307, content="""
      <html><title>You are being redirected...</title>
      <script>document.cookie = 'ready=1; Path=/'; location.reload();</script></html>
    """)
    article = Resource(source=target, status_code=200, content="""
      <html><title>News</title><body><article><h1>Article loaded</h1><p>News body</p></article></body></html>
    """)
    app = TwebBrowserApp(target, width=80, browser_render_policy="never")
    with patch("tweb.tui.fetch_resource", return_value=challenge), patch("tweb.api.fetch_resource", return_value=article):
      async with app.run_test() as pilot:
        await pilot.pause()
        self.assertIsNotNone(app.current_page)
        self.assertEqual(app.current_page.resource.status_code, 200)
        self.assertEqual(app.current_page.resource.content, article.content)
        self.assertIn("Article loaded", app.current_page.rendered)
        self.assertNotIn("You are being redirected", app.current_page.rendered)

  async def test_build_page_reuses_session_for_navigation(self) -> None:
    session = Mock()
    app = TwebBrowserApp(str(TUI_ROOT), width=80, session=session)

    with patch(
      "tweb.tui.fetch_resource",
      return_value=Resource(source=str(TUI_ROOT), content=TUI_ROOT.read_text()),
    ) as mock_fetch_resource:
      async with app.run_test() as pilot:
        await pilot.pause()
        self.assertIs(app.session, session)
        self.assertIs(mock_fetch_resource.call_args.kwargs["session"], session)

  async def test_submit_button_posts_form_data(self) -> None:
    class DeferredLoadApp(TwebBrowserApp):
      def on_mount(self) -> None:
        return

    app = DeferredLoadApp(str(ROOT / "tests" / "fixtures" / "form_post.html"), width=80)

    def fake_fetch_resource(
      target: str,
      encoding: str | None = None,
      cancelled_event=None,
      on_status=None,
      session=None,
      method: str = "get",
      form_data=None,
    ) -> Resource:
      del encoding
      del cancelled_event
      del session
      if on_status is not None:
        on_status(f"Connecting {target}...")
      if method == "post":
        self.assertEqual(target, "https://example.com/submit")
        self.assertEqual(
          form_data,
          [("q", "hello"), ("notes", "memo"), ("category", "articles"), ("scope", "title"), ("safe", "on"), ("go", "1")],
        )
        return Resource(source=target, content="<html><body><p>posted ok</p></body></html>")
      return Resource(source=target, content=(ROOT / "tests" / "fixtures" / "form_post.html").read_text())

    with patch("tweb.tui.fetch_resource", side_effect=fake_fetch_resource) as mock_fetch_resource:
      async with app.run_test(size=(80, 20)) as pilot:
        app._start_load_target(str(ROOT / "tests" / "fixtures" / "form_post.html"), push_history=True)
        await pilot.pause()
        await pilot.pause()
        app.cursor_index = app.current_page.buffer.control_spans[-1].start
        app._sync_cursor()
        self.assertIn(
          "submit Search -> POST https://example.com/submit (application/x-www-form-urlencoded)",
          str(app.query_one("#status", Static).content),
        )

        await pilot.press("enter")
        await pilot.pause()

        self.assertEqual(app.current_page.resource.source, "https://example.com/submit")
        self.assertIn("posted ok", app.current_page.rendered)
        self.assertEqual(mock_fetch_resource.call_args.kwargs["method"], "post")
        self.assertEqual(
          mock_fetch_resource.call_args.kwargs["form_data"],
          [("q", "hello"), ("notes", "memo"), ("category", "articles"), ("scope", "title"), ("safe", "on"), ("go", "1")],
        )

  async def test_enter_toggles_checkbox_dropdown_content(self) -> None:
    app = TwebBrowserApp(str(DROPDOWN), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      self.assertIn("Main menu", app.current_page.rendered)
      self.assertNotIn("One", app.current_page.rendered)
      control_span = next(
        span for span in app.current_page.buffer.control_spans if span.control_id == "demo-menu-checkbox"
      )
      app.cursor_index = control_span.start
      app.action_open_link()
      await pilot.pause()
      self.assertIn("One", app.current_page.rendered)
      self.assertIn("Two", app.current_page.rendered)
      app.action_open_link()
      await pilot.pause()
      self.assertNotIn("One", app.current_page.rendered)

  async def test_enter_runs_javascript_anchor_handler(self) -> None:
    source = Resource(
      source="https://example.com/menu",
      content="""
      <html>
        <body>
          <aside id="menu" style="height:0;overflow:auto">
            <p>Hidden menu entry</p>
          </aside>
          <a id="menu-toggle" href="javascript:void(0);" style="display:block">Menu</a>
        </body>
      </html>
      """,
    )
    app = TwebBrowserApp(source.source, width=80, button_click_policy="dom-only")

    with patch("tweb.tui.fetch_resource", return_value=source):
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        self.assertNotIn("Hidden menu entry", app.current_page.rendered)
        button_span = next(span for span in app.current_page.buffer.control_spans if span.control_id == "menu-toggle")
        app.cursor_index = button_span.start
        app._sync_cursor()
        self.assertIn("click Menu (JS button, policy dom-only)", str(app.query_one("#status", Static).content))

        await pilot.press("enter")
        await pilot.pause()

        self.assertIn("Hidden menu entry", app.current_page.rendered)
        self.assertIn("button updated DOM", str(app.query_one("#status", Static).content))

  async def test_enter_same_page_fragment_jumps_without_reloading(self) -> None:
    source = self._freebsd_fragment_source()
    app = TwebBrowserApp(source.source, width=80)

    with patch("tweb.tui.fetch_resource", return_value=source) as mock_fetch_resource:
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        link_span = next(span for span in app.current_page.buffer.link_spans if span.text == "8")
        app.cursor_index = link_span.start
        app._sync_cursor()

        await pilot.press("enter")
        await pilot.pause()

        self.assertEqual(mock_fetch_resource.call_count, 1)
        self.assertEqual(app.current_page.resource.source, "https://example.com/freebsd#cite_note-8")
        self.assertEqual(
          [request.target for request in app.navigation_history],
          [
            "https://example.com/freebsd",
            "https://example.com/freebsd#cite_note-8",
          ],
        )
        self.assertEqual(
          [request.target for request in app.history],
          [
            "https://example.com/freebsd",
            "https://example.com/freebsd#cite_note-8",
          ],
        )
        current_line, _column = app.current_page.buffer.line_col(app.cursor_index)
        self.assertGreater(current_line, 0)
        current_text = app.current_page.buffer.text.splitlines()[current_line]
        self.assertIn("Footnote target line with FreeBSD release details.", current_text)

  async def test_initial_target_fragment_jumps_to_target_line_after_load(self) -> None:
    source = self._freebsd_fragment_source()
    app = TwebBrowserApp(f"{source.source}#cite_note-8", width=80)

    with patch("tweb.tui.fetch_resource", return_value=source) as mock_fetch_resource:
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()

        self.assertEqual(mock_fetch_resource.call_count, 1)
        self.assertEqual(app.current_page.resource.source, "https://example.com/freebsd#cite_note-8")
        self.assertEqual([request.target for request in app.navigation_history], ["https://example.com/freebsd#cite_note-8"])
        self.assertEqual([request.target for request in app.history], ["https://example.com/freebsd#cite_note-8"])
        current_line, _column = app.current_page.buffer.line_col(app.cursor_index)
        self.assertGreater(current_line, 0)
        current_text = app.current_page.buffer.text.splitlines()[current_line]
        self.assertIn("Footnote target line with FreeBSD release details.", current_text)
        self.assertFalse(app.current_page.is_partial)

  async def test_initial_target_fragment_skips_partial_render_budget(self) -> None:
    class PartialRenderApp(TwebBrowserApp):
      def _initial_render_block_budget(self) -> int | None:
        return 2

    source = self._freebsd_fragment_source()
    app = PartialRenderApp(f"{source.source}#cite_note-8", width=80)

    with patch("tweb.tui.fetch_resource", return_value=source):
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()

        self.assertFalse(app.current_page.is_partial)
        current_line, _column = app.current_page.buffer.line_col(app.cursor_index)
        current_text = app.current_page.buffer.text.splitlines()[current_line]
        self.assertIn("Footnote target line with FreeBSD release details.", current_text)

  async def test_button_type_button_runs_javascript_handler(self) -> None:
    app = TwebBrowserApp(str(BUTTON_CLICK), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      button_span = app.current_page.buffer.control_spans[-1]
      app.cursor_index = button_span.start
      app._sync_cursor()
      self.assertIn("click Log in (JS button, policy network)", str(app.query_one("#status", Static).content))
      self.assertIn("Signed out", app.current_page.rendered)

      await pilot.press("enter")
      await pilot.pause()

      self.assertEqual(app.current_page.resource.source, str(BUTTON_CLICK))
      self.assertIn("Signed in as user@example.com", app.current_page.rendered)
      self.assertIn("button updated DOM", str(app.query_one("#status", Static).content))

  async def test_button_click_reports_blocked_navigation_request(self) -> None:
    app = TwebBrowserApp(str(BUTTON_CLICK_NAVIGATION), width=80, button_click_policy="dom-only")

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      button_span = app.current_page.buffer.control_spans[-1]
      app.cursor_index = button_span.start
      app._sync_cursor()

      await pilot.press("enter")
      await pilot.pause()

      self.assertEqual(app.current_page.resource.source, str(BUTTON_CLICK_NAVIGATION))
      self.assertIn("Trying navigation", app.current_page.rendered)
      self.assertIn(
        "button requested navigation",
        str(app.query_one("#status", Static).content),
      )
      self.assertIn("blocked by dom-only policy", str(app.query_one("#status", Static).content))

  async def test_button_click_reports_dom_update_when_network_is_blocked_by_policy(self) -> None:
    source = Resource(
      source="https://example.com/account",
      content="""
      <html>
        <body>
          <h1>Button Fetch</h1>
          <p id="status">Idle</p>
          <input id="button_accept" type="button" value="Load profile">
          <script>
            document.getElementById("button_accept").addEventListener("click", (event) => {
              event.preventDefault();
              document.getElementById("status").textContent = "Submitting";
              var xhr = new XMLHttpRequest();
              xhr.open("GET", "/api/profile");
              xhr.send();
            });
          </script>
        </body>
      </html>
      """,
    )
    app = TwebBrowserApp(source.source, width=80, button_click_policy="dom-only")

    with patch("tweb.tui.fetch_resource", return_value=source):
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        button_span = app.current_page.buffer.control_spans[-1]
        app.cursor_index = button_span.start
        app._sync_cursor()

        await pilot.press("enter")
        await pilot.pause()

        self.assertEqual(app.current_page.resource.source, source.source)
        self.assertIn("Submitting", app.current_page.rendered)
        self.assertIn("button updated DOM", str(app.query_one("#status", Static).content))
        self.assertIn("skipped network GET https://example.com/api/profile under dom-only policy", str(app.query_one("#status", Static).content))

  async def test_tab_like_button_navigation_loads_target_page(self) -> None:
    source = Resource(
      source="https://example.com/timetable/railway/line-station/40-38/d1",
      content="""
      <html>
        <body>
          <div class="select-type">
            <button class="select-type-btn ek-dw-select" data-dw="2">休日</button>
          </div>
        </body>
      </html>
      """,
    )
    holiday = Resource(
      source="https://example.com/timetable/railway/line-station/40-38/d1?dw=2",
      content="""
      <html>
        <body>holiday loaded</body>
      </html>
      """,
    )
    app = TwebBrowserApp(source.source, width=80)

    with patch("tweb.tui.fetch_resource", side_effect=[source, holiday]):
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        tab_span = app.current_page.buffer.control_spans[0]
        app.cursor_index = tab_span.start
        app._sync_cursor()

        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        self.assertEqual(app.current_page.resource.source, holiday.source)
        self.assertIn("holiday loaded", app.current_page.rendered)

  async def test_tab_visits_checkbox_controls_and_highlights_them(self) -> None:
    app = TwebBrowserApp(str(DROPDOWN), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      content = app.query_one("#content", Static)
      span = next(span for span in content.content.spans if "on blue" in str(span.style))
      self.assertEqual(content.content.plain[span.start:span.end], "[")
      self.assertIn("toggle Main menu", str(app.query_one("#status", Static).content))
      self.assertIn("on blue", str(span.style))

      await pilot.press("enter")
      await pilot.pause()
      self.assertIn("One", content.content.plain)
      self.assertIn("Two", content.content.plain)

  async def test_tab_visits_form_controls_and_enter_edits_or_cycles(self) -> None:
    app = TwebBrowserApp(str(FORM), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      self.assertIn("edit Query", str(app.query_one("#status", Static).content))
      self.assertIn("[input:text q=hello]", app.current_page.rendered)

      await pilot.press("enter")
      await pilot.pause()
      self.assertIn("editing Query", str(app.query_one("#status", Static).content))
      self.assertEqual(str(app.query_one("#content-title", Label).render()), "Editing: Query")
      edit_input = app.screen.query_one("#edit-input", TextArea)
      self.assertEqual(edit_input.text, "hello")
      edit_input.load_text("hellox")
      await pilot.press("enter")
      await pilot.pause()
      self.assertIn("[input:text q=hellox]", app.current_page.rendered)
      self.assertEqual(
        str(app.query_one("#content-title", Label).render()),
        f"{app.current_page.document.title} [QuickJS]",
      )

      await pilot.press("tab")
      await pilot.pause()

      self.assertIn("edit Notes", str(app.query_one("#status", Static).content))

      await pilot.press("tab")
      await pilot.pause()
      self.assertIn("select Category", str(app.query_one("#status", Static).content))
      await pilot.press("enter")
      await pilot.pause()
      self.assertIn("[select", app.current_page.rendered)
      self.assertIn("category=Images]", app.current_page.rendered)

  async def test_popup_edit_cancel_keeps_original_text(self) -> None:
    app = TwebBrowserApp(str(FORM), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      await pilot.press("enter")
      await pilot.pause()
      app.screen.dismiss(None)
      await pilot.pause()
      self.assertIn("[input:text q=hello]", app.current_page.rendered)
      self.assertEqual(
        str(app.query_one("#content-title", Label).render()),
        f"{app.current_page.document.title} [QuickJS]",
      )

  async def test_textarea_popup_supports_newlines_and_ctrl_s_save(self) -> None:
    app = TwebBrowserApp(str(FORM), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      self.assertIn("edit Notes", str(app.query_one("#status", Static).content))

      await pilot.press("enter")
      await pilot.pause()
      edit_input = app.screen.query_one("#edit-input", TextArea)
      self.assertEqual(edit_input.text, "memo")
      edit_input.load_text("line1\nline2")
      await pilot.press("ctrl+s")
      await pilot.pause()
      notes = next(control for control in app.current_page.controls if control.name == "notes")
      self.assertEqual(notes.value, "line1\nline2")

  async def test_single_line_popup_converts_newlines_to_spaces(self) -> None:
    app = TwebBrowserApp(str(FORM), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      await pilot.press("enter")
      await pilot.pause()
      edit_input = app.screen.query_one("#edit-input", TextArea)
      edit_input.load_text("hello\nworld")
      await pilot.press("enter")
      await pilot.pause()
      self.assertIn("[input:text q=hello world]", app.current_page.rendered)

  async def test_password_popup_masks_value_and_keeps_submission_text(self) -> None:
    app = TwebBrowserApp(str(PASSWORD_FORM), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      self.assertIn("[input:password password=******]", app.current_page.rendered)
      self.assertNotIn("secret", app.current_page.rendered)
      app.cursor_index = app.current_page.buffer.first_control_cursor("password")
      app._sync_cursor()
      self.assertIn("edit Password", str(app.query_one("#status", Static).content))

      await pilot.press("enter")
      await pilot.pause()
      self.assertIn('editing Password value="******"', str(app.query_one("#status", Static).content))
      edit_input = app.screen.query_one("#edit-input", Input)
      self.assertEqual(edit_input.value, "secret")
      edit_input.value = "hunter2"
      await pilot.press("enter")
      await pilot.pause()

      self.assertIn("[input:password password=*******]", app.current_page.rendered)
      self.assertNotIn("hunter2", app.current_page.rendered)
      password = next(control for control in app.current_page.controls if control.name == "password")
      self.assertEqual(password.value, "hunter2")

  async def test_question_mark_opens_shortcut_help_popup(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("?")
      await pilot.pause()
      self.assertEqual(str(app.screen.query_one("#shortcuts-title", Label).render()), "Keyboard shortcuts")
      help_body = str(app.screen.query_one("#shortcuts-body", Static).content)
      help_footer = str(app.screen.query_one("#shortcuts-help", Static).content)
      self.assertIn("Tab / Shift-Tab", help_body)
      self.assertIn("/: find in page", help_body)
      self.assertIn("h: show history", help_body)
      self.assertIn("x: toggle normal or DOM view", help_body)
      self.assertIn("v: remove other panes or restore all panes", help_body)
      self.assertIn("?: show this help", help_body)
      self.assertEqual(help_footer, "Esc or ? closes this dialog.")
      await pilot.press("escape")
      await pilot.pause()
      await pilot.press("tab")
      await pilot.pause()
      self.assertIn("tests/fixtures/sample.html", str(app.query_one("#status", Static).content))

  async def test_o_opens_location_popup_and_loads_schemeless_url(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    def fake_fetch_resource(
      target: str,
      encoding: str | None = None,
      cancelled_event=None,
      on_status=None,
      session=None,
      method: str = "get",
      form_data=None,
    ) -> Resource:
      del encoding
      del cancelled_event
      del session
      del form_data
      if on_status is not None:
        on_status(f"Connecting {target}...")
      if target == "http://example.com":
        return Resource(source=target, content="<html><body><h1>Example Domain</h1></body></html>")
      return Resource(source=target, content=TUI_ROOT.read_text())

    with patch("tweb.tui.fetch_resource", side_effect=fake_fetch_resource):
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        self.assertIsInstance(app.screen, OpenLocationScreen)
        self.assertEqual(str(app.screen.query_one("#open-location-title", Label).render()), "Open URL or path")
        open_input = app.screen.query_one("#open-location-input", TextArea)
        self.assertEqual(open_input.text, str(TUI_ROOT))
        open_input.load_text("example.com")
        await pilot.press("enter")
        await pilot.pause()
        self.assertEqual(app.current_page.resource.source, "http://example.com")
        self.assertIn("Example Domain", app.current_page.rendered)

  async def test_o_opens_empty_location_popup_on_welcome_page(self) -> None:
    app = TwebBrowserApp(str(WELCOME_PAGE), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("o")
      await pilot.pause()
      open_input = app.screen.query_one("#open-location-input", TextArea)
      self.assertEqual(open_input.text, "")

  async def test_o_focuses_location_input_every_time(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      for _ in range(5):
        await pilot.press("o")
        await pilot.pause()
        open_input = app.screen.query_one("#open-location-input", TextArea)
        self.assertIs(app.screen.focused, open_input)
        await pilot.press("escape")
        await pilot.pause()
        self.assertNotIsInstance(app.screen, OpenLocationScreen)

  async def test_h_opens_history_popup_and_jumps_to_selected_entry(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      app = TwebBrowserApp(str(root_page), width=80)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        self.assertEqual(app.current_page.document.title, "Page 2")

        await pilot.press("h")
        await pilot.pause()
        self.assertIsInstance(app.screen, HistoryScreen)
        history_body = str(app.screen.query_one("#history-body", Static).content)
        self.assertIn("Page 2 |", history_body)
        self.assertIn("Root |", history_body)
        self.assertIn("*", history_body)

        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        self.assertEqual(app.current_page.document.title, "Root")
        self.assertEqual(
          [request.target for request in app.history],
          [str(page2), str(root_page)],
        )
        self.assertEqual(
          [request.target for request in app.navigation_history],
          [str(root_page), str(page2), str(root_page)],
        )
        self.assertEqual(app.navigation_index, 2)

        await pilot.press("b")
        await pilot.pause()
        self.assertEqual(app.current_page.document.title, "Page 2")

  async def test_h_history_popup_can_be_cancelled(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("h")
      await pilot.pause()
      self.assertIsInstance(app.screen, HistoryScreen)
      await pilot.press("escape")
      await pilot.pause()
      self.assertEqual(app.current_page.document.title, "TUI Root")
      self.assertIn("history cancelled", str(app.query_one("#status", Static).content))

  async def test_h_history_popup_scrolls_without_wrapping_long_entries(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)
    app.history = [
      LoadRequest(
        target=f"https://example.com/section/{index}/very/long/path/that/needs/truncation/{index}",
        title=f"履歴エントリ{index}のかなり長いタイトルで折り返しを防ぎたい",
      )
      for index in range(12)
    ]

    async with app.run_test(size=(60, 12)) as pilot:
      await pilot.pause()
      await pilot.press("h")
      await pilot.pause()
      self.assertIsInstance(app.screen, HistoryScreen)
      history_widget = app.screen.query_one("#history-body", Static)
      history_body = str(history_widget.content)
      self.assertEqual(len(history_body.splitlines()), 4)
      self.assertEqual(sum(1 for line in history_body.splitlines() if line.startswith(">")), 1)
      self.assertEqual(history_widget.virtual_size.height, 4)

      for _ in range(6):
        await pilot.press("down")
        await pilot.pause()

      history_widget = app.screen.query_one("#history-body", Static)
      history_body = str(history_widget.content)
      self.assertEqual(len(history_body.splitlines()), 4)
      self.assertEqual(sum(1 for line in history_body.splitlines() if line.startswith(">")), 1)
      self.assertEqual(history_widget.virtual_size.height, 4)

  async def test_persistent_history_is_loaded_before_initial_page(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      history_path = Path(tmpdir) / "history.json"
      history_path.write_text(f"{root_page}\n{page2}\n", encoding="utf-8")
      app = TwebBrowserApp(str(root_page), width=80, history_path=history_path)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        self.assertEqual(len(app.history), 2)
        self.assertEqual(app.history[0].target, str(page2))
        self.assertEqual(app.history[1].target, str(root_page))

  async def test_persistent_history_load_drops_older_duplicates(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      history_path = Path(tmpdir) / "history.json"
      history_path.write_text(f"{root_page}\n{page2}\n{root_page}\n", encoding="utf-8")
      app = TwebBrowserApp(str(root_page), width=80, history_path=history_path)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        self.assertEqual(
          [request.target for request in app.history],
          [str(page2), str(root_page)],
        )

  async def test_history_is_saved_to_config_file(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      history_path = Path(tmpdir) / "history.json"
      app = TwebBrowserApp(str(root_page), width=80, history_path=history_path)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

      self.assertEqual(
        [request.target for request in app.history],
        [str(root_page), str(page2)],
      )
      self.assertEqual(
        [request.target for request in app._read_persistent_history_requests()],
        [str(root_page), str(page2)],
      )

  async def test_history_revisit_removes_older_duplicate(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      history_path = Path(tmpdir) / "history.json"
      app = TwebBrowserApp(str(root_page), width=80, history_path=history_path)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        open_input = app.screen.query_one("#open-location-input", TextArea)
        open_input.load_text(str(root_page))
        await pilot.press("enter")
        await pilot.pause()
        self.assertEqual(
          [request.target for request in app.history],
          [str(page2), str(root_page)],
        )
        self.assertEqual(
          [request.target for request in app._read_persistent_history_requests()],
          [str(page2), str(root_page)],
        )

  async def test_quit_syncs_current_history_title_after_document_title_change(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, _page2 = self._write_history_test_pages(tmpdir)
      app = TwebBrowserApp(str(root_page), width=80, history_path=Path(tmpdir) / "history.json")

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        app.current_page.document.document.title = "Updated Root"
        with patch.object(app, "exit") as mock_exit:
          app.action_quit()
        self.assertEqual(app.history[-1].title, "Updated Root")
        self.assertEqual(app.navigation_history[app.navigation_index].title, "Updated Root")
        self.assertEqual(app._read_persistent_history_requests()[-1].title, "Updated Root")
        mock_exit.assert_called_once_with()

  async def test_popup_quit_routes_through_app_quit_title_sync(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, _page2 = self._write_history_test_pages(tmpdir)
      app = TwebBrowserApp(str(root_page), width=80, history_path=Path(tmpdir) / "history.json")

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        app.current_page.document.document.title = "Updated Root"
        with patch.object(app, "exit") as mock_exit:
          app.screen.action_quit_app()
        self.assertEqual(app.history[-1].title, "Updated Root")
        self.assertEqual(app.navigation_history[app.navigation_index].title, "Updated Root")
        self.assertEqual(app._read_persistent_history_requests()[-1].title, "Updated Root")
        mock_exit.assert_called_once_with()

  def test_history_save_keeps_disk_entries_added_before_startup_write(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      history_path = Path(tmpdir) / "history.json"
      history_path.write_text(f"{root_page}\n", encoding="utf-8")
      app = TwebBrowserApp(str(root_page), width=80, history_path=history_path)

      app._load_persistent_history()
      history_path.write_text(f"{root_page}\n{page2}\n", encoding="utf-8")
      app.history = app._dedupe_history_requests(
        app.history,
        incoming=LoadRequest(target=str(root_page)),
      )
      app.history.append(LoadRequest(target=str(root_page)))

      app._save_persistent_history()

      self.assertEqual(
        [request.target for request in app._read_persistent_history_requests()],
        [str(page2), str(root_page)],
      )

  async def test_persistent_history_load_preserves_saved_titles(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      history_path = Path(tmpdir) / "history.json"
      history_path.write_text(
        "\n".join(
          [
            f'{{"target":"{root_page}","title":"Root"}}',
            f'{{"target":"{page2}","title":"Page 2"}}',
          ]
        )
        + "\n",
        encoding="utf-8",
      )
      app = TwebBrowserApp(str(root_page), width=80, history_path=history_path)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        self.assertEqual([request.title for request in app.history], ["Page 2", "Root"])

  async def test_test_fixture_pages_are_added_to_history(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      history_path = Path(tmpdir) / "history.json"
      app = TwebBrowserApp(str(TUI_ROOT), width=80, history_path=history_path)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

      self.assertEqual(len(app.history), 2)
      self.assertEqual(app.history[0].title, "TUI Root")
      self.assertEqual(app.history[1].title, "TUI Page 2")
      self.assertTrue(history_path.exists())

  async def test_startup_on_test_fixture_page_marks_history_entry_as_current(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      root_page, page2 = self._write_history_test_pages(tmpdir)
      history_path = Path(tmpdir) / "history.json"
      history_path.write_text(f"{root_page}\n{page2}\n", encoding="utf-8")
      app = TwebBrowserApp(str(TUI_ROOT), width=80, history_path=history_path)

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        self.assertIsInstance(app.screen, HistoryScreen)
        history_body = str(app.screen.query_one("#history-body", Static).content)
        self.assertIn("* TUI Root", history_body)
        await pilot.press("enter")
        await pilot.pause()
        self.assertEqual(app.current_page.document.title, "TUI Root")

  async def test_o_accepts_immediate_typing_without_extra_pause(self) -> None:
    app = TwebBrowserApp(str(WELCOME_PAGE), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("o")
      await pilot.press("x")
      await pilot.pause()
      open_input = app.screen.query_one("#open-location-input", TextArea)
      self.assertEqual(open_input.text, "x")

  async def test_open_location_reports_empty_target(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("o")
      await pilot.pause()
      open_input = app.screen.query_one("#open-location-input", TextArea)
      open_input.load_text("   ")
      await pilot.press("enter")
      await pilot.pause()
      self.assertEqual(app.current_page.resource.source, str(TUI_ROOT))
      self.assertIn("open target is empty", str(app.query_one("#status", Static).content))

  async def test_open_location_popup_supports_cursor_movement_keys(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("o")
      await pilot.pause()
      open_input = app.screen.query_one("#open-location-input", TextArea)
      open_input.load_text("example.com")
      open_input.focus()
      open_input.cursor_location = (0, len("example.com"))
      self.assertEqual(open_input.cursor_location, (0, len("example.com")))

      app.on_key(events.Key("left", None))
      self.assertEqual(open_input.cursor_location, (0, len("example.co")))

      app.on_key(events.Key("ctrl+b", None))
      self.assertEqual(open_input.cursor_location, (0, len("example.c")))

      app.on_key(events.Key("ctrl+a", None))
      self.assertEqual(open_input.cursor_location, (0, 0))

      app.on_key(events.Key("ctrl+f", None))
      self.assertEqual(open_input.cursor_location, (0, 1))

      app.on_key(events.Key("ctrl+e", None))
      self.assertEqual(open_input.cursor_location, (0, len("example.com")))

  async def test_open_location_popup_recovers_focus_for_cursor_keys(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("o")
      await pilot.pause()
      open_input = app.screen.query_one("#open-location-input", TextArea)
      open_input.load_text("example.com")
      open_input.cursor_location = (0, len("example.com"))
      app.screen.set_focus(None)

      await pilot.press("left")
      await pilot.pause()

      self.assertIs(app.screen.focused, open_input)
      self.assertEqual(open_input.cursor_location, (0, len("example.co")))

  async def test_open_location_popup_ignores_modifier_only_keys(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("o")
      await pilot.pause()
      open_input = app.screen.query_one("#open-location-input", TextArea)
      open_input.load_text("example.com")
      open_input.cursor_location = (0, len("example.com"))

      app.on_key(events.Key("left_control", None))

      self.assertEqual(open_input.text, "example.com")
      self.assertEqual(open_input.cursor_location, (0, len("example.com")))

  async def test_s_opens_save_popup_with_default_path(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("s")
      await pilot.pause()
      self.assertIsInstance(app.screen, SavePageScreen)
      self.assertEqual(str(app.screen.query_one("#save-page-title", Label).render()), "Save visible page to")
      save_input = app.screen.query_one("#save-page-input", Input)
      self.assertEqual(save_input.value, "TUI-Root.txt")

  async def test_s_saves_current_visible_page_rendering(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    with tempfile.TemporaryDirectory() as tmpdir:
      target = Path(tmpdir) / "visible-page.txt"

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        save_input = app.screen.query_one("#save-page-input", Input)
        save_input.value = str(target)
        await pilot.press("enter")
        await pilot.pause()

      self.assertEqual(target.read_text(encoding="utf-8"), app.current_page.rendered + "\n")

  async def test_s_removes_terminal_escapes_before_saving(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    with tempfile.TemporaryDirectory() as tmpdir:
      target = Path(tmpdir) / "plain-page.txt"

      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        app.current_page = replace(
          app.current_page,
          rendered="# \x1b[1mStyled heading\x1b[22m",
        )
        await pilot.press("s")
        await pilot.pause()
        save_input = app.screen.query_one("#save-page-input", Input)
        save_input.value = str(target)
        await pilot.press("enter")
        await pilot.pause()

      self.assertEqual(target.read_text(encoding="utf-8"), "# Styled heading\n")

  async def test_s_saves_only_focused_pane_after_v(self) -> None:
    app = TwebBrowserApp(str(CSS_EXTERNAL_GRID), width=40)

    with tempfile.TemporaryDirectory() as tmpdir:
      target = Path(tmpdir) / "focused-pane.txt"

      async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        app.cursor_index = app.current_page.rendered.index("Main content")
        app._sync_cursor()
        await pilot.press("v")
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        save_input = app.screen.query_one("#save-page-input", Input)
        save_input.value = str(target)
        await pilot.press("enter")
        await pilot.pause()

      saved = target.read_text(encoding="utf-8")
      self.assertIn("Main content", saved)
      self.assertIn("Second content", saved)
      self.assertNotIn("Sidebar top.", saved)
      self.assertNotIn("|", saved)

  async def test_c_copies_current_visible_page_rendering(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    with patch("tweb.tui.subprocess.run") as mock_run:
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        self.assertIn("copied to macOS clipboard", str(app.query_one("#status", Static).content))

      mock_run.assert_called_once_with(
        ["pbcopy"],
        input=app.current_page.rendered,
        text=True,
        check=True,
      )

  async def test_c_removes_terminal_escapes_before_copying(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    with patch("tweb.tui.subprocess.run") as mock_run:
      async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        app.current_page = replace(
          app.current_page,
          rendered="# \x1b[1mStyled heading\x1b[22m",
        )
        await pilot.press("c")
        await pilot.pause()

      mock_run.assert_called_once_with(
        ["pbcopy"],
        input="# Styled heading",
        text=True,
        check=True,
      )

  async def test_c_copies_only_focused_pane_after_v(self) -> None:
    app = TwebBrowserApp(str(CSS_EXTERNAL_GRID), width=40)

    with patch("tweb.tui.subprocess.run") as mock_run:
      async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        app.cursor_index = app.current_page.rendered.index("Main content")
        app._sync_cursor()
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

      copied = mock_run.call_args.kwargs["input"]
      self.assertIn("Main content", copied)
      self.assertIn("Second content", copied)
      self.assertNotIn("Sidebar top.", copied)
      self.assertNotIn("|", copied)

  async def test_slash_does_not_open_search_while_open_location_popup_is_visible(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("o")
      await pilot.pause()
      self.assertIsInstance(app.screen, OpenLocationScreen)

      open_input = app.screen.query_one("#open-location-input", TextArea)
      open_input.load_text("")
      await pilot.press("/")
      await pilot.pause()

      self.assertIsInstance(app.screen, OpenLocationScreen)
      self.assertEqual(open_input.text, "/")

  async def test_question_mark_toggles_shortcut_help_popup(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("?")
      await pilot.pause()
      self.assertEqual(str(app.screen.query_one("#shortcuts-title", Label).render()), "Keyboard shortcuts")
      await pilot.press("?")
      await pilot.pause()
      self.assertNotIsInstance(app.screen, ShortcutHelpScreen)
      await pilot.press("tab")
      await pilot.pause()
      self.assertIn("tests/fixtures/sample.html", str(app.query_one("#status", Static).content))

  async def test_enter_does_not_close_shortcut_help_popup(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("?")
      await pilot.pause()
      await pilot.press("enter")
      await pilot.pause()
      self.assertIsInstance(app.screen, ShortcutHelpScreen)

  async def test_slash_opens_search_popup_and_jumps_to_match(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      initial_status = str(app.query_one("#status", Static).content)
      await pilot.press("/")
      await pilot.pause()
      self.assertEqual(str(app.screen.query_one("#search-title", Label).render()), "Find in page")
      search_input = app.screen.query_one("#search-input", TextArea)
      search_input.load_text("Line thirty")
      await pilot.press("enter")
      await pilot.pause()
      content = app.query_one("#content", Static)
      self.assertIn("Line thirty for scrolling.", content.content.plain)
      self.assertNotEqual(str(app.query_one("#status", Static).content), initial_status)
      self.assertIn("col 1", str(app.query_one("#status", Static).content))

      await pilot.press("/")
      await pilot.pause()
      search_input = app.screen.query_one("#search-input", TextArea)
      self.assertEqual(search_input.text, "Line thirty")
      await pilot.press("enter")
      await pilot.pause()
      self.assertIn('wrapped search "Line thirty"', str(app.query_one("#status", Static).content))

  async def test_search_is_case_insensitive(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      await pilot.press("/")
      await pilot.pause()
      search_input = app.screen.query_one("#search-input", TextArea)
      search_input.load_text("line THIRTY")
      await pilot.press("enter")
      await pilot.pause()
      content = app.query_one("#content", Static)
      self.assertIn("Line thirty for scrolling.", content.content.plain)

  async def test_n_and_p_repeat_search_matches(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      await pilot.press("/")
      await pilot.pause()
      search_input = app.screen.query_one("#search-input", TextArea)
      search_input.load_text("Line")
      await pilot.press("enter")
      await pilot.pause()
      first_status = str(app.query_one("#status", Static).content)

      await pilot.press("n")
      await pilot.pause()
      next_status = str(app.query_one("#status", Static).content)
      self.assertNotEqual(next_status, first_status)
      self.assertNotIn('wrapped search "Line"', next_status)

      await pilot.press("p")
      await pilot.pause()
      previous_status = str(app.query_one("#status", Static).content)
      self.assertEqual(previous_status, first_status)

  async def test_p_wraps_to_previous_match(self) -> None:
    app = TwebBrowserApp(str(TUI_LONG), width=30)

    async with app.run_test(size=(30, 8)) as pilot:
      await pilot.pause()
      await pilot.press("/")
      await pilot.pause()
      search_input = app.screen.query_one("#search-input", TextArea)
      search_input.load_text("Line")
      await pilot.press("enter")
      await pilot.pause()

      await pilot.press("p")
      await pilot.pause()
      status = str(app.query_one("#status", Static).content)
      self.assertIn('wrapped search "Line"', status)
      self.assertIn("line 65 col 1", status)

  async def test_search_popup_accepts_typed_text(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("/")
      await pilot.pause()
      await pilot.press("s", "a", "m", "p", "l", "e")
      await pilot.pause()
      search_input = app.screen.query_one("#search-input", TextArea)
      self.assertEqual(search_input.text, "sample")

  async def test_search_reports_no_match(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      await pilot.press("/")
      await pilot.pause()
      search_input = app.screen.query_one("#search-input", TextArea)
      search_input.load_text("missing text")
      await pilot.press("enter")
      await pilot.pause()
      self.assertIn('no match for "missing text"', str(app.query_one("#status", Static).content))

  def test_build_render_buffer_maps_links(self) -> None:
    buffer = _build_render_buffer(
      "Open sample page\nOpen page two\nOpen page three",
      [
        Link(text="Open sample page", href="sample.html"),
        Link(text="Open page two", href="tui_page2.html"),
        Link(text="Open page three", href="tui_page3.html"),
      ],
      [],
      link_metadata=self._metadata_links(
        "Open sample page\nOpen page two\nOpen page three",
        [
          Link(text="Open sample page", href="sample.html"),
          Link(text="Open page two", href="tui_page2.html"),
          Link(text="Open page three", href="tui_page3.html"),
        ],
      ),
    )
    self.assertEqual(len(buffer.link_spans), 3)
    self.assertEqual(buffer.link_spans[1].text, "Open page two")
    self.assertEqual(buffer.link_spans[1].href, "tui_page2.html")

  def test_builds_content_text_with_single_character_cursor(self) -> None:
    buffer = _build_render_buffer(
      "Open sample page\nOpen page two\nOpen page three",
      [
        Link(text="Open sample page", href="sample.html"),
        Link(text="Open page two", href="tui_page2.html"),
        Link(text="Open page three", href="tui_page3.html"),
      ],
      [],
      link_metadata=self._metadata_links(
        "Open sample page\nOpen page two\nOpen page three",
        [
          Link(text="Open sample page", href="sample.html"),
          Link(text="Open page two", href="tui_page2.html"),
          Link(text="Open page three", href="tui_page3.html"),
        ],
      ),
    )
    content = _build_content_text(buffer, buffer.link_spans[1].start)
    self.assertIsInstance(content, Text)
    self.assertEqual(content.plain, "Open sample page\nOpen page two\nOpen page three")
    link_span = next(span for span in content.spans if content.plain[span.start:span.end] == "Open page two")
    cursor_span = next(span for span in content.spans if content.plain[span.start:span.end] == "O")
    self.assertIn("underline", str(link_span.style))
    self.assertIn("cyan", str(link_span.style))
    self.assertIn("on blue", str(cursor_span.style))

  def test_builds_content_text_marks_links_as_clickable_without_cursor(self) -> None:
    buffer = _build_render_buffer(
      "Open sample page\nOpen page two\nOpen page three",
      [
        Link(text="Open sample page", href="sample.html"),
        Link(text="Open page two", href="tui_page2.html"),
        Link(text="Open page three", href="tui_page3.html"),
      ],
      [],
      link_metadata=self._metadata_links(
        "Open sample page\nOpen page two\nOpen page three",
        [
          Link(text="Open sample page", href="sample.html"),
          Link(text="Open page two", href="tui_page2.html"),
          Link(text="Open page three", href="tui_page3.html"),
        ],
      ),
    )
    content = _build_content_text(buffer, buffer.first_cursor_index())
    second_link_span = next(span for span in content.spans if content.plain[span.start:span.end] == "Open page two")
    self.assertIn("underline", str(second_link_span.style))
    self.assertIn("cyan", str(second_link_span.style))

  def test_builds_content_text_does_not_extend_link_underline_into_right_padding(self) -> None:
    buffer = _build_render_buffer(
      "Short",
      [Link(text="Short", href="short.html")],
      [],
      link_metadata=self._metadata_links("Short", [Link(text="Short", href="short.html")]),
    )

    content = _build_content_text(buffer, buffer.first_cursor_index(), viewport_width=12)

    link_span = next(span for span in content.spans if "underline" in str(span.style))
    self.assertEqual(content.plain, "Short       ")
    self.assertEqual(content.plain[link_span.start:link_span.end], "Short")

  def test_builds_content_text_clamps_multiline_link_underline_to_visible_viewport(self) -> None:
    buffer = _build_render_buffer(
      "日本語\n1,503,000+ 記事\nOther",
      [Link(text="日本語\n1,503,000+ 記事", href="/ja")],
      [],
      link_metadata=(
        RenderedLinkMetadata(
          start=0,
          end=len("日本語\n1,503,000+ 記事"),
          text="日本語\n1,503,000+ 記事",
          href="/ja",
          index=0,
        ),
      ),
    )

    first_line = _build_content_text(
      buffer,
      buffer.first_cursor_index(),
      viewport_line=0,
      viewport_height=1,
      viewport_width=20,
    )
    first_link_span = next(span for span in first_line.spans if "underline" in str(span.style))
    self.assertEqual(first_line.plain[first_link_span.start:first_link_span.end], "日本語")

    two_lines = _build_content_text(
      buffer,
      buffer.first_cursor_index(),
      viewport_line=0,
      viewport_height=2,
      viewport_width=20,
    )
    underline_slices = [
      two_lines.plain[span.start:span.end]
      for span in two_lines.spans
      if "underline" in str(span.style)
    ]
    self.assertEqual(underline_slices, ["日本語", "1,503,000+ 記事"])

  def test_builds_content_text_trims_center_aligned_link_padding_from_underline(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            a.link-box { display: block; text-align: center; }
            a.link-box strong, a.link-box small { display: block; }
          </style>
        </head>
        <body>
          <a href="/ja" class="link-box">
            <strong>日本語</strong>
            <small>1,503,000+ 記事</small>
          </a>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    result = render_normal_with_metadata(document.document, width=20, link_style="none", text_styles=False)
    links = [Link(text=text, href=href) for text, href in collect_visible_links(document.document, width=20)]
    buffer = _build_render_buffer(
      result.text,
      links,
      [],
      interactive_keys=_interactive_order_keys(document, links, []),
      link_metadata=result.link_spans,
    )

    content = _build_content_text(buffer, buffer.first_cursor_index(), viewport_width=20, viewport_height=5)

    underline_slices = [
      content.plain[span.start:span.end]
      for span in content.spans
      if "underline" in str(span.style)
    ]
    self.assertEqual(underline_slices, ["日本語", "1,503,000+ 記事"])

  def test_builds_content_text_ignores_foreign_left_column_text_when_link_wraps_in_right_column(self) -> None:
    rendered = "アラカンにもな\nもっとみる       |   れば、山も人生\n"
    original = _build_render_buffer(rendered, [], [])
    buffer = replace(
      original,
      link_spans=[
        LinkSpan(
          start=0,
          end=len("アラカンにもな\nもっとみる       |   れば、山も人生"),
          href="/article",
          text="アラカンにもなれば、山も人生も独りで歩ける",
          index=0,
        )
      ],
      link_starts=[0],
    )

    content = _build_content_text(buffer, buffer.first_cursor_index(), viewport_width=36, viewport_height=5)

    underline_slices = [
      content.plain[span.start:span.end]
      for span in content.spans
      if "underline" in str(span.style)
    ]
    self.assertEqual(underline_slices, ["アラカンにもな", "れば、山も人生"])
    self.assertIsNone(buffer.link_at(rendered.index("もっとみる")))
    self.assertEqual(buffer.link_at(rendered.index("れば、山も人生")).href, "/article")

  def test_build_render_buffer_does_not_treat_left_column_text_as_sidebar_link_target(self) -> None:
    rendered = (
      "の多様性にある。源流区間は細  | - American Packrafting\n"
      "く蛇行する技術的な川、中流域は川幅が広がり適度な瀬が  | Association Releases\n"
      "続く、下流の湿原区間は北海\n"
    )
    buffer = _build_render_buffer(
      rendered,
      [],
      [],
      link_metadata=(
        RenderedLinkMetadata(
          start=0,
          end=len(
            "の多様性にある。源流区間は細  | - American Packrafting\n"
            "く蛇行する技術的な川、中流域は川幅が広がり適度な瀬が  | Association Releases\n"
          ),
          text="American Packrafting\nAssociation Releases",
          href="/sidebar-article",
          index=0,
        ),
      ),
    )

    self.assertIsNone(buffer.link_at(rendered.index("技術的な川")))
    self.assertEqual(buffer.link_at(rendered.index("Association Releases")).href, "/sidebar-article")

  def test_builds_content_text_marks_controls_as_clickable_without_cursor(self) -> None:
    buffer = _build_render_buffer(
      "[input:text q=hello]",
      [],
      controls := [
        FormControl(
          control_id="query",
          kind="text",
          name="q",
          label="Query",
          token="[input:text q=hello]",
          value="hello",
        ),
      ],
      control_metadata=self._metadata_controls("[input:text q=hello]", controls),
    )
    content = _build_content_text(buffer, buffer.first_cursor_index())
    control_span = next(span for span in content.spans if content.plain[span.start:span.end] == "[input:text q=hello]")
    self.assertIn("bold", str(control_span.style))
    self.assertIn("magenta", str(control_span.style))

  def test_builds_content_text_colors_each_block_when_debug_enabled(self) -> None:
    rendered = "First block line\nstill first\n\n  Second block\n\nThird block"
    buffer = _build_render_buffer(rendered, [], [])

    content = _build_content_text(buffer, buffer.first_cursor_index(), debug_block_colors=True)

    first_block_span = next(span for span in content.spans if content.plain[span.start:span.end] == "First block line")
    second_block_span = next(span for span in content.spans if content.plain[span.start:span.end] == "  Second block")
    third_block_span = next(span for span in content.spans if content.plain[span.start:span.end] == "Third block")
    self.assertIn("on #1f3b4d", str(first_block_span.style))
    self.assertIn("on #1f3b4d", str(second_block_span.style))
    self.assertIn("on #1f3b4d", str(third_block_span.style))

  def test_builds_content_text_colors_grid_columns_as_separate_blocks_when_debug_enabled(self) -> None:
    rendered = (
      "Main heading          | Sidebar\n"
      "Main details          | Archive\n"
      "Still left only line  |\n"
    )
    buffer = _build_render_buffer(rendered, [], [])

    content = _build_content_text(buffer, len(buffer.text), debug_block_colors=True, viewport_width=40)

    left_block_span = next(span for span in content.spans if content.plain[span.start:span.end] == "Main heading          ")
    right_block_span = next(span for span in content.spans if content.plain[span.start:span.end].startswith(" Sidebar"))
    self.assertIn("on #1f3b4d", str(left_block_span.style))
    self.assertIn("on #3f2f4d", str(right_block_span.style))
    self.assertTrue(content.plain[right_block_span.start:right_block_span.end].endswith("        "))
    separator_spans = [
      span for span in content.spans
      if content.plain[span.start:span.end] == "|"
    ]
    self.assertFalse(any("on #" in str(span.style) for span in separator_spans))

  def test_builds_content_text_leaves_single_line_grid_separator_uncolored(self) -> None:
    rendered = "Qiita View Qiita Tech Festa 2026  | Login Signup"
    buffer = _build_render_buffer(rendered, [], [])

    content = _build_content_text(buffer, buffer.first_cursor_index(), debug_block_colors=True, viewport_width=56)

    separator_spans = [
      span for span in content.spans
      if content.plain[span.start:span.end] == "|"
    ]
    self.assertFalse(any("on #" in str(span.style) for span in separator_spans))
    left_block_span = next(span for span in content.spans if content.plain[span.start:span.end] == "Qiita View Qiita Tech Festa 2026  ")
    right_block_span = next(span for span in content.spans if content.plain[span.start:span.end].startswith(" Login Signup"))
    self.assertIn("on #1f3b4d", str(left_block_span.style))
    self.assertIn("on #3f2f4d", str(right_block_span.style))

  def test_builds_content_text_colors_right_pane_padding_before_headings_and_lists(self) -> None:
    rendered = (
      "Left rail                  | ## Main heading\n"
      "                           |\n"
      "                           | - First item\n"
    )
    buffer = _build_render_buffer(rendered, [], [])

    content = _build_content_text(buffer, len(buffer.text), debug_block_colors=True, viewport_width=56)

    heading_prefix_span = next(
      span for span in content.spans
      if content.plain[span.start:span.end].startswith(" ## Main heading")
    )
    list_prefix_span = next(
      span for span in content.spans
      if content.plain[span.start:span.end].startswith(" - First item")
    )
    self.assertIn("on #3f2f4d", str(heading_prefix_span.style))
    self.assertIn("on #3f2f4d", str(list_prefix_span.style))

  def test_build_render_buffer_maps_duplicate_control_tokens(self) -> None:
    buffer = _build_render_buffer(
      "[input:search search]\n[input:search search]",
      [],
      controls := [
        FormControl(
          control_id="searchInput",
          kind="text",
          name="search",
          label="Search Wikipedia",
          token="[input:search search]",
        ),
      ],
      control_metadata=self._metadata_controls("[input:search search]\n[input:search search]", controls),
    )
    self.assertEqual(len(buffer.control_spans), 2)
    self.assertEqual(buffer.control_spans[0].start, 0)
    self.assertEqual(buffer.control_spans[1].start, 22)

  def test_build_render_buffer_does_not_map_plain_label_occurrences_as_controls(self) -> None:
    rendered = "Chapter 39\n(3)\nChapter 43"
    buffer = _build_render_buffer(
      rendered,
      [],
      controls := [
        FormControl(
          control_id="like-count",
          kind="button",
          name="like-count",
          label="3",
          token="(3)",
          value="3",
        ),
      ],
      control_metadata=self._metadata_controls(rendered, controls),
    )

    self.assertEqual(len(buffer.control_spans), 1)
    self.assertEqual(rendered[buffer.control_spans[0].start:buffer.control_spans[0].end], "(3)")
    self.assertIsNone(buffer.control_at(rendered.index("39")))
    self.assertIsNone(buffer.control_at(rendered.rindex("43")))

  def test_build_render_buffer_does_not_map_single_character_control_labels_into_body_text(self) -> None:
    rendered = "大丈夫です\n[input:radio font_size=large]\n中くらい\n[input:radio font_size=medium checked]\n小説"
    buffer = _build_render_buffer(
      rendered,
      [],
      controls := [
        FormControl(
          control_id="font-large",
          kind="radio",
          name="font_size",
          label="大",
          token="[input:radio font_size=large]",
          value="large",
        ),
        FormControl(
          control_id="font-medium",
          kind="radio",
          name="font_size",
          label="中",
          token="[input:radio font_size=medium checked]",
          value="medium",
          checked=True,
        ),
      ],
      control_metadata=self._metadata_controls(rendered, controls),
    )

    self.assertEqual(len(buffer.control_spans), 2)
    self.assertEqual(rendered[buffer.control_spans[0].start:buffer.control_spans[0].end], "[input:radio font_size=large]")
    self.assertEqual(rendered[buffer.control_spans[1].start:buffer.control_spans[1].end], "[input:radio font_size=medium checked]")
    self.assertIsNone(buffer.control_at(rendered.index("大丈夫")))
    self.assertIsNone(buffer.control_at(rendered.index("中くらい")))

  def test_build_render_buffer_maps_single_character_links_only_at_word_boundaries(self) -> None:
    rendered = "wikipedia\ni\n"
    buffer = _build_render_buffer(
      rendered,
      [Link(text="i", href="https://example.com/info")],
      [],
      link_metadata=(RenderedLinkMetadata(
        start=rendered.rindex("i"),
        end=rendered.rindex("i") + 1,
        text="i",
        href="https://example.com/info",
        index=0,
      ),),
    )

    self.assertEqual(len(buffer.link_spans), 1)
    self.assertEqual(rendered[buffer.link_spans[0].start:buffer.link_spans[0].end], "i")
    self.assertIsNone(buffer.link_at(rendered.index("wikipedia")))
    self.assertEqual(buffer.link_at(rendered.rindex("i")).href, "https://example.com/info")

  def test_build_render_buffer_prefers_renderer_metadata_for_ambiguous_single_character_links(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content="""
        <html>
          <body>
            <a href="https://example.com/info">i</a>
            <p>wikipedia</p>
          </body>
        </html>
        """,
      )
    )
    result = render_normal_with_metadata(document, width=80, link_style="none", text_styles=False)

    buffer = _build_render_buffer(
      result.text,
      [Link(text=span.text, href=span.href) for span in result.link_spans],
      [],
      link_metadata=result.link_spans,
    )

    self.assertEqual(len(buffer.link_spans), 1)
    self.assertEqual(result.text[buffer.link_spans[0].start:buffer.link_spans[0].end], "i")
    self.assertEqual(buffer.link_at(buffer.link_spans[0].start).href, "https://example.com/info")

  def test_build_render_buffer_moves_between_blocks(self) -> None:
    rendered = "First block line\nstill first\n\n  Second block\n\nThird block"
    buffer = _build_render_buffer(rendered, [], [])

    self.assertEqual(
      buffer.block_starts,
      [
        rendered.index("First block line"),
      ],
    )
    self.assertEqual(buffer.move_block(buffer.block_starts[0], 1), buffer.block_starts[0])
    self.assertEqual(buffer.move_block(buffer.block_starts[0], -1), buffer.block_starts[0])

  def test_build_render_buffer_splits_two_column_grid_into_left_and_right_blocks(self) -> None:
    rendered = (
      "Main heading          | Sidebar\n"
      "Main details          | Archive\n"
      "Still left only line  |\n"
    )
    buffer = _build_render_buffer(rendered, [], [])

    self.assertEqual(
      buffer.block_starts,
      [
        rendered.index("Main heading"),
        rendered.index("Sidebar"),
      ],
    )
    self.assertEqual(
      buffer.move_block(rendered.index("Still left only line"), 1),
      rendered.index("Sidebar"),
    )
    self.assertEqual(
      buffer.move_block(rendered.index("Archive"), -1),
      rendered.index("Main heading"),
    )

  async def test_shift_arrow_moves_between_render_blocks(self) -> None:
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      app.current_page = BrowserPage(
        resource=Resource(source="blocks", content=""),
        document=TWebDocument(parse_document(Resource(source="blocks", content="<html><body></body></html>"))),
        rendered="First block line\nstill first\n\n  Second block\n\nThird block",
        links=[],
        controls=[],
        buffer=_build_render_buffer("First block line\nstill first\n\n  Second block\n\nThird block", [], []),
      )
      app.cursor_index = app.current_page.buffer.block_starts[0]
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("shift+down")
      self.assertEqual(app.cursor_index, app.current_page.buffer.block_starts[0])

      await pilot.press("shift+right")
      self.assertEqual(app.cursor_index, app.current_page.buffer.block_starts[0])

      await pilot.press("shift+left")
      self.assertEqual(app.cursor_index, app.current_page.buffer.block_starts[0])

      await pilot.press("shift+up")
      self.assertEqual(app.cursor_index, app.current_page.buffer.block_starts[0])

  async def test_shift_arrow_moves_from_main_column_to_sidebar_column(self) -> None:
    rendered = (
      "Main heading          | Sidebar\n"
      "Main details          | Archive\n"
      "Still left only line  |\n"
    )
    app = TwebBrowserApp(str(TUI_ROOT), width=80)

    async with app.run_test(size=(80, 20)) as pilot:
      await pilot.pause()
      app.current_page = BrowserPage(
        resource=Resource(source="grid", content=""),
        document=TWebDocument(parse_document(Resource(source="grid", content="<html><body></body></html>"))),
        rendered=rendered,
        links=[],
        controls=[],
        buffer=_build_render_buffer(rendered, [], []),
      )
      app.cursor_index = rendered.index("Still left only line")
      app.viewport_line = 0
      app._sync_cursor()

      await pilot.press("shift+right")
      self.assertEqual(app.cursor_index, rendered.index("Sidebar"))

      await pilot.press("shift+left")
      self.assertEqual(app.cursor_index, rendered.index("Main heading"))


class TuiPageAssemblyTest(unittest.TestCase):
  def setUp(self) -> None:
    self.app = TwebBrowserApp("unused", width=80)
    self.resource = Resource(source="grid", content='<body><div style="display:grid;grid-template-columns:1fr 1fr">'
      '<main><h2>Article</h2><p>Article body.</p><a href="/article">Article link</a></main>'
      '<aside><p>Sidebar</p><a href="/side">Side link</a></aside></div></body>')
    self.document = TWebDocument(parse_document(self.resource))

  def build(self, *, width=80, source_page=None, focus=None):
    rendered, links, controls, lm, cm = self.app._render_document(self.document, content_width=width)
    return self.app._build_browser_page(
      resource=self.resource, document=self.document, rendered=rendered,
      links=links, controls=controls, link_metadata=lm, control_metadata=cm,
      content_width=width, source_page=source_page, pane_focus_target_path=focus,
      is_partial=False,
    )

  def test_toggle_reuses_panes_metadata_and_restores_full_buffer(self) -> None:
    page = self.build()
    self.assertTrue(page.source_pane_groups)
    focus = next(path for path, result in page.pane_render_cache.items() if "Article body." in result.text)
    with patch("tweb.tui.collect_two_pane_targets", side_effect=AssertionError("repeated detection")), patch(
      "tweb.tui.render_normal_subtree_with_metadata", side_effect=AssertionError("repeated pane render"),
    ):
      focused = self.build(source_page=page, focus=focus)
      restored = self.build(source_page=focused)
    self.assertIs(focused.source_buffer, page.source_buffer)
    self.assertIs(restored.buffer, page.buffer)
    self.assertEqual(restored.links, page.links)
    self.assertEqual(restored.source_control_metadata, page.source_control_metadata)
    self.assertNotIn("Sidebar", focused.rendered)
    self.assertTrue(focused.buffer.link_spans)

  def test_resize_discards_pane_render_cache(self) -> None:
    page = self.build()
    resized = self.build(width=60, source_page=page)
    self.assertIsNot(resized.source_buffer, page.source_buffer)
    self.assertIsNot(resized.pane_render_cache, page.pane_render_cache)
    self.assertEqual(resized.content_width, 60)

  def test_image_policy_change_discards_pane_render_cache(self) -> None:
    page = self.build()
    self.app.include_images = False
    updated = self.build(source_page=page)
    self.assertEqual(updated.rendered, page.rendered)
    self.assertIsNot(updated.pane_render_cache, page.pane_render_cache)
    self.assertFalse(updated.include_images)

  def test_mutation_rerender_refreshes_pane_text(self) -> None:
    page = self.build()
    self.document.document.find_first("p").set_text_content("Changed article body.")
    updated = self.build()
    self.assertIn("Changed article body.", updated.rendered)
    self.assertIsNot(updated.pane_render_cache, page.pane_render_cache)
    self.assertTrue(any("Changed article body." in result.text for result in updated.pane_render_cache.values()))

  def test_phase_timings_are_observable(self) -> None:
    with self.assertLogs("tweb", level="DEBUG") as logs:
      page = self.build()
    for name in ("page_build", "source_buffer", "pane_detection", "display_buffer", "pane_regions"):
      self.assertGreaterEqual(page.build_timings_ms[name], 0)
      self.assertTrue(any("phase=" + name + " " in line for line in logs.output))
    self.assertTrue(any("phase=renderer " in line for line in logs.output))
    self.assertTrue(any("phase=controls_and_links " in line for line in logs.output))

  def test_cancelled_assembly_stops_before_pane_detection(self) -> None:
    worker = Mock()
    worker.cancelled_event.is_set.side_effect = [False, True]
    with patch("tweb.tui.get_current_worker", return_value=worker), patch(
      "tweb.tui.collect_two_pane_targets", side_effect=AssertionError("work after cancel"),
    ):
      with self.assertRaises(FetchCancelled):
        self.build()


class TuiCliWidthTest(unittest.TestCase):
  @patch("tweb.tui.TwebBrowserApp")
  @patch("tweb.tui.shutil.get_terminal_size", return_value=os.terminal_size((132, 24)))
  def test_run_tui_browser_uses_terminal_width_when_omitted(
    self,
    mock_terminal_size: Mock,
    mock_app_class: Mock,
  ) -> None:
    mock_app = mock_app_class.return_value
    mock_app.session = Mock()

    result = run_tui_browser(str(TUI_ROOT))

    self.assertEqual(result, 0)
    mock_terminal_size.assert_called_once_with(fallback=(80, 24))
    mock_app_class.assert_called_once_with(
      str(TUI_ROOT),
      encoding=None,
      width=132,
      scripts=None,
      session=None,
      browser_render_policy="never",
      button_click_policy="network",
      use_script_cache=True,
      debug_block_colors=False,
      include_images=True,
      history_path=Path("~/.config/tw/history.json").expanduser(),
    )
    mock_app.run.assert_called_once_with()
    mock_app.session.close.assert_called_once_with()

  @patch("tweb.tui.TwebBrowserApp")
  @patch("tweb.tui.shutil.get_terminal_size")
  def test_run_tui_browser_keeps_explicit_width(
    self,
    mock_terminal_size: Mock,
    mock_app_class: Mock,
  ) -> None:
    mock_app = mock_app_class.return_value
    mock_app.session = Mock()

    result = run_tui_browser(str(TUI_ROOT), width=91)

    self.assertEqual(result, 0)
    mock_terminal_size.assert_not_called()
    self.assertEqual(mock_app_class.call_args.kwargs["width"], 91)
    mock_app.session.close.assert_called_once_with()

  @patch("tweb.tui.TwebBrowserApp")
  @patch("tweb.tui.shutil.get_terminal_size", return_value=os.terminal_size((132, 24)))
  def test_run_tui_browser_handles_keyboard_interrupt_via_app_quit(
    self,
    mock_terminal_size: Mock,
    mock_app_class: Mock,
  ) -> None:
    mock_app = mock_app_class.return_value
    mock_app.session = Mock()
    mock_app.run.side_effect = KeyboardInterrupt()

    result = run_tui_browser(str(TUI_ROOT))

    self.assertEqual(result, 130)
    mock_terminal_size.assert_called_once_with(fallback=(80, 24))
    mock_app.action_quit.assert_called_once_with()
    mock_app.session.close.assert_called_once_with()

  @patch("tweb.tui.shutil.get_terminal_size", return_value=os.terminal_size((132, 24)))
  def test_resolve_width_uses_terminal_width_when_omitted(self, mock_terminal_size: Mock) -> None:
    self.assertEqual(_resolve_width(None), 132)
    mock_terminal_size.assert_called_once_with(fallback=(80, 24))

  @patch("tweb.tui.shutil.get_terminal_size")
  def test_resolve_width_skips_terminal_lookup_when_width_is_explicit(self, mock_terminal_size: Mock) -> None:
    self.assertEqual(_resolve_width(91), 91)
    mock_terminal_size.assert_not_called()
