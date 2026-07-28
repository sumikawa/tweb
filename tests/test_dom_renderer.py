from __future__ import annotations

from pathlib import Path
import unittest

from tweb.fetcher import Resource, fetch_resource
from tweb.parser import parse_document
from tweb.renderers.dom import render_dom


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample.html"
CSS_VISIBILITY = ROOT / "tests" / "fixtures" / "css_visibility.html"
CSS_EMPHASIS = ROOT / "tests" / "fixtures" / "css_emphasis.html"
CSS_DESCENDANTS = ROOT / "tests" / "fixtures" / "css_descendants.html"
CSS_FLEX = ROOT / "tests" / "fixtures" / "css_flex.html"
CSS_EXTERNAL_GRID = ROOT / "tests" / "fixtures" / "css_external_grid.html"


class DomRendererTest(unittest.TestCase):
  def test_renders_compact_tree(self) -> None:
    document = parse_document(fetch_resource(str(SAMPLE)))

    output = render_dom(document)

    self.assertIn("#document", output)
    self.assertIn('- <main>', output)
    self.assertIn('- <a href="https://example.com/docs"> text="the documentation"', output)

  def test_applies_max_depth(self) -> None:
    document = parse_document(fetch_resource(str(SAMPLE)))

    output = render_dom(document, max_depth=1)

    self.assertIn("... 5 child nodes", output)
    self.assertIn("... 3 child nodes", output)

  def test_summary_includes_descendant_text_for_collapsed_main(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content="""
        <html>
          <body>
            <main id="main-content">
              <section>
                <h2>Hydration Data</h2>
                <p>Visible descendant text</p>
              </section>
            </main>
          </body>
        </html>
        """,
      )
    )

    output = render_dom(document, max_depth=2)

    self.assertIn(
      '- <main id="main-content"> text="Hydration Data Visible descendant text"',
      output,
    )

  def test_summary_mode_does_not_truncate_title_attrs_or_text(self) -> None:
    long_title = "Long title " + ("x" * 80)
    long_class = "hero-" + ("y" * 80)
    long_text = "Visible text " + ("z" * 80)
    document = parse_document(
      Resource(
        source="inline",
        content=f"""
        <html>
          <head>
            <title>{long_title}</title>
          </head>
          <body>
            <main class="{long_class}">
              <p>{long_text}</p>
            </main>
          </body>
        </html>
        """,
      )
    )

    output = render_dom(document)

    self.assertIn(f'title="{long_title}"', output)
    self.assertIn(f'class="{long_class}"', output)
    self.assertIn(f'text="{long_text}"', output)

  def test_skips_script_body_by_default(self) -> None:
    document = parse_document(
      fetch_resource(str(ROOT / "tests" / "fixtures" / "scripted.html"))
    )

    output = render_dom(document)

    self.assertIn("- <script> ...", output)
    self.assertNotIn("console.log", output)

  def test_renders_ai_tree_with_full_attrs_and_text(self) -> None:
    document = parse_document(fetch_resource(str(SAMPLE)))

    output = render_dom(document, variant="ai")

    self.assertIn("type=element tag=html parent=document", output)
    self.assertIn(
      'attrs={"href": "https://example.com/docs"}',
      output,
    )
    self.assertIn(
      'type=text parent=',
      output,
    )
    self.assertIn('text="the documentation"', output)

  def test_ai_mode_marks_skipped_script_nodes(self) -> None:
    document = parse_document(
      fetch_resource(str(ROOT / "tests" / "fixtures" / "scripted.html"))
    )

    output = render_dom(document, variant="ai")

    self.assertIn("tag=script", output)
    self.assertIn("skipped=true", output)

  def test_ai_mode_reports_visibility(self) -> None:
    document = parse_document(fetch_resource(str(CSS_VISIBILITY)))

    output = render_dom(document, variant="ai", viewport_columns=80)

    self.assertIn("visible=false hidden_reason=hidden_attr", output)
    self.assertIn("visible=false hidden_reason=display_none", output)
    self.assertIn('visibility="hidden"', output)

  def test_ai_mode_reports_basic_text_styles(self) -> None:
    document = parse_document(fetch_resource(str(CSS_EMPHASIS)))

    output = render_dom(document, variant="ai")

    self.assertIn('font_weight="bold"', output)
    self.assertIn('font_style="italic"', output)
    self.assertIn('text_decoration="line-through"', output)
    self.assertIn('text_decoration="underline"', output)

  def test_ai_mode_reports_descendant_selector_styles(self) -> None:
    document = parse_document(fetch_resource(str(CSS_DESCENDANTS)))

    output = render_dom(document, variant="ai")

    self.assertIn('attrs={"class": "desc-bold"} visible=true font_weight="bold"', output)
    self.assertIn('attrs={"class": "caption-text"} visible=true font_style="italic"', output)

  def test_ai_mode_reports_child_selector_styles_only_for_direct_children(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content="""
        <html>
          <head>
            <style>
              main > p { font-weight: bold; }
            </style>
          </head>
          <body>
            <main>
              <p id="direct">Direct child</p>
              <section><p id="nested">Nested child</p></section>
            </main>
          </body>
        </html>
        """,
      )
    )

    output = render_dom(document, variant="ai")

    self.assertIn('attrs={"id": "direct"} visible=true font_weight="bold"', output)
    self.assertIn('attrs={"id": "nested"} visible=true', output)
    self.assertNotIn('attrs={"id": "nested"} visible=true font_weight="bold"', output)

  def test_ai_mode_reports_flex_properties(self) -> None:
    document = parse_document(fetch_resource(str(CSS_FLEX)))

    output = render_dom(document, variant="ai")

    self.assertIn('attrs={"class": "menu"} visible=true display="flex"', output)
    self.assertIn(
      'attrs={"class": "stack"} visible=true display="flex" flex_direction="column"',
      output,
    )
    self.assertIn('attrs={"class": "label"} visible=true display="inline-flex"', output)

  def test_ai_mode_reports_external_grid_properties(self) -> None:
    document = parse_document(fetch_resource(str(CSS_EXTERNAL_GRID)))

    output = render_dom(document, variant="ai", viewport_columns=80)

    self.assertIn(
      'attrs={"class": "layout"} visible=true display="grid" grid_template_columns="minmax(0, 1fr) 160px"',
      output,
    )
    self.assertIn('attrs={"class": "sidebar"} visible=true', output)

  def test_defaults_to_desktop_viewport_for_visibility(self) -> None:
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

    default_output = render_dom(document, variant="ai")
    narrow_output = render_dom(document, variant="ai", viewport_columns=80)

    self.assertIn('attrs={"class": "hidden lg:block"} visible=true display="block"', default_output)
    self.assertIn('attrs={"class": "hidden lg:block"} visible=false hidden_reason=display_none', narrow_output)


if __name__ == "__main__":
  unittest.main()
