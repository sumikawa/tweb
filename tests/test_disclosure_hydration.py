from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from tweb.api import TWebDocument, _augment_sparse_body_from_hydration
from tweb.fetcher import Resource
from tweb.hydration import HydrationSection, populate_disclosure_sections
from tweb.parser import parse_document
from tweb.runtime_data import RuntimeDataDebugInfo, RuntimeDataResult


class DisclosureHydrationTest(unittest.TestCase):
  def document(self, *, panel: str = "", body: str | None = None) -> TWebDocument:
    body = "Readable article content. " * 30 if body is None else body
    return TWebDocument(parse_document(Resource(
      source="https://example.org/articles/1",
      content=f"""<html><body><main><p>{body}</p></main><aside>
        <button aria-controls="chapters" aria-expanded="false">Chapters</button>
        <div id="chapters" hidden>{panel}</div>
      </aside></body></html>""",
    )))

  def sections(self) -> list[HydrationSection]:
    return [HydrationSection("Chapters", (("First chapter", "/first"), ("Second chapter", "/second")))]

  def result(self, sections: list[HydrationSection]) -> RuntimeDataResult:
    return RuntimeDataResult([], [], sections, RuntimeDataDebugInfo(
      confidence="high", fallback_reason="generic-runtime-collector",
      source_summaries=(), used_site_specific_fallback=False, body_was_substantial=True,
    ))

  @patch("tweb.api.collect_runtime_data")
  def test_readable_article_fills_disclosure_without_site_url(self, collector: Mock) -> None:
    wrapped = self.document()
    before = wrapped.find("main").get_text()
    for _ in range(2):
      debug = _augment_sparse_body_from_hydration(
        wrapped.document, Mock(), extra_sections=self.sections(),
      )
      self.assertEqual(debug.fallback_reason, "body-already-readable-with-disclosure-sections")
    collector.assert_not_called()
    self.assertEqual(wrapped.find("main").get_text(), before)
    panel = wrapped.find("div", attrs={"id": "chapters"})
    self.assertEqual(panel.get_text().count("First chapter"), 1)
    self.assertIn("hidden", panel.attrs)
    button = next(control for control in wrapped.form_controls() if control.kind == "button")
    self.assertTrue(wrapped.click_button_control(button.control_id).dom_changed)
    self.assertNotIn("hidden", panel.attrs)

  @patch("tweb.api.collect_runtime_data")
  def test_unmatched_sections_still_use_collector(self, collector: Mock) -> None:
    wrapped = self.document()
    sections = self.sections() + [HydrationSection("Related", (("Related article", "/related"),))]
    collector.return_value = self.result(sections)
    _augment_sparse_body_from_hydration(wrapped.document, Mock(), extra_sections=sections)
    collector.assert_called_once()

  @patch("tweb.api.collect_runtime_data")
  def test_generic_collector_sections_fill_disclosure(self, collector: Mock) -> None:
    wrapped = self.document(body="Loading")
    collector.return_value = self.result(self.sections())
    _augment_sparse_body_from_hydration(wrapped.document, Mock(), extra_sections=[])
    collector.assert_called_once()
    self.assertIn("First chapter", wrapped.find("div", attrs={"id": "chapters"}).get_text())

  @patch("tweb.api.collect_runtime_data")
  def test_readable_kakuyomu_page_with_runtime_hints_still_collects(self, collector: Mock) -> None:
    wrapped = TWebDocument(parse_document(Resource(
      source="https://kakuyomu.jp/works/123/episodes/456",
      content='<html><body><main>' + "Readable article. " * 30
        + '</main><script id="__NEXT_DATA__" type="application/json">{}</script></body></html>',
    )))
    collector.return_value = self.result([])
    _augment_sparse_body_from_hydration(wrapped.document, Mock(), extra_sections=[])
    collector.assert_called_once()

  def test_existing_native_panel_and_controls_are_preserved(self) -> None:
    for content in ("Native content", '<input name="query">', '<a href="/native"></a>'):
      with self.subTest(content=content):
        wrapped = self.document(panel=content)
        panel = wrapped.find("div", attrs={"id": "chapters"})
        children = list(panel.node.children)
        self.assertEqual(populate_disclosure_sections(wrapped.document, self.sections()), set())
        self.assertEqual(panel.node.children, children)

  def test_empty_sections_do_not_change_panel(self) -> None:
    wrapped = self.document()
    self.assertEqual(populate_disclosure_sections(wrapped.document, [HydrationSection("Chapters", ())]), set())
    self.assertNotIn("data-tweb-hydration-section", wrapped.find("div", attrs={"id": "chapters"}).attrs)


if __name__ == "__main__":
  unittest.main()
