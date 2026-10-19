from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from requests import Response
from tweb.api import TWebDocument
from tweb.fetcher import Resource
from tweb.parser import parse_document
from tweb.runtime_data import _collect_payload, _derive_href, _existing_document_links
from tweb.site_specific import extract_hydration_sections


class GenericRuntimeRecoveryTest(unittest.TestCase):
  def test_identifiers_and_slugs_do_not_create_routes_on_any_domain(self) -> None:
    values = [
      {"title": "Article", "key": "n111", "user": {"urlname": "creator"}},
      {"title": "Topic", "engName": "outdoor/camping"},
      {"title": "Category", "parentDir": "topic", "engName": "outdoor"},
      {"title": "Page", "slug": "some-page"},
    ]
    for origin in ("https://note.com/", "https://example.org/"):
      for value in values:
        with self.subTest(origin=origin, value=value):
          self.assertIsNone(_derive_href(value, key_hint="subCategories", base_url=origin, existing_links={}))

  def test_explicit_routes_and_unambiguous_document_links_are_kept(self) -> None:
    for field in ("href", "url", "path", "pathname", "externalUrl", "external_url"):
      with self.subTest(field=field):
        self.assertEqual(_derive_href(
          {"title": "Guide", field: "/actual/route"}, key_hint="items",
          base_url="https://example.org/", existing_links={},
        ), "/actual/route")
    self.assertEqual(_derive_href(
      {"title": "Guide", "slug": "wrong"}, key_hint="items",
      base_url="https://example.org/", existing_links={"Guide": "/observed"},
    ), "/observed")
    document = parse_document(Resource(source="https://example.org/", content='''<body>
      <a href="/one">Same title</a><a href="/two">Same title</a>
      <a href="/guide">Guide</a><a href="/guide">Guide</a></body>'''))
    self.assertEqual(_existing_document_links(document), {"Guide": "/guide"})

  def test_note_urls_do_not_launch_synthetic_fetch_or_eval(self) -> None:
    for url in ("https://note.com/", "https://note.com/topic/outdoor/camping", "https://example.org/"):
      runtime = Mock()
      self.assertEqual(extract_hydration_sections(runtime, url), [])
      runtime.eval.assert_not_called()
      runtime.session.request.assert_not_called()

  @patch("tweb.js_runtime.requests.request")
  @patch("tweb.api.fetch_rendered_resource")
  def test_page_initiated_delayed_json_fetch_uses_generic_recovery(self, chrome: Mock, fetch: Mock) -> None:
    for origin in ("https://note.com/", "https://example.org/"):
      with self.subTest(origin=origin):
        fetch.reset_mock()
        payload = {"data": {"sections": [{"label_name": "Featured", "notes": [
          {"name": "First article without an explicit destination", "key": "n111", "user": {"urlname": "creator"}},
          {"name": "Second article with an explicit destination", "url": "/observed/second"},
        ]}]}}
        response = Response()
        response.status_code = 200
        response.url = origin + "api/catalog"
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode()
        response._content_consumed = True
        fetch.return_value = response
        wrapped = TWebDocument(parse_document(Resource(source=origin, content="""<html><body>
          <main>Loading...</main><script>
          document.addEventListener('DOMContentLoaded', () => {
            setTimeout(() => fetch('/api/catalog').then(response => response.json()), 25);
          });
          </script></body></html>""")))
        wrapped.execute_embedded_scripts(ignore_errors=False, browser_render_policy="auto")
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[:2], ("GET", origin + "api/catalog"))
        self.assertIn("First article without an explicit destination", wrapped.body_text())
        self.assertTrue(any(link.href == "/observed/second" for link in wrapped.links()))
        self.assertFalse(any(link.href.startswith("/creator/") for link in wrapped.links()))
        self.assertFalse(wrapped.hydration_debug()["used_site_specific_fallback"])
        chrome.assert_not_called()

  def test_unlinked_flight_article_text_is_recovered_without_navigation_noise(self) -> None:
    payload = {"sections": [{"title": "Featured", "notes": [
      {"name": "A readable article title whose destination is unknown", "key": "n111", "user": {"urlname": "creator"}},
      {"name": "Another readable article title without a URL field", "key": "n222", "user": {"urlname": "creator"}},
    ]}], "categories": [{"title": "Topics", "subCategories": [
      {"title": "Outdoors", "engName": "outdoor"}, {"title": "Camping", "engName": "outdoor/camping"},
    ]}], "className": "grid suspicious-css-classes", "reference": "$24:props:children"}
    wrapped = TWebDocument(parse_document(Resource(source="https://example.org/", content="""<html><body>
      <main></main><script>self.__next_f = [[1, %s]];</script></body></html>"""
      % json.dumps("0:" + json.dumps(payload)))))
    wrapped.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")
    text = wrapped.body_text()
    self.assertIn(payload["sections"][0]["notes"][0]["name"], text)
    self.assertIn("Outdoors", text)
    self.assertEqual(wrapped.links(), [])
    self.assertNotIn("suspicious-css-classes", text)
    self.assertNotIn("$24:props:children", text)

  def test_main_removed_by_runtime_is_restored_while_footer_survives(self) -> None:
    article = "This server-rendered article must remain readable. " * 20
    wrapped = TWebDocument(parse_document(Resource(source="https://example.org/", content=f"""<html><body>
      <main><h1>Article</h1><p>{article}</p><a href="/original">Original link</a></main>
      <footer>{'Footer navigation text. ' * 5}</footer>
      <script>document.querySelector('main').remove();</script></body></html>""")))
    wrapped.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")
    self.assertIn(article.strip(), wrapped.body_text())
    self.assertTrue(any(link.href == "/original" for link in wrapped.links()))

  def test_main_replacement_with_working_controls_is_preserved(self) -> None:
    wrapped = TWebDocument(parse_document(Resource(source="https://example.org/", content="""<html><body>
      <main><p>%s</p></main><script>
        document.querySelector('main').remove();
        const input = document.createElement('input');
        input.id = 'mounted-search'; document.body.appendChild(input);
      </script></body></html>""" % ("Initial article content. " * 30))))
    wrapped.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")
    self.assertIsNone(wrapped.find("main"))
    self.assertIsNotNone(wrapped.find("input", attrs={"id": "mounted-search"}))

  def test_long_text_only_sections_are_recovered_but_short_labels_are_not_promoted(self) -> None:
    _texts, _links, sections = _collect_payload({"sections": [{
      "title": "Long article titles", "items": [
        {"title": "An article title with enough context to be readable"},
        {"title": "Another detailed article title that should be visible"},
      ],
    }], "categories": [{"title": "Topics", "items": [{"title": "One"}, {"title": "Two"}]}]},
      base_url="https://example.org/", existing_links={})
    self.assertEqual(next(s for s in sections if s.title == "Long article titles").role, "recovered")
    self.assertEqual(next(s for s in sections if s.title == "Topics").role, "nav")


if __name__ == "__main__":
  unittest.main()
