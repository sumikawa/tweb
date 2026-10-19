from __future__ import annotations

import json
import unittest

from tweb.api import (
  TWebDocument,
  _partition_hydration_sections,
  _select_hydration_body_target,
  _select_hydration_nav_target,
)
from tweb.fetcher import Resource
from tweb.hydration import HydrationSection
from tweb.hydration_targets import (
  find_main_region,
  is_content_container,
  is_empty_body_target,
  is_navigation_container,
  is_navigation_section,
)
from tweb.parser import parse_document


class HydrationTargetsTest(unittest.TestCase):
  def document(self, html: str, source: str = "https://example.org/catalog") -> TWebDocument:
    return TWebDocument(parse_document(Resource(source=source, content="<html><body>" + html + "</body></html>")))

  def test_section_partition_is_independent_of_route_conventions(self) -> None:
    for href in ("/topic/one", "/n/one", "/products/one", "https://other.example/one"):
      with self.subTest(href=href):
        body = HydrationSection("Related articles", (("One", href), ("Two", "/other")))
        nav = HydrationSection("Directory", body.items, role="nav")
        self.assertEqual(_partition_hydration_sections([body, nav]), ([body], [nav]))

  def test_navigation_membership_comes_from_dom_labels_or_observed_links(self) -> None:
    wrapped = self.document('''<h2 id="directory-name">Directory</h2>
      <nav aria-labelledby="directory-name"><a href="/a">First</a><a href="/b">Second</a></nav><main></main>''')
    target = wrapped.find("nav").node
    section = HydrationSection("Directory", (("A", "/arbitrary"), ("B", "/unrelated")))
    self.assertTrue(is_navigation_section(section, target, root=wrapped.document.body))
    observed = HydrationSection("Observed entries", (("First", "/a"), ("Second", "/b")))
    self.assertTrue(is_navigation_section(observed, target))
    self.assertFalse(is_navigation_section(HydrationSection(section.title, section.items, role="recovered"), target))

  def test_semantic_feed_wins_over_misleading_class_names(self) -> None:
    wrapped = self.document('''<main><div role="navigation" class="article-list"></div>
      <div role="feed" class="timeline__nav sidebar" id="feed"></div></main>''')
    feed = wrapped.find("div", attrs={"id": "feed"}).node
    self.assertTrue(is_content_container(feed))
    self.assertFalse(is_navigation_container(feed))
    self.assertIs(_select_hydration_body_target(wrapped.document.body)[0], feed)

  def test_unidentified_empty_panes_do_not_gain_roles_from_class_names(self) -> None:
    wrapped = self.document('''<main><div class="timeline__nav"></div>
      <div class="timeline__body"></div></main>''')
    self.assertIs(_select_hydration_body_target(wrapped.document.body)[0], wrapped.find("main").node)
    self.assertIsNone(_select_hydration_nav_target(wrapped.document.body)[0])

  def test_unique_empty_sibling_of_navigation_is_body_target(self) -> None:
    for source in ("https://example.org/", "https://note.com/"):
      wrapped = self.document('''<main><section><div role="navigation">Directory</div>
        <div id="arbitrary-slot"></div></section></main>''', source)
      self.assertIs(_select_hydration_body_target(wrapped.document.body)[0], wrapped.find("div", attrs={"id": "arbitrary-slot"}).node)

  def test_multiple_body_or_navigation_candidates_fall_back_without_replacement(self) -> None:
    wrapped = self.document('''<main><div role="feed" id="one"><span class="spinner"></span></div><div role="feed" id="two"></div>
      <nav aria-label="One"></nav><nav aria-label="Two"></nav></main>''')
    body_target, replace, _heading = _select_hydration_body_target(wrapped.document.body)
    self.assertIs(body_target, wrapped.find("main").node)
    self.assertFalse(replace)
    self.assertIsNone(_select_hydration_nav_target(wrapped.document.body)[0])

  def test_loading_indicator_in_navigation_is_not_a_body_target(self) -> None:
    wrapped = self.document('<main><nav><div class="loading-spinner"></div></nav></main>')
    target, replace, _heading = _select_hydration_body_target(wrapped.document.body)
    self.assertIs(target, wrapped.find("main").node)
    self.assertFalse(replace)

  def test_hidden_initial_main_is_not_recreated_as_a_hidden_target(self) -> None:
    wrapped = self.document('<div hidden><main></main></div>')
    target, replace, _heading = _select_hydration_body_target(
      wrapped.document.body, initial_main_attrs={}, initial_main_ancestor_specs=[("div", {"hidden": ""})],
    )
    self.assertIs(target, wrapped.document.body)
    self.assertFalse(replace)

  def test_hidden_regions_and_header_navigation_are_not_targets(self) -> None:
    wrapped = self.document('''<div hidden><div role="main" id="hidden-main"></div></div>
      <header><nav>Header links</nav></header><div role="main" id="actual-main">
      <div hidden><div role="feed"></div><nav></nav></div><div role="feed" id="visible-feed"></div></div>''')
    self.assertIs(find_main_region(wrapped.document.body), wrapped.find("div", attrs={"id": "actual-main"}).node)
    self.assertIs(_select_hydration_body_target(wrapped.document.body)[0], wrapped.find("div", attrs={"id": "visible-feed"}).node)
    self.assertIsNone(_select_hydration_nav_target(wrapped.document.body)[0])

  def test_native_and_aria_controls_prevent_empty_target_selection(self) -> None:
    for control in ('<input name="query">', '<div role="textbox"></div>', '<div role="button"></div>', '<div contenteditable=""></div>'):
      with self.subTest(control=control):
        wrapped = self.document('<main><div role="feed" id="widget">' + control + '</div></main>')
        self.assertFalse(is_empty_body_target(wrapped.find("div", attrs={"id": "widget"}).node))
        self.assertIs(_select_hydration_body_target(wrapped.document.body)[0], wrapped.find("main").node)

  def test_aria_banner_and_footer_navigation_are_not_targets(self) -> None:
    wrapped = self.document('''<div role="banner"><div role="navigation"></div></div>
      <main></main><div role="contentinfo"><div role="navigation"></div></div>''')
    self.assertIsNone(_select_hydration_nav_target(wrapped.document.body)[0])

  def test_advertising_or_article_sidebar_is_not_navigation(self) -> None:
    for markup in (
      '<aside><article><a href="/one">One</a><a href="/two">Two</a></article></aside>',
      '<aside><p>Sponsored content</p><a href="/one">One</a><a href="/two">Two</a></aside>',
      '<aside><a href="/sponsored">Advertisement</a></aside>',
    ):
      with self.subTest(markup=markup):
        wrapped = self.document(markup + '<main></main>')
        self.assertFalse(is_navigation_container(wrapped.find("aside").node))
        self.assertIsNone(_select_hydration_nav_target(wrapped.document.body)[0])

  def test_dense_sidebar_links_are_preserved_as_navigation(self) -> None:
    wrapped = self.document('''<aside><h2>Directory</h2><ul>
      <li><a href="/random/a">First entry</a></li><li><a href="/random/b">Second entry</a></li>
      </ul></aside><main></main>''')
    nav, replace = _select_hydration_nav_target(wrapped.document.body)
    self.assertIs(nav, wrapped.find("aside").node)
    self.assertFalse(replace)

  def test_bounded_probe_does_not_treat_unscanned_content_as_empty(self) -> None:
    wrapped = self.document('<main><div role="feed" id="wide">' + '<span></span>' * 70
      + '<input name="unscanned"></div></main>')
    self.assertFalse(is_empty_body_target(wrapped.find("div", attrs={"id": "wide"}).node))

  def test_recovery_uses_semantics_across_domains_and_class_renames(self) -> None:
    payload = {"categories": [{"title": "Directory", "items": [
      {"title": "One", "href": "/records/one"}, {"title": "Two", "href": "/records/two"},
    ]}], "articles": [{"title": "A readable first article", "href": "/topic/first"},
      {"title": "A readable second article", "href": "/topic/second"}]}
    for source, css_class in (("https://example.org/", "unknown-123"), ("https://note.com/", "completely-different")):
      with self.subTest(source=source, css_class=css_class):
        wrapped = self.document('''<header><nav>Header</nav></header><div role="main">
          <div role="navigation" id="directory"></div><div role="feed" id="articles" class="%s"></div>
          </div><script>window.__INITIAL_STATE__ = %s;</script>''' % (css_class, json.dumps(payload)), source)
        wrapped.execute_embedded_scripts(ignore_errors=False, browser_render_policy="never")
        self.assertIn("One", wrapped.find("div", attrs={"id": "directory"}).get_text())
        self.assertNotIn("first article", wrapped.find("div", attrs={"id": "directory"}).get_text())
        self.assertIn("first article", wrapped.find("div", attrs={"id": "articles"}).get_text())
        self.assertNotIn("One", wrapped.find("div", attrs={"id": "articles"}).get_text())
        self.assertEqual(wrapped.find("nav").get_text(), "Header")


if __name__ == "__main__":
  unittest.main()
