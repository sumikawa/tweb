from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from tweb.css import STYLESHEET_CACHE, build_style_context, computed_style_declarations
from tweb.dom import ElementNode
from tweb.fetcher import Resource, create_session
from tweb.parser import parse_document


class CssStyleContextTest(unittest.TestCase):
  def setUp(self) -> None:
    STYLESHEET_CACHE.clear()

  def test_preserves_rule_order_across_indexed_selectors(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              div { font-style: italic; }
              .promo { font-style: normal; }
              [data-state="active"] { font-weight: bold; }
              div .promo { text-decoration: underline; }
            </style>
          </head>
          <body>
            <div>
              <span class="promo" data-state="active">deal</span>
            </div>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    node = document.find_first("span")
    self.assertIsNotNone(node)

    properties = style_context.properties(node)

    self.assertEqual(properties.font_style, "normal")
    self.assertEqual(properties.font_weight, "bold")
    self.assertEqual(properties.text_decoration, "underline")

  def test_prefers_higher_specificity_over_later_rule(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              #deal { font-style: normal; }
              span { font-style: italic; }
            </style>
          </head>
          <body>
            <span id="deal">deal</span>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    node = document.find_first("span")
    self.assertIsNotNone(node)

    properties = style_context.properties(node)

    self.assertEqual(properties.font_style, "normal")

  def test_supports_child_combinator_and_multiple_attribute_selectors(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              main > p[data-state="active"][data-size="lg"] { font-weight: bold; }
              main p[data-state="active"] { font-style: italic; }
            </style>
          </head>
          <body>
            <main>
              <p id="direct" data-state="active" data-size="lg">Direct child</p>
              <section>
                <p id="nested" data-state="active" data-size="lg">Nested child</p>
              </section>
            </main>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    direct = document.find_first("p")
    nested = document.find_all("p")[1]
    self.assertIsNotNone(direct)

    direct_properties = style_context.properties(direct)
    nested_properties = style_context.properties(nested)

    self.assertEqual(direct_properties.font_weight, "bold")
    self.assertEqual(direct_properties.font_style, "italic")
    self.assertIsNone(nested_properties.font_weight)
    self.assertEqual(nested_properties.font_style, "italic")

  def test_inherited_hidden_reason_overrides_cached_node_visibility(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              .hidden { display: none; }
            </style>
          </head>
          <body>
            <div class="hidden">
              <span id="child">secret</span>
            </div>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    node = document.find_first("span")
    self.assertIsNotNone(node)

    visible = style_context.properties(node, inherited_visible=True)
    hidden = style_context.properties(node, inherited_visible=False)

    self.assertTrue(visible.visible)
    self.assertFalse(hidden.visible)
    self.assertEqual(hidden.hidden_reason, "ancestor_hidden")

  def test_treats_aria_hidden_subtree_as_not_visible(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <body>
            <section aria-hidden="true"><p>Carousel clone</p></section>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    section = document.find_first("section")
    paragraph = document.find_first("p")
    self.assertIsNotNone(section)
    self.assertIsNotNone(paragraph)

    section_properties = style_context.properties(section)
    paragraph_properties = style_context.properties(paragraph, inherited_visible=section_properties.visible)
    self.assertFalse(section_properties.visible)
    self.assertEqual(section_properties.hidden_reason, "aria_hidden")
    self.assertFalse(paragraph_properties.visible)
    self.assertEqual(paragraph_properties.hidden_reason, "ancestor_hidden")

  def test_treats_common_hidden_class_names_as_hidden_without_stylesheet(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <body>
            <div class="isHidden">
              <span id="modal">secret</span>
            </div>
            <aside class="contentAside-isHidden">
              <span id="sidebar">hidden sidebar</span>
            </aside>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    modal = document.find_first("div")
    sidebar = document.find_first("aside")
    self.assertIsNotNone(modal)
    self.assertIsNotNone(sidebar)

    modal_properties = style_context.properties(modal)
    sidebar_properties = style_context.properties(sidebar)

    self.assertFalse(modal_properties.visible)
    self.assertEqual(modal_properties.hidden_reason, "hidden_class")
    self.assertFalse(sidebar_properties.visible)
    self.assertEqual(sidebar_properties.hidden_reason, "hidden_class")

  def test_treats_text_rich_splide_container_as_visible_despite_initial_visibility_hidden(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              .splide { visibility: hidden; display: flex; }
            </style>
          </head>
          <body>
            <div class="splide topics-slide">
              <article>
                This slider already contains readable fallback content for multiple cards.
              </article>
            </div>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    splide = document.find_first("div")
    self.assertIsNotNone(splide)

    properties = style_context.properties(splide)

    self.assertTrue(properties.visible)
    self.assertIsNone(properties.hidden_reason)

  def test_treats_zero_height_overflow_auto_container_as_hidden(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              #sidebar { height: 0; overflow: auto; }
            </style>
          </head>
          <body>
            <aside id="sidebar">
              <p>Collapsed menu content</p>
            </aside>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    sidebar = document.find_first("aside")
    paragraph = document.find_first("p")
    self.assertIsNotNone(sidebar)
    self.assertIsNotNone(paragraph)

    sidebar_properties = style_context.properties(sidebar)
    paragraph_properties = style_context.properties(
      paragraph,
      inherited_visible=sidebar_properties.visible,
    )

    self.assertFalse(sidebar_properties.visible)
    self.assertEqual(sidebar_properties.hidden_reason, "zero_height_clipped")
    self.assertFalse(paragraph_properties.visible)
    self.assertEqual(paragraph_properties.hidden_reason, "ancestor_hidden")

  def test_tracks_width_and_flex_properties(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <body>
            <div style="display:flex">
              <section id="left" style="width:55%">Left</section>
              <aside id="right" style="flex: 0 0 45%">Right</aside>
            </div>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    left = document.find_first("section")
    right = document.find_first("aside")
    self.assertIsNotNone(left)
    self.assertIsNotNone(right)

    left_properties = style_context.properties(left)
    right_properties = style_context.properties(right)

    self.assertEqual(left_properties.width, "55%")
    self.assertEqual(right_properties.flex, "0 0 45%")

  def test_tracks_text_align_property(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <body>
            <div id="banner" style="text-align:center">Welcome</div>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    banner = document.find_first("div")
    self.assertIsNotNone(banner)

    properties = style_context.properties(banner)

    self.assertEqual(properties.text_align, "center")

  def test_matches_not_class_selector(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              body { text-align: center; }
              body:not(.writingDirection-vertical) p { text-align: left; }
            </style>
          </head>
          <body class="writingDirection-horizontal">
            <p>Hello</p>
          </body>
        </html>
        """,
      )
    )

    style_context = build_style_context(document, viewport_columns=80)
    paragraph = document.find_first("p")
    self.assertIsNotNone(paragraph)

    properties = style_context.properties(paragraph)

    self.assertEqual(properties.text_align, "left")

  def test_supports_root_custom_properties_in_computed_styles(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <head>
            <style>
              :root { --size-breakpoint-md: 769px; }
              main { display: grid; }
            </style>
          </head>
          <body>
            <main id="content">Body</main>
          </body>
        </html>
        """,
      )
    )

    html = document.find_first("html")
    main = document.find_first("main")
    self.assertIsNotNone(html)
    self.assertIsNotNone(main)

    root_declarations = computed_style_declarations(document, html, viewport_columns=80)
    main_declarations = computed_style_declarations(document, main, viewport_columns=80)

    self.assertEqual(root_declarations.get("--size-breakpoint-md"), "769px")
    self.assertEqual(main_declarations.get("--size-breakpoint-md"), "769px")

  def test_matches_escaped_tailwind_style_class_names(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content=r"""
        <html>
          <head>
            <style>
              .hidden { display: none; }
              @media (min-width: 1024px) {
                .lg\:block { display: block; }
              }
            </style>
          </head>
          <body>
            <aside class="hidden lg:block">Left pane</aside>
          </body>
        </html>
        """,
      )
    )

    aside = next(
      child
      for child in document.body.children
      if isinstance(child, ElementNode) and child.tag == "aside"
    )
    narrow = build_style_context(document, viewport_columns=80)
    wide = build_style_context(document, viewport_columns=160)

    self.assertFalse(narrow.properties(aside).visible)
    self.assertEqual(wide.properties(aside).display, "block")
    self.assertTrue(wide.properties(aside).visible)

  @patch("tweb.css.fetch_resource")
  def test_reuses_fresh_external_stylesheet_cache_across_style_contexts(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/styles/site.css",
      content=".headline { font-weight: bold; }",
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )
    document = parse_document(
      Resource(
        source="https://example.com/article",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">Hello</h1></body>
        </html>
        """,
      )
    )

    first = build_style_context(document, viewport_columns=80)
    second = build_style_context(document, viewport_columns=80)
    heading = document.find_first("h1")
    self.assertIsNotNone(heading)

    self.assertEqual(first.properties(heading).font_weight, "bold")
    self.assertEqual(second.properties(heading).font_weight, "bold")
    self.assertEqual(mock_fetch_resource.call_count, 1)

  @patch("tweb.css.fetch_resource")
  def test_applies_preloaded_stylesheet_before_link_load_event(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/styles/app.css",
      content=".calendar-popup { display: none; }",
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )
    document = parse_document(
      Resource(
        source="https://example.com/app",
        content="""
        <html>
          <head>
            <link rel="preload" as="style" href="/styles/app.css"
                  onload="this.onload=null;this.rel='stylesheet'">
          </head>
          <body><div class="calendar-popup">Hidden calendar</div></body>
        </html>
        """,
      )
    )

    context = build_style_context(document, viewport_columns=80)
    popup = document.find_first("div")
    self.assertIsNotNone(popup)

    self.assertFalse(context.properties(popup).visible)
    mock_fetch_resource.assert_called_once()

  @patch("tweb.css.time.monotonic", side_effect=[100.0, 101.0, 101.0])
  @patch("tweb.css.fetch_resource")
  def test_revalidates_external_stylesheet_cache_with_304(
    self,
    mock_fetch_resource: Mock,
    _mock_monotonic: Mock,
  ) -> None:
    mock_fetch_resource.side_effect = [
      Resource(
        source="https://example.com/styles/site.css",
        content=".headline { font-weight: bold; }",
        headers={"Cache-Control": "max-age=0", "ETag": '"v1"'},
        status_code=200,
      ),
      Resource(
        source="https://example.com/styles/site.css",
        content="",
        headers={"Cache-Control": "max-age=0", "ETag": '"v1"'},
        status_code=304,
      ),
    ]
    document = parse_document(
      Resource(
        source="https://example.com/article",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">Hello</h1></body>
        </html>
        """,
      )
    )

    first = build_style_context(document, viewport_columns=80)
    second = build_style_context(document, viewport_columns=80)
    heading = document.find_first("h1")
    self.assertIsNotNone(heading)

    self.assertEqual(first.properties(heading).font_weight, "bold")
    self.assertEqual(second.properties(heading).font_weight, "bold")
    self.assertEqual(mock_fetch_resource.call_count, 2)
    self.assertEqual(
      mock_fetch_resource.call_args_list[1].kwargs["request_headers"],
      {"If-None-Match": '"v1"'},
    )

  @patch("tweb.css.fetch_resource")
  def test_reuses_external_stylesheet_cache_across_pages_with_same_session(self, mock_fetch_resource: Mock) -> None:
    session = create_session()
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/styles/site.css",
      content=".headline { font-weight: bold; }",
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )
    first = parse_document(
      Resource(
        source="https://example.com/topic/one",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">One</h1></body>
        </html>
        """,
      )
    )
    second = parse_document(
      Resource(
        source="https://example.com/topic/two",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">Two</h1></body>
        </html>
        """,
      )
    )

    try:
      first_context = build_style_context(first, viewport_columns=80, session=session)
      second_context = build_style_context(second, viewport_columns=80, session=session)
      self.assertEqual(first_context.properties(first.find_first("h1")).font_weight, "bold")
      self.assertEqual(second_context.properties(second.find_first("h1")).font_weight, "bold")
      self.assertEqual(mock_fetch_resource.call_count, 1)
    finally:
      session.close()

  @patch("tweb.css.fetch_resource")
  def test_reuses_external_stylesheet_cache_across_sessions_without_vary(self, mock_fetch_resource: Mock) -> None:
    first_session = create_session({"sessionid": "one"})
    second_session = create_session({"sessionid": "two"})
    mock_fetch_resource.return_value = Resource(
      source="https://example.com/styles/site.css",
      content=".headline { font-weight: bold; }",
      headers={"Cache-Control": "max-age=60"},
      status_code=200,
    )
    first = parse_document(
      Resource(
        source="https://example.com/topic/one",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">One</h1></body>
        </html>
        """,
      )
    )
    second = parse_document(
      Resource(
        source="https://example.com/topic/two",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">Two</h1></body>
        </html>
        """,
      )
    )

    try:
      first_context = build_style_context(first, viewport_columns=80, session=first_session)
      second_context = build_style_context(second, viewport_columns=80, session=second_session)
      self.assertEqual(first_context.properties(first.find_first("h1")).font_weight, "bold")
      self.assertEqual(second_context.properties(second.find_first("h1")).font_weight, "bold")
      self.assertEqual(mock_fetch_resource.call_count, 1)
    finally:
      first_session.close()
      second_session.close()

  @patch("tweb.css.fetch_resource")
  def test_splits_external_stylesheet_cache_when_response_varies_on_cookie(self, mock_fetch_resource: Mock) -> None:
    first_session = create_session({"sessionid": "one"})
    second_session = create_session({"sessionid": "two"})
    mock_fetch_resource.side_effect = [
      Resource(
        source="https://example.com/styles/site.css",
        content=".headline { font-weight: bold; }",
        headers={"Cache-Control": "max-age=60", "Vary": "Cookie"},
        status_code=200,
      ),
      Resource(
        source="https://example.com/styles/site.css",
        content=".headline { font-style: italic; }",
        headers={"Cache-Control": "max-age=60", "Vary": "Cookie"},
        status_code=200,
      ),
    ]
    first = parse_document(
      Resource(
        source="https://example.com/topic/one",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">One</h1></body>
        </html>
        """,
      )
    )
    second = parse_document(
      Resource(
        source="https://example.com/topic/two",
        content="""
        <html>
          <head><link rel="stylesheet" href="/styles/site.css"></head>
          <body><h1 class="headline">Two</h1></body>
        </html>
        """,
      )
    )

    try:
      first_context = build_style_context(first, viewport_columns=80, session=first_session)
      second_context = build_style_context(second, viewport_columns=80, session=second_session)
      self.assertEqual(first_context.properties(first.find_first("h1")).font_weight, "bold")
      self.assertEqual(second_context.properties(second.find_first("h1")).font_style, "italic")
      self.assertEqual(mock_fetch_resource.call_count, 2)
    finally:
      first_session.close()
      second_session.close()

  def test_matches_tailwind_arbitrary_value_grid_class_names(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content=r"""
        <html>
          <head>
            <style>
              @media (min-width: 1024px) {
                .lg\:grid { display: grid; }
                .lg\:grid-cols-\[202px_minmax\(0\2c 1fr\)\] {
                  grid-template-columns: 202px minmax(0,1fr);
                }
              }
            </style>
          </head>
          <body>
            <div class="lg:grid lg:grid-cols-[202px_minmax(0,1fr)]">
              <aside>Left pane</aside>
              <main>Main content</main>
            </div>
          </body>
        </html>
        """,
      )
    )

    container = document.find_first("div")
    self.assertIsNotNone(container)
    wide = build_style_context(document, viewport_columns=160)
    properties = wide.properties(container)

    self.assertEqual(properties.display, "grid")
    self.assertEqual(properties.grid_template_columns, "202px minmax(0,1fr)")


if __name__ == "__main__":
  unittest.main()
