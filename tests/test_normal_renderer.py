from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import tweb.renderers.normal as normal_module
from tweb import TWebDocument, fetch_resource, parse_document
from tweb.dom import ElementNode
from tweb.fetcher import Resource
from tweb.renderers.normal import (
  ANSI_BOLD,
  ANSI_BOLD_RESET,
  ANSI_ESCAPE_RE,
  _display_width,
  collect_two_pane_targets,
  collect_visible_links,
  find_main_content_root,
  render_normal,
  render_normal_subtree_with_metadata,
  render_normal_with_metadata,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample.html"
CSS_VISIBILITY = ROOT / "tests" / "fixtures" / "css_visibility.html"
DEFINITION_LIST = ROOT / "tests" / "fixtures" / "definition_list.html"
SEMANTIC_BLOCKS = ROOT / "tests" / "fixtures" / "semantic_blocks.html"
CSS_EMPHASIS = ROOT / "tests" / "fixtures" / "css_emphasis.html"
CSS_DESCENDANTS = ROOT / "tests" / "fixtures" / "css_descendants.html"
CSS_FLEX = ROOT / "tests" / "fixtures" / "css_flex.html"
CSS_EXTERNAL_GRID = ROOT / "tests" / "fixtures" / "css_external_grid.html"
DROPDOWN = ROOT / "tests" / "fixtures" / "dropdown.html"
FORM = ROOT / "tests" / "fixtures" / "form.html"


class NormalRendererTest(unittest.TestCase):
  def test_default_link_style_hides_link_destinations(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(SAMPLE))))

    output = render_normal(document.document, width=80)

    self.assertIn(f"# {ANSI_BOLD}Welcome to tweb{ANSI_BOLD_RESET}", output)
    self.assertIn("- Normal mode renders readable text.", output)
    self.assertIn("the documentation", output)
    self.assertNotIn("[1]", output)
    self.assertNotIn("https://example.com/docs", output)
    self.assertNotIn("Links", output)

  def test_skips_hidden_inputs(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <form>
            <input type="hidden" name="token" value="x">
            <input type="text" name="q">
          </form>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertNotIn("[input:hidden", output)
    self.assertIn("[input:text q]", output)

  def test_inline_link_style_renders_urls_in_place(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(SAMPLE))))

    output = render_normal(document.document, width=80, link_style="inline")

    self.assertIn("the documentation (https://example.com/docs)", output)
    self.assertNotIn("Links", output)

  def test_none_link_style_hides_link_destinations(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(SAMPLE))))

    output = render_normal(document.document, width=80, link_style="none")

    self.assertIn("the documentation", output)
    self.assertNotIn("[1]", output)
    self.assertNotIn("https://example.com/docs", output)
    self.assertNotIn("Links", output)

  def test_uses_accessible_labels_for_empty_links_and_buttons(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <a href="https://example.com/profile" aria-label="Profile link"></a>
          <button title="Follow creator"></button>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("Profile link", output)
    self.assertIn("(Follow creator)", output)

  def test_uses_descendant_accessible_label_for_icon_only_button(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <button><svg aria-label="Like"></svg></button>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("(Like)", output)

  def test_skips_duplicate_accessible_label_for_overlay_card_link(self) -> None:
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

    output = render_normal(parse_document(resource), width=80)

    self.assertEqual(output.count("Card title"), 1)
    self.assertIn("Author name", output)

  def test_skips_empty_fragment_anchor_inside_heading(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <h3>
            <span id="macos-15-limitations" class="fragment"></span>
            <a href="#macos-15-limitations"><span class="fa fa-link"></span></a>
            macOS 15での制限事項
          </h3>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80, link_style="none")

    self.assertIn("macOS 15での制限事項", output)
    self.assertNotIn("#macos-15-limitations", output)

  def test_collect_visible_links_uses_rendered_anchor_text(self) -> None:
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

    links = collect_visible_links(parse_document(resource), width=80)

    self.assertEqual(links, [("« prev", "/prev"), ("next »", "/next")])

  def test_collect_visible_links_uses_accessible_label_for_overlay_card_link(self) -> None:
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

    links = collect_visible_links(parse_document(resource), width=80)

    self.assertEqual(links, [("Card title", "https://example.com/post")])

  def test_collect_visible_links_skips_document_title_render_path(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <title>Document title</title>
        </head>
        <body>
          <main>
            <a href="/docs">Docs</a>
          </main>
        </body>
      </html>
      """,
    )

    with patch("tweb.renderers.normal.render_normal_with_metadata", side_effect=AssertionError("full-document render should not be used")):
      links = collect_visible_links(parse_document(resource), width=80)

    self.assertEqual(links, [("Docs", "/docs")])

  def test_find_main_content_root_prefers_main_then_article_then_body(self) -> None:
    with_main = parse_document(Resource(
      source="inline",
      content="""
      <html>
        <body>
          <article>Article body</article>
          <main>Main body</main>
        </body>
      </html>
      """,
    ))
    main_root = find_main_content_root(with_main)
    self.assertIsNotNone(main_root)
    assert main_root is not None
    self.assertEqual(main_root.tag, "main")

    with_article = parse_document(Resource(
      source="inline",
      content="""
      <html>
        <body>
          <article>Article body</article>
        </body>
      </html>
      """,
    ))
    article_root = find_main_content_root(with_article)
    self.assertIsNotNone(article_root)
    assert article_root is not None
    self.assertEqual(article_root.tag, "article")

    with_body_only = parse_document(Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div>Body text</div>
        </body>
      </html>
      """,
    ))
    body_root = find_main_content_root(with_body_only)
    self.assertIsNotNone(body_root)
    assert body_root is not None
    self.assertEqual(body_root.tag, "body")

  def test_render_normal_subtree_with_metadata_can_skip_control_metadata(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main>
            <a href="/docs">Docs</a>
            <form>
              <input type="text" name="q" value="hello">
              <button>Search</button>
            </form>
          </main>
        </body>
      </html>
      """,
    )
    document = parse_document(resource)
    main = document.body.find_first("main")
    self.assertIsNotNone(main)
    assert main is not None

    result = render_normal_subtree_with_metadata(
      document,
      main,
      width=80,
      link_style="none",
      text_styles=False,
      include_title=False,
      include_control_metadata=False,
    )

    self.assertEqual([span.href for span in result.link_spans], ["/docs"])
    self.assertEqual(result.control_spans, ())

  def test_render_normal_with_metadata_preserves_single_character_link_span(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <a href="https://example.com/post">i</a>
          <p>wikipedia</p>
        </body>
      </html>
      """,
    )

    result = render_normal_with_metadata(parse_document(resource), width=80, link_style="none", text_styles=False)

    self.assertEqual(len(result.link_spans), 1)
    span = result.link_spans[0]
    self.assertEqual(result.text[span.start:span.end], "i")
    self.assertEqual(span.href, "https://example.com/post")

  def test_join_inline_parts_does_not_insert_space_after_opening_bracket(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p><span>[</span><a href="https://example.com/edit">編集</a><span>]</span></p>
          <p><span>[</span><a href="https://example.com/note">8</a><span>]</span></p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80, link_style="none", text_styles=False)

    self.assertIn("[編集]", output)
    self.assertIn("[8]", output)
    self.assertNotIn("[ 編集]", output)
    self.assertNotIn("[ 8]", output)

  def test_wikipedia_heading_keeps_edit_link_on_same_line(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div class="mw-heading mw-heading3">
            <h3 id="history"><span class="mw-headline">歴史</span></h3>
            <span class="mw-editsection">
              <span class="mw-editsection-bracket">[</span>
              <a href="/w/index.php?title=FreeBSD&action=edit&section=3">編集</a>
              <span class="mw-editsection-bracket">]</span>
            </span>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80, link_style="none", text_styles=False)

    self.assertIn("### 歴史 [編集]", output)
    self.assertNotIn("### 歴史\n", output)
    self.assertNotIn("\n[編集]", output)

  def test_collect_two_pane_targets_skips_single_column_article_without_layout_hints(self) -> None:
    resource = Resource(
      source="https://example.com/article",
      content="""
      <html>
        <body>
          <article>
            <h2>Overview</h2>
            <p>Paragraph one.</p>
            <p>Paragraph two.</p>
          </article>
        </body>
      </html>
      """,
    )

    with patch("tweb.renderers.normal.build_style_context", side_effect=AssertionError("style context should not be built")):
      groups = collect_two_pane_targets(parse_document(resource), width=80)

    self.assertEqual(groups, [])

  def test_label_lookup_indexes_are_built_once_per_render_state(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <span id="ship-label">Ship</span>
          <button id="ship" aria-labelledby="ship-label"></button>
          <label for="query">Query</label>
          <input id="query" type="text" name="q">
        </body>
      </html>
      """,
    )
    document = parse_document(resource)
    state = normal_module.RenderState(document=document, width=80, text_styles=False)
    root = document.root
    label_node = document.find_first("label")
    span_node = document.find_first("span")
    self.assertIsNotNone(root)
    self.assertIsNotNone(label_node)
    self.assertIsNotNone(span_node)
    assert root is not None
    assert label_node is not None
    assert span_node is not None

    original_iter_nodes = ElementNode.iter_nodes
    iter_node_calls = 0

    def counting_iter_nodes(node: ElementNode):
      nonlocal iter_node_calls
      iter_node_calls += 1
      yield from original_iter_nodes(node)

    with patch.object(normal_module.ElementNode, "iter_nodes", counting_iter_nodes):
      self.assertEqual(
        normal_module._labelledby_target_control_metadata(state, span_node),
        ("ship", "Ship", "button"),
      )
      self.assertEqual(
        normal_module._labelledby_target_control_metadata(state, span_node),
        ("ship", "Ship", "button"),
      )
      self.assertEqual(
        normal_module._label_target_control_metadata(state, label_node),
        ("query", "Query", "text"),
      )
      self.assertEqual(
        normal_module._label_target_control_metadata(state, label_node),
        ("query", "Query", "text"),
      )

    self.assertEqual(iter_node_calls, 2)

  def test_render_normal_skips_full_style_context_for_rich_static_page(self) -> None:
    links = "".join(
      (
        f'<a href="/item-{index}">Visible encyclopedia item {index} with enough descriptive text '
        "to keep the page readable before any stylesheet download.</a>"
      )
      for index in range(520)
    )
    paragraphs = "".join(
      f"<p>Readable article paragraph {index} with substantial static body text already present in HTML.</p>"
      for index in range(80)
    )
    resource = Resource(
      source="https://example.com/wiki",
      content=f"""
      <html>
        <head>
          <link rel="stylesheet" href="/site.css">
          <link rel="stylesheet" href="/theme.css">
        </head>
        <body>
          <main>{paragraphs}{links}</main>
        </body>
      </html>
      """,
    )

    with patch("tweb.renderers.normal.build_style_context", side_effect=AssertionError("full style context should be skipped")):
      output = render_normal(parse_document(resource), width=80, text_styles=False)

    self.assertIn("Readable article paragraph 0", output)
    self.assertIn("Visible encyclopedia item 0", output)

  def test_render_normal_skips_full_style_context_for_medium_link_count_static_article(self) -> None:
    links = "".join(
      (
        f'<a href="/item-{index}">Visible encyclopedia item {index} with enough descriptive text '
        "to keep the page readable before any stylesheet download.</a>"
      )
      for index in range(420)
    )
    paragraphs = "".join(
      f"<p>Readable article paragraph {index} with substantial static body text already present in HTML.</p>"
      for index in range(80)
    )
    resource = Resource(
      source="https://example.com/wiki-medium-links",
      content=f"""
      <html>
        <head>
          <link rel="stylesheet" href="/site.css">
          <link rel="stylesheet" href="/theme.css">
        </head>
        <body>
          <main>{paragraphs}{links}</main>
        </body>
      </html>
      """,
    )

    with patch("tweb.renderers.normal.build_style_context", side_effect=AssertionError("full style context should be skipped")):
      output = render_normal(parse_document(resource), width=80, text_styles=False)

    self.assertIn("Readable article paragraph 0", output)
    self.assertIn("Visible encyclopedia item 0", output)

  def test_render_normal_subtree_with_metadata_preserves_link_and_control_spans(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <section>
            <a href="/docs">Docs</a>
            <form>
              <input type="text" name="q" value="hello">
              <button>Search</button>
            </form>
          </section>
        </body>
      </html>
      """,
    )
    document = parse_document(resource)
    section = next(child for child in document.body.children if isinstance(child, ElementNode))

    result = render_normal_subtree_with_metadata(
      document,
      section,
      width=80,
      link_style="none",
      text_styles=False,
      include_title=False,
    )

    self.assertEqual(len(result.link_spans), 1)
    self.assertEqual(len(result.control_spans), 2)
    self.assertEqual(result.text[result.link_spans[0].start:result.link_spans[0].end], "Docs")
    self.assertEqual(result.text[result.control_spans[0].start:result.control_spans[0].end], "[input:text q=hello]")
    self.assertEqual(result.text[result.control_spans[1].start:result.control_spans[1].end], "(Search)")

  def test_wraps_long_japanese_list_item_without_lonely_dash_line(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <ul>
            <li>山行日記「塔ノ岳～追いつかないトイレ事情」</li>
          </ul>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=29, text_styles=False)

    self.assertEqual(
      output,
      "- 山行日記「塔ノ岳～追いつか\n"
      "  ないトイレ事情」",
    )

  def test_wraps_mixed_script_text_without_wasting_available_columns(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p>問題はUGOS Proだった。ファイルを転送しようとすると、途中でハングする。</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80, text_styles=False)

    self.assertIn("問題はUGOS Proだった。", output)
    self.assertNotIn("UGOS\nPro", output)
    self.assertNotIn("Pro\nだった。", output)

  def test_wraps_ascii_followed_by_japanese_without_early_line_break(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p>10GbEと高負荷耐性を看板にしている機械が、コピーひとつでこうなる。ベンチマークで速度を測るどころの話じゃない。</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80, text_styles=False)

    self.assertIn("10GbEと高負荷耐性", output)
    self.assertNotIn("10GbE\nと", output)

  def test_splits_mixed_ascii_token_when_it_would_otherwise_overflow(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p>AWS Skill Builderで提供されている Microcredential をまとめる。</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=50, text_styles=False)

    for line in output.splitlines():
      self.assertLessEqual(_display_width(line), 50)
    narrower = render_normal(parse_document(resource), width=51, text_styles=False)
    for line in narrower.splitlines():
      self.assertLessEqual(_display_width(line), 51)
    self.assertIn("Microcredential", output)

  def test_avoids_starting_a_line_with_japanese_punctuation(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p>あいうえ、お</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=8, text_styles=False)

    self.assertEqual(output, "あいう\nえ、お")

  def test_renders_visible_iframe_as_frame_link(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <iframe
            title="reCAPTCHA"
            src="https://www.google.com/recaptcha/enterprise/anchor?ar=1"
          ></iframe>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn(
      "[frame: reCAPTCHA] (https://www.google.com/recaptcha/enterprise/anchor?ar=1)",
      output.replace("\n", ""),
    )

  def test_collect_visible_links_includes_iframe_src(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <iframe
            title="reCAPTCHA"
            src="https://www.google.com/recaptcha/enterprise/anchor?ar=1"
          ></iframe>
        </body>
      </html>
      """,
    )

    links = collect_visible_links(parse_document(resource), width=80)

    self.assertEqual(
      links,
      [("reCAPTCHA", "https://www.google.com/recaptcha/enterprise/anchor?ar=1")],
    )

  def test_can_disable_terminal_text_styles(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(SAMPLE))))

    output = render_normal(document.document, width=80, text_styles=False)

    self.assertIn("# Welcome to tweb", output)
    self.assertNotIn(ANSI_BOLD, output)
    self.assertNotIn(ANSI_BOLD_RESET, output)

  def test_hides_nodes_using_hidden_and_css_visibility(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(CSS_VISIBILITY))))

    narrow = render_normal(document.document, width=80, viewport_columns=80)
    wide = render_normal(document.document, width=120, viewport_columns=120)

    self.assertIn("Visible paragraph.", narrow)
    self.assertNotIn("Hidden attribute paragraph.", narrow)
    self.assertNotIn("Display none paragraph.", narrow)
    self.assertNotIn("Inline hidden paragraph.", narrow)
    self.assertNotIn("Hidden only in narrow viewport.", narrow)
    self.assertIn("Hidden only in wide viewport.", narrow)

    self.assertNotIn("Hidden only in wide viewport.", wide)
    self.assertIn("Hidden only in narrow viewport.", wide)

  def test_hides_common_hidden_class_containers_without_stylesheet(self) -> None:
    document = parse_document(
      Resource(
        source="memory",
        content="""
        <html>
          <body>
            <article>Visible story body</article>
            <div class="widget-displaySetting-modal isHidden">
              <h4>文字サイズ</h4>
              <label>小</label>
              <label>中</label>
              <label>大</label>
            </div>
          </body>
        </html>
        """,
      )
    )

    output = render_normal(document, width=80)

    self.assertIn("Visible story body", output)
    self.assertNotIn("文字サイズ", output)
    self.assertNotIn("小", output)
    self.assertNotIn("中", output)
    self.assertNotIn("大", output)

  def test_uses_desktop_viewport_for_normal_rendering_by_default(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            .sidebar { display: none; }
            @media (min-width: 1024px) {
              .sidebar { display: block; }
            }
          </style>
        </head>
        <body>
          <aside class="sidebar">Left pane</aside>
          <main>Main content</main>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)
    narrow_viewport = render_normal(parse_document(resource), width=80, viewport_columns=80)

    self.assertIn("Left pane", output)
    self.assertIn("Main content", output)
    self.assertNotIn("Left pane", narrow_viewport)

  def test_renders_definition_list_entries_as_separate_blocks(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(DEFINITION_LIST))))

    output = render_normal(document.document, width=80)

    self.assertIn("2026/05/28: Entry one", output)
    self.assertIn("2026/05/27: Entry two", output)
    self.assertIn("  First description.", output)
    self.assertRegex(output, r"2026/05/28: Entry one\s+First description\.")
    self.assertRegex(output, r"2026/05/27: Entry two\s+Second description\.")

  def test_renders_summary_figcaption_and_legend_without_paragraph_gaps(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(SEMANTIC_BLOCKS))))

    output = render_normal(document.document, width=80)

    self.assertRegex(output, r"Expandable heading\nDetail paragraph\.")
    self.assertRegex(output, r"\[Sample photo\]\n  Figure caption text\.")
    self.assertRegex(output, r"Search options\nChoose filters\.")

  def test_handles_block_children_inside_inline_context(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <span>
            Before
            <details open>
              <summary>Inline summary</summary>
              <p>Nested block text.</p>
            </details>
            After
          </span>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("Before Inline summary Nested block text. After", output)

  def test_renders_basic_css_emphasis(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(CSS_EMPHASIS))))

    output = render_normal(document.document, width=80)

    self.assertIn(f"{ANSI_BOLD}Bold text{ANSI_BOLD_RESET}", output)
    self.assertNotIn("**Bold text**", output)
    self.assertIn("_Italic text_", output)
    self.assertIn("~~Strike text~~", output)
    self.assertIn("[underline: Under text]", output)

  def test_preserves_newlines_inside_preformatted_blocks(self) -> None:
    resource = Resource(
      source="inline",
      content="<html><body><pre>\nLine one\nLine two\nLine three\n</pre></body></html>",
    )

    output = render_normal(parse_document(resource), width=10)

    self.assertIn("Line one\nLine two\nLine three", output)
    self.assertNotIn("\n\nLine one", output)

  def test_renders_structural_reply_wrappers_as_indented_nested_list_items(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <ol>
            <li class="comment-set">
              <ul class="comment-info">
                <li>1. Parent</li>
                <li>2026-07-27 18:32</li>
                <li>Parent body</li>
              </ul>
            </li>
            <li>
              <ul class="comment-reply-list">
                <li class="comment-set reply">
                  <ul class="comment-info">
                    <li>6. Reply</li>
                    <li>2026-07-27 18:42</li>
                    <li>&gt;&gt;1<br>Reply body</li>
                  </ul>
                </li>
                <li class="comment-set reply">
                  <ul class="comment-info">
                    <li>23. Reply</li>
                    <li>2026-07-27 20:24</li>
                    <li>Second reply body</li>
                  </ul>
                </li>
              </ul>
            </li>
          </ol>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80, text_styles=False)

    self.assertIn("- 1. Parent - 2026-07-27 18:32 - Parent body", output)
    self.assertIn("  - 6. Reply - 2026-07-27 18:42 - >>1\nReply body", output)
    self.assertIn("  - 23. Reply - 2026-07-27 20:24 - Second reply body", output)
    self.assertNotIn("- - 1. Parent", output)

  def test_preserves_preformatted_newlines_inside_row_flex_container(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <pre><a href="https://example.com/shop">おもてなしとりよし 横浜西口店</a>
神奈川県横浜市西区北幸1-1-13 Comfort178横浜駅前ビル 7F
045-322-3833</pre>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=76, link_style="none", text_styles=False)

    self.assertRegex(
      output,
      "おもてなしとりよし 横浜西口店\\n"
      "神奈川県横浜市西区北幸1-1-13 Comfort178横浜駅前ビル 7F\\n"
      "045-322-3833",
    )

  def test_treats_pre_as_block_inside_main_container(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main>
            <p>Before</p>
            <pre><a href="https://example.com/shop">おもてなしとりよし 横浜西口店</a>
神奈川県横浜市西区北幸1-1-13 Comfort178横浜駅前ビル 7F
045-322-3833</pre>
            <p>After</p>
          </main>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=76, link_style="none", text_styles=False)

    self.assertRegex(
      output,
      "Before\\n\\n"
      "おもてなしとりよし 横浜西口店\\n"
      "神奈川県横浜市西区北幸1-1-13 Comfort178横浜駅前ビル 7F\\n"
      "045-322-3833\\n\\n"
      "After",
    )

  def test_drops_single_leading_blank_line_from_pre_block(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main>
            <p>Before</p>
            <pre>
おもてなしとりよし 横浜西口店
神奈川県横浜市西区北幸1-1-13 Comfort178横浜駅前ビル 7F
045-322-3833
</pre>
          </main>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=76, link_style="none", text_styles=False)

    self.assertRegex(
      output,
      "Before\\n\\n"
      "おもてなしとりよし 横浜西口店\\n"
      "神奈川県横浜市西区北幸1-1-13 Comfort178横浜駅前ビル 7F\\n"
      "045-322-3833",
    )
    self.assertNotRegex(output, "Before\\n\\n\\nおもてなしとりよし")

  def test_renders_descendant_selector_styles(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(CSS_DESCENDANTS))))

    output = render_normal(document.document, width=80)

    self.assertIn(f"{ANSI_BOLD}Descendant bold{ANSI_BOLD_RESET}", output)
    self.assertNotIn("**Descendant bold**", output)
    self.assertIn("_Nested caption_", output)

  def test_renders_child_selector_styles_without_matching_nested_nodes(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            main > span { font-weight: bold; }
          </style>
        </head>
        <body>
          <main>
            <span>Direct child</span>
            <section><span>Nested child</span></section>
          </main>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn(f"{ANSI_BOLD}Direct child{ANSI_BOLD_RESET}", output)
    self.assertIn("Nested child", output)
    self.assertNotIn(f"{ANSI_BOLD}Nested child{ANSI_BOLD_RESET}", output)

  def test_renders_flex_rows_inline_and_columns_as_blocks(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(CSS_FLEX))))

    output = render_normal(document.document, width=80)

    self.assertIn("Home Docs About", output)
    self.assertRegex(output, r"Home Docs About\s+Alpha\s+Beta")
    self.assertIn("Status: Ready now", output)

  def test_renders_two_block_flex_children_as_columns(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div id="mp-left" style="width:55%">
              <h2>Left side</h2>
              <p>Alpha beta gamma delta epsilon zeta eta theta.</p>
              <p>Second left paragraph.</p>
            </div>
            <div id="mp-right" style="width:45%">
              <h2>Right side</h2>
              <p>Sidebar top.</p>
              <p>Sidebar bottom.</p>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=72)

    self.assertIn("Left side", output)
    self.assertIn("Right side", output)
    self.assertIn(" | ", output)
    separator_columns = set()
    for line in output.splitlines():
      clean = ANSI_ESCAPE_RE.sub("", line)
      if "|" in clean:
        separator_columns.add(clean.index("|"))
    self.assertEqual(len(separator_columns), 1)
    self.assertRegex(output, r"\n(?:\s+\|)?\n")
    self.assertIn("Second left paragraph.", output)
    self.assertIn("Sidebar bottom.", output)

  def test_preserves_dom_order_for_main_then_aside_flex_layout(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <section style="display:flex">
            <main style="width:70%">
              <p>Main content line.</p>
              <p>Second content line.</p>
            </main>
            <aside style="width:30%">
              <p>Right pane</p>
              <p>Recent articles</p>
            </aside>
          </section>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("Main content line.", output)
    self.assertIn("Right pane", output)
    self.assertRegex(output, r"Main content line\.\s+\|\s+Right pane")

  def test_biases_auto_sidebar_narrower_than_fill_width_main_in_flex_layout(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <section>
              <p>(Like)</p>
              <p>(Stock)</p>
            </section>
            <div class="content-main" style="width:100%">
              <p>Main content line that should keep most of the available width.</p>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=70, text_styles=False)

    pipe_columns = {
      ANSI_ESCAPE_RE.sub("", line).index("|")
      for line in output.splitlines()
      if "|" in ANSI_ESCAPE_RE.sub("", line)
    }
    self.assertEqual(len(pipe_columns), 1)
    self.assertLess(next(iter(pipe_columns)), 24)
    self.assertIn("Main content line", output)

  def test_prefers_fixed_pixel_sidebar_width_for_primary_content_flex_layout(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <section class="article-body" style="width:calc(100% - 330px)">
              <p>Main content line that should keep most of the available width.</p>
              <p>Second content line that should still mostly belong to the article pane.</p>
            </section>
            <aside style="width:300px">
              <p>Author card</p>
              <p>Table of contents</p>
            </aside>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=100, text_styles=False)

    pipe_columns = {
      ANSI_ESCAPE_RE.sub("", line).index("|")
      for line in output.splitlines()
      if "|" in ANSI_ESCAPE_RE.sub("", line)
    }
    self.assertEqual(len(pipe_columns), 1)
    self.assertGreater(next(iter(pipe_columns)), 55)
    self.assertIn("Author card", output)
    self.assertIn("Main content line", output)

  def test_biases_nav_side_wider_in_ratio_free_footer_flex_layout(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div>
              <p>How developers code is here.</p>
              <p>© 2011-2026 Qiita Inc.</p>
            </div>
            <nav>
              <p>Guide & Help - About - Terms - Privacy - Guideline</p>
              <p>Official Shop - Company - About Us - Careers</p>
            </nav>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=70, text_styles=False)

    pipe_columns = {
      ANSI_ESCAPE_RE.sub("", line).index("|")
      for line in output.splitlines()
      if "|" in ANSI_ESCAPE_RE.sub("", line)
    }
    self.assertEqual(len(pipe_columns), 1)
    self.assertLess(next(iter(pipe_columns)), 26)
    self.assertIn("Guide & Help", output)

  def test_wraps_nested_right_pane_table_to_the_pane_width(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div style="width:20%">
              <p>(Like)</p>
              <p>(Stock)</p>
            </div>
            <main style="width:80%">
              <table>
                <tr><th>項目</th><th>内容</th></tr>
                <tr><td>形式</td><td>実際のAWS環境でのハンズオン（複数チャレンジ）</td></tr>
                <tr><td>合否判定</td><td>全チャレンジの達成度をもとに自動採点。終了後すぐに結果が表示される。</td></tr>
              </table>
            </main>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=70, text_styles=False)

    self.assertIn("(Like)", output)
    self.assertIn("項目", output)
    for line in output.splitlines():
      self.assertLessEqual(_display_width(ANSI_ESCAPE_RE.sub("", line)), 70)

  def test_collapses_two_column_flex_when_one_child_is_empty(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <div class="thumbnail"></div>
            <div class="body">
              <p>チーム&歴代王者が集結「芸人チャンピオン」チームがSnow Manと三つ巴対決!</p>
              <p>2026.7.10</p>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=40)

    self.assertIn("チーム&歴代王者が集結", output)
    self.assertIn("Snow Manと三つ巴対決!", output)
    self.assertNotIn(" | ", output)

  def test_row_flex_with_three_block_children_keeps_article_block_boundaries(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main style="display:flex">
            <section>
              <p>Alpha.</p>
              <h2>Section</h2>
              <p>Body.</p>
            </section>
            <aside>
              <p>Side</p>
            </aside>
            <div>
              <p>Meta</p>
            </div>
          </main>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=60, viewport_columns=160)

    self.assertEqual(
      output.splitlines(),
      ["Alpha.", "", f"## {ANSI_BOLD}Section{ANSI_BOLD_RESET}", "", "Body.", "", "Side", "", "Meta"],
    )

  def test_two_column_flex_ignores_statically_hidden_extra_child(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <main>
              <p>Main content line.</p>
            </main>
            <aside>
              <p>Right pane</p>
            </aside>
            <div style="display:none">Hidden utility drawer</div>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("Main content line.", output)
    self.assertIn("Right pane", output)
    self.assertIn(" | ", output)

  def test_two_column_flex_skips_visible_child_scan_when_structurally_not_two_columns(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:flex">
            <section><p>Left</p></section>
            <main><p>Main</p></main>
            <aside><p>Extra</p></aside>
          </div>
        </body>
      </html>
      """,
    )

    document = parse_document(resource)
    original_visible_element_children = normal_module._visible_element_children

    def wrapped_visible_element_children(node, state, inherited_visible):
      if node.tag == "div" and node.attrs.get("style") == "display:flex":
        raise AssertionError("structurally non-two-column flex container should return before visible child scan")
      return original_visible_element_children(node, state, inherited_visible)

    with patch("tweb.renderers.normal._visible_element_children", side_effect=wrapped_visible_element_children):
      output = render_normal(document, width=80)

    self.assertIn("Left", output)
    self.assertIn("Main", output)
    self.assertIn("Extra", output)

  def test_child_properties_reuses_render_state_cache(self) -> None:
    document = parse_document(
      Resource(
        source="inline",
        content="""
        <html>
          <body>
            <main>
              <section>Body</section>
            </main>
          </body>
        </html>
        """,
      )
    )
    section = document.body.find_first("section")
    self.assertIsNotNone(section)
    assert section is not None

    class FakeStyleContext:
      def __init__(self) -> None:
        self.calls = 0

      def properties(self, node, inherited_visible=True):
        del node, inherited_visible
        self.calls += 1
        return normal_module.StyleProperties(visible=True)

    style_context = FakeStyleContext()
    state = normal_module.RenderState(document=document, style_context=style_context)

    first = normal_module._child_properties(section, state, True)
    second = normal_module._child_properties(section, state, True)

    self.assertIsNotNone(first)
    self.assertIs(first, second)
    self.assertEqual(style_context.calls, 1)

  def test_renders_external_stylesheet_grid_as_two_columns(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(CSS_EXTERNAL_GRID))))

    narrow = render_normal(document.document, width=40, viewport_columns=40)
    wide = render_normal(document.document, width=80, viewport_columns=80)

    self.assertRegex(narrow, r"Second content line\.\s+Sidebar top\.")
    self.assertIn("Main content line.", wide)
    self.assertIn("Sidebar top.", wide)
    self.assertIn(" | ", wide)

  def test_renders_tailwind_arbitrary_value_grid_as_two_columns(self) -> None:
    resource = Resource(
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
            <aside>
              <p>Left pane</p>
              <p>Topic links</p>
            </aside>
            <main>
              <p>Main content line.</p>
              <p>Second content line.</p>
            </main>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("Left pane", output)
    self.assertIn("Main content line.", output)
    self.assertIn(" | ", output)

  def test_prefers_sidebar_left_when_grid_dom_order_is_main_then_aside(self) -> None:
    resource = Resource(
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
            <main id="main-content">
              <p>Main content line.</p>
            </main>
            <aside>
              <p>Left pane</p>
            </aside>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("Left pane", output)
    self.assertIn("Main content line.", output)
    self.assertRegex(output, r"Left pane\s+\|\s+Main content line\.")

  def test_ignores_react_comment_markers_inside_grid_layout(self) -> None:
    resource = Resource(
      source="inline",
      content=r"""
      <html>
        <body>
          <div style="display:grid; grid-template-columns:202px minmax(0,1fr);">
            <!--$-->
            <aside>
              <p>Left pane</p>
            </aside>
            <!--/$-->
            <main>
              <p>Main content</p>
            </main>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("Left pane", output)
    self.assertIn("Main content", output)
    self.assertIn(" | ", output)

  def test_renders_basic_table_with_header_separator(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <table>
            <caption>Release status</caption>
            <thead>
              <tr><th>Name</th><th>Status</th></tr>
            </thead>
            <tbody>
              <tr><td>Alpha</td><td>Ready</td></tr>
              <tr><td>Beta</td><td>Blocked</td></tr>
            </tbody>
          </table>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=32)

    self.assertIn("Release status", output)
    self.assertIn("Name  | Status", output)
    self.assertIn("----- | -------", output)
    self.assertIn("Alpha | Ready", output)
    self.assertIn("Beta  | Blocked", output)

  def test_wraps_table_cells_to_requested_width(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <table>
            <tr><th>Topic</th><th>Notes</th></tr>
            <tr>
              <td>Rendering</td>
              <td>Long status text that should wrap inside the second column.</td>
            </tr>
          </table>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=28)

    self.assertIn("Topic", output)
    self.assertIn("Rendering", output)
    self.assertIn("Long status", output)
    separator_columns = set()
    for line in output.splitlines():
      clean = ANSI_ESCAPE_RE.sub("", line)
      if "|" in clean:
        separator_columns.add(clean.index("|"))
    self.assertEqual(len(separator_columns), 1)

  def test_pads_missing_cells_in_short_rows(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <table>
            <tr><th>Key</th><th>Value</th></tr>
            <tr><td>A</td><td>1</td></tr>
            <tr><td>B</td></tr>
          </table>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=20)

    self.assertIn("A   | 1", output)
    self.assertIn("B   |", output)

  def test_renders_inline_block_table_as_grid(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div>
            <table style="display:inline-block">
              <tr><th>項目</th><th>従来のDocker</th><th>Apple Container</th></tr>
              <tr><td><strong>実行環境</strong></td><td>共有Linuxカーネル</td><td>個別の軽量Linux VM</td></tr>
            </table>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=60)

    self.assertIn("項目     | 従来のDocker", output)
    self.assertIn("-------- | -------------", output)
    self.assertIn("実行環境 | 共有Linux", output)
    self.assertIn("個別の軽量Linux", output)

  def test_centers_text_for_text_align_center_containers(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="text-align:center">
            Welcome to Wikipedia
            <p>the free encyclopedia</p>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=40)
    lines = [line for line in output.splitlines() if line.strip()]

    self.assertEqual(lines[0], "          Welcome to Wikipedia")
    self.assertEqual(lines[1], "         the free encyclopedia")

  def test_not_selector_can_override_centered_ancestor_alignment(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            body { text-align: center; }
            body:not(.writingDirection-vertical) p { text-align: left; }
          </style>
        </head>
        <body class="writingDirection-horizontal">
          <p>Welcome to Wikipedia</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=40)
    lines = [line for line in output.splitlines() if line.strip()]

    self.assertEqual(lines[0], "Welcome to Wikipedia")

  def test_inline_block_container_keeps_child_left_alignment(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="text-align:center">
            <div style="display:inline-block; text-align:left">
              <p>Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda.</p>
            </div>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=40)
    lines = [line for line in output.splitlines() if line.strip()]

    self.assertEqual(lines[0], "Alpha beta gamma delta epsilon zeta eta")
    self.assertEqual(lines[1], "theta iota kappa lambda.")

  def test_zero_margin_paragraphs_do_not_insert_blank_lines(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            p { margin: 0; }
          </style>
        </head>
        <body>
          <p>Alpha beta gamma.</p>
          <p>Delta epsilon zeta.</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=40)

    self.assertEqual(output.splitlines(), ["Alpha beta gamma.", "Delta epsilon zeta."])

  def test_default_paragraphs_still_insert_blank_lines(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p>Alpha beta gamma.</p>
          <p>Delta epsilon zeta.</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=40)

    self.assertEqual(output.splitlines(), ["Alpha beta gamma.", "", "Delta epsilon zeta."])

  def test_two_column_grid_preserves_blank_lines_around_headings(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            p { margin: 0; }
          </style>
        </head>
        <body>
          <div style="display:grid; grid-template-columns:24px minmax(0, 1fr);">
            <aside>
              <p>Side</p>
            </aside>
            <article>
              <p>Alpha.</p>
              <h2>Section</h2>
              <p>Body.</p>
              <h3>Subsection</h3>
              <p>More.</p>
            </article>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=60, viewport_columns=160)

    self.assertEqual(
      output.splitlines(),
      [
        "Side             | Alpha.",
        "",
        "                 | ## \x1b[1mSection\x1b[22m",
        "",
        "                 | Body.",
        "",
        "                 | ### \x1b[1mSubsection\x1b[22m",
        "",
        "                 | More.",
      ],
    )

  def test_keeps_grid_separator_aligned_after_sidebar_runs_out(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div style="display:grid; grid-template-columns:minmax(0, 1fr) 80px;">
            <div>
              <p>Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda.</p>
              <p>Second line stays on the left.</p>
            </div>
            <aside>
              <p>Side</p>
            </aside>
          </div>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=60)

    separator_columns = {
      line.index("|")
      for line in output.splitlines()
      if "|" in line
    }
    self.assertEqual(len(separator_columns), 1)

  def test_wraps_wide_text_to_requested_display_width(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p>日本語日本語日本語日本語日本語日本語日本語日本語日本語日本語</p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=20)

    for line in output.splitlines():
      if line.strip():
        self.assertLessEqual(_display_width(line), 20)

  def test_wraps_bold_text_without_counting_ansi_sequences(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p><span style="font-weight:bold">ABCDEFGHIJKLMNOPQRSTUVWXYZ</span></p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=10)

    for line in output.splitlines():
      if line.strip():
        self.assertLessEqual(_display_width(line), 10)

  def test_hides_unchecked_dropdown_content_until_toggled(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(DROPDOWN))))

    collapsed = render_normal(document.document, width=80)

    self.assertIn("[input:checkbox demo-menu-checkbox] Main menu", collapsed)
    self.assertIn("After menu.", collapsed)
    self.assertNotIn("One", collapsed)
    self.assertNotIn("Two", collapsed)

    self.assertTrue(document.toggle_checkbox("demo-menu-checkbox"))
    expanded = render_normal(document.document, width=80)

    self.assertIn("One", expanded)
    self.assertIn("Two", expanded)
    self.assertNotIn("[1]", expanded)

  def test_renders_form_values_and_controls(self) -> None:
    document = TWebDocument(parse_document(fetch_resource(str(FORM))))

    output = render_normal(document.document, width=80)
    normalized = output.replace("\n", "")

    self.assertIn("[input:text q=hello]", output)
    self.assertIn("[textarea notes=memo]", output)
    self.assertIn("[select", output)
    self.assertIn("category=Articles]", normalized)
    self.assertIn("[input:radio scope=title checked]", normalized)
    self.assertIn("[input:checkbox safe checked]", normalized)
    self.assertIn("(Search)", output)

  def test_renders_form_controls_even_when_css_makes_them_block_or_flex(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            textarea { display: flex; }
            button { display: block; }
          </style>
        </head>
        <body>
          <form action="/search" method="get">
            <textarea name="q" aria-label="検索"></textarea>
            <button type="submit">Google 検索</button>
          </form>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("[textarea q]", output)
    self.assertIn("(Google 検索)", output)

  def test_omits_src_values_from_image_labels_without_alt(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <button type="button">
            <img src="data:image/svg+xml;base64,PHN2Zz4KPC9zdmc+" />
          </button>
          <p><img src="https://example.com/image.png" /></p>
          <p><img src="data:image/png;base64,AAAA" /></p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80)

    self.assertIn("([image])", output)
    self.assertTrue(output.endswith("[image]"))
    self.assertNotIn("data:image", output)
    self.assertNotIn("https://example.com/image.png", output)

  def test_uses_image_alt_inside_link_when_image_becomes_block(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head>
          <style>
            img { display: block; }
          </style>
        </head>
        <body>
          <p>
            <a href="https://example.com/full.jpg">
              <img src="https://example.com/thumb.jpg" alt="Dinner photo" />
            </a>
          </p>
        </body>
      </html>
      """,
    )

    output = render_normal(parse_document(resource), width=80, link_style="none")

    self.assertIn("[Dinner photo]", output)
    self.assertNotIn("https://example.com/full.jpg", output)


if __name__ == "__main__":
  unittest.main()
