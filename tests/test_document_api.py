from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from requests import Request
from requests.cookies import RequestsCookieJar

import tweb.api as api_module
import tweb.interactions as interactions_module
from tweb.api import (
  AgentActionRequest,
  HydrationSection,
  TWebDocument,
  _ExecutionDocumentMetrics,
  _augment_sparse_body_from_hydration,
  _build_hydration_section_block,
  _clone_dom_node,
  _document_has_hidden_content_hint,
  _extract_sparse_document_link_sections,
  _extract_site_specific_hydration_sections,
  _linked_app_script_sources,
  _maybe_replace_with_browser_rendered_document,
  _materialize_react_bailout_segments,
  _maybe_replace_with_alternate_html_document,
  _prune_inline_loading_placeholders,
  _prune_duplicate_nav_sections,
  _replay_bootstrap_scripts,
  _runtime_has_network_payloads,
  _should_merge_sparse_document_link_sections_for_substantial_body,
  _should_replay_bootstrap_script,
  _should_dispatch_dom_content_loaded_for_static_page,
  _should_skip_expensive_page_events,
  _should_skip_delayed_external_scripts_for_static_page,
  _should_skip_large_inline_script_for_static_page,
  _should_skip_large_delayed_script_for_static_page,
  _should_restore_initial_body_after_hydration,
)
from tweb.dom import ElementNode, TextNode
from tweb.fetcher import (
  BrowserRenderRequest,
  BrowserRenderResult,
  FetchError,
  Resource,
  create_session,
  fetch_resource,
)
from tweb.interactions import register_parents_for_interactions, sync_interactive_document
from tweb.js_runtime import GLOBAL_EXTERNAL_SCRIPT_CACHE, _reset_external_script_cache_state_for_tests
from tweb.js_runtime_helpers import JavaScriptRuntimeError
from tweb.parser import parse_document
from tweb.renderers.normal import render_normal, render_normal_with_metadata
from tweb.runtime_data import _collect_payload, _expand_nuxt_data_payload
from tweb.site_specific import _extract_kakuyomu_toc_sections
from tweb.site_specific import _extract_note_home_runtime_sections
from tweb.site_specific import _extract_note_topic_runtime_sections
from tweb.site_specific import extract_hydration_sections


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample.html"
BROKEN = ROOT / "tests" / "fixtures" / "broken.html"
FORM = ROOT / "tests" / "fixtures" / "form.html"
PASSWORD_FORM = ROOT / "tests" / "fixtures" / "form_password.html"
BUTTON_CLICK = ROOT / "tests" / "fixtures" / "button_click.html"
BUTTON_CLICK_FETCH = ROOT / "tests" / "fixtures" / "button_click_fetch.html"
BUTTON_CLICK_NAVIGATION = ROOT / "tests" / "fixtures" / "button_click_navigation.html"


def load_document(path: Path) -> TWebDocument:
  return TWebDocument(parse_document(fetch_resource(str(path))))


