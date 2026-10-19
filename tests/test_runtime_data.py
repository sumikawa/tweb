from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from tweb.fetcher import Resource
from tweb.js_runtime import QuickJSRuntime
from tweb.js_runtime_helpers import JavaScriptRuntimeError
from tweb.parser import parse_document
from tweb.runtime_data import (
  _chunk_payloads,
  _scan_inline_script_payloads,
  _window_root_payloads,
  collect_runtime_data,
)


class RuntimeDataTest(unittest.TestCase):
  def test_collects_sections_from_nested_apollo_references(self) -> None:
    state = {
      "ROOT_QUERY": {"catalog": {"__ref": "Catalog:1"}},
      "Catalog:1": {"title": "Reference guides", "items": [{"__ref": "Guide:1"}, {"__ref": "Guide:2"}]},
      "Guide:1": {"title": "First guide", "url": "/first"},
      "Guide:2": {"title": "Second guide", "url": "/second"},
    }
    payload = {"props": {"pageProps": {"__APOLLO_STATE__": state}}}
    for source in ("inline", "window", "window-no-query-root", "network"):
      with self.subTest(source=source):
        script = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + '</script>'
        document = parse_document(Resource(
          source="https://example.org/catalog",
          content="<html><body>Loading" + (script if source == "inline" else "") + "</body></html>",
        ))
        runtime = QuickJSRuntime(document)
        if source.startswith("window"):
          runtime_state = {key: value for key, value in state.items() if key != "ROOT_QUERY"} if source == "window-no-query-root" else state
          runtime.eval("window.__APOLLO_STATE__ = " + json.dumps(runtime_state))
        if source == "network":
          runtime.runtime_data_network_payloads = lambda: [{
            "url": "https://example.org/api/catalog", "body": json.dumps(payload),
          }]
        result = collect_runtime_data(document, runtime, body_was_substantial=False, fallback_reason="test")
        section = next(section for section in result.sections if section.title == "Reference guides")
        self.assertEqual(section.items, (("First guide", "/first"), ("Second guide", "/second")))

  def test_labels_generic_network_items_from_the_api_path(self) -> None:
    document = parse_document(Resource(
      source="https://example.com/",
      content="<html><body><main>Existing readable content</main></body></html>",
    ))
    runtime = Mock()
    runtime.eval.return_value = "[]"
    runtime.runtime_data_network_payloads.return_value = [{
      "url": "https://example.com/api/personalized-articles?results=50",
      "body": json.dumps({
        "items": [
          {"title": "First recommendation", "link": "/articles/first"},
          {"title": "Second recommendation", "link": "/articles/second"},
        ],
      }),
    }]

    result = collect_runtime_data(
      document,
      runtime,
      body_was_substantial=True,
      fallback_reason="test",
    )

    self.assertEqual(result.sections[0].title, "Personalized Articles")
    self.assertEqual(result.sections[0].items[0][0], "First recommendation")
    self.assertEqual(result.sections[0].items[0][1], "/articles/first")

  def test_keeps_large_linked_network_listing_as_recovered_content(self) -> None:
    document = parse_document(Resource(
      source="https://example.com/",
      content="<html><body><main>Existing readable content</main></body></html>",
    ))
    runtime = Mock()
    runtime.eval.return_value = "[]"
    runtime.runtime_data_network_payloads.return_value = [{
      "url": "https://example.com/api/recommendations?results=50",
      "body": json.dumps({
        "items": [
          {"title": f"Recommendation {index}", "link": f"/articles/{index}"}
          for index in range(50)
        ],
      }),
    }]

    result = collect_runtime_data(
      document,
      runtime,
      body_was_substantial=True,
      fallback_reason="test",
    )

    self.assertEqual(result.sections[0].role, "recovered")
    self.assertEqual(len(result.sections[0].items), 50)

  def test_scan_inline_script_payloads_collects_all_supported_sources_in_one_pass(self) -> None:
    document = parse_document(
      Resource(
        source="https://example.com",
        content="""
        <html>
          <body>
            <script id="__NEXT_DATA__" type="application/json">
              {"sections":[{"title":"JSON payload","items":[{"text":"First","href":"/first"}]}]}
            </script>
            <script>
              window.__data = JSON.parse("{\\"sections\\":[{\\"title\\":\\"Parsed payload\\",\\"items\\":[{\\"text\\":\\"Second\\",\\"href\\":\\"/second\\"}]}]}");
            </script>
            <script>
              var boot = {"sections":[{"title":"Literal payload","items":[{"text":"Third","href":"/third"}]}]};
            </script>
            <script>
              self.__next_f.push([1, "{\\"sections\\":[{\\"title\\":\\"Chunk payload\\",\\"items\\":[{\\"text\\":\\"Fourth\\",\\"href\\":\\"/fourth\\"}]}]}"]);
            </script>
          </body>
        </html>
        """,
      )
    )

    inline_json, inline_json_parse, inline_literal, inline_chunk = _scan_inline_script_payloads(document)

    self.assertEqual(inline_json[0][0], "__NEXT_DATA__")
    self.assertEqual(inline_json[0][1]["sections"][0]["title"], "JSON payload")
    self.assertEqual(inline_json_parse[0][0], "__data")
    self.assertEqual(inline_json_parse[0][1]["sections"][0]["title"], "Parsed payload")
    self.assertTrue(any(payload["sections"][0]["title"] == "Literal payload" for _name, payload in inline_literal))
    self.assertTrue(any(payload["sections"][0]["title"] == "Chunk payload" for _name, payload in inline_chunk))

  def test_scan_inline_script_payloads_skips_expensive_literal_scan_for_rich_page(self) -> None:
    large_literal = "x" * (270 * 1024)
    rich_links = "".join(f'<a href="/item/{index}">Item {index}</a>' for index in range(170))
    rich_controls = "".join('<button type="button">Open</button>' for _ in range(12))
    document = parse_document(
      Resource(
        source="https://example.com",
        content=f"""
        <html>
          <body>
            <main>
              <p>{"Readable content " * 40}</p>
              {rich_links}
              {rich_controls}
            </main>
            <script id="__NEXT_DATA__" type="application/json">
              {{"sections":[{{"title":"JSON payload","items":[{{"text":"First","href":"/first"}}]}}]}}
            </script>
            <script>
              var filler = "{large_literal}";
              var boot = {{"sections":[{{"title":"Literal payload","items":[{{"text":"Third","href":"/third"}}]}}]}};
            </script>
          </body>
        </html>
        """,
      )
    )

    inline_json, _inline_json_parse, inline_literal, _inline_chunk = _scan_inline_script_payloads(
      document,
      body_was_substantial=True,
      document_link_count=170,
      document_control_count=12,
    )

    self.assertEqual(inline_json[0][0], "__NEXT_DATA__")
    self.assertEqual(inline_json[0][1]["sections"][0]["title"], "JSON payload")
    self.assertFalse(any(payload["sections"][0]["title"] == "Literal payload" for _name, payload in inline_literal))

  def test_window_root_payloads_can_skip_large_duplicate_root_names(self) -> None:
    document = parse_document(Resource(source="https://example.com", content="<html><body></body></html>"))
    runtime = QuickJSRuntime(document)
    runtime.eval(
      """
      window.__data = {
        categories: [
          {
            title: "Top Picks",
            items: [
              { title: "First Forecast", url: "/forecast/first" }
            ]
          }
        ]
      };
      """,
      drain_timers=False,
    )

    self.assertEqual(_window_root_payloads(runtime, skip_names={"__data"}), [])
    payloads = _window_root_payloads(runtime, skip_names=set())
    self.assertEqual(payloads[0][0], "__data")
    self.assertEqual(payloads[0][1]["categories"][0]["title"], "Top Picks")

  def test_window_root_payloads_falls_back_to_per_root_eval_after_memory_error(self) -> None:
    runtime = Mock()
    payloads_by_name = {
      "__NUXT__": [["__NUXT__", {"title": "Nuxt payload"}]],
      "__NEXT_DATA__": [["__NEXT_DATA__", {"title": "Next payload"}]],
    }

    def fake_eval(source: str, drain_timers: bool = False):
      self.assertFalse(drain_timers)
      if "const roots =" in source:
        raise JavaScriptRuntimeError("JavaScript memory limit exceeded")
      for root_name, payload in payloads_by_name.items():
        if json.dumps(root_name) in source:
          return json.dumps(payload)
      if json.dumps("__INITIAL_STATE__") in source:
        raise JavaScriptRuntimeError("JavaScript memory limit exceeded")
      return "[]"

    runtime.eval.side_effect = fake_eval

    payloads = _window_root_payloads(runtime, skip_names={"__data"})

    self.assertEqual(payloads, [
      ("__NUXT__", {"title": "Nuxt payload"}),
      ("__NEXT_DATA__", {"title": "Next payload"}),
    ])

  def test_window_root_payloads_skips_throwing_roots(self) -> None:
    document = parse_document(Resource(source="https://example.com", content="<html><body></body></html>"))
    runtime = QuickJSRuntime(document)
    runtime.eval(
      """
      Object.defineProperty(window, "__data", {
        configurable: true,
        get() {
          throw null;
        },
      });
      window.__NEXT_DATA__ = {
        sections: [
          {
            title: "Recovered payload",
            items: [{text: "Visible", href: "/visible"}],
          },
        ],
      };
      """,
      drain_timers=False,
    )

    payloads = _window_root_payloads(runtime)

    self.assertEqual(payloads, [
      ("__NEXT_DATA__", {"sections": [{"title": "Recovered payload", "items": [{"text": "Visible", "href": "/visible"}]}]}),
    ])

  def test_chunk_payloads_skip_throwing_globals(self) -> None:
    document = parse_document(Resource(source="https://example.com", content="<html><body></body></html>"))
    runtime = QuickJSRuntime(document)
    runtime.eval(
      """
      Object.defineProperty(window, "__next_f", {
        configurable: true,
        get() {
          throw null;
        },
      });
      window.webpackJsonp = [
        ["bootstrap", "{\\"sections\\":[{\\"title\\":\\"Chunk payload\\",\\"items\\":[{\\"text\\":\\"Chunk item\\",\\"href\\":\\"/chunk\\"}]}]}"],
      ];
      """,
      drain_timers=False,
    )

    payloads = _chunk_payloads(runtime)

    self.assertEqual(payloads, [
      ("webpackJsonp", {"sections": [{"title": "Chunk payload", "items": [{"text": "Chunk item", "href": "/chunk"}]}]}),
    ])


if __name__ == "__main__":
  unittest.main()