class DocumentApiTest(unittest.TestCase):
  def setUp(self) -> None:
    super().setUp()
    self._cache_tmpdir = TemporaryDirectory()
    self._cache_env_patch = patch.dict(os.environ, {"TWEB_SCRIPT_CACHE_DIR": self._cache_tmpdir.name})
    self._cache_env_patch.start()
    _reset_external_script_cache_state_for_tests()

  def tearDown(self) -> None:
    _reset_external_script_cache_state_for_tests()
    self._cache_env_patch.stop()
    self._cache_tmpdir.cleanup()
    super().tearDown()

  def test_cookie_challenge_reload_preserves_session_and_replaces_document(self) -> None:
    source = "https://example.com/news/article"
    document = TWebDocument(parse_document(Resource(source=source, content="""
      <html><title>You are being redirected...</title>
      <script>document.cookie = 'challenge=passed; Path=/; Secure; SameSite=Lax';
      location.reload();</script></html>
    """)))
    session = create_session()

    def fetch(target, *, session):
      self.assertEqual(target, source)
      prepared = session.prepare_request(Request("GET", target))
      self.assertIn("challenge=passed", prepared.headers.get("Cookie", ""))
      return Resource(source=source, content="<html><title>News</title><body><article>Article loaded</article></body></html>", status_code=200)

    with patch("tweb.api.fetch_resource", side_effect=fetch) as fetch_mock:
      document.execute_embedded_scripts(session=session, browser_render_policy="never", ignore_errors=False)
    self.assertEqual(fetch_mock.call_count, 1)
    self.assertEqual(document.title, "News")
    self.assertIn("Article loaded", document.body_text())
    self.assertEqual(document.reloaded_resource.status_code, 200)

  def test_reload_works_without_explicit_session(self) -> None:
    document = TWebDocument(parse_document(Resource(source="https://example.com/", content="""
      <html><body>Loading<script>document.cookie = 'ready=1; Path=/'; setTimeout(() => location.reload(), 0);</script></body></html>
    """)))
    with patch("tweb.api.fetch_resource", return_value=Resource(
      source="https://example.com/", content="<html><body>Done</body></html>",
    )) as fetch_mock:
      document.execute_embedded_scripts(ignore_errors=False)
    self.assertEqual(fetch_mock.call_args.kwargs["session"].cookies.get("ready"), "1")
    self.assertIn("Done", document.body_text())

  def test_reload_loop_is_bounded_and_logged(self) -> None:
    resource = Resource(source="https://example.com/", content="<html><script>location.reload();</script></html>")
    document = TWebDocument(parse_document(resource))
    with patch("tweb.api.fetch_resource", return_value=resource) as fetch_mock, self.assertLogs("tweb", level="DEBUG") as logs:
      document.execute_embedded_scripts(ignore_errors=False)
    self.assertEqual(fetch_mock.call_count, 3)
    self.assertTrue(any("reason=reload-limit" in line for line in logs.output))

  def test_reload_button_respects_dom_only_policy(self) -> None:
    document = TWebDocument(parse_document(Resource(source="https://example.com/", content="""
      <html><body><button id="reload" type="button">Reload</button>
      <script>document.getElementById("reload").addEventListener("click", () => location.reload());</script></body></html>
    """)))
    document.execute_embedded_scripts(ignore_errors=False)
    button = next(control for control in document.form_controls() if control.kind == "button")
    result = document.click_button_control(button.control_id, policy="dom-only")
    self.assertTrue(result.blocked_by_policy)
    self.assertEqual(result.navigation_target, "https://example.com/")
    self.assertIsNone(document._js_runtime.reload_target)

  def test_trusts_only_cross_site_scripts_linked_to_a_stylesheet_asset_tree(self) -> None:
    document = TWebDocument(parse_document(Resource(
      source="https://www.example.com/",
      content="""
      <html><head>
        <link rel="preload stylesheet" href="https://cdn.example.net/app/v1/css/main.css">
        <script src="https://cdn.example.net/app/v1/js/main.js"></script>
        <script src="https://cdn.example.net/tracking/logger.js"></script>
        <script src="https://ads.example.net/app/v1/js/ad.js"></script>
        <script src="/local.js"></script>
      </head><body></body></html>
      """,
    )))

    self.assertEqual(
      _linked_app_script_sources(document),
      {"https://cdn.example.net/app/v1/js/main.js"},
    )

  def test_detects_runtime_network_payloads_as_hydration_hints(self) -> None:
    runtime = Mock()
    runtime.runtime_data_network_payloads.return_value = [{
      "url": "https://example.com/api/feed",
      "body": '{"items":[]}',
    }]

    self.assertTrue(_runtime_has_network_payloads(runtime))

  def test_expands_nuxt_data_reference_payloads(self) -> None:
    payload = [
      ["ShallowReactive", 1],
      {"data": 2, "serverRendered": 9},
      ["ShallowReactive", 3],
      {"items": 4},
      [
        {"title": 5, "href": 6},
        {"title": 7, "href": 8},
      ],
      "First notice",
      "/notice-1",
      "Second notice",
      "/notice-2",
      True,
    ]

    expanded = _expand_nuxt_data_payload(payload)

    self.assertIsInstance(expanded, dict)
    assert isinstance(expanded, dict)
    self.assertTrue(expanded["serverRendered"])
    self.assertEqual(
      expanded["data"]["items"],
      [
        {"title": "First notice", "href": "/notice-1"},
        {"title": "Second notice", "href": "/notice-2"},
      ],
    )

  def test_restores_initial_body_after_hydration_when_hydration_takes_over(self) -> None:
    document = parse_document(
      Resource(
        source="https://example.com/",
        content="""
        <html>
          <body>
            <main>
              <h1>Original article heading</h1>
              <p>This initial article body is long enough to remain preferable when hydration-only fallback text takes over the page after script execution and hides the original readable content.</p>
              <p>Additional article detail keeps the original body comfortably above the substantial-content threshold used by the restore heuristic.</p>
              <p>Further explanatory copy keeps the initial visible body safely above the restore threshold and makes the comparison robust against short hydration-only replacements.</p>
              <p>A fourth paragraph ensures the initial body remains decisively substantial even after whitespace normalization in the restore heuristic.</p>
            </main>
          </body>
        </html>
        """,
      )
    )
    initial_body_clone = _clone_dom_node(document.body)
    section = ElementNode(tag="section", attrs={"data-tweb-hydration": "1"})
    document.body.children = [section]
    heading = ElementNode(tag="h2")
    heading.append_child(TextNode(text="Hydration Data"))
    section.append_child(heading)
    paragraph = ElementNode(tag="p")
    paragraph.append_child(
      TextNode(
        text=(
          "Short fallback body text that is long enough to pass the minimum current-text threshold "
          "while still clearly representing a hydration-only takeover rather than a healthy restored article body."
        )
      )
    )
    section.append_child(paragraph)

    self.assertTrue(_should_restore_initial_body_after_hydration(document, initial_body_clone))

  def test_keeps_hydrated_app_when_mount_adds_form_controls(self) -> None:
    initial_paragraph = " ".join(f"initial portal navigation item {index}" for index in range(40))
    document = parse_document(
      Resource(
        source="https://example.com/",
        content=f"""
        <html>
          <body>
            <header>{initial_paragraph}</header>
            <main id="app"></main>
            <input type="search" name="q">
          </body>
        </html>
        """,
      )
    )
    initial_body_clone = _clone_dom_node(document.body)
    rendered_text = " ".join(f"rendered route option {index}" for index in range(30))
    rendered = parse_document(
      Resource(
        source="https://example.com/",
        content=f"""
        <html>
          <body>
            <section data-tweb-hydration="1">
              <h2>Route search</h2>
              <p>{rendered_text}</p>
              <input name="start">
              <input name="goal">
              <select name="basis"><option>Departure</option></select>
              <button>Search</button>
            </section>
          </body>
        </html>
        """,
      )
    )
    document.body.attrs = dict(rendered.body.attrs)
    document.body.children = [_clone_dom_node(child) for child in rendered.body.children]

    self.assertFalse(_should_restore_initial_body_after_hydration(document, initial_body_clone))

  @patch("tweb.api._document_visible_text")
  def test_restore_after_hydration_avoids_full_visible_probe_for_healthy_marker_body(
    self,
    mock_document_visible_text: Mock,
  ) -> None:
    paragraphs = "".join(
      (
        f"<p>Readable hydrated article paragraph {index} keeps the visible preview substantial "
        "and close to the original body so the expensive exact visible-text probe should not run.</p>"
      )
      for index in range(8)
    )
    document = parse_document(
      Resource(
        source="https://example.com/",
        content=f"""
        <html>
          <body>
            <main>
              <h1>Original article heading</h1>
              {paragraphs}
            </main>
          </body>
        </html>
        """,
      )
    )
    initial_body_clone = _clone_dom_node(document.body)
    hydrated = parse_document(
      Resource(
        source="https://example.com/",
        content=f"""
        <html>
          <body>
            <section data-tweb-hydration="1">
              <h1>Original article heading</h1>
              {paragraphs}
            </section>
          </body>
        </html>
        """,
      )
    )
    document.body.attrs = dict(hydrated.body.attrs)
    document.body.children = [_clone_dom_node(child) for child in hydrated.body.children]

    self.assertFalse(_should_restore_initial_body_after_hydration(document, initial_body_clone))
    mock_document_visible_text.assert_not_called()

  @patch("tweb.api._extract_hidden_dom_sections")
  def test_augment_hydration_skips_hidden_dom_recovery_for_substantial_link_dense_body(
    self,
    mock_extract_hidden_dom_sections: Mock,
  ) -> None:
    links = "".join(
      f'<a href="/item-{index}">Visible item {index} with enough descriptive text to count as readable content.</a>'
      for index in range(80)
    )
    controls = "".join(f'<button type="button">Control {index}</button>' for index in range(8))
    hidden = "".join(
      (
        '<section style="display:none">'
        f'<p>Hidden detail {index} with enough text to look recoverable if we chose to scan it.</p>'
        f'{links}'
        '</section>'
      )
      for index in range(4)
    )
    document = parse_document(
      Resource(
        source="https://example.com/article",
        content=f"""
        <html>
          <body>
            <main>
              <h1>Readable article</h1>
              <p>This page already contains substantial visible body text before any hidden recovery.</p>
              {links}
              {controls}
              {hidden}
            </main>
          </body>
        </html>
        """,
      )
    )
    runtime = Mock()
    runtime.runtime_data_network_payloads.return_value = []
    mock_extract_hidden_dom_sections.return_value = []

    debug = _augment_sparse_body_from_hydration(document, runtime)

    self.assertIsNotNone(debug)
    mock_extract_hidden_dom_sections.assert_not_called()

  def test_execute_embedded_scripts_restores_initial_body_after_script_clobber(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <main>
                <h1>Original article heading</h1>
                <p>This initial article body is long enough to remain preferable when runtime script execution accidentally clobbers the DOM and leaves only a tiny fragment behind.</p>
                <p>Additional article detail keeps the original body comfortably above the substantial-content threshold used by the body-clobber restore heuristic.</p>
                <p>Further explanatory copy ensures the initial page has enough links and text to look like a meaningful readable document before any scripts run.</p>
                <p><a href="/alpha">Alpha</a> <a href="/beta">Beta</a> <a href="/gamma">Gamma</a> <a href="/delta">Delta</a></p>
                <p><a href="/epsilon">Epsilon</a> <a href="/zeta">Zeta</a> <a href="/eta">Eta</a> <a href="/theta">Theta</a></p>
                <p><a href="/iota">Iota</a> <a href="/kappa">Kappa</a> <a href="/lambda">Lambda</a> <a href="/mu">Mu</a></p>
                <p><a href="/nu">Nu</a> <a href="/xi">Xi</a> <a href="/omicron">Omicron</a> <a href="/pi">Pi</a></p>
                <p><a href="/rho">Rho</a> <a href="/sigma">Sigma</a> <a href="/tau">Tau</a> <a href="/upsilon">Upsilon</a></p>
              </main>
              <script>
                document.body.innerHTML = '<div>S</div>';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=True, browser_render_policy="never")

    self.assertIn("Original article heading", document.body_text())
    self.assertIn("Alpha", document.body_text())
    self.assertNotEqual(document.body_text().strip(), "S")

  def test_initial_body_clobber_check_skips_exact_visible_scan_for_healthy_inline_preview(self) -> None:
    document = parse_document(
      Resource(
        source="https://example.com/",
        content="""
        <html>
          <body>
            <main>
              <h1>Original article heading</h1>
              <p>This visible article body remains readable after script execution and should not trigger the restore heuristic.</p>
              <p>Additional article detail keeps the current body comfortably above the tiny clobber threshold.</p>
              <p>Further explanatory copy ensures the inline preview is already enough to prove the body is healthy.</p>
              <p>A fourth paragraph makes the current page decisively substantial before any exact visible-text walk would run.</p>
            </main>
          </body>
        </html>
        """,
      )
    )
    initial_body_clone = _clone_dom_node(document.body)

    with patch("tweb.api._collect_visible_text", wraps=api_module._collect_visible_text) as mock_collect_visible_text:
      self.assertFalse(api_module._looks_like_initial_body_clobber(document, initial_body_clone))

    self.assertNotIn(
      document.body,
      [call.args[0] for call in mock_collect_visible_text.call_args_list],
    )

  def test_collect_payload_extracts_numbered_dict_sections(self) -> None:
    payload = {
      "pinia": {
        "dataCache": {
          "pageStore": {
            "hp-part-top-pickups": {
              "title": "トップパーツ（ピックアップ）",
              "props": {
                "caption1": "国立国会図書館サーチ",
                "link1": "/search",
                "image1": "/img/search.png",
                "alt1": "search",
                "caption2": "デジタルコレクション",
                "link2": "/digital",
                "image2": "/img/digital.png",
                "alt2": "digital",
              },
            },
          },
        },
      },
    }

    texts, links, sections = _collect_payload(
      payload,
      base_url="https://www.ndl.go.jp/",
      existing_links={},
    )

    self.assertIn("トップパーツ（ピックアップ）", texts)
    self.assertIn(
      HydrationSection(
        title="トップパーツ（ピックアップ）",
        items=(
          ("国立国会図書館サーチ", "/search"),
          ("デジタルコレクション", "/digital"),
        ),
        role=None,
      ),
      sections,
    )
    self.assertIn(("国立国会図書館サーチ", "/search"), {(link.text, link.href) for link in links})
    self.assertIn(("デジタルコレクション", "/digital"), {(link.text, link.href) for link in links})

  @patch("tweb.site_specific.fetch_resource", side_effect=FetchError("offline"))
  def test_extracts_note_home_runtime_sections(self, mock_fetch_resource) -> None:
    class FakeRuntime:
      def __init__(self) -> None:
        self.probe = "[]"

      def eval(self, source: str, drain_timers: bool = False):
        if 'window["__twebNoteHomeSections"] || \'[]\'' in source:
          return self.probe
        if 'window["__twebNoteHomeSections"] = JSON.stringify(sections);' in source:
          self.probe = json.dumps(
            [
              {
                "title": "フォロー中",
                "items": [
                  {"text": "First Note", "href": "/creator/n/n111"},
                  {"text": "Second Note", "href": "/creator/n/n222"},
                ],
              },
            ]
          )
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        return None

    sections = extract_hydration_sections(
      FakeRuntime(),
      "https://note.com/",
    )

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "フォロー中")
    self.assertEqual(
      sections[0].items,
      (("First Note", "/creator/n/n111"), ("Second Note", "/creator/n/n222")),
    )
    mock_fetch_resource.assert_called_once()

  @patch("tweb.site_specific.fetch_resource", side_effect=FetchError("offline"))
  def test_extracts_note_home_runtime_sections_after_pending_probe(self, mock_fetch_resource) -> None:
    class FakeRuntime:
      def __init__(self) -> None:
        self.probe = "__tweb_pending__"
        self.drain_calls = 0

      def eval(self, source: str, drain_timers: bool = False):
        if 'window["__twebNoteHomeSections"] = ' in source:
          self.probe = "__tweb_pending__"
          return None
        if 'window["__twebNoteHomeSections"] || \'[]\'' in source:
          return self.probe
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        self.drain_calls += 1
        if self.drain_calls == 3:
          self.probe = json.dumps(
            [
              {
                "title": "フォロー中",
                "items": [
                  {"text": "First Note", "href": "/creator/n/n111"},
                  {"text": "Second Note", "href": "/creator/n/n222"},
                ],
              },
            ]
          )

    runtime = FakeRuntime()
    sections = extract_hydration_sections(runtime, "https://note.com/")

    self.assertEqual(runtime.drain_calls, 3)
    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "フォロー中")
    self.assertEqual(
      sections[0].items,
      (("First Note", "/creator/n/n111"), ("Second Note", "/creator/n/n222")),
    )
    mock_fetch_resource.assert_called_once()

  @patch("tweb.site_specific.fetch_resource", side_effect=FetchError("offline"))
  def test_retries_note_home_runtime_probe_after_empty_result(self, mock_fetch_resource) -> None:
    class FakeRuntime:
      def __init__(self) -> None:
        self.probe = "[]"
        self.launches = 0

      def eval(self, source: str, drain_timers: bool = False):
        if 'window["__twebNoteHomeSections"] = ' in source:
          self.launches += 1
          if self.launches == 1:
            self.probe = "[]"
          else:
            self.probe = json.dumps(
              [
                {
                  "title": "フォロー中",
                  "items": [
                    {"text": "First Note", "href": "/creator/n/n111"},
                    {"text": "Second Note", "href": "/creator/n/n222"},
                  ],
                },
              ]
            )
          return None
        if 'window["__twebNoteHomeSections"] || \'[]\'' in source:
          return self.probe
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        return None

    runtime = FakeRuntime()
    sections = extract_hydration_sections(runtime, "https://note.com/")

    self.assertEqual(runtime.launches, 2)
    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "フォロー中")
    mock_fetch_resource.assert_called_once()

  @patch("tweb.site_specific.fetch_resource")
  def test_falls_back_to_python_fetch_for_note_home_runtime_sections(self, mock_fetch_resource) -> None:
    class FakeRuntime:
      def __init__(self) -> None:
        self.probe = "[]"
        self.session = object()

      def eval(self, source: str, drain_timers: bool = False):
        if 'window["__twebNoteHomeSections"] = ' in source:
          self.probe = "[]"
          return None
        if 'window["__twebNoteHomeSections"] || \'[]\'' in source:
          return self.probe
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        return None

    mock_fetch_resource.return_value = Resource(
      source="https://note.com/api/v3/mkit_layouts/json?context=home_tl&page=1",
      content=json.dumps(
        {
          "data": {
            "sections": [
              {
                "label_name": "フォロー中",
                "notes": [
                  {
                    "title": "First Note",
                    "key": "naaa111",
                    "user": {"urlname": "creator"},
                  },
                  {
                    "title": "Second Note",
                    "key": "nbbb222",
                    "user": {"urlname": "creator"},
                  },
                ],
              },
            ],
          },
        }
      ),
    )

    sections = _extract_note_home_runtime_sections(FakeRuntime(), "https://note.com/")

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "フォロー中")
    self.assertEqual(
      sections[0].items,
      (("First Note", "/creator/n/naaa111"), ("Second Note", "/creator/n/nbbb222")),
    )
    mock_fetch_resource.assert_called_once()

  @patch("tweb.site_specific.fetch_resource")
  def test_falls_back_to_python_fetch_for_note_topic_runtime_sections(self, mock_fetch_resource) -> None:
    class FakeRuntime:
      def __init__(self) -> None:
        self.probe = "[]"
        self.session = object()

      def eval(self, source: str, drain_timers: bool = False):
        if 'window["__twebNoteTopicSections"] = JSON.stringify(sections);' in source:
          self.probe = "[]"
          return None
        if 'window["__twebNoteTopicSections"] || \'[]\'' in source:
          return self.probe
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        return None

    mock_fetch_resource.return_value = Resource(
      source="https://note.com/api/v3/mkit_layouts/json?context=category_lifestyle&page=1",
      content=json.dumps(
        {
          "data": {
            "sections": [
              {
                "label_name": "ミニマリズム",
                "notes": [
                  {
                    "name": "First Note",
                    "key": "naaa111",
                    "user": {"urlname": "creator"},
                  },
                  {
                    "name": "Second Note",
                    "key": "nbbb222",
                    "user": {"urlname": "creator"},
                  },
                ],
              },
            ],
          },
        }
      ),
    )

    sections = _extract_note_topic_runtime_sections(FakeRuntime(), "https://note.com/topic/lifestyle")

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "ミニマリズム")
    self.assertEqual(
      sections[0].items,
      (("First Note", "/creator/n/naaa111"), ("Second Note", "/creator/n/nbbb222")),
    )
    mock_fetch_resource.assert_called_once_with(
      "https://note.com/api/v3/mkit_layouts/json?context=category_lifestyle&page=1",
      session=unittest.mock.ANY,
    )

  @patch("tweb.site_specific.fetch_resource")
  def test_falls_back_to_python_fetch_for_nested_note_topic_runtime_sections(self, mock_fetch_resource) -> None:
    class FakeRuntime:
      def __init__(self) -> None:
        self.probe = "[]"
        self.session = object()

      def eval(self, source: str, drain_timers: bool = False):
        if 'window["__twebNoteTopicSections"] = JSON.stringify(sections);' in source:
          self.probe = "[]"
          return None
        if 'window["__twebNoteTopicSections"] || \'[]\'' in source:
          return self.probe
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        return None

    mock_fetch_resource.return_value = Resource(
      source="https://note.com/api/v3/mkit_layouts/json?context=category_outdoor_camping&page=1",
      content=json.dumps(
        {
          "data": {
            "sections": [
              {
                "label_name": "キャンプギア",
                "notes": [
                  {
                    "name": "First Note",
                    "key": "naaa111",
                    "user": {"urlname": "creator"},
                  },
                  {
                    "name": "Second Note",
                    "key": "nbbb222",
                    "user": {"urlname": "creator"},
                  },
                ],
              },
            ],
          },
        }
      ),
    )

    sections = _extract_note_topic_runtime_sections(FakeRuntime(), "https://note.com/topic/outdoor/camping")

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "キャンプギア")
    self.assertEqual(
      sections[0].items,
      (("First Note", "/creator/n/naaa111"), ("Second Note", "/creator/n/nbbb222")),
    )
    mock_fetch_resource.assert_called_once_with(
      "https://note.com/api/v3/mkit_layouts/json?context=category_outdoor_camping&page=1",
      session=unittest.mock.ANY,
    )

  @patch("tweb.site_specific.fetch_resource", side_effect=FetchError("offline"))
  def test_extracts_note_topic_runtime_sections(self, mock_fetch_resource) -> None:
    class FakeRuntime:
      def __init__(self) -> None:
        self.probe = "[]"

      def eval(self, source: str, drain_timers: bool = False):
        if 'window["__twebNoteTopicSections"] || \'[]\'' in source:
          return self.probe
        if 'window["__twebNoteTopicSections"] = JSON.stringify(sections);' in source:
          self.probe = json.dumps(
            [
              {
                "title": "開発効率化",
                "items": [
                  {"text": "First Note", "href": "/creator/n/n111"},
                  {"text": "Second Note", "href": "/creator/n/n222"},
                ],
              },
            ]
          )
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        return None

    sections = _extract_note_topic_runtime_sections(
      FakeRuntime(),
      "https://note.com/topic/computer_it",
    )

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "開発効率化")
    self.assertEqual(
      sections[0].items,
      (("First Note", "/creator/n/n111"), ("Second Note", "/creator/n/n222")),
    )
    mock_fetch_resource.assert_called_once()

  def test_extracts_kakuyomu_toc_sections(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "Work:822139842650897571" in source:
          return json.dumps(
            [
              {
                "title": "逆行転生3年目",
                "items": [
                  {
                    "text": "第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化",
                    "href": "/works/822139842650897571/episodes/822139845052603357",
                  },
                  {
                    "text": "第32話 8/15(月)〜31(水) 追加調整",
                    "href": "/works/822139842650897571/episodes/822139845892635822",
                  },
                ],
              },
            ]
          )
        return None

    sections = _extract_kakuyomu_toc_sections(
      FakeRuntime(),
      "https://kakuyomu.jp/works/822139842650897571",
    )

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "逆行転生3年目")
    self.assertEqual(
      sections[0].items,
      (
        ("第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化", "/works/822139842650897571/episodes/822139845052603357"),
        ("第32話 8/15(月)〜31(水) 追加調整", "/works/822139842650897571/episodes/822139845892635822"),
      ),
    )

  def test_extracts_kakuyomu_toc_sections_for_episode_url(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "Work:822139842650897571" in source:
          return json.dumps(
            [
              {
                "title": "逆行転生3年目",
                "items": [
                  {
                    "text": "第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化",
                    "href": "/works/822139842650897571/episodes/822139845052603357",
                  },
                  {
                    "text": "第32話 8/15(月)〜31(水) 追加調整",
                    "href": "/works/822139842650897571/episodes/822139845892635822",
                  },
                ],
              },
            ]
          )
        return None

    sections = _extract_kakuyomu_toc_sections(
      FakeRuntime(),
      "https://kakuyomu.jp/works/822139842650897571/episodes/2912051601840758084",
    )

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "逆行転生3年目")
    self.assertEqual(
      sections[0].items,
      (
        ("第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化", "/works/822139842650897571/episodes/822139845052603357"),
        ("第32話 8/15(月)〜31(水) 追加調整", "/works/822139842650897571/episodes/822139845892635822"),
      ),
    )

  def test_augments_inline_json_runtime_sections(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main id="app"></main>
              <script id="__NEXT_DATA__" type="application/json">
                {
                  "props": {
                    "pageProps": {
                      "featured": {
                        "title": "Featured",
                        "items": [
                          {"title": "First Entry", "href": "/first"},
                          {"title": "Second Entry", "href": "/second"}
                        ]
                      }
                    }
                  }
                }
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    text = document.body_text()
    self.assertIn("Featured", text)
    self.assertIn("First Entry", text)
    debug = document.hydration_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertEqual(debug["confidence"], "high")
    self.assertTrue(
      any(
        entry["source_type"] == "inline-json" and entry["source_name"] == "__NEXT_DATA__"
        for entry in debug["source_summaries"]
      )
    )

  def test_injects_missing_recovered_body_section_even_when_short_body_has_many_controls(self) -> None:
    controls = "".join(f'<button type="button">Action {index}</button>' for index in range(8))
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article/123",
          content=f"""
          <html>
            <body>
              <main>
                <header>
                  <h1>Article Title</h1>
                  <p>2026年8月7日・14日合併号</p>
                </header>
                <section>{controls}</section>
              </main>
              <script id="__NEXT_DATA__" type="application/json">
                {{
                  "props": {{
                    "pageProps": {{
                      "article": {{
                        "title": "Article Title",
                        "contentHtml": "<p>Lead paragraph with enough readable article text to require recovery.</p><p>Second paragraph keeps the missing article body clearly distinct from the surrounding chrome.</p><p>Third paragraph confirms the recovered section has multiple long body items.</p>"
                      }}
                    }}
                  }}
                }}
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    text = document.body_text()
    self.assertIn("Lead paragraph with enough readable article text to require recovery.", text)
    self.assertIn("Second paragraph keeps the missing article body clearly distinct", text)
    debug = document.hydration_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertTrue(
      any(
        entry["source_type"] == "inline-json" and entry["source_name"] == "__NEXT_DATA__"
        for entry in debug["source_summaries"]
      )
    )
    self.assertEqual(text.count("Lead paragraph with enough readable article text to require recovery."), 1)

  @patch("tweb.js_runtime.requests.request")
  def test_augments_runtime_fetch_json_sections(self, mock_request: Mock) -> None:
    response = Mock()
    response.url = "https://example.com/api/feed"
    response.status_code = 200
    response.reason = "OK"
    response.text = json.dumps(
      {
        "sections": [
          {
            "title": "Top Stories",
            "items": [
              {"title": "Story A", "href": "/story-a"},
              {"title": "Story B", "href": "/story-b"},
            ],
          },
        ],
      }
    )
    response.content = response.text.encode("utf-8")
    response.headers = {"Content-Type": "application/json"}
    response.close = Mock()
    mock_request.return_value = response

    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main id="app">Loading...</main>
              <script>
                fetch('/api/feed').then((response) => response.json()).then((_payload) => {
                  document.querySelector('#app').textContent = 'Loading...';
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    text = document.body_text()
    self.assertIn("Top Stories", text)
    self.assertIn("Story A", text)
    debug = document.hydration_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertTrue(any(entry["source_type"] == "network" for entry in debug["source_summaries"]))

  @patch("tweb.js_runtime.fetch_resource")
  def test_reuses_external_script_cache_within_single_document_run(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/static/app.js",
      content=(
        "document.body.setAttribute("
        "'data-cache-seen', "
        "String(Number(document.body.getAttribute('data-cache-seen') || '0') + 1)"
        ");"
      ),
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <script src="/static/app.js"></script>
              <script src="/static/app.js"></script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(mock_fetch_resource.call_count, 1)
    self.assertEqual(document.body.get("data-cache-seen"), "2")
    debug = document.javascript_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertEqual(debug["script_cache"]["hits"], 1)
    self.assertEqual(debug["script_cache"]["misses"], 1)
    self.assertEqual(debug["counts"]["external_script_fetches"], 1)
    self.assertEqual(debug["counts"]["embedded_external_scripts"], 2)

  @patch("tweb.js_runtime.fetch_resource")
  def test_can_disable_external_script_cache(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/static/app.js",
      content=(
        "document.body.setAttribute("
        "'data-cache-seen', "
        "String(Number(document.body.getAttribute('data-cache-seen') || '0') + 1)"
        ");"
      ),
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <script src="/static/app.js"></script>
              <script src="/static/app.js"></script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, use_script_cache=False)

    self.assertEqual(mock_fetch_resource.call_count, 2)
    debug = document.javascript_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertEqual(debug["script_cache"]["enabled"], False)
    self.assertEqual(debug["script_cache"]["bypasses"], 2)
    self.assertEqual(debug["counts"]["external_script_fetches"], 2)

  @patch("tweb.api._elapsed_ms_since")
  @patch("tweb.api._safe_perf_counter")
  def test_javascript_debug_includes_slowest_script_entries(
    self,
    mock_safe_perf_counter: Mock,
    mock_elapsed_ms_since: Mock,
  ) -> None:
    mock_safe_perf_counter.side_effect = [float(value) for value in range(10, 310, 10)]
    elapsed_map = {
      10.0: 100.0,
      20.0: 17.0,
      30.0: 43.0,
      40.0: 3.0,
      50.0: 2.0,
    }
    mock_elapsed_ms_since.side_effect = lambda started_at: elapsed_map.get(started_at, 0.0)
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <script>window.first = true;</script>
              <script>window.second = true;</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    debug = document.javascript_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    slow_scripts = debug.get("slow_scripts")
    self.assertIsInstance(slow_scripts, list)
    assert isinstance(slow_scripts, list)
    self.assertEqual(len(slow_scripts), 2)
    self.assertEqual(slow_scripts[0]["src"], "https://example.com/app#inline-1")
    self.assertEqual(slow_scripts[0]["duration_ms"], 43.0)
    self.assertEqual(slow_scripts[1]["src"], "https://example.com/app#inline-0")
    self.assertEqual(slow_scripts[1]["duration_ms"], 17.0)
    self.assertFalse(slow_scripts[0]["delayed"])

  @patch("tweb.js_runtime.fetch_resource")
  def test_reuses_external_script_cache_across_document_runs(self, mock_fetch_resource: Mock) -> None:
    GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/static/app.js",
      content=(
        "document.body.setAttribute("
        "'data-cache-seen', "
        "String(Number(document.body.getAttribute('data-cache-seen') || '0') + 1)"
        ");"
      ),
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )

    def build_document() -> TWebDocument:
      return TWebDocument(
        parse_document(
          Resource(
            source="https://example.com/app",
            content="""
            <html>
              <body>
                <script src="/static/app.js"></script>
              </body>
            </html>
            """,
          )
        )
      )

    try:
      first = build_document()
      second = build_document()

      first.execute_embedded_scripts(ignore_errors=False)
      second.execute_embedded_scripts(ignore_errors=False)

      self.assertEqual(mock_fetch_resource.call_count, 1)
      second_debug = second.javascript_debug()
      self.assertIsNotNone(second_debug)
      assert second_debug is not None
      self.assertEqual(second_debug["script_cache"]["hits"], 1)
      self.assertEqual(second_debug["counts"].get("external_script_fetches", 0), 0)
    finally:
      GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()

  @patch("tweb.js_runtime.fetch_resource")
  def test_reuses_external_script_cache_across_process_resets_from_disk(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/static/app.js",
      content="document.body.setAttribute('data-cache-seen', 'disk');",
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )

    def build_document() -> TWebDocument:
      return TWebDocument(
        parse_document(
          Resource(
            source="https://example.com/app",
            content="""
            <html>
              <body>
                <script src="/static/app.js"></script>
              </body>
            </html>
            """,
          )
        )
      )

    first = build_document()
    first.execute_embedded_scripts(ignore_errors=False)

    _reset_external_script_cache_state_for_tests()
    second = build_document()
    second.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(mock_fetch_resource.call_count, 1)
    second_debug = second.javascript_debug()
    self.assertIsNotNone(second_debug)
    assert second_debug is not None
    self.assertEqual(second_debug["script_cache"]["hits"], 1)
    self.assertEqual(second.body.get("data-cache-seen"), "disk")

  @patch("tweb.js_runtime.fetch_resource")
  def test_reuses_external_script_cache_across_pages_with_same_session(self, mock_fetch_resource: Mock) -> None:
    GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
    session = create_session()
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/static/app.js",
      content=(
        "document.body.setAttribute("
        "'data-cache-seen', "
        "String(Number(document.body.getAttribute('data-cache-seen') || '0') + 1)"
        ");"
      ),
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )

    def build_document(source: str) -> TWebDocument:
      return TWebDocument(
        parse_document(
          Resource(
            source=source,
            content="""
            <html>
              <body>
                <script src="/static/app.js"></script>
              </body>
            </html>
            """,
          )
        )
      )

    try:
      first = build_document("https://example.com/topic/one")
      second = build_document("https://example.com/topic/two")

      first.execute_embedded_scripts(ignore_errors=False, session=session)
      second.execute_embedded_scripts(ignore_errors=False, session=session)

      self.assertEqual(mock_fetch_resource.call_count, 1)
      second_debug = second.javascript_debug()
      self.assertIsNotNone(second_debug)
      assert second_debug is not None
      self.assertEqual(second_debug["script_cache"]["hits"], 1)
    finally:
      GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
      session.close()

  @patch("tweb.js_runtime.fetch_resource")
  def test_reuses_external_script_cache_across_sessions_without_vary(self, mock_fetch_resource: Mock) -> None:
    GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
    first_session = create_session({"sessionid": "one"})
    second_session = create_session({"sessionid": "two"})
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/static/app.js",
      content=(
        "document.body.setAttribute("
        "'data-cache-seen', "
        "String(Number(document.body.getAttribute('data-cache-seen') || '0') + 1)"
        ");"
      ),
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )

    def build_document(source: str) -> TWebDocument:
      return TWebDocument(
        parse_document(
          Resource(
            source=source,
            content="""
            <html>
              <body>
                <script src="/static/app.js"></script>
              </body>
            </html>
            """,
          )
        )
      )

    try:
      first = build_document("https://example.com/topic/one")
      second = build_document("https://example.com/topic/two")
      first.execute_embedded_scripts(ignore_errors=False, session=first_session)
      second.execute_embedded_scripts(ignore_errors=False, session=second_session)

      self.assertEqual(mock_fetch_resource.call_count, 1)
      second_debug = second.javascript_debug()
      self.assertIsNotNone(second_debug)
      assert second_debug is not None
      self.assertEqual(second_debug["script_cache"]["hits"], 1)
    finally:
      GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
      first_session.close()
      second_session.close()

  @patch("tweb.js_runtime.fetch_resource")
  def test_splits_external_script_cache_when_response_varies_on_cookie(self, mock_fetch_resource: Mock) -> None:
    GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
    first_session = create_session({"sessionid": "one"})
    second_session = create_session({"sessionid": "two"})
    mock_fetch_resource.side_effect = [
      Resource(
        source="https://example.com/static/app.js",
        content="document.body.setAttribute('data-cache-seen', 'one');",
        headers={"Cache-Control": "max-age=60", "Vary": "Cookie"},
        status_code=200,
      ),
      Resource(
        source="https://example.com/static/app.js",
        content="document.body.setAttribute('data-cache-seen', 'two');",
        headers={"Cache-Control": "max-age=60", "Vary": "Cookie"},
        status_code=200,
      ),
    ]

    def build_document(source: str) -> TWebDocument:
      return TWebDocument(
        parse_document(
          Resource(
            source=source,
            content="""
            <html>
              <body>
                <script src="/static/app.js"></script>
              </body>
            </html>
            """,
          )
        )
      )

    try:
      first = build_document("https://example.com/topic/one")
      second = build_document("https://example.com/topic/two")
      first.execute_embedded_scripts(ignore_errors=False, session=first_session)
      second.execute_embedded_scripts(ignore_errors=False, session=second_session)

      self.assertEqual(mock_fetch_resource.call_count, 2)
      self.assertEqual(first.body.get("data-cache-seen"), "one")
      self.assertEqual(second.body.get("data-cache-seen"), "two")
    finally:
      GLOBAL_EXTERNAL_SCRIPT_CACHE.clear()
      first_session.close()
      second_session.close()

  @patch("tweb.api.time.perf_counter", side_effect=SystemError("timer broken"))
  @patch("tweb.api.time.monotonic", return_value=456.0)
  def test_execute_embedded_scripts_tolerates_perf_counter_failures(
    self,
    _mock_monotonic: Mock,
    _mock_perf_counter: Mock,
  ) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>content</main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertIn("content", document.body_text())

  def test_replays_declarative_bootstrap_scripts_after_runtime_reset(self) -> None:
    source = "const API_PATH = '/api/'; const A = 1; const B = 2; const C = 3; const D = 4;"
    runtime = Mock()

    replayed = _replay_bootstrap_scripts(
      runtime,
      [(source, "https://example.com/constants.js"), (source, "https://example.com/constants.js")],
    )

    self.assertEqual(replayed, 1)
    runtime.eval.assert_called_once_with(
      source,
      source_url="https://example.com/constants.js",
      drain_timers=False,
    )

  def test_only_replays_bootstrap_scripts_without_runtime_side_effects(self) -> None:
    constants = "const API = '/'; const A = 1; const B = 2; const C = 3; const D = 4;"
    component = constants + " document.body.appendChild(document.createElement('main'));"
    jquery = (
      "/*! jQuery JavaScript Library v1.5.2 */"
      "!function(window){window.jQuery=window.$=function(){};}(window);"
    )
    jquery_plugin = "/*! Uses jQuery JavaScript Library */ window.plugin = function() {};"

    self.assertTrue(_should_replay_bootstrap_script(constants))
    self.assertTrue(_should_replay_bootstrap_script(jquery))
    self.assertFalse(_should_replay_bootstrap_script(component))
    self.assertFalse(_should_replay_bootstrap_script(jquery_plugin))

  @patch("tweb.api._extract_site_specific_hydration_sections", side_effect=FetchError("missing script"))
  def test_execute_embedded_scripts_ignores_hydration_extraction_failures_when_requested(
    self,
    _mock_extract: Mock,
  ) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>content</main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=True)

    self.assertIn("content", document.body_text())

  @patch("tweb.js_runtime.fetch_resource", side_effect=FetchError("missing module"))
  def test_execute_embedded_scripts_ignores_delayed_module_fetch_failures_when_requested(
    self,
    _mock_fetch_resource: Mock,
  ) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>content</main>
              <script type="module" src="/missing-module.js"></script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=True)

    self.assertIn("content", document.body_text())

  @patch.object(TWebDocument, "_runtime")
  def test_execute_embedded_scripts_skips_expensive_page_events_when_body_is_already_substantial(
    self,
    mock_runtime_factory: Mock,
  ) -> None:
    runtime = Mock()
    runtime.external_script_preflight_safe.return_value = True
    runtime.performance_summary.return_value = {"timings_ms": {}, "counts": {}}
    runtime.runtime_data_network_payloads.return_value = []
    runtime.load_external_script_source.return_value = "console.log('deferred');"
    mock_runtime_factory.return_value = runtime

    repeated_links = "".join(
      f'<a href="/item{i}">Visible item {i} with enough text to count as substantial content</a>'
      for i in range(50)
    )
    deferred_scripts = "".join(
      f'<script defer src="/deferred-{i}.js"></script>'
      for i in range(20)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content=f"""
          <html>
            <body>
              <main>{repeated_links}</main>
              {deferred_scripts}
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    runtime.dispatch_page_events.assert_not_called()
    runtime.dispatch_dom_content_loaded.assert_called_once_with(
      time_limit_seconds=None,
      continue_on_event_callback_error=False,
    )

  @patch.object(TWebDocument, "_runtime")
  def test_execute_embedded_scripts_skips_delayed_external_fetches_for_rich_static_page(
    self,
    mock_runtime_factory: Mock,
  ) -> None:
    runtime = Mock()
    runtime.performance_summary.return_value = {"timings_ms": {}, "counts": {}}
    runtime.runtime_data_network_payloads.return_value = []
    mock_runtime_factory.return_value = runtime

    repeated_links = "".join(
      f'<a href="/item{i}">Visible item {i} with enough text to count as substantial content</a>'
      for i in range(180)
    )
    controls = "".join(
      f'<button type="button">Control {i}</button>'
      for i in range(40)
    )
    module_scripts = "".join(
      f'<script type="module" src="/module-{i}.js"></script>'
      for i in range(20)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content=f"""
          <html>
            <body>
              <main>{repeated_links}{controls}</main>
              {module_scripts}
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    runtime.load_external_script_source.assert_not_called()
    debug = document.javascript_debug()
    assert debug is not None
    counts = debug["counts"]
    self.assertEqual(counts.get("embedded_delayed_scripts"), 20)
    self.assertEqual(counts.get("skipped_delayed_external_scripts"), 20)

  def test_should_skip_expensive_page_events_avoids_exact_main_visible_scan_when_inline_preview_is_sufficient(
    self,
  ) -> None:
    repeated_links = "".join(
      (
        f'<a href="/item{i}">Visible item {i} with enough text to count as substantial content '
        "and comfortably satisfy the rich body threshold for delayed page-event skipping.</a>"
      )
      for i in range(80)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content=f"""
          <html>
            <body>
              <main>{repeated_links}</main>
            </body>
          </html>
          """,
        )
      )
    )

    main = document.document.body.find_first("main")
    assert main is not None
    original_collect_visible_text = api_module._collect_visible_text
    main_visible_calls: list[ElementNode] = []

    def tracking_collect_visible_text(node: ElementNode, owner_document, exclude=None):
      if node is main:
        main_visible_calls.append(node)
      return original_collect_visible_text(node, owner_document, exclude=exclude)

    with patch.object(api_module, "_collect_visible_text", side_effect=tracking_collect_visible_text):
      self.assertTrue(_should_skip_expensive_page_events(document, delayed_script_count=20))
    self.assertEqual(main_visible_calls, [])

  def test_should_skip_expensive_page_events_uses_exact_main_visible_scan_for_sparse_inline_preview(
    self,
  ) -> None:
    hidden_links = "".join(
      f'<a href="/item{i}" style="display:none">Hidden item {i} with enough text to count as substantial content</a>'
      for i in range(50)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content=f"""
          <html>
            <body>
              <main>{hidden_links}</main>
            </body>
          </html>
          """,
        )
      )
    )

    main = document.document.body.find_first("main")
    assert main is not None
    original_collect_visible_text = api_module._collect_visible_text
    main_visible_calls: list[ElementNode] = []

    def tracking_collect_visible_text(node: ElementNode, owner_document, exclude=None):
      if node is main:
        main_visible_calls.append(node)
      return original_collect_visible_text(node, owner_document, exclude=exclude)

    with patch.object(api_module, "_collect_visible_text", side_effect=tracking_collect_visible_text):
      self.assertFalse(_should_skip_expensive_page_events(document, delayed_script_count=20))
    self.assertEqual(len(main_visible_calls), 1)

  @patch("tweb.api._document_visible_text")
  def test_dom_content_loaded_static_gate_avoids_exact_visible_body_scan_for_rich_page(
    self,
    mock_document_visible_text: Mock,
  ) -> None:
    repeated_links = "".join(
      (
        f'<a href="/item{i}">Visible item {i} with enough text to keep the body readable '
        "without requiring an exact visible-text scan.</a>"
      )
      for i in range(220)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content=f"""
          <html>
            <body>
              <main>{repeated_links}</main>
            </body>
          </html>
          """,
        )
      )
    )

    self.assertFalse(api_module._should_dispatch_dom_content_loaded_for_static_page(document))
    mock_document_visible_text.assert_not_called()

  def test_skips_telemetry_only_hydration_values(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify({ texts, links, sections });" in source:
          return json.dumps(
            {
              "texts": [
                "arn:aws:iam::418295679277:role/atw-prd01-rum-put-batch-metrics",
                "ap-northeast-1:3b37d76c-f42a-46ed-a32b-57823417e61d",
                "voSHJG0Gzt6bT2AIg0iR0aZS6E1mHanl7i6KtmkH",
              ],
              "links": [],
              "sections": [],
            }
          )
        return None

      def runtime_data_network_payloads(self):
        return []

    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>Loading...</main>
              <script id="__NEXT_DATA__" type="application/json">{}</script>
            </body>
          </html>
          """,
        )
      )
    )

    debug = _augment_sparse_body_from_hydration(document.document, FakeRuntime())

    text = document.body_text()
    self.assertNotIn("Hydration Data", text)
    self.assertNotIn("arn:aws:iam::418295679277", text)
    self.assertIsNotNone(debug)

  @patch("tweb.site_specific.fetch_resource", side_effect=FetchError("offline"))
  def test_augments_note_topic_sections_from_runtime_probe(self, mock_fetch: Mock) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify({ texts, links, sections });" in source:
          return json.dumps({"texts": [], "links": [], "sections": []})
        if 'window["__twebNoteTopicSections"] = JSON.stringify(sections);' in source:
          return None
        if 'window["__twebNoteTopicSections"] || \'[]\'' in source:
          return json.dumps(
            [
              {
                "title": "開発効率化",
                "items": [
                  {"text": "First Note", "href": "/creator/n/n111"},
                  {"text": "Second Note", "href": "/creator/n/n222"},
                ],
              },
            ]
          )
        return None

      def _drain_async_work(self, *args, **kwargs) -> None:
        return None

    document = parse_document(
      Resource(
        source="https://note.com/topic/computer_it",
        content="""
        <html>
          <body>
            <a href="#main-content">skip</a>
            <main id="main-content"></main>
            <footer>footer</footer>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("開発効率化", text)
    mock_fetch.assert_called_once()

  def test_skips_hydration_probe_when_body_is_substantial_without_root_hints(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        raise AssertionError("hydration probe should be skipped")

    document = parse_document(
      Resource(
        source="https://example.com/",
        content="""
        <html>
          <body>
            <main>
              <h1>Example</h1>
              <p>This page already contains enough visible content to avoid runtime hydration probing.</p>
              <p>It should not attempt a fallback scan when the document has no known hydration root markers.</p>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    text = TWebDocument(document).body_text()
    self.assertIn("Example", text)
    self.assertNotIn("Hydration Data", text)

  def test_preserves_compact_functional_ui_over_hydration_values(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify({ texts, links, sections });" in source:
          return json.dumps(
            {
              "texts": ["Unselected runtime dataset detail " * 20],
              "links": [],
              "sections": [],
            }
          )
        return None

      def runtime_data_network_payloads(self):
        return []

    document = parse_document(
      Resource(
        source="https://example.com/app",
        content="""
        <html>
          <body>
            <main id="app">
              <h1>Choose your region</h1>
              <p>Select a region to load the relevant public information for your area.</p>
              <label>Region <select><option>North</option><option>South</option></select></label>
              <a href="/all-regions">View all regions</a>
            </main>
            <script id="__NEXT_DATA__" type="application/json">{}</script>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    self.assertIn("Choose your region", wrapped.body_text(visible_only=True))
    self.assertEqual(len(wrapped.form_controls()), 1)
    self.assertNotIn("Hydration Data", wrapped.body_text())
    self.assertNotIn("Unselected runtime dataset detail", wrapped.body_text())

  def test_ignores_hydration_probe_oom_when_body_is_already_readable(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        raise JavaScriptRuntimeError("SyntaxError: out of memory")

    document = parse_document(
      Resource(
        source="https://example.com/",
        content="""
        <html>
          <body>
            <main>
              <h1>Readable page</h1>
              <p>This page already contains enough visible content to keep rendering useful even if the hydration probe runs out of memory.</p>
              <script>window.pageBooted = true;</script>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    text = TWebDocument(document).body_text()
    self.assertIn("Readable page", text)
    self.assertNotIn("Hydration Data", text)

  def test_ignores_runtime_collector_failure_when_body_is_substantial_but_hidden_surplus_forces_probe(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        raise JavaScriptRuntimeError("null [callback=event:DOMContentLoaded]")

    document = parse_document(
      Resource(
        source="https://example.com/",
        content="""
        <html>
          <body>
            <main>
              <h1>Readable page</h1>
              <p>
                This page already contains enough visible content to stay useful even if runtime
                hydration recovery fails after the document has become readable, and it keeps the
                main booking, search, and ranking content directly in the initial HTML response.
              </p>
            </main>
            <div style="display:none">
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
              Hidden surplus content Hidden surplus content Hidden surplus content Hidden surplus content
            </div>
          </body>
        </html>
        """,
      )
    )

    debug = _augment_sparse_body_from_hydration(document, FakeRuntime())

    text = TWebDocument(document).body_text()
    self.assertIn("Readable page", text)
    self.assertEqual(debug.fallback_reason, "runtime-collector-failed-with-substantial-body")
    self.assertNotIn("Hydration Data", text)

  def test_augments_embedded_json_richtext_when_visible_body_is_only_shell(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return "[]"

    document = parse_document(
      Resource(
        source="https://github.com/example/project",
        content="""
        <html>
          <body>
            <main>
              <nav>
                <p>
                  Navigation shell content that is long enough to count as substantial body text
                  before the runtime collector checks whether richer embedded data exists elsewhere
                  in the document tree for this page.
                </p>
              </nav>
            </main>
            <script type="application/json" data-target="react-app.embeddedData">
              {
                "overviewFiles": [
                  {
                    "displayName": "README.md",
                    "richText": "<article class=\\"markdown-body\\"><h1>OpenAI Python API library</h1><p>The OpenAI Python library provides convenient access to the OpenAI REST API from any Python application.</p><p>Installation and usage details live in the README and linked documentation.</p><p><a href=\\"/docs\\">Project documentation</a></p></article>"
                  }
                ]
              }
            </script>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("OpenAI Python API library", text)
    self.assertIn("convenient access to the OpenAI REST API", text)
    self.assertTrue(any(link.href == "/docs" for link in wrapped.links()))

  def test_uses_head_description_when_client_shell_body_and_runtime_data_are_empty(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify({ texts, links, sections });" in source:
          return json.dumps({"texts": [], "links": [], "sections": []})
        return None

    document = parse_document(
      Resource(
        source="https://example.com/article/1",
        content="""
        <html>
          <head>
            <title>Client shell article</title>
            <meta
              name="description"
              content="This article body only exists in a client-rendered shell, so the head description should become a visible fallback instead of leaving the page blank for terminal rendering."
            >
          </head>
          <body>
            <div id="app-root"></div>
            <script>window.mountArticle && window.mountArticle()</script>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("head description should become a visible fallback", text)
    self.assertIsNotNone(wrapped.find("section", attrs={"data-tweb-head-fallback": "description"}))

  def test_extracts_sparse_document_link_sections(self) -> None:
    document = parse_document(
      Resource(
        source="https://example.com/news",
        content="""
        <html>
          <body>
            <main>
              <a href="/story-1">Long headline about a major event that still needs to appear in text mode</a>
              <a href="/story-2">Second long headline with enough detail to be useful as a recovered fallback item</a>
              <a href="/story-3">Third long headline covering another public story in the same sparse page shell</a>
              <a href="/story-4">Fourth long headline that confirms the page has enough meaningful anchor text</a>
              <a href="/story-5">Fifth long headline that should be included in the fallback section as well</a>
              <a href="/story-6">Sixth long headline to satisfy the minimum recovered-link threshold for sparse pages</a>
            </main>
          </body>
        </html>
        """,
      )
    )

    sections = _extract_sparse_document_link_sections(document)

    self.assertEqual(len(sections), 1)
    self.assertEqual(sections[0].title, "Recovered Links")
    joined = " ".join(text for text, _href in sections[0].items)
    self.assertIn("Long headline about a major event", joined)
    self.assertIn("Sixth long headline", joined)

  def test_skips_hydration_append_when_full_visible_body_already_contains_runtime_section(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return "[]"

    intro = " ".join(
      [
        "This article already contains a long visible introduction that should keep hydration fallback from appending duplicate recovered sections."
        for _ in range(8)
      ]
    )
    document = parse_document(
      Resource(
        source="https://example.com/news",
        content=f"""
        <html>
          <body>
            <main>
              <p>{intro}</p>
              <h2>Top Stories</h2>
              <a href="/story-1">First long headline about a major event that already appears in the visible document body</a>
              <a href="/story-2">Second long headline with enough detail to be useful without hydration duplication</a>
              <a href="/story-3">Third long headline covering another public story in the same document shell</a>
              <a href="/story-4">Fourth long headline that confirms the page has enough meaningful anchor text</a>
              <a href="/story-5">Fifth long headline that should stay in the visible body without extra recovery</a>
              <a href="/story-6">Sixth long headline to ensure the page exceeds sparse-link fallback thresholds</a>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(
      document,
      FakeRuntime(),
      extra_sections=[
        HydrationSection(
          title="Top Stories",
          items=(
            ("First long headline about a major event that already appears in the visible document body", "/story-1"),
            ("Second long headline with enough detail to be useful without hydration duplication", "/story-2"),
          ),
        ),
      ],
    )

    text = TWebDocument(document).body_text()
    self.assertNotIn("Hydration Data", text)
    self.assertNotIn("Recovered Links", text)

  def test_skips_duplicate_recovered_section_when_visible_body_already_contains_it(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return "[]"

    intro = " ".join(
      [
        "This article already contains the readable body and should not receive the same recovered section again."
        for _ in range(6)
      ]
    )
    paragraph_one = (
      "The first visible paragraph already explains the main result in enough detail to keep the article readable "
      "without any hydration fallback duplication."
    )
    paragraph_two = (
      "The second visible paragraph already covers the supporting evidence and the surrounding context, so repeating "
      "it in a recovered section would only create noise."
    )
    document = parse_document(
      Resource(
        source="https://example.com/articles/readable",
        content=f"""
        <html>
          <body>
            <main>
              <p>{intro}</p>
              <h2>Detailed Results</h2>
              <p>{paragraph_one}</p>
              <p>{paragraph_two}</p>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(
      document,
      FakeRuntime(),
      extra_sections=[
        HydrationSection(
          title="Detailed Results",
          role="recovered",
          items=(
            (paragraph_one, None),
            (paragraph_two, None),
          ),
        ),
      ],
    )

    text = TWebDocument(document).body_text()
    self.assertNotIn("Hydration Data", text)
    self.assertEqual(text.count(paragraph_one), 1)
    self.assertEqual(text.count(paragraph_two), 1)

  def test_skips_duplicate_non_recovered_section_when_visible_body_already_contains_it(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return "[]"

    paragraph_one = (
      "The agreement explains how to connect to the hotspot and what data is collected during sign in."
    )
    paragraph_two = (
      "The second paragraph describes the available service area and the support window in plain language."
    )
    document = parse_document(
      Resource(
        source="https://example.com/wifi",
        content=f"""
        <html>
          <body>
            <main>
              <h2>How to use this service</h2>
              <p>{paragraph_one}</p>
              <p>{paragraph_two}</p>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(
      document,
      FakeRuntime(),
      extra_sections=[
        HydrationSection(
          title="How to use this service",
          items=(
            (paragraph_one, None),
            (paragraph_two, None),
          ),
        ),
      ],
    )

    text = TWebDocument(document).body_text()
    self.assertNotIn("Hydration Data", text)
    self.assertEqual(text.count(paragraph_one), 1)
    self.assertEqual(text.count(paragraph_two), 1)

  def test_augments_short_visible_body_with_hidden_recovered_content(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return "[]"

    document = parse_document(
      Resource(
        source="https://example.com/",
        content="""
        <html>
          <body>
            <main>
              <section>
                <h1>Privacy search for everything</h1>
                <p>Use the search box to look up web pages without tracking.</p>
                <div hidden>
                  <p>Add our free extension to block web trackers across the web and keep browsing calmer every day.</p>
                  <a href="/browser">Get our free browser for even more privacy protections today</a>
                </div>
              </section>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("Privacy search for everything", text)
    self.assertIn("Add our free extension to block web trackers", text)
    self.assertTrue(any(link.href == "/browser" for link in wrapped.links()))

  def test_augments_short_visible_body_with_sparse_document_links(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return "[]"

    document = parse_document(
      Resource(
        source="https://example.com/",
        content="""
        <html>
          <body>
            <main>
              <section>
                <h1>Top stories</h1>
                <p>Read the day's news roundup.</p>
                <a href="/story-1">Long headline about a major event that still needs to appear in text mode</a>
                <a href="/story-2">Second long headline with enough detail to be useful as a recovered fallback item</a>
                <a href="/story-3">Third long headline covering another public story in the same sparse page shell</a>
                <a href="/story-4">Fourth long headline that confirms the page has enough meaningful anchor text</a>
                <a href="/story-5">Fifth long headline that should be included in the fallback section as well</a>
                <a href="/story-6">Sixth long headline to satisfy the minimum recovered-link threshold for sparse pages</a>
              </section>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("Top stories", text)
    self.assertIn("Long headline about a major event", text)
    self.assertIn("Sixth long headline", text)
    self.assertGreaterEqual(len(wrapped.links()), 6)

  def test_augments_substantial_body_with_sparse_document_links_when_visible_links_are_short(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return "[]"

    intro = " ".join(
      [
        "This launch article already contains a readable introduction, but the detailed mission links are still tucked behind a delayed client shell."
        for _ in range(5)
      ]
    )
    document = parse_document(
      Resource(
        source="https://example.com/jaxa",
        content=f"""
        <html>
          <body>
            <main>
              <h1>Mission Updates</h1>
              <p>{intro}</p>
              <a href="/overview">Overview of the current mission status and key milestones</a>
              <div hidden>
                <a href="/topic-1">Detailed mission update covering propulsion, navigation, and communications milestones</a>
                <a href="/topic-2">Second long mission update with subsystem verification details and launch preparation work</a>
                <a href="/topic-3">Third long mission update focused on orbit planning and payload coordination tasks</a>
                <a href="/topic-4">Fourth long mission update summarizing environmental tests and hardware integration work</a>
                <a href="/topic-5">Fifth long mission update describing staffing, operations readiness, and telemetry rehearsals</a>
                <a href="/topic-6">Sixth long mission update explaining the publication schedule for future technical releases</a>
              </div>
              <script id="__NEXT_DATA__">{{}}</script>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("Recovered Links", text)
    self.assertIn("Detailed mission update covering propulsion", text)
    self.assertGreaterEqual(len(wrapped.links()), 7)

  def test_substantial_body_sparse_document_links_gate_skips_link_dense_pages(self) -> None:
    self.assertFalse(
      _should_merge_sparse_document_link_sections_for_substantial_body(
        current_links=180,
        current_controls=2,
        hydration_body_length=1200,
        has_hidden_content_hint=True,
      )
    )
    self.assertFalse(
      _should_merge_sparse_document_link_sections_for_substantial_body(
        current_links=18,
        current_controls=12,
        hydration_body_length=1200,
        has_hidden_content_hint=False,
      )
    )
    self.assertTrue(
      _should_merge_sparse_document_link_sections_for_substantial_body(
        current_links=18,
        current_controls=2,
        hydration_body_length=1200,
        has_hidden_content_hint=False,
      )
    )

  @patch("tweb.api.fetch_resource")
  def test_replaces_sparse_page_with_alternate_html_fallback_link(self, mock_fetch_resource: Mock) -> None:
    sparse = parse_document(
      Resource(
        source="https://duckduckgo.com/?q=OpenAI",
        content="""
        <html>
          <body>
            <main>
              <input id="state_hidden" type="text" value="">
              <a href="/html/?q=OpenAI">here</a>
            </main>
          </body>
        </html>
        """,
      )
    )
    fallback_resource = Resource(
      source="https://duckduckgo.com/html/?q=OpenAI",
      content="""
      <html>
        <body>
          <main>
            <h1>OpenAI at DuckDuckGo</h1>
            <a href="https://openai.com/">OpenAI</a>
            <p>OpenAI develops AI systems and APIs.</p>
          </main>
        </body>
      </html>
      """,
    )
    mock_fetch_resource.return_value = fallback_resource

    wrapped = TWebDocument(sparse)
    session = create_session()
    try:
      wrapped.execute_embedded_scripts(ignore_errors=True, session=session, browser_render_policy="never")
    finally:
      session.close()

    self.assertIn("OpenAI develops AI systems", wrapped.body_text())
    self.assertEqual(wrapped.document.source, "https://duckduckgo.com/html/?q=OpenAI")
    mock_fetch_resource.assert_called()

  def test_recovers_inline_script_json_literals_for_short_shell_pages(self) -> None:
    wrapped = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <main>
                <h1>Private browsing</h1>
                <p>
                  Search and browse with less tracking while keeping a simple visible shell that is
                  long enough to count as substantial body text before runtime-data recovery decides
                  whether additional embedded copy should still be surfaced for terminal rendering.
                </p>
              </main>
              <script id="__NEXT_DATA__">
                window.__translations = {
                  "hero": [{"type": 0, "value": "Trusted by tens of millions worldwide!"}],
                  "cta": [{"type": 0, "value": "Want even more protection?"}],
                  "feature": [{"type": 0, "value": "Block most ads and cookie popups by default."}]
                };
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    wrapped.execute_embedded_scripts(ignore_errors=True, browser_render_policy="never")

    text = wrapped.body_text()
    self.assertIn("Private browsing", text)
    self.assertIn("Trusted by tens of millions worldwide!", text)
    self.assertIn("Want even more protection?", text)
    self.assertIn("Block most ads and cookie popups by default.", text)

  def test_augments_kakuyomu_accordion_and_click_opens_it(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify({ texts, links, sections });" in source:
          return json.dumps({"texts": [], "links": [], "sections": []})
        if "Work:822139842650897571" in source:
          return json.dumps(
            [
              {
                "title": "逆行転生3年目",
                "items": [
                  {
                    "text": "第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化",
                    "href": "/works/822139842650897571/episodes/822139845052603357",
                  },
                  {
                    "text": "第32話 8/15(月)〜31(水) 追加調整",
                    "href": "/works/822139842650897571/episodes/822139845892635822",
                  },
                ],
              },
            ]
          )
        return None

    wrapped = TWebDocument(
      parse_document(
        Resource(
          source="https://kakuyomu.jp/works/822139842650897571",
          content="""
          <html>
            <body>
              <div class="NewBox_box__45ont NewBox_borderStyle-solid__F7tjp NewBox_borderColor-defaultGray__NGE9f NewBox_borderSize-bb-m__wEqyb">
                <button type="button" class="Button_button__kcHya Button_widthfill__fMKti Button_heightauto__BdNgx">
                  <div class="WorkTocAccordion_trigger__dJ0jR">
                    <h3 class="Heading_heading__lQ85n">逆行転生3年目</h3>
                    <div>31話</div>
                  </div>
                </button>
                <div class="WorkTocAccordion_contents__6nJhY"></div>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    _augment_sparse_body_from_hydration(wrapped.document, FakeRuntime())
    button = next(control for control in wrapped.form_controls() if control.kind == "button")
    content = wrapped.find("div", attrs={"class": "WorkTocAccordion_contents__6nJhY"})
    self.assertIsNotNone(content)
    self.assertIn("hidden", content.attrs)

    result = wrapped.click_button_control(button.control_id)

    content = wrapped.find("div", attrs={"class": "WorkTocAccordion_contents__6nJhY"})
    self.assertTrue(result.dom_changed)
    self.assertEqual(result.classification, "dom_updated")
    self.assertIsNotNone(content)
    self.assertNotIn("hidden", content.attrs)
    self.assertIn("第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化", content.get_text())

  @patch("tweb.api.collect_runtime_data")
  def test_kakuyomu_episode_uses_site_specific_sections_without_generic_runtime_collector(
    self,
    mock_collect_runtime_data: Mock,
  ) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "Work:822139842650897571" in source:
          return json.dumps(
            [
              {
                "title": "逆行転生3年目",
                "items": [
                  {
                    "text": "第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化",
                    "href": "/works/822139842650897571/episodes/822139845052603357",
                  },
                  {
                    "text": "第32話 8/15(月)〜31(水) 追加調整",
                    "href": "/works/822139842650897571/episodes/822139845892635822",
                  },
                ],
              },
            ]
          )
        raise AssertionError("generic runtime collector should not run")

    wrapped = TWebDocument(
      parse_document(
        Resource(
          source="https://kakuyomu.jp/works/822139842650897571/episodes/2912051601840758084",
          content="""
          <html>
            <body>
              <main>
                <article>
                  <h1>本文見出し</h1>
                  <p>
                    これは本文がすでに十分読めているケースで、site-specific の目次補完だけで済むべきです。
                    そのため generic runtime collector を追加で走らせる必要はありません。
                  </p>
                  <p>
                    さらに本文量を増やして substantial 判定を満たし、episode ページの TOC だけを差し込む
                    fast path が成立する状態を作っています。
                  </p>
                </article>
              </main>
              <aside>
                <button type="button">
                  <div class="WorkTocAccordion_trigger__dJ0jR">
                    <h3 class="Heading_heading__lQ85n">逆行転生3年目</h3>
                    <div>31話</div>
                  </div>
                </button>
                <div class="WorkTocAccordion_contents__6nJhY"></div>
              </aside>
            </body>
          </html>
          """,
        )
      )
    )

    debug = _augment_sparse_body_from_hydration(wrapped.document, FakeRuntime())

    self.assertIsNotNone(debug)
    self.assertEqual(debug.fallback_reason, "body-already-readable-with-disclosure-sections")
    self.assertTrue(debug.used_site_specific_fallback)
    mock_collect_runtime_data.assert_not_called()
    content = wrapped.find("div", attrs={"class": "WorkTocAccordion_contents__6nJhY"})
    self.assertIsNotNone(content)
    self.assertIn("第31話 8/1(月)〜14(日) 拡張IOCSの独自システム化", content.get_text())

  @patch("tweb.api.collect_runtime_data")
  def test_readable_page_without_runtime_hints_skips_generic_runtime_collector(
    self,
    mock_collect_runtime_data: Mock,
  ) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        return None

    wrapped = TWebDocument(
      parse_document(
        Resource(
          source="https://kakuyomu.jp/works/822139842650897571/episodes/2912051601840758084",
          content="""
          <html>
            <body>
              <main>
                <article>
                  <h1>本文見出し</h1>
                  <p>
                    これは本文がすでに十分読めているケースで、runtime hint が存在しないときに
                    hydration の generic collector を省けることを確認するテストです。
                  </p>
                  <p>
                    目次補完がなくても表示本文は維持され、追加の recovered section は不要です。
                    さらに本文量を増やして substantial 判定を確実に満たし、live の Kakuyomu episode
                    ページと同じく generic collector を呼ばずにそのまま表示できる条件へ寄せています。
                  </p>
                </article>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    debug = _augment_sparse_body_from_hydration(wrapped.document, FakeRuntime())

    self.assertIsNotNone(debug)
    self.assertEqual(debug.fallback_reason, "body-already-readable-without-runtime-hints")
    self.assertFalse(debug.used_site_specific_fallback)
    mock_collect_runtime_data.assert_not_called()

  def test_augments_generic_disclosure_section_and_click_opens_it(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify(result);" in source:
          return "[]"
        return json.dumps("[]")

    sections = [
      HydrationSection(
        title="Episode List",
        items=(
          ("Episode 1", "/episodes/1"),
          ("Episode 2", "/episodes/2"),
        ),
      ),
    ]

    wrapped = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/series",
          content="""
          <html>
            <body>
              <main>
                <section class="accordion">
                  <button type="button" aria-controls="episode-list">
                    <h3>Episode List</h3>
                  </button>
                  <div id="episode-list" class="accordion-panel" hidden></div>
                </section>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    _augment_sparse_body_from_hydration(
      wrapped.document,
      runtime=FakeRuntime(),
      extra_sections=sections,
    )
    button = next(control for control in wrapped.form_controls() if control.kind == "button")
    content = wrapped.find("div", attrs={"id": "episode-list"})
    self.assertIsNotNone(content)
    self.assertIn("hidden", content.attrs)

    result = wrapped.click_button_control(button.control_id)

    content = wrapped.find("div", attrs={"id": "episode-list"})
    self.assertTrue(result.dom_changed)
    self.assertEqual(result.classification, "dom_updated")
    self.assertIsNotNone(content)
    self.assertNotIn("hidden", content.attrs)
    self.assertIn("Episode 1", content.get_text())

  def test_skips_generic_text_noise_when_runtime_sections_exist(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify({ texts, links, sections });" in source:
          return json.dumps(
            {
              "texts": ["Claude Tag", "ハイドレーションブレイク"],
              "links": [],
              "sections": [],
            }
          )
        return None

    document = parse_document(
      Resource(
        source="https://note.com/",
        content="""
        <html>
          <body>
            <main>
              <div class="timeline">
                <div class="timeline__nav"></div>
                <div class="timeline__body"></div>
              </div>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(
      document,
      FakeRuntime(),
      extra_sections=[
        HydrationSection(
          title="フォロー中",
          items=(
            ("First Note", "/creator/n/n111"),
            ("Second Note", "/creator/n/n222"),
          ),
        ),
      ],
    )

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("First Note", text)
    self.assertNotIn("Claude Tag", text)
    self.assertNotIn("ハイドレーションブレイク", text)
    self.assertIn("Second Note", text)
    main = wrapped.find("main")
    self.assertIsNotNone(main)
    self.assertEqual(main.find("h3").text, "フォロー中")
    self.assertTrue(any(link.text == "First Note" and link.href == "/creator/n/n111" for link in wrapped.links()))

  def test_skips_low_signal_hydration_noise_when_article_body_is_already_present(self) -> None:
    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "return JSON.stringify({ texts, links, sections });" in source:
          return json.dumps(
            {
              "texts": [
                "note://note/n8b86db63a143",
                "2026-06-24T23:03:21.000+09:00",
                "3カラム",
                "公開",
                "削除",
              ],
              "links": [],
              "sections": [
                {
                  "title": "Orca echo(オルカエコー)のキーマップを考えてみた話｜はち@Kurashi-Hack(暮らしハック)",
                  "items": [
                    {"text": "トップ", "href": None},
                    {"text": "コンピュータ・IT", "href": None},
                    {"text": "パソコン・周辺機器", "href": None},
                  ],
                },
                {
                  "title": "Orca echo(オルカエコー)のキーマップを考えてみた話",
                  "items": [
                    {"text": "2dc8fa53-f25b-49dd-aa57-c49854a82dfd", "href": None},
                    {"text": "261222f8-21ef-4eaf-841e-2c463a6bde78", "href": None},
                  ],
                },
              ],
            }
          )
        return None

    document = parse_document(
      Resource(
        source="https://note.com/hachi_ocl/n/n8b86db63a143",
        content="""
        <html>
          <body>
            <main>
              <article>
                <h1>Orca echo(オルカエコー)のキーマップを考えてみた話</h1>
                <p>前回の記事に引き続き、今回も話題のキーボードについて書きたいと思う。</p>
                <p>かなり気が早いが、今のうちにキーマップを考えておこうと思う。</p>
                <p>ここから先は、各レイヤーに割り当てた内容を細かく見ていく。</p>
                <p>親指キーというのは、キーボード上では一等地であり、ホームポジションから手を動かさずに使える重要な場所だ。</p>
              </article>
            </main>
          </body>
        </html>
        """,
      )
    )

    _augment_sparse_body_from_hydration(document, FakeRuntime())

    wrapped = TWebDocument(document)
    text = wrapped.body_text()
    self.assertIn("前回の記事に引き続き", text)
    self.assertNotIn("3カラム", text)
    self.assertNotIn("公開", text)
    self.assertNotIn("削除", text)
    self.assertNotIn("トップ", text)
    self.assertNotIn("2dc8fa53-f25b-49dd-aa57-c49854a82dfd", text)
    self.assertIsNone(wrapped.find("section", attrs={"data-tweb-hydration": "1"}))

  def test_extracts_title_body_and_links(self) -> None:
    document = load_document(SAMPLE)

    self.assertEqual(document.title, "tweb sample")
    self.assertIn("Welcome to tweb", document.body_text())
    self.assertIn("Phase 1 sets up the project structure", document.body_text())

    links = document.links()
    self.assertEqual(len(links), 1)
    self.assertEqual(links[0].text, "the documentation")
    self.assertEqual(links[0].href, "https://example.com/docs")

  def test_tolerates_broken_html(self) -> None:
    document = load_document(BROKEN)

    self.assertEqual(document.title, "broken sample")
    self.assertIn("Broken markup still yields text.", document.body_text())
    self.assertEqual(
      [(link.text, link.href) for link in document.links()],
      [("Link without closing tags", "/broken")],
    )

  def test_preserves_comment_nodes_in_dom(self) -> None:
    custom = TWebDocument(
      parse_document(
        Resource(
          source="inline",
          content="<html><body><!--marker--><template id='tpl'></template></body></html>",
        )
      )
    )

    comments = custom.document.find_all("#comment")
    self.assertEqual(len(comments), 1)
    self.assertEqual(comments[0].attrs.get("__text"), "marker")
    template = custom.find("template", attrs={"id": "tpl"})
    self.assertIsNotNone(template)
    self.assertEqual(custom.body_text(), "")

  def test_find_and_find_all(self) -> None:
    document = load_document(SAMPLE)

    heading = document.find("h1")
    self.assertIsNotNone(heading)
    self.assertEqual(heading.text, "Welcome to tweb")

    items = document.find_all("li")
    self.assertEqual(len(items), 2)
    self.assertEqual(items[0].get_text(), "Normal mode renders readable text.")

  def test_find_with_attrs(self) -> None:
    document = load_document(SAMPLE)

    link = document.find("a", attrs={"href": "https://example.com/docs"})

    self.assertIsNotNone(link)
    self.assertEqual(link.get("href"), "https://example.com/docs")
    self.assertEqual(link.text, "the documentation")

  def test_select_supports_basic_css_like_selectors(self) -> None:
    document = load_document(SAMPLE)

    paragraph_links = document.select("main p a")
    self.assertEqual(len(paragraph_links), 1)
    self.assertEqual(paragraph_links[0].text, "the documentation")

  def test_select_supports_class_id_and_attr(self) -> None:
    custom = TWebDocument(
      parse_document(
        fetch_resource(str(ROOT / "tests" / "fixtures" / "selectors.html"))
      )
    )

    self.assertEqual(custom.select("#primary")[0].name, "section")
    self.assertEqual(custom.select(".entry-title")[0].text, "Entry Title")
    self.assertEqual(
      custom.select('a[data-role="nav"]')[0].get("href"),
      "/next",
    )

  def test_select_supports_combined_attrs_groups_and_child_combinator(self) -> None:
    custom = TWebDocument(
      parse_document(
        Resource(
          source="inline",
          content="""
          <html>
            <head>
              <title>selectors</title>
            </head>
            <body>
              <main>
                <link rel="stylesheet" href="/a.css" data-precedence="default"/>
                <style data-precedence="default"></style>
                <script async="" src="/app.js"></script>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    self.assertEqual(len(custom.select('link[rel="stylesheet"][data-precedence]')), 1)
    self.assertEqual(len(custom.select('link[rel="stylesheet"][data-precedence],style[data-precedence]')), 2)
    self.assertEqual(custom.select('head > title')[0].text, "selectors")
    self.assertEqual(custom.select('script[async][src]')[0].get("src"), "/app.js")

  def test_snapshot_exposes_structured_page_data(self) -> None:
    document = load_document(FORM)

    snapshot = document.snapshot(max_depth=4)

    self.assertEqual(snapshot.title, "Form Demo")
    self.assertIn("Search", snapshot.body_text)
    self.assertEqual(snapshot.links, ())
    self.assertEqual(snapshot.form_controls[0].control_id, "q")
    self.assertEqual(snapshot.form_controls[0].kind, "text")
    self.assertEqual(snapshot.form_controls[2].options[0].value, "articles")
    self.assertTrue(any(node.tag == "form" for node in snapshot.dom_nodes if node.node_type == "element"))
    self.assertTrue(any(node.text == "Search" for node in snapshot.dom_nodes if node.node_type == "text"))

  def test_snapshot_to_dict_is_json_safe(self) -> None:
    document = load_document(SAMPLE)

    payload = document.snapshot().to_dict()

    self.assertEqual(payload["title"], "tweb sample")
    self.assertEqual(payload["links"][0]["href"], "https://example.com/docs")
    self.assertIn("dom_nodes", payload)

  def test_snapshot_supports_structured_read_only_queries(self) -> None:
    document = load_document(FORM)

    snapshot = document.snapshot(max_depth=4)

    self.assertEqual(snapshot.control("q").label, "Query")
    self.assertEqual(
      [control.control_id for control in snapshot.find_controls(kind="radio", name="scope")],
      ["scope-title", "scope-all"],
    )
    self.assertEqual(
      snapshot.find_controls(label_contains="safe")[0].control_id,
      "safe",
    )

    form_node = snapshot.find_nodes(tag="form", limit=1)[0]
    self.assertEqual(snapshot.node(form_node.node_id).tag, "form")
    self.assertTrue(
      any(node.text == "Query" for node in snapshot.find_nodes(node_type="text", text_contains="query"))
    )
    self.assertEqual(
      snapshot.find_nodes(tag="option", attrs={"selected": ""}, visible=True)[0].attrs["value"],
      "articles",
    )
    self.assertEqual(
      snapshot.control("q").supported_actions,
      ("set_text", "append_text", "backspace_text", "debug_control"),
    )
    self.assertEqual(
      snapshot.find_controls(kind="submit")[0].supported_actions,
      ("submit_form", "debug_control"),
    )

  def test_snapshot_supports_structured_link_queries(self) -> None:
    document = load_document(SAMPLE)

    snapshot = document.snapshot()

    self.assertEqual(
      snapshot.link(href="https://example.com/docs").text,
      "the documentation",
    )
    self.assertEqual(
      [link.href for link in snapshot.find_links(text_contains="documentation")],
      ["https://example.com/docs"],
    )

  def test_snapshot_marks_hidden_controls_not_visible(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com",
          content="""
          <html>
            <head>
              <style>
                #hidden-control { display: none; }
              </style>
            </head>
            <body>
              <main>
                <input id="visible-control" type="text" value="ok" />
                <input id="hidden-control" type="checkbox" checked />
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    snapshot = document.snapshot()

    self.assertTrue(snapshot.control("visible-control").visible)
    self.assertFalse(snapshot.control("hidden-control").visible)
    self.assertEqual(snapshot.control("hidden-control").hidden_reason, "display_none")

  def test_debug_control_describes_text_input_and_submit_preview(self) -> None:
    document = load_document(FORM)

    self.assertTrue(document.set_text_control("q", "phase9"))
    self.assertTrue(document.cycle_select_control("category"))

    query = document.debug_control("q", current_source="https://example.com/form")
    self.assertIsNotNone(query)
    self.assertEqual(query.kind, "text")
    self.assertEqual(query.form_method, "get")
    self.assertEqual(query.form_enctype, "application/x-www-form-urlencoded")
    self.assertEqual(query.form_action, "https://example.com/search")
    self.assertEqual(query.value, "phase9")
    self.assertIsNone(query.submit_preview)

    submit_id = next(control.control_id for control in document.form_controls() if control.kind == "submit")
    submit = document.debug_control(submit_id, current_source="https://example.com/form")
    self.assertIsNotNone(submit)
    self.assertEqual(submit.kind, "submit")
    self.assertEqual(submit.click_hint, "submit")
    self.assertEqual(submit.submit_preview.enctype, "application/x-www-form-urlencoded")
    self.assertEqual(
      submit.submit_preview.url,
      "https://example.com/search?q=phase9&notes=memo&category=images&scope=title&safe=on&go=1",
    )
    self.assertEqual(
      submit.submit_preview.form_data,
      (("q", "phase9"), ("notes", "memo"), ("category", "images"), ("scope", "title"), ("safe", "on"), ("go", "1")),
    )

  def test_debug_controls_describes_button_click_hints(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/menu",
          content="""
          <html>
            <body>
              <button id="details" aria-controls="panel">Details</button>
              <div id="panel" hidden>Panel body</div>
            </body>
          </html>
          """,
        )
      )
    )

    debug = document.debug_control("details")
    self.assertIsNotNone(debug)
    self.assertEqual(debug.kind, "button")
    self.assertEqual(debug.click_hint, "disclosure_toggle")
    self.assertEqual(debug.controlled_target, "panel")

  def test_javascript_anchor_is_exposed_as_button_control(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/menu",
          content="""
          <html>
            <body>
              <aside id="menu" style="height:0;overflow:auto">
                <p>Hidden menu entry</p>
              </aside>
              <a id="menu-toggle" href="javascript:void(0);">Menu</a>
            </body>
          </html>
          """,
        )
      )
    )

    control = document.form_controls()[0]
    self.assertEqual(control.control_id, "menu-toggle")
    self.assertEqual(control.kind, "button")
    self.assertEqual(control.label, "Menu")

    debug = document.debug_control("menu-toggle")
    self.assertIsNotNone(debug)
    self.assertEqual(debug.kind, "button")
    self.assertEqual(debug.click_hint, "disclosure_toggle")
    self.assertEqual(debug.controlled_target, "menu")

  def test_render_marks_block_level_javascript_anchor_as_button_control(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
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
      )
    )

    rendered = render_normal_with_metadata(document.document, width=76, link_style="none")
    self.assertEqual(
      [span.control_id for span in rendered.control_spans],
      ["menu-toggle"],
    )
    self.assertEqual(rendered.link_spans, ())

  def test_form_controls_resolve_button_labels_from_aria_labelledby_and_title(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/buttons",
          content="""
          <html>
            <body>
              <span id="ship-label">Ship to 52404</span>
              <button id="ship" aria-labelledby="ship-label"></button>
              <button id="follow" title="Follow creator"></button>
            </body>
          </html>
          """,
        )
      )
    )

    controls = {control.control_id: control for control in document.form_controls()}
    self.assertEqual(controls["ship"].label, "Ship to 52404")
    self.assertEqual(controls["follow"].label, "Follow creator")

  def test_form_controls_build_label_and_id_indexes_once(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/buttons",
          content="""
          <html>
            <body>
              <span id="ship-label">Ship to 52404</span>
              <button id="ship" aria-labelledby="ship-label"></button>
              <label for="query">Query</label>
              <input id="query" type="text" name="q">
            </body>
          </html>
          """,
        )
      )
    )

    original_iter_elements = interactions_module._iter_elements
    iter_element_calls = 0

    def counting_iter_elements(current_document):
      nonlocal iter_element_calls
      iter_element_calls += 1
      yield from original_iter_elements(current_document)

    with patch.object(interactions_module, "_iter_elements", counting_iter_elements):
      controls = {control.control_id: control for control in document.form_controls()}

    self.assertEqual(controls["ship"].label, "Ship to 52404")
    self.assertEqual(controls["query"].label, "Query")
    self.assertEqual(iter_element_calls, 3)

  def test_form_controls_expose_picker_like_travel_launchers(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/travel",
          content="""
          <html>
            <body>
              <main>
                <button class="flex cursor-pointer items-center justify-between" type="button">日付指定なし 1泊</button>
                <div class="peopleCounter flex cursor-pointer items-center justify-between" data-gaclickid="OpenPeopleModal">
                  <span>大人2名</span><span>子供0名</span><span>1室</span>
                </div>
                <label class="cursor-pointer">
                  <input class="hidden" checked type="checkbox" />
                  <div class="cursor-pointer appearance-none rounded-full">すぐに使う 貯める</div>
                </label>
                <ul>
                  <li class="opacity-visible rounded-full cursor-pointer"></li>
                  <li class="rounded-full cursor-pointer"></li>
                  <li class="rounded-full cursor-pointer"></li>
                </ul>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    controls = [control for control in document.form_controls() if control.kind == "picker"]
    self.assertEqual([control.kind for control in controls], ["picker", "picker", "picker", "picker", "picker", "picker"])
    self.assertEqual(
      [control.label for control in controls],
      ["日付指定なし 1泊", "大人2名 子供0名 1室", "すぐに使う 貯める", "carousel page 1", "carousel page 2", "carousel page 3"],
    )

  def test_form_controls_treat_form_scoped_popup_buttons_as_pickers(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/ndl",
          content="""
          <html>
            <body>
              <form>
                <button type="submit" aria-haspopup="listbox" aria-controls="search-scope-panel">資料種別</button>
                <button type="submit" aria-haspopup="dialog" aria-controls="date-from-calendar">開始日</button>
              </form>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(
      [(control.kind, control.label) for control in controls],
      [("select", "資料種別"), ("picker", "開始日")],
    )

  def test_form_controls_treat_clickable_popup_launchers_as_pickers(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/ndl",
          content="""
          <html>
            <body>
              <div role="combobox" aria-haspopup="listbox" aria-controls="scope-selector">
                <span aria-label="資料種別"></span>
              </div>
              <div role="button" aria-haspopup="dialog" aria-controls="date-to-calendar">
                <span aria-label="終了日"></span>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([(control.kind, control.label) for control in controls], [("select", "資料種別"), ("picker", "終了日")])

  def test_picker_controls_support_click_and_debug_actions(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/travel",
          content="""
          <html>
            <body>
              <main>
                <button class="flex cursor-pointer items-center justify-between" type="button">日付指定なし 1泊</button>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    picker = document.form_controls()[0]
    self.assertEqual(picker.kind, "picker")

    snapshot = document.snapshot()
    self.assertEqual(snapshot.form_controls[0].supported_actions, ("click_button", "debug_control"))

    debug = document.debug_control(picker.control_id, current_source="https://example.com/travel")
    self.assertIsNotNone(debug)
    self.assertEqual(debug.kind, "picker")
    self.assertEqual(debug.click_hint, "javascript")

  def test_form_controls_expose_synthetic_search_shell_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/search-shell",
          content="""
          <html>
            <body>
              <nav aria-label="Top navigation with search field, account and cart">
                <div id="federated-search-box"></div>
              </nav>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(
      [(control.kind, control.input_type, control.label) for control in controls],
      [("text", "search", "Search"), ("submit", "", "Search")],
    )

  def test_form_controls_do_not_duplicate_existing_search_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/search-shell",
          content="""
          <html>
            <body>
              <nav aria-label="Top navigation with search field, account and cart">
                <div id="federated-search-box">
                  <form>
                    <input type="search" name="q" aria-label="Search by keyword" />
                    <button type="submit">Search</button>
                  </form>
                </div>
              </nav>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(len(controls), 2)
    self.assertEqual(controls[0].kind, "text")
    self.assertEqual(controls[1].kind, "submit")

  def test_form_controls_expose_synthetic_custom_search_bar_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/custom-search",
          content="""
          <html>
            <body>
              <custom-site-search-bar placeholder="キーワードを入力してください"></custom-site-search-bar>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(
      [(control.kind, control.input_type, control.label) for control in controls],
      [("text", "search", "Search"), ("submit", "", "Search")],
    )

  def test_form_controls_expose_synthetic_location_search_control(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/store-selector",
          content="""
          <html>
            <body>
              <div
                id="store-selector-trigger-desktop"
                class="header-store-container hide-on-mobile v2 pf-header-store"
                data-name="store selector menu"
                data-testid="pickup-address-header"
              ></div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(
      [(control.kind, control.input_type, control.label) for control in controls],
      [("text", "text", "Store search")],
    )

  def test_form_controls_do_not_duplicate_existing_location_search_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/store-selector",
          content="""
          <html>
            <body>
              <div
                id="store-selector-trigger-desktop"
                class="header-store-container hide-on-mobile v2 pf-header-store"
                data-name="store selector menu"
              >
                <form>
                  <input type="text" name="store-head-search" placeholder="Enter city, state or ZIP code" />
                </form>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(len(controls), 1)
    self.assertEqual(controls[0].kind, "text")

  def test_debug_controls_describes_tab_navigation_hint(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/timetable/railway/line-station/40-38/d1",
          content="""
          <html>
            <body>
              <div class="ek-direction-tabs">
                <button class="ek-dw-select" data-dw="2">休日</button>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    tab = document.debug_controls()[0]
    self.assertEqual(tab.kind, "tab")
    self.assertEqual(tab.click_hint, "navigation")
    self.assertEqual(tab.navigation_target, "https://example.com/timetable/railway/line-station/40-38/d1?dw=2")

  def test_agent_actions_keep_mutations_outside_beautifulsoup_style_reads(self) -> None:
    document = load_document(FORM)

    actions = document.agent_actions()
    self.assertTrue(actions.set_text_control("q", "phase9"))
    self.assertTrue(actions.cycle_select_control("category"))

    button = document.find("button")
    self.assertIsNotNone(button)
    self.assertEqual(document.find("input", attrs={"name": "q"}).get("value"), "phase9")
    self.assertEqual(document.form_controls()[2].value, "images")

  def test_agent_actions_support_generic_structured_invoke(self) -> None:
    document = load_document(FORM)

    actions = document.agent_actions()
    result = actions.invoke(AgentActionRequest(action="set_text", control_id="q", value="phase9"))
    self.assertEqual(result.status, "ok")
    self.assertTrue(result.changed)
    self.assertEqual(document.form_controls()[0].value, "phase9")

    submit_id = next(control.control_id for control in document.form_controls() if control.kind == "submit")
    submission = actions.invoke(
      AgentActionRequest(
        action="submit_form",
        control_id=submit_id,
        current_source="https://example.com/form",
      )
    )
    self.assertEqual(submission.status, "ok")
    self.assertEqual(submission.submission["method"], "get")
    self.assertEqual(submission.submission["enctype"], "application/x-www-form-urlencoded")
    self.assertEqual(
      submission.submission["url"],
      "https://example.com/search?q=phase9&notes=memo&category=articles&scope=title&safe=on&go=1",
    )

    debug = actions.invoke(
      AgentActionRequest(
        action="debug_control",
        control_id=submit_id,
        current_source="https://example.com/form",
      )
    )
    self.assertEqual(debug.status, "ok")
    self.assertEqual(debug.debug["click_hint"], "submit")

  def test_agent_actions_invoke_reports_not_found_and_supported_actions(self) -> None:
    document = load_document(FORM)

    missing = document.agent_actions().invoke(AgentActionRequest(action="set_text", control_id="missing", value="x"))
    self.assertEqual(missing.status, "not_found")
    self.assertEqual(missing.reason, "control_not_found")
    self.assertEqual(missing.available_actions, ())

    submit_id = next(control.control_id for control in document.form_controls() if control.kind == "submit")
    unsupported = document.agent_actions().invoke(AgentActionRequest(action="set_text", control_id=submit_id, value="x"))
    self.assertEqual(unsupported.status, "unsupported")
    self.assertEqual(unsupported.reason, "action_not_supported_for_control")
    self.assertEqual(unsupported.available_actions, ("submit_form", "debug_control"))

  def test_agent_actions_invoke_requires_confirmation_for_password_inputs(self) -> None:
    document = load_document(PASSWORD_FORM)

    password = next(control for control in document.form_controls() if control.input_type == "password")
    self.assertEqual(password.value, "secret")
    blocked = document.agent_actions().invoke(
      AgentActionRequest(action="set_text", control_id=password.control_id, value="s3cr3t")
    )
    self.assertEqual(blocked.status, "requires_confirmation")
    self.assertEqual(blocked.reason, "password_input_requires_confirmation")
    self.assertTrue(blocked.requires_confirmation)
    self.assertFalse(blocked.changed)
    self.assertEqual(document.form_controls()[1].value, "secret")

    confirmed = document.agent_actions().invoke(
      AgentActionRequest(
        action="set_text",
        control_id=password.control_id,
        value="s3cr3t",
        confirmed=True,
      )
    )
    self.assertEqual(confirmed.status, "ok")
    self.assertTrue(confirmed.changed)
    self.assertEqual(document.form_controls()[1].value, "s3cr3t")

  def test_exposes_form_controls_and_submission(self) -> None:
    document = load_document(FORM)

    controls = document.form_controls()
    self.assertEqual(
      [control.kind for control in controls],
      ["text", "textarea", "select", "radio", "radio", "checkbox", "submit"],
    )
    self.assertEqual(controls[0].value, "hello")
    self.assertEqual(controls[2].value, "articles")

    self.assertTrue(document.append_text_to_control("q", "!"))
    self.assertTrue(document.backspace_control_text("q"))
    self.assertTrue(document.cycle_select_control("category"))
    self.assertTrue(document.select_radio_control("scope-all"))
    self.assertTrue(document.toggle_checkbox("safe"))

    submission = document.submit_form_control(controls[-1].control_id, "https://example.com/form")
    self.assertIsNotNone(submission)
    self.assertEqual(submission.method, "get")
    self.assertEqual(
      submission.url(),
      "https://example.com/search?q=hello&notes=memo&category=images&scope=all&go=1",
    )

  def test_exposes_post_form_submission_data(self) -> None:
    document = TWebDocument(
      parse_document(
        fetch_resource(
          str(ROOT / "tests" / "fixtures" / "form_post.html")
        )
      )
    )

    controls = document.form_controls()
    submission = document.submit_form_control(controls[-1].control_id, "https://example.com/form")
    self.assertIsNotNone(submission)
    self.assertEqual(submission.method, "post")
    self.assertEqual(submission.action, "https://example.com/submit")
    self.assertEqual(
      submission.form_data(),
      [("q", "hello"), ("notes", "memo"), ("category", "articles"), ("scope", "title"), ("safe", "on"), ("go", "1")],
    )

  def test_masks_password_controls_but_submits_real_value(self) -> None:
    document = load_document(PASSWORD_FORM)

    controls = document.form_controls()
    password = next(control for control in controls if control.name == "password")
    self.assertEqual(password.kind, "text")
    self.assertEqual(password.input_type, "password")
    self.assertEqual(password.value, "secret")
    self.assertEqual(password.token, "[input:password password=******]")

    submission = document.submit_form_control(controls[-1].control_id, "https://example.com/login")
    self.assertIsNotNone(submission)
    self.assertEqual(submission.form_data(), [("user", "alice"), ("password", "secret"), ("go", "1")])

  def test_updates_mirrored_text_controls_with_same_name(self) -> None:
    document = load_document(FORM)
    # Add a second mirrored input like Wikipedia's duplicated search box.
    first_input = document.find("input", attrs={"name": "q"}).node
    duplicate = ElementNode(tag="input", attrs=dict(first_input.attrs))
    document.document.body.append_child(duplicate)
    # Re-sync interaction metadata after direct DOM change.
    register_parents_for_interactions(document.document)
    sync_interactive_document(document.document)

    self.assertTrue(document.append_text_to_control("q", "!"))
    inputs = [node for node in document.document.find_all("input") if node.attrs.get("name") == "q"]
    self.assertEqual([node.attrs.get("value") for node in inputs], ["hello!", "hello!"])

  def test_assigns_unique_generated_control_ids(self) -> None:
    document = load_document(ROOT / "tests" / "fixtures" / "duplicate_buttons.html")

    controls = document.form_controls()
    submit_controls = [control for control in controls if control.kind == "submit"]
    self.assertEqual(
      [control.control_id for control in submit_controls],
      ["tweb-button-1", "tweb-button-2"],
    )

    first = document.submit_form_control(submit_controls[0].control_id, "https://example.com/page")
    second = document.submit_form_control(submit_controls[1].control_id, "https://example.com/page")
    self.assertIsNotNone(first)
    self.assertIsNotNone(second)
    self.assertEqual(first.params, (("slot", "first"),))
    self.assertEqual(second.params, (("slot", "second"),))

  def test_button_type_button_is_not_treated_as_submit(self) -> None:
    document = load_document(ROOT / "tests" / "fixtures" / "button_only.html")

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["text", "button"])
    self.assertIsNone(document.submit_form_control(controls[-1].control_id, "https://example.com/login"))

  def test_exposes_google_custom_search_fallback_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <gcse:searchbox-only resultsurl="/schresult.html"></gcse:searchbox-only>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(
      [(control.kind, control.name, control.value) for control in controls],
      [("text", "q", ""), ("submit", "search", "/schresult.html")],
    )

  def test_exposes_google_custom_search_div_fallback_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <div class="gcse-searchbox-only"></div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual(
      [(control.kind, control.name, control.value) for control in controls],
      [("text", "q", ""), ("submit", "search", "/")],
    )

  def test_document_write_in_external_script_exposes_google_custom_search_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <div id="search">
                <script src="https://example.com/search.js"></script>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_script(
      "document.write('<div class=\"gcse-searchbox-only\" data-resultsurl=\"/schresult.html\"></div>');",
      source_url="https://example.com/search.js",
    )

    controls = document.form_controls()
    self.assertEqual(
      [(control.kind, control.name, control.value) for control in controls],
      [("text", "q", ""), ("submit", "search", "/")],
    )

  def test_button_without_form_owner_is_not_treated_as_submit(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/menu",
          content="""
          <html>
            <body>
              <nav>
                <button>くらし</button>
              </nav>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["button"])
    self.assertIsNone(document.submit_form_control(controls[0].control_id, "https://example.com/menu"))

  def test_submit_button_with_form_attribute_uses_associated_form(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/menu",
          content="""
          <html>
            <body>
              <form id="topic-form" action="/topic">
                <input type="hidden" name="slug" value="lifestyle" />
              </form>
              <nav>
                <button form="topic-form" name="go" value="1">くらし</button>
              </nav>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["submit"])
    submission = document.submit_form_control(controls[0].control_id, "https://example.com/menu")
    self.assertIsNotNone(submission)
    self.assertEqual(submission.method, "get")
    self.assertEqual(submission.url(), "https://example.com/topic?slug=lifestyle&go=1")

  def test_click_button_control_runs_javascript_handler(self) -> None:
    document = load_document(BUTTON_CLICK)
    document.execute_embedded_scripts(ignore_errors=False)

    controls = document.form_controls()
    button = next(control for control in controls if control.kind == "button")

    result = document.click_button_control(button.control_id)
    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "dom_updated")
    self.assertTrue(result.dom_changed)
    self.assertIn("Signed in as user@example.com", document.body_text())

  def test_click_button_control_runs_javascript_anchor_handler(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/menu",
          content="""
          <html>
            <body>
              <aside id="menu" style="height:0;overflow:auto">
                <p>Hidden menu entry</p>
              </aside>
              <a id="menu-toggle" href="javascript:void(0);">Menu</a>
            </body>
          </html>
          """,
        )
      )
    )

    button = next(control for control in document.form_controls() if control.control_id == "menu-toggle")
    result = document.click_button_control(button.control_id)

    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "dom_updated")
    self.assertTrue(result.dom_changed)
    self.assertIn("Hidden menu entry", document.body_text(visible_only=True))
    result = document.click_button_control(button.control_id)
    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "dom_updated")
    self.assertNotIn("Hidden menu entry", document.body_text(visible_only=True))

  def test_click_button_control_reports_blocked_navigation_request(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/account",
          content=BUTTON_CLICK_NAVIGATION.read_text(),
        )
      )
    )
    document.execute_embedded_scripts(ignore_errors=False)

    button = next(control for control in document.form_controls() if control.kind == "button")
    result = document.click_button_control(button.control_id, policy="dom-only")

    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "navigation_requested")
    self.assertTrue(result.blocked_by_policy)
    self.assertEqual(result.navigation_target, "https://example.com/next")
    self.assertIn("Trying navigation", document.body_text())

  def test_click_button_control_treats_prevented_button_with_blocked_network_as_clicked(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/account",
          content="""
          <html>
            <body>
              <p id="status">Idle</p>
              <input id="button_accept" type="button" value="Accept">
              <script>
                document.getElementById("button_accept").addEventListener("click", (event) => {
                  event.preventDefault();
                  document.getElementById("status").textContent = "Submitting";
                  var xhr = new XMLHttpRequest();
                  xhr.open("POST", "/wi2auth/xhr/login");
                  xhr.send("");
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )
    document.execute_embedded_scripts(ignore_errors=False)

    button = next(control for control in document.form_controls() if control.control_id == "button_accept")
    result = document.click_button_control(button.control_id, policy="dom-only")

    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "network_requested")
    self.assertTrue(result.blocked_by_policy)
    self.assertEqual(len(result.network_requests), 1)
    self.assertEqual(result.network_requests[0].method, "POST")
    self.assertEqual(result.network_requests[0].url, "https://example.com/wi2auth/xhr/login")
    self.assertIn("Submitting", document.body_text())

  def test_agent_actions_invoke_reports_blocked_button_policy(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/account",
          content=BUTTON_CLICK_NAVIGATION.read_text(),
        )
      )
    )
    document.execute_embedded_scripts(ignore_errors=False)

    button = next(control for control in document.form_controls() if control.kind == "button")
    result = document.agent_actions().invoke(
      AgentActionRequest(action="click_button", control_id=button.control_id, policy="dom-only")
    )

    self.assertEqual(result.status, "blocked")
    self.assertEqual(result.reason, "blocked_by_policy")
    self.assertEqual(result.button_click["classification"], "navigation_requested")
    self.assertTrue(result.button_click["blocked_by_policy"])

  def test_agent_actions_invoke_keeps_blocked_network_button_as_successful_click(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/account",
          content="""
          <html>
            <body>
              <p id="status">Idle</p>
              <input id="button_accept" type="button" value="Accept">
              <script>
                document.getElementById("button_accept").addEventListener("click", (event) => {
                  event.preventDefault();
                  document.getElementById("status").textContent = "Submitting";
                  var xhr = new XMLHttpRequest();
                  xhr.open("POST", "/wi2auth/xhr/login");
                  xhr.send("");
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )
    document.execute_embedded_scripts(ignore_errors=False)

    button = next(control for control in document.form_controls() if control.control_id == "button_accept")
    result = document.agent_actions().invoke(
      AgentActionRequest(action="click_button", control_id=button.control_id, policy="dom-only")
    )

    self.assertEqual(result.status, "ok")
    self.assertIsNone(result.reason)
    self.assertTrue(result.changed)
    self.assertEqual(result.button_click["classification"], "network_requested")
    self.assertTrue(result.button_click["blocked_by_policy"])

  @patch("tweb.js_runtime.requests.request")
  def test_click_button_control_allows_network_policy_and_reports_request(self, mock_request: Mock) -> None:
    response = Mock()
    response.url = "https://example.com/api/profile"
    response.status_code = 200
    response.reason = "OK"
    response.text = "Profile loaded"
    response.headers = {}
    response.close = Mock()
    mock_request.return_value = response

    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/account",
          content=BUTTON_CLICK_FETCH.read_text(),
        )
      )
    )
    document.execute_embedded_scripts(ignore_errors=False)

    button = next(control for control in document.form_controls() if control.kind == "button")
    result = document.click_button_control(button.control_id, policy="network")

    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "network_requested")
    self.assertFalse(result.blocked_by_policy)
    self.assertEqual(len(result.network_requests), 1)
    self.assertEqual(result.network_requests[0].method, "GET")
    self.assertEqual(result.network_requests[0].url, "https://example.com/api/profile")
    self.assertTrue(result.dom_changed)
    self.assertIn("Profile loaded", document.body_text())

  @patch("tweb.api.fetch_resource")
  def test_execute_embedded_scripts_skips_third_party_external_scripts(self, mock_fetch_resource: Mock) -> None:
    page = Resource(
      source="https://example.com/page",
      content="""
      <html>
        <body>
          <script src="https://thirdparty.example.net/widget.js"></script>
          <p>Body</p>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(page))

    document.execute_embedded_scripts(ignore_errors=False)

    mock_fetch_resource.assert_not_called()
    self.assertEqual(document.body_text(), "Body")

  @patch("tweb.js_runtime.fetch_resource")
  def test_execute_embedded_scripts_keeps_same_site_subdomain_scripts(self, mock_fetch_resource: Mock) -> None:
    page = Resource(
      source="https://example.co.jp/page",
      content="""
      <html>
        <body>
          <script src="https://cdn.example.co.jp/app.js"></script>
        </body>
      </html>
      """,
    )
    mock_fetch_resource.return_value = Resource(
      source="https://cdn.example.co.jp/app.js",
      content="document.body.textContent = 'same-site';",
    )
    document = TWebDocument(parse_document(page))

    document.execute_embedded_scripts(ignore_errors=False)

    mock_fetch_resource.assert_called_once_with(
      "https://cdn.example.co.jp/app.js",
      session=None,
      request_headers=None,
    )
    self.assertEqual(document.body_text(), "same-site")

  def test_exposes_role_tab_as_clickable_control(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/tabs",
          content="""
          <html>
            <body>
              <div role="tablist">
                <button role="tab" aria-selected="true" aria-controls="weekday-panel">平日</button>
                <div role="tab" aria-controls="holiday-panel">休日</div>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["tab", "tab"])
    self.assertEqual(controls[0].token, "[tab: 平日 selected]")
    self.assertTrue(controls[0].checked)
    self.assertEqual(controls[1].label, "休日")
    self.assertEqual(controls[1].token, "[tab: 休日]")
    self.assertIn("[tab: 平日 selected]", render_normal(document.document, width=80, text_styles=False))

  def test_exposes_role_button_div_as_clickable_control(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/account",
          content="""
          <html>
            <body>
              <div role="button" aria-label="Account menu"></div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["button"])
    self.assertEqual(controls[0].label, "Account menu")
    self.assertEqual(controls[0].token, "(Account menu)")
    self.assertIn("(Account menu)", render_normal(document.document, width=80, text_styles=False))

  def test_exposes_clickable_aria_label_shell_as_button_control(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/store",
          content="""
          <html>
            <body>
              <div class="cursor-pointer" aria-label="Choose store"></div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["button"])
    self.assertEqual(controls[0].label, "Choose store")
    self.assertEqual(controls[0].token, "(Choose store)")
    self.assertIn("(Choose store)", render_normal(document.document, width=80, text_styles=False))

  def test_exposes_clickable_icon_shell_with_descendant_label_as_button_control(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/store",
          content="""
          <html>
            <body>
              <div class="cursor-pointer">
                <svg aria-label="Choose store"></svg>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["button"])
    self.assertEqual(controls[0].label, "Choose store")
    self.assertEqual(controls[0].token, "(Choose store)")
    self.assertIn("(Choose store)", render_normal(document.document, width=80, text_styles=False))

  def test_click_button_control_accepts_role_tab(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/tabs",
          content="""
          <html>
            <body>
              <div role="tablist">
                <button role="tab" aria-selected="true" aria-controls="weekday-panel">平日</button>
                <button role="tab" aria-controls="holiday-panel">休日</button>
              </div>
              <section id="weekday-panel">平日ダイヤ</section>
              <section id="holiday-panel" hidden>休日ダイヤ</section>
              <script>
                document.querySelectorAll('[role="tab"]').forEach((tab) => {
                  tab.addEventListener('click', () => {
                    document.querySelectorAll('[role="tab"]').forEach((candidate) => {
                      candidate.setAttribute('aria-selected', String(candidate === tab));
                    });
                    document.getElementById('weekday-panel').toggleAttribute('hidden', tab.textContent.trim() !== '平日');
                    document.getElementById('holiday-panel').toggleAttribute('hidden', tab.textContent.trim() !== '休日');
                  });
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )
    document.execute_embedded_scripts(ignore_errors=False)

    tab = next(control for control in document.form_controls() if control.label == "休日")
    result = document.click_button_control(tab.control_id)

    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "dom_updated")
    self.assertTrue(result.dom_changed)
    refreshed = {control.label: control for control in document.form_controls()}
    self.assertFalse(refreshed["平日"].checked)
    self.assertTrue(refreshed["休日"].checked)
    self.assertIn("休日ダイヤ", document.body_text())

  def test_button_group_with_tab_like_classes_is_exposed_as_tab_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/tabs",
          content="""
          <html>
            <body>
              <div class="select-type">
                <button class="select-type-btn">平日</button>
                <button class="select-type-btn active">休日</button>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    controls = document.form_controls()
    self.assertEqual([control.kind for control in controls], ["tab", "tab"])
    self.assertEqual(controls[0].token, "[tab: 平日]")
    self.assertEqual(controls[1].token, "[tab: 休日 selected]")
    self.assertIn("[tab: 休日 selected]", render_normal(document.document, width=80, text_styles=False))

  def test_click_button_control_uses_native_activation_for_class_based_tabs(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/tabs",
          content="""
          <html>
            <body>
              <div class="select-type">
                <button class="select-type-btn active">平日</button>
                <button class="select-type-btn">休日</button>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    tab = next(control for control in document.form_controls() if control.kind == "tab" and control.label == "休日")
    result = document.click_button_control(tab.control_id)

    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "dom_updated")
    self.assertTrue(result.dom_changed)
    refreshed = {control.label: control for control in document.form_controls()}
    self.assertFalse(refreshed["平日"].checked)
    self.assertTrue(refreshed["休日"].checked)

  def test_click_button_control_returns_navigation_for_ekitan_style_tabs(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/timetable/railway/line-station/40-38/d1",
          content="""
          <html>
            <body>
              <div class="select-type">
                <button class="select-type-btn ek-dw-select" data-dw="0">平日</button>
                <button class="select-type-btn ek-dw-select" data-dw="2">休日</button>
              </div>
              <div class="select-type">
                <button class="select-type-btn ek-list-select">リスト形式</button>
                <button class="select-type-btn ek-pocket-select active">ポケット形式</button>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    holiday = next(control for control in document.form_controls() if control.kind == "tab" and control.label == "休日")
    holiday_result = document.click_button_control(holiday.control_id)
    self.assertEqual(holiday_result.navigation_target, "https://example.com/timetable/railway/line-station/40-38/d1?dw=2")

    list_tab = next(control for control in document.form_controls() if control.kind == "tab" and control.label == "リスト形式")
    list_result = document.click_button_control(list_tab.control_id)
    self.assertEqual(list_result.navigation_target, "https://example.com/timetable/railway/line-station/40-38/d1?view=list")

  def test_click_button_control_tab_tolerates_background_timer_runaway_after_dom_update(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/tabs",
          content="""
          <html>
            <body>
              <div role="tablist">
                <button role="tab" aria-selected="true">平日</button>
                <button role="tab">休日</button>
              </div>
              <section id="weekday-panel">平日ダイヤ</section>
              <section id="holiday-panel" hidden>休日ダイヤ</section>
              <script>
                const chunks = [];
                document.querySelectorAll('[role="tab"]').forEach((tab) => {
                  tab.addEventListener('click', () => {
                    document.querySelectorAll('[role="tab"]').forEach((candidate) => {
                      candidate.setAttribute('aria-selected', String(candidate === tab));
                    });
                    document.getElementById('weekday-panel').toggleAttribute('hidden', tab.textContent.trim() !== '平日');
                    document.getElementById('holiday-panel').toggleAttribute('hidden', tab.textContent.trim() !== '休日');
                    function spin() {
                      chunks.push('x'.repeat(1000));
                      setTimeout(spin, 0);
                    }
                    setTimeout(spin, 0);
                  });
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )
    document.execute_embedded_scripts(ignore_errors=False)

    tab = next(control for control in document.form_controls() if control.kind == "tab" and control.label == "休日")
    result = document.click_button_control(tab.control_id)

    self.assertTrue(result.clicked)
    self.assertEqual(result.classification, "dom_updated")
    self.assertTrue(result.dom_changed)
    refreshed = {control.label: control for control in document.form_controls()}
    self.assertTrue(refreshed["休日"].checked)
    self.assertIn("休日ダイヤ", document.body_text())

  @patch("tweb.api.fetch_rendered_resource")
  def test_replaces_broken_js_render_with_browser_rendered_dom(self, mock_fetch_rendered_resource) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/app",
      content="""
      <html>
        <body>
          <main>
            <h3>Rendered Title</h3>
            <a href="/article">Rendered Link</a>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>loading</main>
              <script>
                document.querySelector('main').remove();
                document.body.append('Something went wrong. Try again.');
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertIsNotNone(document.find("main"))
    self.assertIn("Rendered Title", document.body_text())
    self.assertEqual(document.links()[0].href, "/article")
    mock_fetch_rendered_resource.assert_called_once_with("https://example.com/app", session=None)

  @patch("tweb.api.fetch_rendered_resource")
  def test_does_not_auto_render_cookie_backed_script_pages_without_failure_signal(self, mock_fetch_rendered_resource) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/app",
      content="""
      <html>
        <body>
          <main>
            <h3>Rendered Personalized Feed</h3>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>Server rendered shell</main>
              <script>document.body.dataset.ready = '1';</script>
            </body>
          </html>
          """,
        )
      )
    )
    jar = RequestsCookieJar()
    jar.set("sid", "abc", domain=".example.com", path="/")
    session = create_session(jar)
    try:
      document.execute_embedded_scripts(ignore_errors=False, session=session, browser_render_policy="auto")
    finally:
      session.close()

    self.assertIn("Server rendered shell", document.body_text())
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_uses_browser_render_for_client_render_bailout_marker(self, mock_fetch_rendered_resource) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/app",
      content="""
      <html>
        <body>
          <main>
            <h3>Rendered Topic Section</h3>
            <p>開発効率化</p>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main id="main-content"></main>
              <template data-dgst="BAILOUT_TO_CLIENT_SIDE_RENDERING"></template>
              <script>document.body.dataset.ready = '1';</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertIn("Rendered Topic Section", document.body_text())
    self.assertIn("開発効率化", document.body_text())
    mock_fetch_rendered_resource.assert_called_once_with("https://example.com/app", session=None)

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_skips_browser_render_for_bailout_marker_when_main_is_already_readable(
    self,
    mock_fetch_rendered_resource,
  ) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/topic/outdoor",
          content="""
          <html>
            <body>
              <main id="main-content">
                <section>
                  <h1>アウトドア</h1>
                  <p>
                    これは十分に長い本文です。React bailout marker が hidden で残っていても、
                    すでに可視の main 本文が十分読める場合は browser-render fallback に
                    倒れないことを確認するため、同じ説明を繰り返して長さを確保します。
                    これは十分に長い本文です。React bailout marker が hidden で残っていても、
                    すでに可視の main 本文が十分読める場合は browser-render fallback に
                    倒れないことを確認するため、同じ説明を繰り返して長さを確保します。
                  </p>
                </section>
              </main>
              <template id="B:3"></template>
              <section id="S:3" hidden>
                <aside>
                  <a href="/topic/outdoor">アウトドア</a>
                </aside>
              </section>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertIn("アウトドア", document.body_text(visible_only=True))
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_skips_browser_render_for_bailout_marker_when_hydration_hints_can_fill_main(
    self,
    mock_fetch_rendered_resource,
  ) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/outdoor",
          content="""
          <html>
            <body>
              <main id="main-content"></main>
              <template data-dgst="BAILOUT_TO_CLIENT_SIDE_RENDERING"></template>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "30:[\\"$\\",\\"$L32\\",null,{\\"mobile\\":[\\"$\\",\\"$L33\\",null,{\\"categories\\":[{\\"id\\":24,\\"title\\":\\"趣味・関心\\",\\"subCategories\\":[{\\"tagName\\":\\"アウトドア\\",\\"title\\":\\"アウトドア\\",\\"engName\\":\\"outdoor\\"},{\\"tagName\\":\\"キャンプ\\",\\"title\\":\\"キャンプ\\",\\"engName\\":\\"outdoor/camping\\"}]}]}]}"]);
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    text = document.body_text()
    self.assertIn("アウトドア", text)
    self.assertIn("キャンプ", text)
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_uses_browser_render_for_loading_shell_main(self, mock_fetch_rendered_resource) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/app",
      content="""
      <html>
        <body>
          <main>
            <h3>Rendered Feed</h3>
            <p>First article title</p>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>
                <div class="loading-spinner"></div>
              </main>
              <script>document.body.dataset.ready = '1';</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertIn("Rendered Feed", document.body_text())
    self.assertIn("First article title", document.body_text())
    mock_fetch_rendered_resource.assert_called_once_with("https://example.com/app", session=None)

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_uses_browser_render_for_google_enablejs_interstitial(self, mock_fetch_rendered_resource) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://www.google.com/search?q=test",
      content="""
      <html>
        <body>
          <main>
            <h3>JavaScript challenge</h3>
            <p>続行するには、ウェブブラウザで JavaScript を有効にしてください。</p>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://www.google.com/search?q=test",
          content="""
          <html>
            <body>
              <div style="display:none">
                Google 検索にアクセスできない場合は、ここをクリックするか、フィードバックを送信してください。
              </div>
              <script>document.body.dataset.ready = "1";</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertIn("JavaScript challenge", document.body_text())
    mock_fetch_rendered_resource.assert_called_once_with("https://www.google.com/search?q=test", session=None)

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_skips_browser_render_for_article_with_extra_loading_widget(self, mock_fetch_rendered_resource) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/article",
      content="""
      <html>
        <body>
          <main>
            <h1>Rendered Feed</h1>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article",
          content="""
          <html>
            <body>
              <main>
                <article>
                  <h1>Article Title</h1>
                  <p>
                    これは十分に長い本文です。loading widget が別枠で残っていても、
                    すでに本文自体は読めているケースでは browser-render fallback に
                    倒れないことを確認するため、同じ説明文を繰り返して長さを確保します。
                    これは十分に長い本文です。loading widget が別枠で残っていても、
                    すでに本文自体は読めているケースでは browser-render fallback に
                    倒れないことを確認するため、同じ説明文を繰り返して長さを確保します。
                    これは十分に長い本文です。loading widget が別枠で残っていても、
                    すでに本文自体は読めているケースでは browser-render fallback に
                    倒れないことを確認するため、同じ説明文を繰り返して長さを確保します。
                    これは十分に長い本文です。loading widget が別枠で残っていても、
                    すでに本文自体は読めているケースでは browser-render fallback に
                    倒れないことを確認するため、同じ説明文を繰り返して長さを確保します。
                  </p>
                </article>
                <div class="extra-item-container">
                  <div class="loading-spinner"></div>
                </div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertIn("Article Title", document.body_text())
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_skips_browser_render_for_article_with_substantial_content_outside_loading_placeholder(
    self,
    mock_fetch_rendered_resource,
  ) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/article",
      content="""
      <html>
        <body>
          <main>
            <h1>Rendered Feed</h1>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article",
          content="""
          <html>
            <body>
              <main>
                <div class="article-wrapper">
                  <h1>Article Title</h1>
                  <p>
                    これは十分に長い本文です。extra item 内に loading dots が残っていても、
                    すでに読める記事本文が main の大半を占めるケースでは browser-render
                    fallback に倒れないことを確認するため、説明文を繰り返して長さを確保します。
                    これは十分に長い本文です。extra item 内に loading dots が残っていても、
                    すでに読める記事本文が main の大半を占めるケースでは browser-render
                    fallback に倒れないことを確認するため、説明文を繰り返して長さを確保します。
                  </p>
                </div>
                <div class="extra-item-container">
                  <div class="loading-dots"></div>
                  <ul>
                    <li>トップ</li>
                    <li>アウトドア</li>
                    <li>キャンプ</li>
                  </ul>
                </div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertIn("Article Title", document.body_text())
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_logs_reason_when_loading_placeholder_triggers_browser_render(
    self,
    mock_fetch_rendered_resource,
  ) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/app",
      content="""
      <html>
        <body>
          <main>
            <h3>Rendered Feed</h3>
            <p>First article title</p>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>
                <div class="loading-spinner"></div>
              </main>
              <script>document.body.dataset.ready = '1';</script>
            </body>
          </html>
          """,
        )
      )
    )

    with self.assertLogs("tweb", level="DEBUG") as captured:
      document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertTrue(
      any(
        "action=try" in entry and "reason=loading-placeholder" in entry
        for entry in captured.output
      )
    )
    self.assertTrue(
      any(
        "action=apply" in entry
        and "reason=browser-rendered-document-accepted" in entry
        and "trigger=auto-fallback" in entry
        for entry in captured.output
      )
    )

  def test_manual_retry_logs_trigger_and_uses_injected_browser_render_fetcher(self) -> None:
    calls: list[str] = []

    def fake_browser_render_fetcher(request: BrowserRenderRequest, *, session=None) -> BrowserRenderResult:
      del session
      calls.append(request.target)
      return BrowserRenderResult(
        source=request.target,
        content="""
        <html>
          <body>
            <main>
              <h1>Rendered Feed</h1>
            </main>
          </body>
        </html>
        """,
      )

    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>
                <div class="loading-spinner"></div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    with self.assertLogs("tweb", level="DEBUG") as captured:
      document.execute_embedded_scripts(
        ignore_errors=False,
        browser_render_policy="always",
        browser_render_fetcher=fake_browser_render_fetcher,
      )

    self.assertEqual(calls, ["https://example.com/app"])
    self.assertTrue(document.browser_rendered_via_chrome)
    self.assertTrue(
      any(
        "action=try" in entry
        and "reason=policy-always" in entry
        and "trigger=manual-retry" in entry
        for entry in captured.output
      )
    )

  def test_auto_policy_logs_failure_class_when_browser_render_fetcher_is_unavailable(self) -> None:
    def unavailable_browser_render_fetcher(request: BrowserRenderRequest, *, session=None) -> BrowserRenderResult:
      del request, session
      raise FetchError("browser-render provider unavailable: webkit")

    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>
                <div class="loading-spinner"></div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    with self.assertLogs("tweb", level="DEBUG") as captured:
      document.execute_embedded_scripts(
        ignore_errors=False,
        browser_render_policy="auto",
        browser_render_fetcher=unavailable_browser_render_fetcher,
      )

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertTrue(
      any(
        "reason=browser-render-fetch-failed" in entry
        and "failure_class=provider-unavailable" in entry
        and "trigger=auto-fallback" in entry
        for entry in captured.output
      )
    )

  def test_manual_retry_log_sanitizes_source_url(self) -> None:
    def fake_browser_render_fetcher(request: BrowserRenderRequest, *, session=None) -> BrowserRenderResult:
      del session
      return BrowserRenderResult(
        source=request.target,
        content="""
        <html>
          <body>
            <main><h1>Rendered Feed</h1></main>
          </body>
        </html>
        """,
      )

    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app?token=secret#frag",
          content="""
          <html>
            <body>
              <main><div class="loading-spinner"></div></main>
            </body>
          </html>
          """,
        )
      )
    )

    with self.assertLogs("tweb", level="DEBUG") as captured:
      document.execute_embedded_scripts(
        ignore_errors=False,
        browser_render_policy="always",
        browser_render_fetcher=fake_browser_render_fetcher,
      )

    joined = "\n".join(captured.output)
    self.assertNotIn("secret", joined)
    self.assertNotIn("#frag", joined)
    self.assertIn("token=%3Credacted%3E", joined)

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_logs_reason_when_substantial_content_skips_browser_render(
    self,
    mock_fetch_rendered_resource,
  ) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/article",
      content="""
      <html>
        <body>
          <main>
            <h1>Rendered Feed</h1>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article",
          content="""
          <html>
            <body>
              <main>
                <div class="article-wrapper">
                  <h1>Article Title</h1>
                  <p>
                    これは十分に長い本文です。extra item 内に loading dots が残っていても、
                    すでに読める記事本文が main の大半を占めるケースでは browser-render
                    fallback に倒れないことを確認するため、説明文を繰り返して長さを確保します。
                    これは十分に長い本文です。extra item 内に loading dots が残っていても、
                    すでに読める記事本文が main の大半を占めるケースでは browser-render
                    fallback に倒れないことを確認するため、説明文を繰り返して長さを確保します。
                  </p>
                </div>
                <div class="extra-item-container">
                  <div class="loading-dots"></div>
                  <ul>
                    <li>トップ</li>
                    <li>アウトドア</li>
                    <li>キャンプ</li>
                  </ul>
                </div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    with self.assertLogs("tweb", level="DEBUG") as captured:
      document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertTrue(
      any(
        "action=try" in entry and "reason=loading-placeholder" in entry
        for entry in captured.output
      )
    )
    self.assertTrue(
      any(
        "action=skip" in entry and "reason=substantial-content-outside-loading-placeholder" in entry
        for entry in captured.output
      )
    )
    self.assertFalse(document.browser_rendered_via_chrome)

  def test_body_text_visible_only_ignores_hidden_failure_shells(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <noscript>JavaScript is not available. Please enable JavaScript.</noscript>
              <main>
                <h1>Visible title</h1>
                <div style="display: none;">Something went wrong. Try again.</div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    self.assertIn("Something went wrong", document.body_text())
    self.assertEqual(document.body_text(visible_only=True), "Visible title")

  def test_body_text_visible_only_uses_selected_options_for_closed_selects(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/form",
          content="""
          <html>
            <body>
              <select id="single">
                <option>First choice</option>
                <option>Hidden choice</option>
              </select>
              <select id="multiple" multiple>
                <option selected>Selected alpha</option>
                <option>Hidden beta</option>
                <option selected>Selected gamma</option>
              </select>
            </body>
          </html>
          """,
        )
      )
    )

    self.assertEqual(
      document.body_text(visible_only=True),
      "First choice Selected alpha Selected gamma",
    )

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_skips_browser_render_for_hidden_error_shell_with_visible_main(self, mock_fetch_rendered_resource) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <noscript>
                JavaScript is not available. Please enable JavaScript or switch to a supported browser.
              </noscript>
              <div id="react-root">
                <main>
                  <h1>Everything happens here.</h1>
                  <p>Continue with phone number</p>
                </main>
                <div id="ScriptLoadFailure" style="display: none;">
                  Something went wrong. Try again.
                  Some privacy related extensions may cause issues.
                </div>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertIn("Everything happens here.", document.body_text(visible_only=True))
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_prunes_visible_error_shell_when_main_is_already_readable(self, mock_fetch_rendered_resource) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <div class="app-shell">
                <main>
                  <h1>Everything happens here.</h1>
                  <p>
                    Continue with phone number and use the main article content that already fills
                    the page with enough readable text to avoid any fallback behavior from kicking in.
                  </p>
                  <p>
                    This extra paragraph keeps the visible text substantial so the failure shell can
                    be safely removed from the final output instead of being rendered at the end.
                  </p>
                </main>
              </div>
              <section class="error-shell">
                <h1>申し訳ありません、ただ今障害が発生しております。</h1>
                <p>復旧作業中ですのでしばらくお待ちください。問い合わせフォームまでご連絡ください。</p>
                <a href="https://help.example.com/contact">問い合わせフォームへ</a>
              </section>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertIn("Everything happens here.", document.body_text())
    self.assertNotIn("障害が発生しております", document.body_text())
    self.assertNotIn("問い合わせフォームへ", document.body_text(visible_only=True))

  @patch("tweb.api.fetch_resource")
  def test_execute_embedded_scripts_restores_same_site_noscript_iframe_shells(self, mock_fetch_resource) -> None:
    def fake_fetch_resource(url: str, session=None):
      if url == "https://example.com/common_header.html":
        return Resource(
          source=url,
          content="""
          <html>
            <body>
              <div class="headerBox">
                <form id="searchform" action="/search.html">
                  <input type="text" name="q" title="ここに検索語を入力">
                  <button type="submit" name="sa" value="検索">検索</button>
                </form>
                <button id="gnavBtn" type="button">メニュー 閉じる</button>
                <a href="/english/index.html">English</a>
              </div>
            </body>
          </html>
          """,
        )
      if url == "https://example.com/common_footer.html":
        return Resource(
          source=url,
          content="""
          <html>
            <body>
              <nav>
                <a href="/about/index.html">警察庁について</a>
                <a href="/news/index.html">お知らせ</a>
              </nav>
            </body>
          </html>
          """,
        )
      raise AssertionError(url)

    mock_fetch_resource.side_effect = fake_fetch_resource
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <header id="header" role="banner">
                <noscript><iframe src="/common_header.html" title="header"></iframe></noscript>
              </header>
              <main>
                <h1>Main body</h1>
              </main>
              <footer id="footer" role="contentinfo">
                <noscript><iframe src="/common_footer.html" title="footer"></iframe></noscript>
              </footer>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    controls = document.form_controls()
    self.assertTrue(any(control.name == "q" and control.kind == "text" for control in controls))
    self.assertTrue(any(control.value == "検索" for control in controls))
    self.assertIn("English", document.body_text())
    self.assertIn("警察庁について", document.body_text())

  @patch("tweb.api.fetch_resource")
  def test_execute_embedded_scripts_skips_populated_noscript_iframe_shells(self, mock_fetch_resource) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <header id="header" role="banner">
                <p>
                  Existing header content stays in place because this shell is already populated
                  with substantial visible text before any fallback fetch is considered.
                </p>
                <noscript><iframe src="/common_header.html" title="header"></iframe></noscript>
              </header>
              <main><h1>Main body</h1></main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    mock_fetch_resource.assert_not_called()
    self.assertIn("Existing header content stays in place because this shell is already populated", document.body_text())

  def test_execute_embedded_scripts_prunes_repeated_loading_cluster_when_main_is_already_readable(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>
                <h1>Everything happens here.</h1>
                <p>
                  This page already has enough readable text to keep the primary content useful
                  without any browser-render fallback.
                </p>
                <p>
                  The remaining content below is only a leftover loading cluster and should be
                  pruned from the visible output once the page body is already substantial.
                </p>
              </main>
              <div class="carousel-placeholder">
                <p>Loading...</p>
                <p>Loading...</p>
                <p>Loading...</p>
                <p>Loading...</p>
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    visible = document.body_text(visible_only=True)
    self.assertIn("Everything happens here.", visible)
    self.assertNotIn("Loading... Loading... Loading...", visible)

  def test_prunes_single_inline_loading_placeholder_when_visible_content_is_substantial(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>
                <div class="loading">Loading...</div>
                <section>
                  <h1>Everything happens here.</h1>
                  <p>
                    This page already has enough readable text to keep the primary content useful
                    without any browser-render fallback.
                  </p>
                  <p>
                    The remaining content below should stay visible after the inline loading
                    placeholder is pruned from the output.
                  </p>
                  <p>
                    Additional text keeps the page above the threshold for generic placeholder
                    pruning.
                  </p>
                </section>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    visible = document.body_text(visible_only=True)
    self.assertIn("Everything happens here.", visible)
    self.assertNotIn("Loading...", visible)

  def test_prunes_inline_loading_placeholder_without_exact_body_scan_when_preview_is_large(self) -> None:
    document = parse_document(
      Resource(
        source="https://example.com/app",
        content="""
        <html>
          <body>
            <main>
              <div class="loading">Loading...</div>
              <section>
                <h1>Everything happens here.</h1>
                <p>
                  This page already has enough readable text to keep the primary content useful
                  without any browser-render fallback.
                </p>
                <p>
                  The remaining content below should stay visible after the inline loading
                  placeholder is pruned from the output.
                </p>
                <p>
                  Additional text keeps the page above the threshold for generic placeholder
                  pruning.
                </p>
                <p>
                  Another paragraph keeps the inline preview comfortably above the guard threshold
                  so the exact body-wide visible-text CSS walk should not run.
                </p>
              </section>
            </main>
          </body>
        </html>
        """,
      )
    )

    with patch("tweb.api._collect_visible_text", wraps=api_module._collect_visible_text) as mock_collect_visible_text:
      _prune_inline_loading_placeholders(document)

    visible = TWebDocument(document).body_text(visible_only=True)
    self.assertIn("Everything happens here.", visible)
    self.assertNotIn("Loading...", visible)
    self.assertEqual(mock_collect_visible_text.call_args_list, [])

  def test_skips_expensive_page_events_for_static_link_dense_portal(self) -> None:
    links = "".join(f'<a href="/item{i}">Item {i}</a>' for i in range(180))
    controls = "".join(
      f'<button type="button">Button {i}</button>' for i in range(24)
    )
    paragraphs = "".join(
      f"<p>Paragraph {i} contains enough readable public-information text for static rendering.</p>"
      for i in range(24)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>
                {paragraphs}
                <nav>{links}</nav>
                <section>{controls}</section>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=True, browser_render_policy="never")

    debug = document.javascript_debug()
    self.assertNotIn("page_event_dispatch", debug["timings_ms"])
    self.assertIn("dom_content_loaded_dispatch", debug["timings_ms"])

  def test_skips_expensive_page_events_for_link_dense_low_control_portal_without_load_interest(self) -> None:
    links = "".join(
      f'<a href="/item{i}">Item {i} with readable public information text</a>'
      for i in range(170)
    )
    paragraphs = "".join(
      f"<p>Paragraph {i} contains enough readable public-information text for static rendering.</p>"
      for i in range(28)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>
                {paragraphs}
                <nav>{links}</nav>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    debug = document.javascript_debug()
    self.assertNotIn("page_event_dispatch", debug["timings_ms"])
    self.assertIn("dom_content_loaded_dispatch", debug["timings_ms"])

  def test_link_dense_low_control_portal_keeps_load_events_when_runtime_requests_them(self) -> None:
    links = "".join(
      f'<a href="/item{i}">Item {i} with readable public information text</a>'
      for i in range(170)
    )
    paragraphs = "".join(
      f"<p>Paragraph {i} contains enough readable public-information text for static rendering.</p>"
      for i in range(28)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>{paragraphs}<nav>{links}</nav></main>
              <script>
                window.addEventListener('load', () => {{
                  document.body.setAttribute('data-load', '1');
                }});
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    debug = document.javascript_debug()
    self.assertIn("page_event_dispatch", debug["timings_ms"])
    self.assertEqual(document.body.get("data-load"), "1")

  def test_link_dense_high_control_portal_keeps_load_events_when_runtime_requests_them(self) -> None:
    links = "".join(
      f'<a href="/item{i}">Item {i} with readable public information text</a>'
      for i in range(170)
    )
    controls = "".join(f'<button type="button">Button {i}</button>' for i in range(24))
    paragraphs = "".join(
      f"<p>Paragraph {i} contains enough readable public-information text for static rendering.</p>"
      for i in range(28)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>{paragraphs}<nav>{links}</nav><section>{controls}</section></main>
              <script>
                window.addEventListener('load', () => {{
                  document.body.setAttribute('data-load', '1');
                }});
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    debug = document.javascript_debug()
    self.assertIn("page_event_dispatch", debug["timings_ms"])
    self.assertEqual(document.body.get("data-load"), "1")

  def test_static_portal_dispatches_ready_and_load_when_listeners_present(self) -> None:
    links = "".join(f'<a href="/item{i}">Item {i}</a>' for i in range(180))
    controls = "".join(
      f'<button type="button">Button {i}</button>' for i in range(24)
    )
    paragraphs = "".join(
      f"<p>Paragraph {i} contains enough readable public-information text for static rendering.</p>"
      for i in range(24)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>{paragraphs}<nav>{links}</nav><section>{controls}</section></main>
              <script>
                document.addEventListener('DOMContentLoaded', () => {{
                  document.body.setAttribute('data-ready', '1');
                }});
                window.addEventListener('load', () => {{
                  document.body.setAttribute('data-load', '1');
                }});
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    self.assertEqual(document.body.get("data-ready"), "1")
    self.assertEqual(document.body.get("data-load"), "1")

  def test_static_portal_dispatches_load_when_main_is_behind_load_gate(self) -> None:
    links = "".join(f'<a href="/item{i}">Item {i}</a>' for i in range(180))
    controls = "".join(f'<button type="button">Button {i}</button>' for i in range(24))
    paragraphs = "".join(
      f"<p>Paragraph {i} contains enough readable public-information text for static rendering.</p>"
      for i in range(24)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <head>
              <style>
                html.enable-javascript main {{ visibility: hidden; }}
                html.enable-javascript.window-load main {{ visibility: visible; }}
              </style>
              <script>
                document.documentElement.classList.add('enable-javascript');
                window.addEventListener('load', () => document.documentElement.classList.add('window-load'));
              </script>
            </head>
            <body><main>{paragraphs}<nav>{links}</nav><section>{controls}</section></main></body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    self.assertIn("window-load", document.document.root.attrs.get("class", ""))
    self.assertIn("Paragraph 0", document.body_text(visible_only=True))

  @patch.object(TWebDocument, "_runtime")
  def test_very_dense_static_portal_skips_all_lifecycle_events(
    self,
    mock_runtime_factory: Mock,
  ) -> None:
    runtime = Mock()
    runtime.external_script_preflight_safe.return_value = True
    runtime.performance_summary.return_value = {"timings_ms": {}, "counts": {}}
    runtime.runtime_data_network_payloads.return_value = []
    mock_runtime_factory.return_value = runtime
    links = "".join(
      f'<a href="/item-{index}">Dense public information item {index}</a>'
      for index in range(420)
    )
    controls = "".join(f"<button>Control {index}</button>" for index in range(24))
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/dense-portal",
          content=f"<html><body><main>{links}{controls}</main></body></html>",
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    runtime.dispatch_page_events.assert_not_called()
    runtime.dispatch_dom_content_loaded.assert_not_called()

  def test_large_delayed_script_can_be_skipped_only_for_rich_static_page(self) -> None:
    links = "".join(
      f'<a href="/item-{index}">Public information item {index}</a>'
      for index in range(180)
    )
    controls = "".join(f"<button>Control {index}</button>" for index in range(12))
    paragraphs = "".join(
      f"<p>Readable public information paragraph {index} with complete static content.</p>"
      for index in range(60)
    )
    rich_document = TWebDocument(parse_document(Resource(
      source="https://example.com/portal",
      content=f"<html><body><main>{paragraphs}{links}{controls}</main></body></html>",
    )))
    sparse_document = TWebDocument(parse_document(Resource(
      source="https://example.com/app",
      content="<html><body><main>Loading</main></body></html>",
    )))
    large_source = "x" * (512 * 1024)
    medium_large_source = "x" * (300 * 1024)

    self.assertTrue(
      _should_skip_large_delayed_script_for_static_page(rich_document, large_source)
    )
    self.assertTrue(
      _should_skip_large_delayed_script_for_static_page(rich_document, medium_large_source)
    )
    self.assertFalse(
      _should_skip_large_delayed_script_for_static_page(rich_document, "x" * 1024)
    )
    self.assertFalse(
      _should_skip_large_delayed_script_for_static_page(sparse_document, large_source)
    )

    self.assertTrue(
      _should_skip_large_inline_script_for_static_page(rich_document, large_source)
    )
    self.assertFalse(
      _should_skip_large_inline_script_for_static_page(rich_document, medium_large_source)
    )
    self.assertFalse(
      _should_skip_large_inline_script_for_static_page(sparse_document, large_source)
    )

  def test_many_delayed_external_scripts_can_be_skipped_for_moderately_rich_static_page(self) -> None:
    links = "".join(
      f'<a href="/item-{index}">Visible retail item {index} with enough text to be readable.</a>'
      for index in range(58)
    )
    controls = "".join(f"<button>Control {index}</button>" for index in range(25))
    paragraphs = "".join(
      f"<p>Readable landing page section {index} with enough static merchandising copy.</p>"
      for index in range(18)
    )
    module_scripts = "".join(
      f'<script type="module" src="/app-{index}.js"></script>'
      for index in range(56)
    )
    document = TWebDocument(parse_document(Resource(
      source="https://example.com/store",
      content=f"<html><body><main>{paragraphs}{links}{controls}</main>{module_scripts}</body></html>",
    )))

    self.assertTrue(_should_skip_delayed_external_scripts_for_static_page(document))

  @patch.object(TWebDocument, "_runtime")
  def test_execute_embedded_scripts_skips_runtime_for_rich_static_page(
    self,
    mock_runtime_factory: Mock,
  ) -> None:
    links = "".join(
      (
        f'<a href="/item-{index}">Visible encyclopedia item {index} with enough descriptive text '
        "to keep the page readable before any script execution.</a>"
      )
      for index in range(520)
    )
    controls = "".join(f"<button>Control {index}</button>" for index in range(12))
    paragraphs = "".join(
      f"<p>Readable article paragraph {index} with substantial static body text already present in HTML.</p>"
      for index in range(80)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/wiki",
          content=f"""
          <html>
            <body>
              <main>{paragraphs}{links}{controls}</main>
              <script id="__NEXT_DATA__" type="application/json">{{}}</script>
              <script>window.__inlineBoot = true;</script>
            </body>
          </html>
          """,
        )
      )
    )

    with patch.object(document, "form_controls", side_effect=AssertionError("form_controls should not be used for static-rich skip")):
      document.execute_embedded_scripts(ignore_errors=False)

    mock_runtime_factory.assert_not_called()
    debug = document.javascript_debug()
    assert debug is not None
    self.assertEqual(debug["counts"]["embedded_scripts_skipped_for_static_page"], 1)
    self.assertEqual(debug["timings_ms"]["hydration"], 0.0)

  @patch.object(TWebDocument, "_runtime")
  def test_does_not_skip_expensive_page_events_when_most_content_is_hidden(
    self,
    mock_runtime_factory: Mock,
  ) -> None:
    runtime = Mock()
    runtime.external_script_preflight_safe.return_value = True
    runtime.performance_summary.return_value = {"timings_ms": {}, "counts": {}}
    runtime.runtime_data_network_payloads.return_value = []
    mock_runtime_factory.return_value = runtime

    links = "".join(f'<a href="/item{i}">Item {i}</a>' for i in range(220))
    controls = "".join(
      f'<button type="button">Button {i}</button>' for i in range(24)
    )
    hidden_blocks = "".join(
      (
        '<section style="display:none">'
        f'<p>Hidden detail {i} with enough text to dominate the full body length.</p>'
        f'{links}'
        '</section>'
      )
      for i in range(8)
    )
    visible_paragraphs = "".join(
      f"<p>Visible paragraph {i} keeps the page readable without exposing every hidden block.</p>"
      for i in range(16)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>
                {visible_paragraphs}
                <nav>{links}</nav>
                <section>{controls}</section>
                {hidden_blocks}
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    runtime.dispatch_page_events.assert_called_once()

  @patch("tweb.api.fetch_rendered_resource")
  def test_auto_policy_avoids_visible_probe_for_healthy_body_text(self, mock_fetch_rendered_resource) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article",
          content="""
          <html>
            <body>
              <article>
                <h1>Healthy article</h1>
                <p>This page already has readable content.</p>
              </article>
            </body>
          </html>
          """,
        )
      )
    )

    calls: list[bool] = []
    original_body_text = TWebDocument.body_text

    def wrapped_body_text(instance: TWebDocument, *, visible_only: bool = False) -> str:
      calls.append(visible_only)
      return original_body_text(instance, visible_only=visible_only)

    with patch.object(TWebDocument, "body_text", autospec=True, side_effect=wrapped_body_text):
      document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertEqual(calls, [])
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api._find_prunable_client_failure_shells")
  def test_execute_embedded_scripts_skips_prune_scan_for_healthy_body_text(
    self,
    mock_find_prunable_client_failure_shells,
  ) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article",
          content="""
          <html>
            <body>
              <main>
                <h1>Healthy article</h1>
                <p>This page already has readable content.</p>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    mock_find_prunable_client_failure_shells.assert_not_called()

  @patch("tweb.api._iter_element_paths")
  def test_prune_inline_loading_placeholders_skips_scan_without_loading_text(
    self,
    mock_iter_element_paths: Mock,
  ) -> None:
    document = parse_document(
      Resource(
        source="https://example.com/article",
        content="""
        <html>
          <body>
            <main>
              <h1>Healthy article</h1>
              <p>This page already has readable content.</p>
            </main>
          </body>
        </html>
        """,
      )
    )

    _prune_inline_loading_placeholders(document)

    mock_iter_element_paths.assert_not_called()

  def test_alternate_html_fallback_avoids_exact_visible_probe_for_healthy_body(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article",
          content="""
          <html>
            <body>
              <main>
                <h1>Healthy article</h1>
                <p>
                  This page already has enough visible readable content to skip alternate HTML
                  fallback probing entirely because the main article body is clearly present.
                </p>
                <p>
                  Additional content keeps the quick inline visible probe above the sparse-page
                  threshold without requiring a full CSS-aware visible-only body walk.
                </p>
                <p>
                  A final paragraph adds enough readable body text to push the inline visible
                  preview past four hundred characters, which is the threshold used to skip the
                  alternate HTML fallback branch for already healthy pages.
                </p>
                <a href="/more">Read more</a>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    calls: list[bool] = []
    original_body_text = TWebDocument.body_text

    def wrapped_body_text(instance: TWebDocument, *, visible_only: bool = False) -> str:
      calls.append(visible_only)
      return original_body_text(instance, visible_only=visible_only)

    session = create_session()
    try:
      with patch.object(TWebDocument, "body_text", autospec=True, side_effect=wrapped_body_text):
        _maybe_replace_with_alternate_html_document(document, session=session)
    finally:
      session.close()

    self.assertEqual(calls, [])

  def test_execute_embedded_scripts_avoids_exact_visible_probe_for_healthy_hidden_content_mix(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/article",
          content="""
          <html>
            <body>
              <main>
                <h1>Healthy article</h1>
                <p>
                  This page already has enough visible readable content to avoid any runtime
                  hydration fallback, even if unrelated hidden UI fragments are present.
                </p>
                <p>
                  The visible text should be considered substantial without requiring a full CSS
                  selector walk for the exact visible-only body probe.
                </p>
              </main>
              <div style="display: none;">
                Hidden drawer text that should not force an exact visible probe.
              </div>
            </body>
          </html>
          """,
        )
      )
    )

    calls: list[bool] = []
    original_body_text = TWebDocument.body_text

    def wrapped_body_text(instance: TWebDocument, *, visible_only: bool = False) -> str:
      calls.append(visible_only)
      return original_body_text(instance, visible_only=visible_only)

    with patch.object(TWebDocument, "body_text", autospec=True, side_effect=wrapped_body_text):
      document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    self.assertTrue(calls)
    self.assertNotIn(True, calls)

  def test_execution_document_metrics_reuses_counts_across_static_page_checks(self) -> None:
    delayed_scripts = "".join(
      f'<script defer src="/assets/chunk-{index}.js"></script>'
      for index in range(24)
    )
    links = "".join(f'<a href="/item-{index}">Item {index}</a>' for index in range(180))
    controls = "".join(
      f'<input type="text" name="field-{index}" value="{index}">'
      for index in range(48)
    )
    paragraphs = "".join(
      f"<p>Paragraph {index} with enough text to keep the visible body substantial.</p>"
      for index in range(120)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>
                {paragraphs}
                <nav>{links}</nav>
                <section>{controls}</section>
              </main>
              {delayed_scripts}
            </body>
          </html>
          """,
        )
      )
    )

    body_text_calls: list[bool] = []
    links_calls = 0
    controls_calls = 0
    original_body_text = TWebDocument.body_text
    original_links = TWebDocument.links
    original_form_controls = TWebDocument.form_controls

    def wrapped_body_text(instance: TWebDocument, *, visible_only: bool = False) -> str:
      body_text_calls.append(visible_only)
      return original_body_text(instance, visible_only=visible_only)

    def wrapped_links(instance: TWebDocument):
      nonlocal links_calls
      links_calls += 1
      return original_links(instance)

    def wrapped_form_controls(instance: TWebDocument):
      nonlocal controls_calls
      controls_calls += 1
      return original_form_controls(instance)

    metrics = _ExecutionDocumentMetrics(document)
    with patch.object(TWebDocument, "body_text", autospec=True, side_effect=wrapped_body_text), patch.object(
      TWebDocument,
      "links",
      autospec=True,
      side_effect=wrapped_links,
    ), patch.object(
      TWebDocument,
      "form_controls",
      autospec=True,
      side_effect=wrapped_form_controls,
    ):
      self.assertTrue(_should_skip_delayed_external_scripts_for_static_page(document, metrics=metrics))
      self.assertTrue(_should_skip_large_inline_script_for_static_page(document, "x" * (600 * 1024), metrics=metrics))
      self.assertTrue(_should_skip_large_delayed_script_for_static_page(document, "x" * (300 * 1024), metrics=metrics))
      self.assertTrue(_should_skip_expensive_page_events(document, delayed_script_count=24, metrics=metrics))
      self.assertTrue(_should_dispatch_dom_content_loaded_for_static_page(document, metrics=metrics))

    self.assertEqual(body_text_calls.count(False), 1)
    self.assertEqual(body_text_calls.count(True), 1)
    self.assertEqual(links_calls, 1)
    self.assertEqual(controls_calls, 1)

  def test_prune_inline_loading_placeholders_reuses_cached_visible_metrics(self) -> None:
    paragraphs = "".join(
      f"<p>Paragraph {index} with enough text to keep the body visible.</p>"
      for index in range(30)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>{paragraphs}</main>
              <div class="loading">Loading...</div>
            </body>
          </html>
          """,
        )
      )
    )

    body_text_calls: list[bool] = []
    original_body_text = TWebDocument.body_text

    def wrapped_body_text(instance: TWebDocument, *, visible_only: bool = False) -> str:
      body_text_calls.append(visible_only)
      return original_body_text(instance, visible_only=visible_only)

    with patch.object(TWebDocument, "body_text", autospec=True, side_effect=wrapped_body_text):
      metrics = _ExecutionDocumentMetrics(document)
      self.assertGreater(metrics.visible_body_len(), 240)
      self.assertEqual(body_text_calls.count(False), 0)
      self.assertEqual(body_text_calls.count(True), 1)
      _prune_inline_loading_placeholders(document.document, metrics=metrics)

    self.assertEqual(body_text_calls.count(True), 1)
    self.assertNotIn("Loading...", document.body_text())

  @patch("tweb.api.fetch_rendered_resource")
  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_auto_policy_skips_browser_render_when_runtime_sections_can_fill_main(
    self,
    mock_extract_site_specific_hydration_sections,
    mock_fetch_rendered_resource,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="フォロー中",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://note.com/",
      content="""
      <html>
        <body>
          <main>
            <h3>Rendered Personalized Feed</h3>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/",
          content="""
          <html>
            <body>
              <main>
                <div class="timeline">
                  <div class="timeline__nav"></div>
                  <div class="timeline__body"><div class="loading-spinner"></div></div>
                </div>
              </main>
              <script>document.querySelector('.timeline__body').replaceChildren();</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    self.assertIn("First Note", document.body_text())
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_rechecks_runtime_sections_after_dispatch_page_events(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.side_effect = [
      [],
      [
        HydrationSection(
          title="フォロー中",
          items=(
            ("First Note", "/creator/n/n111"),
            ("Second Note", "/creator/n/n222"),
          ),
        ),
      ],
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/",
          content="""
          <html>
            <body>
              <main>
                <div class="grid place-content-center py-14">
                  <div class="loading-spinner"></div>
                </div>
              </main>
              <script>document.body.dataset.ready = '1';</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    main = document.find("main")
    self.assertIsNotNone(main)
    self.assertIn("First Note", main.text)
    self.assertIn("Second Note", main.text)
    self.assertEqual(mock_extract_site_specific_hydration_sections.call_count, 2)

  @patch("tweb.api.fetch_rendered_resource")
  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_auto_policy_skips_browser_render_when_runtime_sections_can_recreate_missing_main(
    self,
    mock_extract_site_specific_hydration_sections,
    mock_fetch_rendered_resource,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="アウトドア",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/outdoor",
          content="""
          <html>
            <body>
              <main id="main-content" class="topic-main">
                <p>Loading...</p>
              </main>
              <template data-dgst="BAILOUT_TO_CLIENT_SIDE_RENDERING"></template>
              <script>
                document.querySelector('main').remove();
                document.body.dataset.ready = '1';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")

    self.assertFalse(document.browser_rendered_via_chrome)
    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(main)
    assert main is not None
    self.assertEqual(main.get("class"), "topic-main")
    self.assertIn("First Note", main.text)
    mock_fetch_rendered_resource.assert_not_called()

  @patch("tweb.api.fetch_rendered_resource")
  def test_always_policy_forces_browser_render_even_without_failure_signal(self, mock_fetch_rendered_resource) -> None:
    mock_fetch_rendered_resource.return_value = Resource(
      source="https://example.com/app",
      content="""
      <html>
        <body>
          <main>
            <h3>Rendered Personalized Feed</h3>
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <main>Server rendered shell</main>
              <script>document.body.dataset.ready = '1';</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="always")

    self.assertIn("Rendered Personalized Feed", document.body_text())
    mock_fetch_rendered_resource.assert_called_once_with("https://example.com/app", session=None)

  def test_browser_render_replacement_syncs_title_from_rendered_dom(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <head><title>Server Shell</title></head>
            <body>
              <main>loading</main>
            </body>
          </html>
          """,
        )
      )
    )
    rendered = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <head><title>Rendered Title</title></head>
            <body>
              <main><h1>Rendered Body</h1></main>
            </body>
          </html>
          """,
        )
      )
    )
    rendered.document.title = "Rendered Title Rendered Body loading"

    with patch("tweb.api.TWebDocument", return_value=rendered):
      _maybe_replace_with_browser_rendered_document(
        document,
        initial_had_main=True,
        browser_render_policy="always",
        browser_render_fetcher=(
          lambda request, session=None: BrowserRenderResult(
            source=request.target,
            content="<html></html>",
          )
        ),
      )

    self.assertTrue(document.browser_rendered_via_chrome)
    self.assertEqual(document.title, "Rendered Title")
    self.assertIn("Rendered Body", document.body_text())

  def test_augments_next_f_article_list_without_browser_render(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/creator",
          content="""
          <html>
            <body>
              <main>
                <section>
                  <h2>記事一覧</h2>
                  <p>
                    これは十分に長いサーバーレンダリング済みの紹介文です。
                    既存の hydration 補完が早期 return しないことを確認するため、
                    160 文字を超えるように同じ説明を繰り返しています。
                    これは十分に長いサーバーレンダリング済みの紹介文です。
                    既存の hydration 補完が早期 return しないことを確認するため、
                    160 文字を超えるように同じ説明を繰り返しています。
                  </p>
                </section>
              </main>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "0:{\\"target\\":[{\\"type\\":\\"TextNote\\",\\"name\\":\\"First Article\\",\\"key\\":\\"naaa111\\",\\"user\\":{\\"urlname\\":\\"creator\\"}},{\\"type\\":\\"TextNote\\",\\"name\\":\\"Second Article\\",\\"key\\":\\"nbbb222\\",\\"user\\":{\\"urlname\\":\\"creator\\"}}]}"]);
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    text = document.body_text()
    self.assertIn("First Article", text)
    self.assertIn("Second Article", text)
    listing = document.find("ul", attrs={"data-tweb-hydration-role": "section-items"})
    self.assertIsNotNone(listing)
    links = listing.find_all("a")
    self.assertEqual(
      [(link.text, link.get("href")) for link in links],
      [("First Article", "/creator/n/naaa111"), ("Second Article", "/creator/n/nbbb222")],
    )
    debug = document.hydration_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertTrue(
      any(
        entry["source_type"] == "chunk" and entry["source_name"] == "__next_f"
        for entry in debug["source_summaries"]
      )
    )

  def test_augments_next_f_article_list_keeps_twenty_four_links(self) -> None:
    target_items = [
      {
        "type": "TextNote",
        "name": f"Article {index}",
        "key": f"n{index:03d}",
        "user": {"urlname": "creator"},
      }
      for index in range(30)
    ]
    payload = json.dumps({"target": target_items}, ensure_ascii=False).replace('"', '\\"')
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/creator",
          content=f"""
          <html>
            <body>
              <main>
                <section>
                  <h2>記事一覧</h2>
                  <p>
                    これは十分に長いサーバーレンダリング済みの紹介文です。
                    既存の hydration 補完が早期 return しないことを確認するため、
                    160 文字を超えるように同じ説明を繰り返しています。
                    これは十分に長いサーバーレンダリング済みの紹介文です。
                    既存の hydration 補完が早期 return しないことを確認するため、
                    160 文字を超えるように同じ説明を繰り返しています。
                  </p>
                </section>
              </main>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "0:{payload}"]);
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    listing = document.find("ul", attrs={"data-tweb-hydration-role": "section-items"})
    self.assertIsNotNone(listing)
    assert listing is not None
    links = listing.find_all("a")
    self.assertEqual(len(links), 24)
    self.assertEqual(links[0].text, "Article 0")
    self.assertEqual(links[-1].text, "Article 23")

  def test_augments_note_home_timeline_articles_from_nested_next_f_note_objects(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/",
          content="""
          <html>
            <body>
              <main>
                <div class="timeline">
                  <div class="timeline__nav"></div>
                  <div class="timeline__body"></div>
                </div>
              </main>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "0:{\\"homeTimeline\\":{\\"sections\\":[{\\"id\\":\\"featured\\",\\"notes\\":[{\\"user\\":{\\"urlname\\":\\"creator\\"},\\"key\\":\\"naaa111\\",\\"title\\":\\"First Article\\",\\"type\\":\\"ImageNote\\"},{\\"title\\":\\"Second Article\\",\\"type\\":\\"TextNote\\",\\"key\\":\\"nbbb222\\",\\"user\\":{\\"urlname\\":\\"creator\\"}}]}],\\"categories\\":[{\\"title\\":\\"くらし\\",\\"subCategories\\":[{\\"title\\":\\"ライフスタイル\\",\\"engName\\":\\"lifestyle\\"},{\\"title\\":\\"住まい・暮らし\\",\\"engName\\":\\"home\\"}]}]}}"]);
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    timeline_nav = document.find("div", attrs={"class": "timeline__nav"})
    timeline_body = document.find("div", attrs={"class": "timeline__body"})
    self.assertIsNotNone(timeline_nav)
    self.assertIsNotNone(timeline_body)
    self.assertIn("くらし", timeline_nav.text)
    self.assertIn("First Article", timeline_body.text)
    self.assertIn("Second Article", timeline_body.text)
    links = timeline_body.find_all("a")
    self.assertEqual(
      [(link.text, link.get("href")) for link in links[:2]],
      [("First Article", "/creator/n/naaa111"), ("Second Article", "/creator/n/nbbb222")],
    )

  def test_augments_next_f_category_sections_without_browser_render(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <main id="main-content"></main>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "30:[\\"$\\",\\"$L32\\",null,{\\"mobile\\":[\\"$\\",\\"$L33\\",null,{\\"categories\\":[{\\"id\\":3,\\"title\\":\\"テクノロジー\\",\\"subCategories\\":[{\\"tagName\\":\\"科学・テクノロジー\\",\\"title\\":\\"科学・テクノロジー\\",\\"engName\\":\\"science_technology\\"},{\\"tagName\\":\\"コンピュータ・IT\\",\\"title\\":\\"コンピュータ・IT\\",\\"engName\\":\\"computer_it\\"},{\\"tagName\\":\\"コンピュータ・IT_プログラミング\\",\\"title\\":\\"プログラミング\\",\\"engName\\":\\"computer_it/programming\\"}]}]}]}"]);
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    text = document.body_text()
    self.assertIn("Hydration Data", text)
    self.assertIn("テクノロジー", text)
    self.assertIn("コンピュータ・IT", text)
    self.assertIn("プログラミング", text)
    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("### テクノロジー", rendered)
    self.assertIn("コンピュータ・IT", rendered)
    links = document.links()
    self.assertTrue(any(link.text == "コンピュータ・IT" and link.href == "/topic/computer_it" for link in links))
    self.assertTrue(any(link.text == "プログラミング" and link.href == "/topic/computer_it/programming" for link in links))

  @patch("tweb.js_runtime.subprocess.run", return_value=Mock(returncode=-11))
  def test_skips_crash_risky_inline_json_parse_script_and_recovers_payload_from_html(self, _mock_run: Mock) -> None:
    payload = json.dumps(
      {
        "categories": [
          {
            "title": "Top Picks",
            "items": [
              {"title": "First Forecast", "url": "/forecast/first"},
              {"title": "Second Forecast", "url": "/forecast/second"},
            ],
          }
        ]
      }
    )
    escaped = json.dumps(payload)
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/weather",
          content=f"""
          <html>
            <body>
              <main>
                <p>Loading weather data...</p>
              </main>
              <script>window.__data = JSON.parse({escaped});</script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=True)

    text = document.body_text()
    self.assertIn("Hydration Data", text)
    self.assertIn("Top Picks", text)
    self.assertIn("First Forecast", text)
    debug = document.hydration_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertTrue(
      any(
        entry["source_type"] == "inline-json-parse" and entry["source_name"] == "__data"
        for entry in debug["source_summaries"]
      )
    )

  def test_ignores_challenge_network_payloads_in_hydration_fallback(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <main></main>
            </body>
          </html>
          """,
        )
      )
    )

    class FakeRuntime:
      def eval(self, source: str, drain_timers: bool = False):
        if "const roots" in source:
          return "[]"
        if "window.__next_f" in source or "window.webpackJsonp" in source:
          return "[]"
        return "[]"

      def runtime_data_network_payloads(self):
        return [
          {
            "url": "https://example.com/__challenge/token/inputs",
            "body": "{\"token\":\"abc123\",\"hash\":\"deadbeef\"}",
          }
        ]

    debug = _augment_sparse_body_from_hydration(document.document, FakeRuntime())

    self.assertIsNotNone(debug)
    self.assertEqual(document.body_text().strip(), "")

  def test_recreates_missing_main_before_inserting_hydration_content(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <a href="#main-content">メインコンテンツへスキップ</a>
              <main id="main-content" class="topic-main">
                <p>Loading...</p>
              </main>
              <footer>footer</footer>
              <script>
                document.querySelector('main').remove();
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "30:[\\"$\\",\\"$L32\\",null,{\\"mobile\\":[\\"$\\",\\"$L33\\",null,{\\"categories\\":[{\\"id\\":3,\\"title\\":\\"テクノロジー\\",\\"subCategories\\":[{\\"tagName\\":\\"科学・テクノロジー\\",\\"title\\":\\"科学・テクノロジー\\",\\"engName\\":\\"science_technology\\"},{\\"tagName\\":\\"コンピュータ・IT\\",\\"title\\":\\"コンピュータ・IT\\",\\"engName\\":\\"computer_it\\"}]}]}]}"]);
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(main)
    self.assertEqual(main.get("class"), "topic-main")
    self.assertIn("Hydration Data", main.text)
    body_children = [child.tag for child in document.document.body.children if hasattr(child, "tag")]
    self.assertEqual(body_children[:3], ["a", "main", "footer"])

  def test_recreates_missing_main_inside_original_parent_container(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <div class="shell">
                <header>header</header>
                <div class="content-grid">
                  <aside>aside</aside>
                  <main id="main-content" class="topic-main">
                    <p>Loading...</p>
                  </main>
                </div>
                <footer>footer</footer>
              </div>
              <script>
                document.querySelector('main').remove();
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "30:[\\"$\\",\\"$L32\\",null,{\\"mobile\\":[\\"$\\",\\"$L33\\",null,{\\"categories\\":[{\\"id\\":3,\\"title\\":\\"テクノロジー\\",\\"subCategories\\":[{\\"tagName\\":\\"科学・テクノロジー\\",\\"title\\":\\"科学・テクノロジー\\",\\"engName\\":\\"science_technology\\"},{\\"tagName\\":\\"コンピュータ・IT\\",\\"title\\":\\"コンピュータ・IT\\",\\"engName\\":\\"computer_it\\"}]}]}]}"]);
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    grid = document.find("div", attrs={"class": "content-grid"})
    self.assertIsNotNone(grid)
    self.assertEqual(
      [child.tag for child in grid.node.children if hasattr(child, "tag")],
      ["aside", "main"],
    )
    shell = document.find("div", attrs={"class": "shell"})
    self.assertIsNotNone(shell)
    self.assertEqual(
      [child.tag for child in shell.node.children if hasattr(child, "tag")],
      ["header", "div", "footer"],
    )
    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertLess(rendered.find("Hydration Data"), rendered.find("footer"))

  def test_recovers_hidden_dom_content_when_visible_body_is_sparse(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/search",
          content="""
          <html>
            <body>
              <a href="#main-content">メイン コンテンツにスキップ</a>
              <main id="main-content">
                <div style="display: none;">
                  <h2>Recovered Result</h2>
                  <p>
                    プログラミングやシステム開発の現場で、特に深い意味を持たない仮の文字列として使われる言葉（メタ構文変数）
                  </p>
                  <a href="https://ja.wikipedia.org/wiki/%E3%83%A1%E3%82%BF%E6%A7%8B%E6%96%87%E5%A4%89%E6%95%B0">
                    メタ構文変数 - Wikipedia
                  </a>
                </div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("Recovered Content", rendered)
    self.assertNotIn("-\n  プログラミングやシステム開発", rendered)
    self.assertIn("プログラミングやシステム開発の現場で、特に深い意味を持たない仮の文字列として使", rendered)
    self.assertIn("わ\nれる言葉（メタ構文変数）", rendered)
    self.assertIn("\n\n- メタ構文変数 - Wikipedia", rendered)
    self.assertIn("メタ構文変数 - Wikipedia", rendered)

  def test_hidden_dom_recovery_renders_more_than_twelve_items(self) -> None:
    hidden_items = "\n".join(
      f'<p>Recovered hidden result item number {index:02d} with enough text to pass filtering.</p>'
      for index in range(1, 15)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/search",
          content=f"""
          <html>
            <body>
              <main id="main-content">
                <div style="display: none;">
                  {hidden_items}
                </div>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("Recovered hidden result item number 12", rendered)
    self.assertIn("Recovered hidden result item number 13", rendered)
    self.assertIn("Recovered hidden result item number 14", rendered)

  def test_execute_embedded_scripts_retries_sparse_post_load_timers_after_runtime_activity(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content="""
          <html>
            <head><title>Initial Title</title></head>
            <body>
              <main></main>
              <script>
                document.addEventListener('DOMContentLoaded', () => {
                  document.body.setAttribute('data-hydration-started', '1');
                });
                window.addEventListener('load', () => {
                  setTimeout(() => {
                    document.querySelector('main').textContent = 'Loaded after post-load timer';
                  }, 0);
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    self.assertEqual(document.body.get("data-hydration-started"), "1")
    self.assertIn("Loaded after post-load timer", document.body_text())

  def test_sparse_post_load_retry_continues_after_ignored_timer_error(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content="""
          <html>
            <body>
              <main></main>
              <script>
                document.addEventListener('DOMContentLoaded', () => {
                  document.body.setAttribute('data-hydration-started', '1');
                });
                window.addEventListener('load', () => {
                  setTimeout(() => { throw new Error('optional widget failed'); }, 1000);
                  setTimeout(() => {
                    document.querySelector('main').textContent = 'Loaded after later timer';
                  }, 5000);
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=True, browser_render_policy="never")

    self.assertIn("Loaded after later timer", document.body_text())

  def test_delayed_scripts_drain_ready_post_load_timer_on_readable_page(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content="""
          <html>
            <body>
              <main>
                This server-rendered portal body is already readable and long enough to avoid
                sparse-page recovery, while a deferred application script adds current notices.
              </main>
              <script defer>
                document.body.setAttribute('data-app-started', '1');
                Promise.resolve().then(() => {
                  document.body.setAttribute('data-app-ready', '1');
                });
                window.addEventListener('load', () => {
                  setTimeout(() => {
                    const section = document.createElement('section');
                    section.textContent = 'Current notices loaded after the page event';
                    document.querySelector('main').appendChild(section);
                  }, 0);
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    self.assertIn("Current notices loaded after the page event", document.body_text())

  def test_hidden_dom_recovery_keeps_text_rich_hidden_sidebar_content(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content="""
          <html>
            <body>
              <main id="main-content">
                <aside class="sidebar" style="display: none;">
                  <h2>Important notice archive</h2>
                  <p>
                    This hidden sidebar already contains substantial explanatory content about
                    public procedures, deadlines, and service updates that should be recovered.
                  </p>
                  <a href="/notice-1">Detailed notice about service changes and filing windows</a>
                  <a href="/notice-2">Frequently asked questions for the updated process</a>
                </aside>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("Recovered Content", rendered)
    self.assertIn("public procedures, deadlines, and service updates", rendered)
    self.assertIn("Detailed notice about service changes and filing windows", rendered)

  def test_hidden_dom_recovery_promotes_titled_hidden_section(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content="""
          <html>
            <body>
              <main id="main-content">
                <section class="collapsed-panel" style="display: none;">
                  <h2>Disaster updates</h2>
                  <a href="/updates/1">Heavy rain warning for northern area</a>
                  <a href="/updates/2">Evacuation advisory and shelter list</a>
                </section>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("Disaster updates", rendered)
    self.assertIn("Heavy rain warning for northern area", rendered)
    self.assertIn("Evacuation advisory and shelter list", rendered)

  def test_hidden_dom_recovery_promotes_h1_titled_hidden_section(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content="""
          <html>
            <body>
              <main id="main-content">
                <section class="collapsed-panel" style="display: none;">
                  <h1>Hotel rankings</h1>
                  <a href="/ranking/sales">Best selling stays this week</a>
                  <a href="/ranking/popular">Most popular stays this week</a>
                </section>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("Hotel rankings", rendered)
    self.assertIn("Best selling stays this week", rendered)
    self.assertIn("Most popular stays this week", rendered)

  def test_hidden_dom_recovery_keeps_large_tab_surplus_on_readable_page(self) -> None:
    visible_text = " ".join(
      f"Visible public guidance paragraph {index} contains useful service information."
      for index in range(12)
    )
    hidden_items = "".join(
      f'<li><a href="/notice/{index}">Archived public notice number {index}</a></li>'
      for index in range(18)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content=f"""
          <html>
            <body>
              <main>
                <h1>Public portal</h1>
                <p>{visible_text}</p>
                <section hidden>
                  <h2>Archived notices</h2>
                  <ul>{hidden_items}</ul>
                </section>
              </main>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")

    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("guidance paragraph 10 contains useful service information", rendered)
    self.assertIn("Archived notices", rendered)
    self.assertIn("Archived public notice number 17", rendered)

  def test_hidden_iframe_only_does_not_trigger_hidden_content_hint(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/portal",
          content="""
          <html>
            <body>
              <main>
                Visible public guidance remains readable without runtime recovery and should not
                trigger the hidden-content path when the only hidden nodes are empty iframes.
              </main>
              <iframe style="display:none;visibility:hidden"></iframe>
              <div id="tracker" style="display:none"></div>
            </body>
          </html>
          """,
        )
      )
    )

    self.assertFalse(_document_has_hidden_content_hint(document.document.body))

  def test_build_hydration_section_block_keeps_twenty_four_non_recovered_items(self) -> None:
    block = _build_hydration_section_block(
      HydrationSection(
        title="Daily articles",
        items=tuple(
          (f"Article {index}", f"/articles/{index}")
          for index in range(30)
        ),
      )
    )

    listing = block.find_first("ul")
    self.assertIsNotNone(listing)
    assert listing is not None
    links = listing.find_all("a")
    self.assertEqual(len(links), 24)
    self.assertEqual(links[0].text_content(), "Article 0")
    self.assertEqual(links[-1].text_content(), "Article 23")

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_restores_initial_body_layout_when_note_topic_runtime_data_exists(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="開発効率化",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <div class="shell">
                <aside>left pane</aside>
                <main id="main-content"></main>
                <footer>footer</footer>
              </div>
              <script>
                document.querySelector('aside').remove();
                document.querySelector('footer').remove();
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    shell = document.find("div", attrs={"class": "shell"})
    self.assertIsNotNone(shell)
    self.assertEqual(
      [child.tag for child in shell.node.children if hasattr(child, "tag")],
      ["aside", "main", "footer"],
    )
    self.assertIn("left pane", document.body_text())
    self.assertIn("開発効率化", document.body_text())
    self.assertNotIn("Something went wrong", document.body_text())

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_restores_missing_layout_siblings_without_reverting_healthy_header_updates(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="開発効率化",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <header><h1>Original brand</h1></header>
              <div class="shell">
                <aside>left pane</aside>
                <main id="main-content"></main>
                <footer>footer</footer>
              </div>
              <script>
                document.querySelector('header h1').textContent = 'Updated brand';
                document.querySelector('aside').remove();
                document.querySelector('footer').remove();
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    header = document.find("header")
    shell = document.find("div", attrs={"class": "shell"})
    self.assertIsNotNone(header)
    self.assertIsNotNone(shell)
    self.assertIn("Updated brand", header.text)
    self.assertIn("left pane", document.body_text())
    self.assertIn("footer", document.body_text())
    self.assertIn("開発効率化", document.body_text())
    self.assertNotIn("Original brand", document.body_text())

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_recreates_missing_layout_ancestor_before_restoring_main_shell(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="開発効率化",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/app",
          content="""
          <html>
            <body>
              <div class="shell">
                <aside>left pane</aside>
                <main id="main-content"></main>
              </div>
              <script>
                const shell = document.querySelector('.shell');
                const main = document.querySelector('main');
                shell.replaceWith(main);
                main.textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    shell = document.find("div", attrs={"class": "shell"})
    aside = document.find("aside")
    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(shell)
    self.assertIsNotNone(aside)
    self.assertIsNotNone(main)
    self.assertIn("left pane", shell.text)
    self.assertIn("Hydration Data", main.text)
    self.assertIn("開発効率化", main.text)

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_routes_topic_navigation_sections_into_aside(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="開発効率化",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
      HydrationSection(
        title="くらし",
        items=(
          ("ライフスタイル", "/topic/lifestyle"),
          ("住まい・暮らし", "/topic/home"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <div class="shell">
                <aside>left pane</aside>
                <main id="main-content"></main>
              </div>
              <script>
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    aside = document.find("aside")
    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(aside)
    self.assertIsNotNone(main)
    self.assertIn("くらし", aside.text)
    self.assertIn("ライフスタイル", aside.text)
    self.assertNotIn("開発効率化", aside.text)
    self.assertIn("Hydration Data", main.text)
    self.assertIn("開発効率化", main.text)
    self.assertNotIn("くらし", main.text)

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_prefers_main_nav_container_over_header_nav_for_hydration_sections(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="くらし",
        items=(
          ("ライフスタイル", "/topic/lifestyle"),
          ("住まい・暮らし", "/topic/home"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/",
          content="""
          <html>
            <body>
              <header>
                <nav class="top-nav">top nav</nav>
              </header>
              <main>
                <div class="timeline">
                  <div class="timeline__nav"></div>
                  <div class="timeline__body">body</div>
                </div>
              </main>
              <script>
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    header_nav = document.find("nav", attrs={"class": "top-nav"})
    timeline_nav = document.find("div", attrs={"class": "timeline__nav"})
    self.assertIsNotNone(header_nav)
    self.assertIsNotNone(timeline_nav)
    self.assertNotIn("くらし", header_nav.text)
    self.assertIn("くらし", timeline_nav.text)
    self.assertIn("ライフスタイル", timeline_nav.text)

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_prefers_non_nav_main_child_for_home_body_sections_when_content_class_is_unknown(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="フォロー中",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
      HydrationSection(
        title="くらし",
        items=(
          ("ライフスタイル", "/topic/lifestyle"),
          ("住まい・暮らし", "/topic/home"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/",
          content="""
          <html>
            <body>
              <main>
                <div class="left-nav">急上昇</div>
                <div class="right-pane"></div>
              </main>
              <script>
                document.querySelector('main').append(' ');
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    left_nav = document.find("div", attrs={"class": "left-nav"})
    right_pane = document.find("div", attrs={"class": "right-pane"})
    main = document.find("main")
    self.assertIsNotNone(left_nav)
    self.assertIsNotNone(right_pane)
    self.assertIsNotNone(main)
    self.assertNotIn("フォロー中", left_nav.text)
    self.assertIn("フォロー中", right_pane.text)
    self.assertNotEqual(main.find("h3"), right_pane.find("h3"))

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_keeps_topic_linked_body_sections_out_of_left_pane_when_items_are_long(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="本文",
        items=(
          ("これは本文側に残したい長いトピック導線テキストです", "/topic/lifestyle"),
          ("こちらも左 pane ではなく本文側に表示したい長い関連導線です", "/topic/home"),
        ),
      ),
      HydrationSection(
        title="くらし",
        items=(
          ("ライフスタイル", "/topic/lifestyle"),
          ("住まい・暮らし", "/topic/home"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <div class="shell">
                <aside>left pane</aside>
                <main id="main-content"></main>
              </div>
              <script>
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    aside = document.find("aside")
    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(aside)
    self.assertIsNotNone(main)
    self.assertIn("くらし", aside.text)
    self.assertNotIn("これは本文側に残したい長いトピック導線テキストです", aside.text)
    self.assertIn("これは本文側に残したい長いトピック導線テキストです", main.text)

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_augments_note_topic_categories_into_existing_left_pane_from_inline_next_f_chunk(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="本文",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <div class="shell">
                <aside>
                  <section>
                    <a href="/trend">急上昇</a>
                  </section>
                </aside>
                <main id="main-content"></main>
              </div>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "30:[\\"$\\",\\"$L32\\",null,{\\"mobile\\":[\\"$\\",\\"$L33\\",null,{\\"categories\\":[{\\"id\\":3,\\"title\\":\\"テクノロジー\\",\\"subCategories\\":[{\\"tagName\\":\\"科学・テクノロジー\\",\\"title\\":\\"科学・テクノロジー\\",\\"engName\\":\\"science_technology\\"},{\\"tagName\\":\\"コンピュータ・IT\\",\\"title\\":\\"コンピュータ・IT\\",\\"engName\\":\\"computer_it\\"}]}]}]}"]);
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    aside = document.find("aside")
    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(aside)
    self.assertIsNotNone(main)
    self.assertIn("急上昇", aside.text)
    self.assertIn("テクノロジー", aside.text)
    self.assertIn("コンピュータ・IT", aside.text)
    self.assertIn("First Note", main.text)
    debug = document.hydration_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertTrue(
      any(
        entry["source_type"] == "inline-chunk" and entry["source_name"] == "__next_f"
        for entry in debug["source_summaries"]
      )
    )

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_augments_note_topic_categories_from_single_quoted_inline_next_f_chunk(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="本文",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/computer_it",
          content="""
          <html>
            <body>
              <div class="shell">
                <aside>
                  <section>
                    <a href="/trend">急上昇</a>
                  </section>
                </aside>
                <main id="main-content"></main>
              </div>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, '30:["$","$L32",null,{"mobile":["$","$L33",null,{"categories":[{"id":3,"title":"テクノロジー","subCategories":[{"tagName":"科学・テクノロジー","title":"科学・テクノロジー","engName":"science_technology"},{"tagName":"コンピュータ・IT","title":"コンピュータ・IT","engName":"computer_it"}]}]}]}']);
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    aside = document.find("aside")
    self.assertIsNotNone(aside)
    self.assertIn("テクノロジー", aside.text)
    self.assertIn("コンピュータ・IT", aside.text)

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_drops_duplicate_note_topic_categories_from_body_when_left_pane_already_contains_them(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="登山",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/outdoor",
          content="""
          <html>
            <body>
              <div class="shell">
                <aside>
                  <section>
                    <ul>
                      <li>1 アルゼンチン代表</li>
                      <li>2 開発効率化</li>
                      <li>3 さよならララ</li>
                      <li>4 大統領のケーキ</li>
                      <li>5 夏の暮らし</li>
                    </ul>
                  </section>
                  <section>
                    <h3>くらし</h3>
                    <ul>
                      <li>ライフスタイル</li>
                    </ul>
                  </section>
                  <section>
                    <h3>社会・経済</h3>
                    <ul>
                      <li>社会問題・時事</li>
                    </ul>
                  </section>
                  <section>
                    <h3>テクノロジー</h3>
                    <ul>
                      <li>コンピュータ・IT</li>
                    </ul>
                  </section>
                  <section>
                    <h3>エンタメ</h3>
                    <ul>
                      <li>エンタメ全般</li>
                    </ul>
                  </section>
                  <section>
                    <h3>趣味・関心</h3>
                    <ul>
                      <li>アウトドア</li>
                    </ul>
                  </section>
                  <section>
                    <h3>創作</h3>
                    <ul>
                      <li>創作全般</li>
                    </ul>
                  </section>
                  <section>
                    <h3>まなび</h3>
                    <ul>
                      <li>キャリア</li>
                    </ul>
                  </section>
                </aside>
                <main id="main-content"></main>
              </div>
              <script>
                self.__next_f = self.__next_f || [];
                self.__next_f.push([1, "30:[\\"$\\",\\"$L32\\",null,{\\"mobile\\":[\\"$\\",\\"$L33\\",null,{\\"categories\\":[{\\"id\\":24,\\"title\\":\\"趣味・関心\\",\\"subCategories\\":[{\\"tagName\\":\\"アウトドア\\",\\"title\\":\\"アウトドア\\",\\"engName\\":\\"outdoor\\"}]}]}]}"]);
                self.__next_f.push([1, "0:{\\"categories\\":[{\\"title\\":\\"くらし\\"},{\\"title\\":\\"社会・経済\\"},{\\"title\\":\\"テクノロジー\\"},{\\"title\\":\\"エンタメ\\"},{\\"title\\":\\"趣味・関心\\"},{\\"title\\":\\"創作\\"},{\\"title\\":\\"まなび\\"}]}"]);
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    aside = document.find("aside")
    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(aside)
    self.assertIsNotNone(main)
    self.assertIn("くらし", aside.text)
    self.assertIn("First Note", main.text)
    self.assertNotIn("Categories", main.text)
    self.assertNotIn("くらし", main.text)
    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertNotIn("### Categories", rendered)

  def test_prunes_duplicate_nav_sections_from_main(self) -> None:
    document = parse_document(
      Resource(
        source="https://note.com/topic/outdoor",
        content="""
        <html>
          <body>
            <aside>
              <ul>
                <li>1 アルゼンチン代表</li>
                <li>2 開発効率化</li>
                <li>3 さよならララ</li>
                <li>4 大統領のケーキ</li>
                <li>5 夏の暮らし</li>
              </ul>
              <section><h3>くらし</h3><ul><li>ライフスタイル</li></ul></section>
              <section><h3>社会・経済</h3><ul><li>社会問題・時事</li></ul></section>
              <section><h3>テクノロジー</h3><ul><li>コンピュータ・IT</li></ul></section>
              <section><h3>エンタメ</h3><ul><li>エンタメ全般</li></ul></section>
              <section><h3>趣味・関心</h3><ul><li>アウトドア</li></ul></section>
              <section><h3>創作</h3><ul><li>創作全般</li></ul></section>
              <section><h3>まなび</h3><ul><li>キャリア</li></ul></section>
            </aside>
            <main id="main-content">
              <section>
                <h3>Recovered Links</h3>
                <ul>
                  <li><a href="/topic/argentina">1 アルゼンチン代表</a></li>
                  <li><a href="/topic/dev">2 開発効率化</a></li>
                  <li><a href="/topic/lala">3 さよならララ</a></li>
                  <li><a href="/topic/cake">4 大統領のケーキ</a></li>
                  <li><a href="/topic/summer">5 夏の暮らし</a></li>
                </ul>
              </section>
              <section>
                <h3>Categories</h3>
                <ul>
                  <li>くらし</li>
                  <li>社会・経済</li>
                  <li>テクノロジー</li>
                  <li>エンタメ</li>
                  <li>趣味・関心</li>
                  <li>創作</li>
                  <li>まなび</li>
                </ul>
              </section>
              <section>
                <h3>登山</h3>
                <ul>
                  <li><a href="/creator/n/n111">First Note</a></li>
                  <li><a href="/creator/n/n222">Second Note</a></li>
                </ul>
              </section>
            </main>
          </body>
        </html>
        """,
      )
    )

    _prune_duplicate_nav_sections(document)

    rendered = render_normal(document, width=80, text_styles=False)
    self.assertNotIn("### Recovered Links", rendered)
    self.assertNotIn("### Categories", rendered)
    self.assertIn("### 登山", rendered)

  def test_materializes_react_bailout_segment_into_visible_layout(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content="""
        <html>
          <body>
            <div class="grid">
              <!--$?--><template id="B:0"></template><div>loading</div><!--/$-->
              <main id="main-content"></main>
            </div>
            <div id="S:0" hidden>
              <aside>left pane</aside>
            </div>
          </body>
        </html>
        """,
      )
    )

    _materialize_react_bailout_segments(document.body)

    grid = TWebDocument(document).find("div", attrs={"class": "grid"})
    self.assertIsNotNone(grid)
    tags = [child.tag for child in grid.node.children if hasattr(child, "tag")]
    self.assertIn("aside", tags)
    self.assertIn("main", tags)
    aside = next(child for child in grid.node.children if hasattr(child, "tag") and child.tag == "aside")
    self.assertEqual(aside.text_content(), "left pane")
    self.assertIsNone(TWebDocument(document).find("div", attrs={"id": "S:0"}))

  def test_materializes_react_bailout_segment_with_nonzero_ids(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content="""
        <html>
          <body>
            <div class="grid">
              <!--$?--><template id="B:3"></template><div>loading</div><!--/$-->
              <main id="main-content"></main>
            </div>
            <section id="S:3" hidden>
              <aside>left pane</aside>
            </section>
          </body>
        </html>
        """,
      )
    )

    _materialize_react_bailout_segments(document.body)

    grid = TWebDocument(document).find("div", attrs={"class": "grid"})
    self.assertIsNotNone(grid)
    tags = [child.tag for child in grid.node.children if hasattr(child, "tag")]
    self.assertIn("aside", tags)
    self.assertIn("main", tags)
    aside = next(child for child in grid.node.children if hasattr(child, "tag") and child.tag == "aside")
    self.assertEqual(aside.text_content(), "left pane")
    self.assertIsNone(TWebDocument(document).find("section", attrs={"id": "S:3"}))

  @patch("tweb.api._extract_site_specific_hydration_sections")
  def test_restores_hidden_react_bailout_sidebar_for_note_topic_layout(
    self,
    mock_extract_site_specific_hydration_sections,
  ) -> None:
    mock_extract_site_specific_hydration_sections.return_value = [
      HydrationSection(
        title="七夕",
        items=(
          ("First Note", "/creator/n/n111"),
          ("Second Note", "/creator/n/n222"),
        ),
      ),
    ]
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://note.com/topic/lifestyle",
          content="""
          <html>
            <body>
              <div class="grid">
                <!--$?--><template id="B:0"></template><div>loading</div><!--/$-->
                <main id="main-content"></main>
              </div>
              <div id="S:0" hidden>
                <aside>left pane</aside>
              </div>
              <script>
                document.querySelector('main').textContent = 'Something went wrong. Try again.';
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    grid = document.find("div", attrs={"class": "grid"})
    aside = document.find("aside")
    main = document.find("main", attrs={"id": "main-content"})
    self.assertIsNotNone(grid)
    self.assertIsNotNone(aside)
    self.assertIsNotNone(main)
    tags = [child.tag for child in grid.node.children if hasattr(child, "tag")]
    self.assertIn("aside", tags)
    self.assertIn("main", tags)
    self.assertLess(tags.index("aside"), tags.index("main"))
    self.assertIn("left pane", aside.text)
    self.assertIn("七夕", main.text)


if __name__ == "__main__":
  unittest.main()
