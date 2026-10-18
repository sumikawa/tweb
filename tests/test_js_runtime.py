from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import ANY, Mock, patch
from urllib.parse import urlparse

from requests import Session

from tweb import TWebDocument, fetch_resource, parse_document
from tweb.fetcher import FetchError, Resource
from tweb.js_runtime import (
  ASYNC_DRAIN_STABLE_TIMER_EARLY_STOP_STEPS,
  JavaScriptRuntimeError,
  QuickJSRuntime,
  RuntimeStats,
  _reset_external_script_cache_state_for_tests,
  _extract_webpack_jsonp_array_modules,
  _find_matching_js_pair_lenient,
  _patch_js_module_stack_underflow,
  _rewrite_js_object_literal_methods,
  _safeguard_string_method_receivers,
  _split_webpack_jsonp_array_modules,
  _split_top_level_js_items,
)
from tweb.js_runtime_helpers import _patch_esm_exports, _patch_import_meta
from tweb.renderers.normal import ANSI_BOLD, ANSI_BOLD_RESET, render_normal


ROOT = Path(__file__).resolve().parents[1]
JS_DOM = ROOT / "tests" / "fixtures" / "js_dom.html"


class JsRuntimeTest(unittest.TestCase):
  def setUp(self) -> None:
    super().setUp()
    self._cache_tmpdir = tempfile.TemporaryDirectory()
    self._cache_env_patch = patch.dict(os.environ, {"TWEB_SCRIPT_CACHE_DIR": self._cache_tmpdir.name})
    self._cache_env_patch.start()
    _reset_external_script_cache_state_for_tests()

  def tearDown(self) -> None:
    _reset_external_script_cache_state_for_tests()
    self._cache_env_patch.stop()
    self._cache_tmpdir.cleanup()
    super().tearDown()

  def load_document(self) -> TWebDocument:
    return TWebDocument(parse_document(fetch_resource(str(JS_DOM))))

  def test_updates_text_content(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      document.querySelector('#title').textContent = 'New Title';
      document.querySelector('.message').textContent = 'Updated body';
      """
    )

    output = render_normal(document.document, width=80)
    self.assertIn(f"# {ANSI_BOLD}New Title{ANSI_BOLD_RESET}", output)
    self.assertIn("Updated body", output)

  def test_updates_attributes_and_inner_html(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const title = document.querySelector('#title');
      title.setAttribute('data-state', 'active');
      const message = document.querySelector('.message');
      message.innerHTML = '<strong>Changed</strong> text';
      """
    )

    title = document.find("h1", attrs={"data-state": "active"})
    self.assertIsNotNone(title)
    self.assertEqual(document.find("strong").text, "Changed")
    self.assertIn("Changed text", document.body_text())

  def test_query_selector_all_returns_multiple_nodes(self) -> None:
    document = self.load_document()

    count = document.execute_script(
      """
      document.querySelector('.message').innerHTML =
        '<span class="item">One</span><span class="item">Two</span>';
      document.querySelectorAll('.item').length;
      """
    )

    self.assertEqual(count, 2)

  def test_query_selector_supports_attribute_prefix_match(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const meta = document.createElement('meta');
      meta.setAttribute('name', 'twitter-site-verification');
      meta.setAttribute('content', 'abc123');
      document.head.appendChild(meta);
      const match = document.querySelector('[name^=tw][content]');
      [
        String(document.querySelectorAll('[name^=tw]').length),
        match ? match.getAttribute('content') : '',
      ].join('|');
      """
    )

    self.assertEqual(result, "1|abc123")

  def test_safeguard_string_method_receivers_supports_to_lower_case(self) -> None:
    rewritten = _safeguard_string_method_receivers(
      "title.toLowerCase() + other.slice(1)",
      {"toLowerCase"},
    )

    self.assertIn("__twebStringReceiver(title).toLowerCase()", rewritten)
    self.assertIn("other.slice(1)", rewritten)

  def test_safeguard_string_method_receivers_preserves_dollar_prefixed_identifier(self) -> None:
    rewritten = _safeguard_string_method_receivers(
      "$title.toLowerCase()",
      {"toLowerCase"},
    )

    self.assertEqual(rewritten, "__twebStringReceiver($title).toLowerCase()")

  def test_safeguard_string_method_receivers_supports_index_of(self) -> None:
    rewritten = _safeguard_string_method_receivers(
      "title.indexOf('abc') + other.slice(1)",
      {"indexOf"},
    )

    self.assertIn("__twebStringReceiver(title).indexOf('abc')", rewritten)
    self.assertIn("other.slice(1)", rewritten)

  def test_selector_query_cache_reuses_results_until_dom_mutation(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    first = json.loads(runtime._query_all(".message"))
    second = json.loads(runtime._query_all(".message"))
    counts = runtime.performance_summary()["counts"]
    self.assertEqual(len(first), 1)
    self.assertEqual(second, first)
    self.assertEqual(counts.get("selector_query_cache_misses"), 1)
    self.assertEqual(counts.get("selector_query_cache_hits"), 1)

    message_id = first[0]
    runtime._set_attribute(message_id, "data-state", "updated")
    third = json.loads(runtime._query_all(".message"))
    counts = runtime.performance_summary()["counts"]
    self.assertEqual(third, first)
    self.assertEqual(counts.get("selector_query_cache_misses"), 2)
    self.assertEqual(counts.get("selector_query_cache_hits"), 1)

  def test_node_ids_use_identity_indexes_and_remain_stable(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)
    message = document.find("p", attrs={"class": "message"})
    self.assertIsNotNone(message)
    message_node = message.node
    text = message_node.children[0]

    element_id = runtime._ensure_node_id(message_node)
    text_id = runtime._ensure_text_node_id(text)

    self.assertEqual(runtime._ensure_node_id(message_node), element_id)
    self.assertEqual(runtime._ensure_text_node_id(text), text_id)
    self.assertEqual(runtime._node_identity_ids[id(message_node)], element_id)
    self.assertEqual(runtime._text_node_identity_ids[id(text)], text_id)

  def test_selector_query_cache_survives_text_only_dom_mutation(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    first = json.loads(runtime._query_all(".message"))
    message_id = first[0]
    child_ids = json.loads(runtime._get_child_nodes(message_id))
    text_id = child_ids[0]

    runtime._set_text_content(text_id, "Updated body text")
    second = json.loads(runtime._query_all(".message"))
    counts = runtime.performance_summary()["counts"]

    self.assertEqual(second, first)
    self.assertEqual(counts.get("selector_query_cache_misses"), 1)
    self.assertEqual(counts.get("selector_query_cache_hits"), 1)
    self.assertEqual(counts.get("text_only_dom_mutations"), 1)

  def test_dom_lookup_cache_reuses_id_tag_and_class_queries_until_dom_mutation(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    first_by_id = runtime._get_element_by_id("root")
    second_by_id = runtime._get_element_by_id("root")
    first_by_tag = json.loads(runtime._get_elements_by_tag_name("p"))
    second_by_tag = json.loads(runtime._get_elements_by_tag_name("p"))
    first_by_class = json.loads(runtime._get_elements_by_class_name("message"))
    second_by_class = json.loads(runtime._get_elements_by_class_name("message"))

    counts = runtime.performance_summary()["counts"]
    self.assertEqual(first_by_id, second_by_id)
    self.assertEqual(first_by_tag, second_by_tag)
    self.assertEqual(first_by_class, second_by_class)
    self.assertEqual(counts.get("dom_lookup_cache_misses"), 3)
    self.assertEqual(counts.get("dom_lookup_cache_hits"), 3)

    added = runtime._create_element("section")
    runtime._append_child(first_by_class[0], added)
    runtime._get_elements_by_tag_name("p")
    counts = runtime.performance_summary()["counts"]
    self.assertEqual(counts.get("dom_lookup_cache_misses"), 4)
    self.assertEqual(counts.get("dom_lookup_cache_hits"), 3)

  def test_dom_lookup_cache_survives_text_only_dom_mutation(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    first = json.loads(runtime._get_elements_by_class_name("message"))
    message_id = first[0]
    child_ids = json.loads(runtime._get_child_nodes(message_id))
    text_id = child_ids[0]

    runtime._set_text_content(text_id, "Updated body text")
    second = json.loads(runtime._get_elements_by_class_name("message"))
    counts = runtime.performance_summary()["counts"]

    self.assertEqual(second, first)
    self.assertEqual(counts.get("dom_lookup_cache_misses"), 1)
    self.assertEqual(counts.get("dom_lookup_cache_hits"), 1)
    self.assertEqual(counts.get("text_only_dom_mutations"), 1)

  def test_parent_node_tracks_reparented_nodes_without_full_tree_search(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const first = document.createElement('div');
      first.id = 'first-parent';
      const second = document.createElement('div');
      second.id = 'second-parent';
      const child = document.createElement('span');
      child.textContent = 'moved';
      document.body.appendChild(first);
      document.body.appendChild(second);
      first.appendChild(child);
      const beforeMove = child.parentNode === first;
      second.appendChild(child);
      const afterMove = child.parentNode === second;
      const removedFromFirst = first.childNodes.length === 0;
      [String(beforeMove), String(afterMove), String(removedFromFirst)].join('|');
      """
    )

    self.assertEqual(result, "true|true|true")

  def test_supports_document_title_and_body_queries(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      document.title = 'Updated Document Title';
      document.body.querySelector('.message').textContent = 'Body query updated';
      """
    )

    self.assertEqual(document.title, "Updated Document Title")
    self.assertIn("Body query updated", document.body_text())

  def test_exposes_top_level_window_relationships(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const iframe = document.createElement('iframe');
      document.body.appendChild(iframe);
      [
        String(window.self === window),
        String(window.parent === window),
        String(window.top === window),
        String(window.opener === null),
        String(window.frames.length),
        String(window.frames.item(0) === iframe.contentWindow),
      ].join('|');
      """
    )

    self.assertEqual(result, "true|true|true|true|1|true")

  def test_huge_allocation_hits_memory_limit(self) -> None:
    document = self.load_document()
    document._runtime(reset=True)._ctx.set_memory_limit(8 * 1024 * 1024)

    with self.assertRaisesRegex(JavaScriptRuntimeError, "memory limit exceeded|null"):
      document.execute_script(
        """
        const chunks = [];
        while (true) {
          chunks.push('x'.repeat(1000));
        }
        """
      )

  def test_supports_active_element_range_and_tree_walker(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const range = document.createRange();
      range.selectNodeContents(document.body);
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
        acceptNode(node) {
          return node.tagName === 'P' ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        }
      });
      const node = walker.nextNode();
      [
        String(document.activeElement === document.body),
        String(range.commonAncestorContainer === document.body),
        node ? node.tagName : ''
      ].join('|');
      """
    )

    self.assertEqual(result, "true|true|P")

  def test_supports_focus_blur_and_click_methods(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      let clicked = 0;
      main.addEventListener('click', () => {
        clicked += 1;
      });
      main.focus();
      const focused = document.activeElement === main;
      main.click();
      main.blur();
      [
        String(focused),
        String(clicked),
        String(document.activeElement === document.body),
      ].join('|');
      """
    )

    self.assertEqual(result, "true|1|true")

  def test_rewrites_object_literal_shorthand_methods(self) -> None:
    source = """
    function build(kind) {
      return {
        [kind](value) {
          return { nested(value) { return value + 1; } }.nested(value) + 1;
        },
        plain(value) {
          return value + 2;
        },
      };
    }
    """

    rewritten = _rewrite_js_object_literal_methods(source)

    self.assertIn("[kind]:function(value)", rewritten)
    self.assertIn("plain:function(value)", rewritten)
    self.assertIn("nested:function(value)", rewritten)

  def test_rewritten_object_literal_methods_evaluate_in_quickjs(self) -> None:
    source = """
    var kind = 'dynamic';
    var handlers = {
      [kind](value) {
        return value + 1;
      },
      plain(value) {
        return value + 2;
      },
    };
    handlers.dynamic(1) + handlers.plain(1);
    """

    runtime = self.load_document()
    rewritten = _rewrite_js_object_literal_methods(source)

    self.assertEqual(runtime.execute_script(rewritten), 5)

  def test_safeguards_selected_string_receiver_methods(self) -> None:
    rewritten = _safeguard_string_method_receivers(
      "title.charAt(0) + items.slice(1) + title.slice(1)",
      {"charAt"},
    )

    self.assertIn("__twebStringReceiver(title).charAt(0)", rewritten)
    self.assertIn("items.slice(1)", rewritten)
    self.assertIn("title.slice(1)", rewritten)

  def test_patches_compile_failing_assigned_object_entries(self) -> None:
    seen_sources: list[str] = []

    def checker(source: str) -> None:
      seen_sources.append(source)
      if "bad(value)" in source:
        raise JavaScriptRuntimeError("InternalError: stack underflow")

    patched = _patch_js_module_stack_underflow(
      "function(){var handlers={good(value){return value;},bad(value){return value+1;}};return handlers;}",
      compile_checker=checker,
    )

    self.assertIn("good(value)", patched)
    self.assertIn("bad:function(){return Promise.resolve();}", patched)
    self.assertTrue(any("bad(value)" in source for source in seen_sources))

  def test_splits_sparse_webpack_jsonp_array_modules(self) -> None:
    modules = _split_webpack_jsonp_array_modules(
      "[,function(module){return 1;},function(module){return { value: 2 };}]"
    )

    self.assertEqual(len(modules), 3)
    self.assertEqual(modules[0], "")
    self.assertTrue(modules[1].startswith("function(module){return 1;"))
    self.assertTrue(modules[2].startswith("function(module){return { value: 2 };"))

  def test_splits_webpack_jsonp_modules_with_try_catch(self) -> None:
    modules = _split_webpack_jsonp_array_modules(
      "[function(e,t,n){var data=function(){return{ok:true}};try{data()}catch(err){}},function(){return 1;}]"
    )

    self.assertEqual(len(modules), 2)
    self.assertIn("catch(err){}", modules[0])
    self.assertTrue(modules[1].startswith("function(){return 1;"))

  def test_splits_webpack_jsonp_modules_with_regex_heavy_body(self) -> None:
    modules = _split_webpack_jsonp_array_modules(
      "[function(e,t,n){var x=new RegExp([\"(\\\\\\\\.)\",\"([\\\\/.])?(?:(?:\\\\:(\\\\w+)(?:\\\\(((?:\\\\\\\\.|[^\\\\\\\\()])+)\\\\))?|\\\\(((?:\\\\\\\\.|[^\\\\\\\\()])+)\\\\))([+*?])?|(\\\\*))\"].join(\"|\"),\"g\");function y(v){return v.replace(/([.+*?=^!:${}()[\\]|/\\\\])/g,\"\\\\$1\")}try{x.exec('a/b')}catch(err){}},function(){return 1;}]"
    )

    self.assertEqual(len(modules), 2)
    self.assertIn("new RegExp([", modules[0])
    self.assertIn("replace(/([.+*?=^!:${}()[\\]|/\\\\])/g", modules[0])
    self.assertTrue(modules[1].startswith("function(){return 1;"))

  def test_extracts_webpack_jsonp_modules_with_regex_quantifiers(self) -> None:
    modules_expr, module_end, module_items = _extract_webpack_jsonp_array_modules(
      "[function(module){return /a{1,2}/.test('aa');}] rest",
      0,
    )

    self.assertEqual(modules_expr, "[function(module){return /a{1,2}/.test('aa');}]")
    self.assertEqual(module_end, len(modules_expr) - 1)
    self.assertEqual(len(module_items), 1)
    self.assertIn("/a{1,2}/", module_items[0])

  def test_finds_matching_js_array_lenient_with_nested_module_arrays(self) -> None:
    source = (
      "[,function(e,t,n){var styles=[\"none\",\"disabled\",\"basic\"];"
      "return /a[b,c]/.test('abc')},function(){return 1;}] tail"
    )

    end = _find_matching_js_pair_lenient(source, 0, "[", "]")

    self.assertEqual(end, source.index("] tail"))
    self.assertIn("function(){return 1;}", source[: end + 1])

  def test_supports_legacy_attach_event_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      let count = 0;
      function handler() { count += 1; }
      main.attachEvent('onclick', handler);
      main.click();
      main.detachEvent('onclick', handler);
      main.click();
      String(count);
      """
    )

    self.assertEqual(result, "1")

  def test_supports_image_audio_and_canvas_helpers(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const image = new Image(320, 180);
      image.src = 'https://example.com/image.png';
      const audio = new Audio('/sample.mp3');
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      const imageData = context.createImageData(2, 2);
      Promise.all([image.decode(), audio.play()]).then(() => {
        document.querySelector('main').textContent = [
          String(image.width),
          String(image.height),
          String(typeof image.style),
          String('object-fit' in image.style),
          String(audio.src),
          String(typeof context.fillRect),
          String(imageData.data.length),
          canvas.toDataURL()
        ].join('|');
      });
      """
    )

    self.assertEqual(
      document.body_text(),
      "320|180|object|false|/sample.mp3|function|16|data:image/png;base64,",
    )

  def test_supports_focus_and_keyboard_event_constructors(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const focus = new FocusEvent('focusout', { bubbles: true });
      const key = new KeyboardEvent('keydown', { key: 'Tab', code: 'Tab', keyCode: 9 });
      const input = new InputEvent('input', { data: 'a', inputType: 'insertText' });
      [
        focus.type,
        String(focus.bubbles),
        key.key,
        key.code,
        String(key.which),
        input.inputType,
      ].join('|');
      """
    )

    self.assertEqual(result, "focusout|true|Tab|Tab|9|insertText")

  def test_iframe_exposes_content_document_and_window(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const iframe = document.createElement('iframe');
      document.body.appendChild(iframe);
      const inner = iframe.contentDocument;
      const script = inner.createElement('script');
      script.textContent = 'window.frameLoaded = true;';
      inner.getElementsByTagName('head')[0].appendChild(script);
      [
        String(iframe.contentWindow !== null),
        String(inner !== null),
        inner.documentElement.tagName,
        inner.head.tagName,
        inner.body.tagName,
      ].join('|');
      """
    )

    self.assertEqual(result, "true|true|HTML|HEAD|BODY")

  def test_iframe_document_supports_open_write_and_close(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const iframe = document.createElement('iframe');
      document.body.appendChild(iframe);
      const inner = iframe.contentDocument;
      inner.open();
      inner.write('<main id="frame-main">Frame body</main>');
      inner.writeln('<p>Second row</p>');
      inner.close();
      [
        inner.getElementById('frame-main').textContent,
        inner.body.textContent,
      ].join('|');
      """
    )

    self.assertEqual(result, "Frame body|Frame body Second row")

  def test_iframe_dispatches_load_and_supports_window_messages(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const iframe = document.createElement('iframe');
      iframe.addEventListener('load', () => {
        document.body.setAttribute('data-iframe-loaded', '1');
        iframe.contentWindow.addEventListener('message', (event) => {
          iframe.contentWindow.parent.postMessage('child:' + event.data, '*');
        });
        window.addEventListener('message', (event) => {
          document.body.setAttribute('data-iframe-message', String(event.data));
        });
        iframe.contentWindow.postMessage('ping', '*');
      });
      document.body.appendChild(iframe);
      [
        String(iframe.contentWindow.location.href),
        String(iframe.contentDocument.defaultView === iframe.contentWindow),
      ].join('|');
      """
    )

    self.assertEqual(result, "about:blank|true")
    self.assertEqual(document.body.get("data-iframe-loaded"), "1")
    self.assertEqual(document.body.get("data-iframe-message"), "child:ping")

  def test_fragment_inserted_iframe_dispatches_load(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const fragment = document.createDocumentFragment();
      const iframe = document.createElement('iframe');
      iframe.addEventListener('load', () => {
        document.body.setAttribute('data-fragment-iframe-loaded', '1');
      });
      fragment.appendChild(iframe);
      document.body.appendChild(fragment);
      String(document.querySelectorAll('iframe').length);
      """
    )

    self.assertEqual(result, "1")
    self.assertEqual(document.body.get("data-fragment-iframe-loaded"), "1")

  def test_supports_is_equal_node(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const title = document.querySelector('#title');
      const clone = title.cloneNode(true);
      const other = title.cloneNode(true);
      other.setAttribute('data-extra', '1');
      [
        String(title.isEqualNode(clone)),
        String(title.isEqualNode(other)),
        String(title.isSameNode(clone)),
      ].join('|');
      """
    )

    self.assertEqual(result, "true|false|false")

  def test_supports_string_normalize(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      'テスト'.normalize('NFC')
      """
    )

    self.assertEqual(result, "テスト")

  def test_supports_modern_array_and_string_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      [
        ['a b'.replaceAll(' ', '-'), [1, 2].flatMap((value) => [value, value]).join(','), ['x', 'y'].at(-1)].join('|')
      ][0]
      """
    )

    self.assertEqual(result, "a-b|1,1,2,2|y")

  def test_supports_object_has_own(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const values = { present: 1 };
      [
        String(Object.hasOwn(values, 'present')),
        String(Object.hasOwn(values, 'missing')),
      ].join('|');
      """
    )

    self.assertEqual(result, "true|false")

  def test_supports_intl_collator_compare(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const collator = new Intl.Collator('ja', { usage: 'search' });
      [
        typeof collator.compare,
        String(collator.compare('a', 'b') < 0),
        String(collator.compare('a', 'a') === 0),
      ].join('|');
      """
    )

    self.assertEqual(result, "function|true|true")

  def test_supports_closest_and_replace_children_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const title = document.querySelector('#title');
      const main = title.closest('main');
      const container = document.createElement('div');
      container.replaceChildren('before', document.createElement('span'));
      container.lastChild.textContent = 'after';
      main.prepend(container);
      document.body.firstElementChild.tagName + '|' + main.firstElementChild.textContent;
      """
    )

    self.assertEqual(result, "MAIN|before after")

  def test_supports_replace_with_helper(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const title = document.querySelector('#title');
      const strong = document.createElement('strong');
      strong.textContent = 'updated';
      title.replaceWith(strong, ' tail');
      [
        document.querySelector('main').firstElementChild.tagName,
        String(document.querySelector('main').textContent.trim().startsWith('updated tail')),
      ].join('|');
      """
    )

    self.assertEqual(result, "STRONG|true")

  def test_supports_dialog_and_scroll_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const dialog = document.createElement('dialog');
      document.body.appendChild(dialog);
      dialog.showModal();
      const openAfterShow = String(dialog.open);
      dialog.close();
      const openAfterClose = String(dialog.open);
      const main = document.querySelector('main');
      main.scrollTo(10, 20);
      main.scroll(30, 40);
      [openAfterShow, openAfterClose, typeof main.scrollTo, typeof dialog.showModal].join('|');
      """
    )

    self.assertEqual(result, "true|false|function|function")

  def test_supports_audio_context_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const ctx = new AudioContext();
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.5, 0);
      gain.gain.setTargetAtTime(0.75, 1, 0.1);
      const source = ctx.createBufferSource();
      source.playbackRate.setValueAtTime(1.25, 0);
      source.connect(gain).connect(ctx.destination);
      ctx.suspend();
      ctx.resume();
      [
        typeof ctx.createMediaElementSource,
        String(gain.gain.value),
        String(source.playbackRate.value),
        ctx.state,
      ].join('|');
      """
    )

    self.assertEqual(result, "function|0.75|1.25|running")

  def test_supports_template_content_and_attribute_names(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const template = document.createElement('template');
      const fragment = template.content;
      const child = document.createElement('span');
      child.setAttribute('data-kind', 'demo');
      fragment.appendChild(child);
      [
        String(template instanceof HTMLTemplateElement),
        String(fragment.nodeType === Node.DOCUMENT_FRAGMENT_NODE),
        child.getAttributeNames().includes('data-kind'),
        child.hasAttributeNS(null, 'data-kind')
      ].join('|');
      """
    )

    self.assertEqual(result, "true|true|true|true")

  def test_supports_rel_list_named_node_map_and_namespace_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const link = document.createElement('link');
      link.rel = 'preload stylesheet';
      link.relList.remove('stylesheet');
      link.relList.add('prefetch');
      link.setAttribute('data-kind', 'demo');
      const svg = document.createElement('svg');
      document.body.append(link, svg);
      [
        link.relList.contains('preload'),
        link.relList.supports('prefetch'),
        link.attributes.getNamedItem('data-kind').value,
        document.documentElement.namespaceURI,
        svg.namespaceURI,
        document.documentElement.localName
      ].join('|');
      """
    )

    self.assertEqual(
      result,
      "true|true|demo|http://www.w3.org/1999/xhtml|http://www.w3.org/2000/svg|html",
    )

  def test_supports_element_query_selector_and_id_class_name(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const main = document.documentElement.querySelector('main');
      const title = main.querySelector('#title');
      title.id = 'renamed-title';
      title.className = 'headline primary';
      """
    )

    title = document.find("h1", attrs={"id": "renamed-title"})
    self.assertIsNotNone(title)
    self.assertEqual(title.get("class"), "headline primary")

  def test_supports_create_element_append_and_location(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const card = document.createElement('section');
      card.id = 'dynamic-card';
      const heading = document.createElement('h2');
      heading.textContent = location.pathname.endsWith('js_dom.html')
        ? 'Dynamic heading'
        : 'Wrong path';
      card.appendChild(heading);
      card.append(' dynamic text');
      document.body.appendChild(card);
      """
    )

    section = document.find("section", attrs={"id": "dynamic-card"})
    self.assertIsNotNone(section)
    self.assertIn("Dynamic heading dynamic text", section.text)

  def test_supports_moving_child_from_detached_subtree(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main id="app">
            <!--$?--><template id="B:0"></template><div id="S:0" hidden><div id="moved">Moved</div></div><!--/$-->
          </main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_script(
      """
      const stash = document.getElementById('S:0');
      stash.parentNode.removeChild(stash);
      const marker = document.getElementById('B:0').previousSibling;
      const parent = marker.parentNode;
      parent.insertBefore(stash.firstChild, document.getElementById('B:0').nextSibling);
      """
    )

    moved = document.find("div", attrs={"id": "moved"})
    self.assertIsNotNone(moved)
    self.assertEqual(moved.text, "Moved")

  def test_execute_inline_scripts_runs_embedded_scripts(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            const p = document.createElement('p');
            p.textContent = 'Inline script text';
            document.body.appendChild(p);
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_inline_scripts()

    self.assertIn("Inline script text", document.body_text())

  def test_execute_embedded_scripts_loads_external_scripts(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      script_path.write_text(
        "const p = document.createElement('p'); p.textContent = window.navigator.userAgent; document.body.appendChild(p);",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertIn("Mozilla/5.0", document.body_text())

  def test_execute_embedded_scripts_delays_async_external_scripts_until_after_inline(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "async.js"
      script_path.write_text(
        """
        document.body.setAttribute(
          'data-order',
          (document.body.getAttribute('data-order') || '') + '|async'
        );
        """,
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script async src="{script_path.name}"></script>
            <script>
              document.body.setAttribute('data-order', 'inline');
            </script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body.get("data-order"), "inline|async")

  def test_execute_embedded_scripts_delayed_classic_external_script_keeps_window_this(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "defer.js"
      script_path.write_text(
        "document.body.setAttribute('data-classic-this', String(this === window));",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script defer src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body.get("data-classic-this"), "true")

  def test_dynamic_external_script_loads_after_append(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "dynamic.js"
      script_path.write_text(
        "document.body.setAttribute('data-dynamic', 'loaded');",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body></body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_script(
        f"""
        const script = document.createElement('script');
        script.src = '{script_path.name}';
        document.head.appendChild(script);
        """
      )

      self.assertEqual(document.body.get("data-dynamic"), "loaded")

  def test_document_write_external_script_is_parser_blocking(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      failing_path = Path(tmpdir) / "failing.js"
      failing_path.write_text(
        "throw new Error('optional legacy dependency failed');",
        encoding="utf-8",
      )
      dependency_path = Path(tmpdir) / "dependency.js"
      dependency_path.write_text(
        "window.parserDependency = 'ready';",
        encoding="utf-8",
      )
      loader_path = Path(tmpdir) / "loader.js"
      loader_path.write_text(
        "document.write('<script src=\"failing.js\"><' + '/script>');"
        "document.write('<script src=\"dependency.js\"><' + '/script>');",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body>
            <script src="loader.js"></script>
            <script>
              document.body.setAttribute('data-parser-dependency', window.parserDependency);
            </script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body.get("data-parser-dependency"), "ready")
      debug = document.javascript_debug()
      self.assertEqual(debug["counts"]["parser_inserted_script_errors"], 1)
      self.assertTrue(debug["parser_inserted_script_errors"][0]["src"].endswith("/failing.js"))
      self.assertIn("optional legacy dependency failed", debug["parser_inserted_script_errors"][0]["error"])

  @patch.object(QuickJSRuntime, "script_preflight_safe", return_value=False)
  def test_document_write_skips_large_parser_script_after_crash_preflight(self, mock_preflight: Mock) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      dangerous_path = Path(tmpdir) / "dangerous.js"
      dangerous_path.write_text(
        "document.body.setAttribute('data-dangerous', '1');/*" + ("x" * 200_000) + "*/",
        encoding="utf-8",
      )
      loader_path = Path(tmpdir) / "loader.js"
      loader_path.write_text(
        "document.write('<script src=\"dangerous.js\"><' + '/script>');",
        encoding="utf-8",
      )
      document = TWebDocument(
        parse_document(
          Resource(
            source=str(Path(tmpdir) / "index.html"),
            content='<html><body><script src="loader.js"></script></body></html>',
          )
        )
      )

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertIsNone(document.body.get("data-dangerous"))
      debug = document.javascript_debug()
      self.assertEqual(debug["counts"]["parser_inserted_script_errors"], 1)
      self.assertIn("crash preflight", debug["parser_inserted_script_errors"][0]["error"])
      mock_preflight.assert_called_once()

  def test_dynamic_external_script_dispatches_load_listener(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "dynamic.js"
      script_path.write_text(
        "document.body.setAttribute('data-dynamic', 'loaded');",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body></body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_script(
        f"""
        const script = document.createElement('script');
        script.addEventListener('load', () => {{
          document.body.setAttribute('data-load-event', '1');
        }});
        script.src = '{script_path.name}';
        document.head.appendChild(script);
        """
      )

      self.assertEqual(document.body.get("data-load-event"), "1")

  def test_dynamic_external_script_loads_when_src_is_set_after_append(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "dynamic.js"
      script_path.write_text(
        "document.body.setAttribute('data-dynamic-after-append', 'loaded');",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body></body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_script(
        f"""
        const script = document.createElement('script');
        document.head.appendChild(script);
        script.src = '{script_path.name}';
        """
      )

      self.assertEqual(document.body.get("data-dynamic-after-append"), "loaded")

  def test_dynamic_external_script_set_attribute_after_append_dispatches_load_once(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "dynamic.js"
      script_path.write_text(
        """
        window.dynamicLoadCount = (window.dynamicLoadCount || 0) + 1;
        document.body.setAttribute('data-load-count', String(window.dynamicLoadCount));
        """,
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body></body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_script(
        f"""
        const script = document.createElement('script');
        let loadEvents = 0;
        script.addEventListener('load', () => {{
          loadEvents += 1;
          document.body.setAttribute('data-load-events', String(loadEvents));
        }});
        document.head.appendChild(script);
        script.setAttribute('src', '{script_path.name}');
        """
      )

      self.assertEqual(document.body.get("data-load-count"), "1")
      self.assertEqual(document.body.get("data-load-events"), "1")

  def test_dynamic_external_script_failure_during_page_events_raises_runtime_error(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "dynamic.js"
      script_path.write_text(
        "throw null;",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script>
              document.addEventListener('DOMContentLoaded', () => {{
                const script = document.createElement('script');
                script.src = {script_path.name!r};
                document.head.appendChild(script);
              }});
            </script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      with self.assertRaises(JavaScriptRuntimeError) as raised:
        document.execute_embedded_scripts(ignore_errors=False)

      self.assertTrue(str(raised.exception).startswith("null"))
      self.assertIn("dynamic.js", str(raised.exception))

  def test_dynamic_external_script_failure_during_page_events_is_ignored_when_requested(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "dynamic.js"
      script_path.write_text(
        "throw null;",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <main>before</main>
            <script>
              document.addEventListener('DOMContentLoaded', () => {{
                const script = document.createElement('script');
                script.src = {script_path.name!r};
                document.head.appendChild(script);
              }});
            </script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=True)

      self.assertIn("before", document.body_text())

  @patch("tweb.js_runtime.fetch_resource", side_effect=FetchError("missing script"))
  def test_dynamic_external_script_fetch_failure_during_page_events_is_ignored_when_requested(
    self,
    _mock_fetch_resource: Mock,
  ) -> None:
    resource = Resource(
      source="https://example.com",
      content="""
      <html>
        <body>
          <main>before</main>
          <script>
            document.addEventListener('DOMContentLoaded', () => {
              const script = document.createElement('script');
              script.src = '/missing.js';
              document.head.appendChild(script);
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=True)

    self.assertIn("before", document.body_text())

  @patch("tweb.js_runtime.time.perf_counter", side_effect=SystemError("timer broken"))
  @patch("tweb.js_runtime.time.monotonic", return_value=123.0)
  def test_runtime_stats_falls_back_when_perf_counter_is_unavailable(
    self,
    _mock_monotonic: Mock,
    _mock_perf_counter: Mock,
  ) -> None:
    stats = RuntimeStats()

    stats.add_timing("script_eval", 100.0)

    self.assertEqual(stats.timings_ms["script_eval"], 23000.0)

  @patch("tweb.js_runtime._elapsed_ms_since", side_effect=[0.0, 6000.0, 6000.0])
  def test_async_drain_stops_after_wall_clock_budget(
    self,
    _mock_elapsed_ms_since: Mock,
  ) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com",
          content="<html><body><main>before</main></body></html>",
        )
      )
    )
    runtime = QuickJSRuntime(document.document)
    runtime._ctx = Mock()
    microtask_calls = {"count": 0}

    def fake_eval(source: str):
      if "__twebRunNextMicrotask();" in source:
        microtask_calls["count"] += 1
        return microtask_calls["count"] == 1
      return False

    runtime._ctx.eval = Mock(side_effect=fake_eval)
    runtime._execute_pending_job = Mock(return_value=False)

    runtime._drain_async_work(max_wall_time_ms=5000)

    self.assertEqual(runtime.performance_summary()["counts"]["async_drain_early_stops"], 1)

  def test_async_drain_stops_after_pending_job_budget(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com",
          content="<html><body><main>before</main></body></html>",
        )
      )
    )
    runtime = QuickJSRuntime(document.document)
    runtime._ctx = Mock()
    runtime._ctx.eval = Mock(return_value=False)
    runtime._execute_pending_job = Mock(side_effect=[True, True, False])

    runtime._drain_async_work(max_pending_job_steps=2)

    self.assertEqual(runtime.performance_summary()["counts"]["async_drain_early_stops"], 1)

  def test_async_drain_stops_after_microtask_budget(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com",
          content="<html><body><main>before</main></body></html>",
        )
      )
    )
    runtime = QuickJSRuntime(document.document)
    runtime._ctx = Mock()
    microtask_calls = {"count": 0}

    def fake_eval(source: str):
      if "__twebRunNextMicrotask();" in source:
        microtask_calls["count"] += 1
        return microtask_calls["count"] == 1
      return False

    runtime._ctx.eval = Mock(side_effect=fake_eval)
    runtime._execute_pending_job = Mock(return_value=False)

    runtime._drain_async_work(max_microtask_steps=1)

    self.assertEqual(runtime.performance_summary()["counts"]["async_drain_early_stops"], 1)

  def test_execute_embedded_scripts_keeps_runtime_after_ignored_inline_null_error(self) -> None:
    resource = Resource(
      source="https://example.com",
      content="""
      <html>
        <body>
          <script>window.first = 1;</script>
          <script>throw null;</script>
          <script>window.third = 3;</script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    first_runtime = Mock()
    first_runtime.eval.side_effect = [None, JavaScriptRuntimeError("null"), None]
    document._runtime = Mock(return_value=first_runtime)

    with patch("tweb.api._extract_site_specific_hydration_sections", return_value=[]), patch(
      "tweb.api._augment_sparse_body_from_hydration"
    ):
      document.execute_embedded_scripts(ignore_errors=True)

    self.assertEqual(first_runtime.eval.call_count, 3)
    first_runtime.eval.assert_called_with("window.third = 3;", source_url=None, drain_timers=False)
    first_runtime.dispatch_page_events.assert_called_once_with(
      time_limit_seconds=None,
      continue_on_event_callback_error=True,
    )
    self.assertEqual(document._runtime.call_count, 1)
    debug = document.javascript_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertEqual(debug["counts"]["ignored_script_errors"], 1)
    self.assertEqual(debug["counts"]["runtime_resets_after_ignored_errors"], 0)
    self.assertEqual(debug["ignored_script_errors"][0]["src"], "https://example.com#inline-1")
    self.assertEqual(debug["ignored_script_errors"][0]["error"], "null")
    self.assertFalse(debug["ignored_script_errors"][0]["runtime_reset"])

  def test_execute_embedded_scripts_resets_runtime_after_ignored_external_null_error(self) -> None:
    resource = Resource(
      source="https://example.com",
      content="""
      <html>
        <body>
          <script src="https://example.com/a.js"></script>
          <script>window.third = 3;</script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    with patch("tweb.api._prefetch_external_script_sources", return_value=(None, {})), patch(
      "tweb.api.resolve_resource_url",
      return_value="https://example.com/a.js",
    ), patch("tweb.api._should_load_external_script", return_value=True):
      first_runtime = Mock()
      first_runtime.load_external_script_source.return_value = "throw null;"
      first_runtime.eval.side_effect = [JavaScriptRuntimeError("null")]
      second_runtime = Mock()
      document._runtime = Mock(side_effect=[first_runtime, second_runtime])

      with patch("tweb.api._extract_site_specific_hydration_sections", return_value=[]), patch(
        "tweb.api._augment_sparse_body_from_hydration"
      ):
        document.execute_embedded_scripts(ignore_errors=True)

    self.assertEqual(document._runtime.call_count, 2)
    second_runtime.eval.assert_called_once_with("window.third = 3;", source_url=None, drain_timers=False)
    debug = document.javascript_debug()
    self.assertIsNotNone(debug)
    assert debug is not None
    self.assertEqual(debug["counts"]["runtime_resets_after_ignored_errors"], 1)
    self.assertTrue(debug["ignored_script_errors"][0]["runtime_reset"])

  def test_normalize_context_exception_includes_script_for_null_error(self) -> None:
    runtime = QuickJSRuntime(parse_document(fetch_resource(str(JS_DOM))))
    runtime._current_script_info = {"src": "https://example.com/app.js"}
    runtime._ctx = Mock(memory=Mock(return_value={"malloc_size": 1234, "malloc_limit": 0}))
    error = runtime._normalize_context_exception(RuntimeError("null"))

    self.assertEqual(
      str(error),
      "null (script=https://example.com/app.js, malloc_size=1234)",
    )

  def test_take_async_error_message_includes_callback_label_for_null(self) -> None:
    runtime = QuickJSRuntime(parse_document(fetch_resource(str(JS_DOM))))
    runtime._ctx.eval(
      """
      window.__twebLastAsyncError = null;
      window.__twebLastAsyncCallbackLabel = 'event:load';
      """
    )

    self.assertEqual(runtime._take_async_error_message(), "null [callback=event:load]")

  def test_eval_retries_html_entity_escaped_script_source(self) -> None:
    runtime = QuickJSRuntime(parse_document(fetch_resource(str(JS_DOM))))

    runtime.eval("Object.defineProperty(window, &#x27;escaped_flag&#x27;, { value: 1 });", drain_timers=False)

    self.assertEqual(runtime._ctx.eval("window.escaped_flag"), 1)

  def test_eval_ignores_named_window_property_sync_errors(self) -> None:
    runtime = QuickJSRuntime(parse_document(fetch_resource(str(JS_DOM))))
    runtime._ctx.eval(
      """
      __twebSyncNamedWindowProperties = function() {
        throw null;
      };
      """
    )

    runtime.eval("window.syncSafeFlag = 1;", drain_timers=False)

    self.assertEqual(runtime._ctx.eval("window.syncSafeFlag"), 1)

  def test_named_window_property_sync_skips_inherited_window_property(self) -> None:
    runtime = QuickJSRuntime(
      parse_document(
        fetch_resource(
          str(ROOT / "tests" / "fixtures" / "named-window-property-inherited.html")
        )
      )
    )
    runtime._ctx.eval(
      """
      Object.defineProperty(Object.getPrototypeOf(window), 'inheritedFlag', {
        configurable: true,
        value: 42,
      });
      """
    )

    runtime._ctx.eval("__twebSyncNamedWindowProperties();")

    self.assertEqual(runtime._ctx.eval("window.inheritedFlag"), 42)
    self.assertFalse(
      runtime._ctx.eval(
        "Object.prototype.hasOwnProperty.call(window, 'inheritedFlag')"
      )
    )

  def test_named_window_property_sync_skips_when_dom_is_clean(self) -> None:
    runtime = QuickJSRuntime(parse_document(fetch_resource(str(JS_DOM))))

    runtime._sync_named_window_properties()
    runtime._sync_named_window_properties()

    counts = runtime.performance_summary()["counts"]
    self.assertEqual(counts["named_window_property_sync_calls"], 2)
    self.assertEqual(counts["named_window_property_sync_runs"], 1)
    self.assertEqual(counts["named_window_property_sync_skips"], 1)

  def test_named_window_property_sync_reruns_after_name_mutation(self) -> None:
    runtime = QuickJSRuntime(parse_document(fetch_resource(str(JS_DOM))))

    runtime._sync_named_window_properties()
    runtime.eval(
      """
      const marker = document.createElement('form');
      marker.setAttribute('name', 'rerunMarker');
      document.body.appendChild(marker);
      """,
      drain_timers=False,
    )
    runtime._sync_named_window_properties()

    counts = runtime.performance_summary()["counts"]
    self.assertEqual(counts["named_window_property_sync_calls"], 4)
    self.assertEqual(counts["named_window_property_sync_runs"], 2)
    self.assertEqual(counts["named_window_property_sync_skips"], 2)
    self.assertIsNotNone(runtime._ctx.eval("window.rerunMarker"))

  def test_exposes_element_constructor_and_instanceof(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      String(main instanceof Element) + '|' + String(main instanceof HTMLElement);
      """
    )

    self.assertEqual(result, "true|true")

  def test_dom_parser_exposes_xml_elements_and_namespaced_tags(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const parsed = new DOMParser().parseFromString(`
        <rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
          <title>Public notice</title>
          <link>https://example.com/notice</link>
          <dc:date>2026-07-19T00:00:00+09:00</dc:date>
          <dc:subject>Notice</dc:subject>
        </item></channel></rss>
      `, 'text/xml');
      const item = parsed.documentElement.getElementsByTagName('item')[0];
      [
        item.getElementsByTagName('title')[0].textContent,
        item.getElementsByTagName('link')[0].textContent,
        item.getElementsByTagName('dc:date')[0].textContent,
        item.getElementsByTagName('dc:subject')[0].textContent,
      ].join('|');
      """
    )

    self.assertEqual(
      result,
      "Public notice|https://example.com/notice|2026-07-19T00:00:00+09:00|Notice",
    )

  def test_supports_comment_fragment_clone_and_is_connected(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const fragment = document.createDocumentFragment();
      const comment = document.createComment('marker');
      const item = document.createElement('span');
      item.textContent = 'inside fragment';
      fragment.appendChild(comment);
      fragment.appendChild(item);
      document.body.appendChild(fragment);
      const clone = item.cloneNode(true);
      document.body.appendChild(clone);
      [
        String(comment.nodeType),
        String(item.isConnected),
        String(clone.textContent),
        String(comment instanceof Comment),
        String(fragment instanceof DocumentFragment),
      ].join('|');
      """
    )

    self.assertEqual(result, "8|true|inside fragment|true|true")

  def test_supports_outer_html_and_element_sibling_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      main.innerHTML = '<span id="first">one</span> text <span id="second">two</span>';
      const first = document.querySelector('#first');
      const second = document.querySelector('#second');
      [
        first.outerHTML,
        String(main.firstElementChild.id),
        String(main.lastElementChild.id),
        String(second.previousElementSibling.id),
        String(first.nextElementSibling.id),
        String(main.childElementCount),
        String(second.getRootNode().nodeName)
      ].join('|');
      """
    )

    self.assertEqual(
      result,
      '<span id="first">one</span>|first|second|first|second|2|#document',
    )

  def test_supports_setting_outer_html(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      main.innerHTML = '<span id="first">one</span><span id="second">two</span>';
      const first = document.querySelector('#first');
      first.outerHTML = '<strong id="replaced">done</strong>';
      [
        String(!!document.querySelector('#replaced')),
        String(document.querySelector('main').firstElementChild.id),
        String(document.querySelector('main').childElementCount),
        document.querySelector('main').textContent.trim()
      ].join('|');
      """
    )

    self.assertEqual(result, "true|replaced|2|done two")

  def test_supports_document_root_node_metadata(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const root = document.querySelector('#title').getRootNode();
      [
        String(root === document),
        String(root.nodeType),
        String(root.nodeName),
        String(document.firstChild === document.doctype),
        String(document.lastChild === document.documentElement),
        String(document.childNodes.length),
        String(document.doctype.ownerDocument === document)
      ].join('|');
      """
    )

    self.assertEqual(result, "true|9|#document|true|true|2|true")

  def test_hides_builtin_document_and_element_keys(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const body = document.body;
      body.customField = 'ok';
      [
        Object.keys(document).length,
        Object.keys(body).join(','),
        String(body.customField)
      ].join('|');
      """
    )

    self.assertEqual(result, "2|customField|ok")

  def test_unknown_element_properties_default_to_undefined(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      [String(main.unknownProp), String(main['data-missing'])].join('|');
      """
    )

    self.assertEqual(result, "undefined|undefined")

  def test_detached_nodes_keep_stable_parent_lookups(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      main.innerHTML = '<span id="first">one</span>';
      const first = document.querySelector('#first');
      main.innerHTML = '<span id="second">two</span>';
      [
        String(first.parentNode),
        String(first.parentElement),
        String(first.isConnected)
      ].join('|');
      """
    )

    self.assertEqual(result, "null|null|false")

  def test_supports_request_and_url_search_params(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      data_path = Path(tmpdir) / "query.txt"
      data_path.write_text("ok", encoding="utf-8")
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body>
            <main id="app"></main>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_script(
        """
        const params = new URLSearchParams({ q: 'x y' });
        document.querySelector('#app').setAttribute('data-query', params.toString());
        const request = new Request('query.txt', { method: 'GET' });
        fetch(request)
          .then((response) => response.text())
          .then((text) => {
            document.querySelector('#app').textContent = text;
          });
        """
      )

      self.assertEqual(document.body_text(), "ok")
      self.assertEqual(document.find("main", attrs={"id": "app"}).get("data-query"), "q=x%20y")

  def test_supports_extended_url_search_params_methods(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const params = new URLSearchParams('a=1&a=2&b=3');
      const visits = [];
      params.forEach((value, key) => visits.push(`${key}:${value}`));
      const before = [
        String(params.has('a')),
        String(params.has('a', '2')),
        params.getAll('a').join(','),
        String(params.size),
        visits.join('|')
      ].join(';');
      params.delete('a', '1');
      params.set('b', '4');
      params.append('c', '5');
      params.sort();
      [before, params.toString()].join(' -> ');
      """
    )

    self.assertEqual(
      result,
      "true;true;1,2;3;a:1|a:2|b:3 -> a=2&b=4&c=5",
    )

  def test_supports_storage_headers_and_response_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      localStorage.clear();
      localStorage.setItem('alpha', '1');
      localStorage.beta = '2';
      const headers = new Headers({ Accept: 'text/plain' });
      headers.set('X-Test', 'ok');
      const response = new Response('body', { status: 201, headers: { 'content-type': 'text/plain' } });
      const clone = response.clone();
      Promise.all([response.blob(), clone.text()]).then(([blob, text]) => {
        document.body.setAttribute(
          'data-runtime',
          [
            Object.prototype.toString.call(localStorage),
            String(typeof Storage),
            String(localStorage instanceof Storage),
            String(localStorage.length),
            localStorage.getItem('beta'),
            String(headers.has('Accept')),
            Array.from(headers.entries()).map(([key, value]) => `${key}:${value}`).join(','),
            new Request('/demo').credentials,
            String(blob.size),
            blob.type,
            text
          ].join('|')
        );
      });
      """
    )

    self.assertIsNotNone(result)
    self.assertEqual(
      document.body.get("data-runtime"),
      "[object Storage]|function|true|2|2|true|accept:text/plain,x-test:ok|same-origin|4|text/plain|body",
    )

  def test_supports_url_and_layout_measurements(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const resolved = new URL('/hello?q=1', location.href);
      const main = document.querySelector('main');
      [
        resolved.href,
        resolved.pathname,
        String(main.clientWidth > 0),
        String(main.clientHeight > 0),
        String(document.scrollingElement === document.documentElement),
        String(getComputedStyle(main).getPropertyValue('display'))
      ].join('|');
      """
    )

    self.assertEqual(
      result,
      "/hello?q=1|/hello|true|true|true|",
    )

  def test_supports_get_elements_by_class_name(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      [
        typeof document.getElementsByClassName,
        String(String(document.getElementsByClassName).includes('[native code]')),
        String(document.getElementsByClassName('message').length),
        String(main.getElementsByClassName('message').length)
      ].join('|');
      """
    )

    self.assertEqual(result, "function|true|1|1")

  def test_supports_import_node(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const template = document.createElement('template');
      template.innerHTML = '<section><p class="copy">Imported</p></section>';
      const imported = document.importNode(template.content, true);
      document.body.appendChild(imported);
      const copy = document.querySelector('.copy');
      [
        String(typeof document.importNode),
        String(imported instanceof DocumentFragment),
        copy ? copy.textContent : '',
      ].join('|');
      """
    )

    self.assertEqual(result, "function|true|Imported")

  def test_image_constructor_is_callable_without_new(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const image = Image(320, 180);
      [
        String(image instanceof Image),
        String(image.width),
        String(image.height)
      ].join('|');
      """
    )

    self.assertEqual(result, "true|320|180")

  def test_get_computed_style_reads_stylesheet_custom_properties(self) -> None:
    resource = Resource(
      source="inline",
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
    document = TWebDocument(parse_document(resource))

    result = document.execute_script(
      """
      [
        getComputedStyle(document.documentElement).getPropertyValue('--size-breakpoint-md'),
        getComputedStyle(document.querySelector('main')).getPropertyValue('display')
      ].join('|');
      """
    )

    self.assertEqual(result, "769px|grid")

  def test_document_exposes_dom_node_metadata(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      [
        String(document.nodeType),
        document.nodeName,
        String(document.firstChild === document.doctype),
        document.compatMode,
        String(document.getRootNode() === document)
      ].join('|');
      """
    )

    self.assertEqual(result, "9|#document|true|CSS1Compat|true")

  def test_nodes_expose_dom_constructors_for_instanceof_checks(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <form id="signup"><input id="email"/></form>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    result = document.execute_script(
      """
      const form = document.querySelector('form');
      const input = document.querySelector('input');
      [
        String(document instanceof Document),
        String(form instanceof HTMLFormElement),
        String(input instanceof HTMLInputElement),
        String(input.getRootNode() === document)
      ].join('|');
      """
    )

    self.assertEqual(result, "true|true|true|true")

  def test_unknown_node_properties_behave_like_expandos(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const link = document.createElement('link');
      const before = typeof link.__reactEvents$test;
      link.__reactEvents$test = new Set();
      const after = [typeof link.__reactEvents$test, typeof link.__reactEvents$test.has].join('|');
      [before, after].join('::');
      """
    )

    self.assertEqual(result, "undefined::object|function")

  def test_response_body_stream_yields_bytes(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const reader = new Response('abc').body.getReader();
      reader.read().then(({ value, done }) => {
        document.querySelector('main').textContent = [
          String(done),
          String(Object.prototype.toString.call(value)),
          String(value.byteLength || value.length)
        ].join('|');
      });
      """
    )

    self.assertEqual(document.body_text(), "false|[object Uint8Array]|3")

  def test_readable_stream_waits_for_late_enqueue(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const stream = new ReadableStream({
        start(controller) {
          setTimeout(() => controller.enqueue(new Uint8Array([65, 66])), 0);
        }
      });
      const reader = stream.getReader();
      reader.read().then(({ value, done }) => {
        document.querySelector('main').textContent = [
          String(done),
          String(value.byteLength),
          String(value[0]),
          String(value[1])
        ].join('|');
      });
      """
    )

    self.assertEqual(document.body_text(), "false|2|65|66")

  def test_readable_stream_tee_copies_future_chunks(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const stream = new ReadableStream({
        start(controller) {
          setTimeout(() => {
            controller.enqueue('A');
            controller.enqueue('B');
            controller.close();
          }, 0);
        }
      });
      const [left, right] = stream.tee();
      const leftReader = left.getReader();
      const rightReader = right.getReader();
      Promise.all([
        leftReader.read().then(({ value }) => value),
        leftReader.read().then(({ value }) => value),
        rightReader.read().then(({ value }) => value),
        rightReader.read().then(({ value }) => value),
      ]).then((values) => {
        document.querySelector('main').textContent = values.join('|');
      });
      """
    )

    self.assertEqual(document.body_text(), "A|B|A|B")

  def test_readable_stream_pull_runs_when_reader_waits(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      let pulls = 0;
      const stream = new ReadableStream({
        pull(controller) {
          pulls += 1;
          controller.enqueue(String(pulls));
          if (pulls >= 2) {
            controller.close();
          }
        }
      });
      const reader = stream.getReader();
      Promise.all([
        reader.read().then(({ value }) => value),
        reader.read().then(({ value }) => value),
      ]).then((values) => {
        document.querySelector('main').textContent = values.join('|');
      });
      """
    )

    self.assertEqual(document.body_text(), "1|2")

  def test_get_computed_style_exposes_direct_properties(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      main.style.setProperty('display', 'grid');
      main.style.setProperty('padding-top', '12px');
      const style = getComputedStyle(main);
      [
        style.display,
        style.paddingTop,
        style.getPropertyValue('padding-top'),
        style.item(0),
        String(Array.from(style).includes('display'))
      ].join('|');
      """
    )

    self.assertEqual(result, "grid|12px|12px|display|true")

  def test_element_style_returns_empty_string_and_supports_camel_case_assignment(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      const initial = main.style.backgroundColor;
      main.style.backgroundColor = 'rgba(1, 2, 3, 0.5)';
      [
        initial,
        main.style.backgroundColor,
        main.style.getPropertyValue('background-color'),
        main.getAttribute('style'),
      ].join('|');
      """
    )

    self.assertEqual(
      result,
      "|rgba(1, 2, 3, 0.5)|rgba(1, 2, 3, 0.5)|background-color: rgba(1, 2, 3, 0.5)",
    )

  def test_supports_attribute_node_removal(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      main.setAttribute('data-mode', 'full');
      const attr = main.getAttributeNode('data-mode');
      const removed = main.removeAttributeNode(attr);
      [
        removed.name,
        removed.value,
        String(main.hasAttribute('data-mode')),
        String(attr.ownerElement === null)
      ].join('|');
      """
    )

    self.assertEqual(result, "data-mode|full|false|true")

  def test_named_node_map_updates_after_attribute_removal(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      main.setAttribute('data-a', '1');
      main.setAttribute('data-b', '2');
      const attrs = main.attributes;
      const removed = [];
      while (attrs.length) {
        removed.push(main.removeAttributeNode(attrs[0]).name);
      }
      [removed.join(','), String(attrs.length)].join('|');
      """
    )

    self.assertEqual(result, "data-a,data-b|0")

  def test_text_encoder_decoder_support_utf8_streaming(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const encoder = new TextEncoder();
      const bytes = encoder.encode('くらし');
      const decoder = new TextDecoder();
      const first = decoder.decode(bytes.slice(0, 4), { stream: true });
      const second = decoder.decode(bytes.slice(4));
      document.querySelector('main').textContent = [
        String(bytes.length > 4),
        first + second
      ].join('|');
      """
    )

    self.assertEqual(document.body_text(), "true|くらし")

  def test_url_search_params_are_readable_and_mutable(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const url = new URL('https://example.com/path?bg-color=fff&width=320#top');
      const before = url.searchParams.get('bg-color');
      url.searchParams.set('width', '640');
      url.searchParams.append('canvas', '100:50');
      [before, url.search, url.href].join('|');
      """
    )

    self.assertEqual(
      result,
      "fff|?bg-color=fff&width=640&canvas=100%3A50|https://example.com/path?bg-color=fff&width=640&canvas=100%3A50#top",
    )

  def test_link_elements_dispatch_load_when_inserted(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const link = document.createElement('link');
      link.href = '/styles.css';
      link.rel = 'stylesheet';
      link.addEventListener('load', () => {
        document.querySelector('main').textContent = 'loaded';
      });
      document.head.appendChild(link);
      """
    )

    self.assertEqual(document.body_text(), "loaded")

  def test_append_child_does_not_create_dom_cycles(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      const section = document.createElement('section');
      const article = document.createElement('article');
      main.appendChild(section);
      section.appendChild(article);
      article.appendChild(section);
      [main.childElementCount, section.childElementCount, article.childElementCount].join('|');
      """
    )

    self.assertEqual(result, "1|1|0")

  def test_updates_location_via_history_and_assign(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      history.replaceState({ ok: true }, '', '/alpha?x=1#top');
      const first = [location.pathname, location.search, location.hash, String(history.state.ok)].join('|');
      location.assign('/beta');
      const second = [location.pathname, location.search, location.hash].join('|');
      first + '::' + second;
      """
    )

    self.assertEqual(result, "/alpha|?x=1|#top|true::/beta||")

  def test_supports_image_and_canvas_shims(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const canvas = document.createElement('canvas');
      canvas.width = 8;
      canvas.height = 6;
      const ctx = canvas.getContext('2d');
      const image = new Image();
      image.addEventListener('load', () => {
        document.body.setAttribute('data-image-loaded', '1');
      });
      const blobUrl = URL.createObjectURL({ kind: 'blob' });
      image.src = blobUrl;
      URL.revokeObjectURL(blobUrl);
      const data = ctx.getImageData(0, 0, 2, 3);
      [
        String(image.complete),
        String(data.width),
        String(data.height),
        String(canvas.toDataURL().startsWith('data:image/png;base64,')),
      ].join('|');
      """
    )

    self.assertEqual(result, "true|2|3|true")
    self.assertEqual(document.body.get("data-image-loaded"), "1")

  def test_supports_microtask_and_message_apis(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const channel = new MessageChannel();
      channel.port1.onmessage = (event) => {
        document.body.setAttribute('data-channel', String(event.data));
      };
      window.addEventListener('message', (event) => {
        document.body.setAttribute('data-window-message', String(event.data));
      });
      queueMicrotask(() => {
        document.body.setAttribute('data-microtask', '1');
      });
      channel.port2.postMessage('from-channel');
      window.postMessage('from-window', '*');
      [
        typeof queueMicrotask,
        typeof postMessage,
        typeof MessageChannel,
        typeof setImmediate,
      ].join('|');
      """
    )

    self.assertEqual(result, "function|function|function|undefined")
    self.assertEqual(document.body.get("data-microtask"), "1")
    self.assertEqual(document.body.get("data-channel"), "from-channel")
    self.assertEqual(document.body.get("data-window-message"), "from-window")

  def test_supports_blob_worker_message_roundtrip(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const workerUrl = URL.createObjectURL(new Blob([`
        self.addEventListener('message', (event) => {
          postMessage('reply:' + event.data);
        });
        postMessage('ready');
      `], { type: 'text/javascript' }));
      const worker = new Worker(workerUrl);
      const seen = [];
      worker.addEventListener('message', (event) => {
        seen.push(String(event.data));
        document.body.setAttribute('data-worker-messages', seen.join('|'));
        if (event.data === 'ready') {
          worker.postMessage('ping');
          URL.revokeObjectURL(workerUrl);
        }
      });
      'ok';
      """
    )

    self.assertEqual(result, "ok")
    self.assertEqual(document.body.get("data-worker-messages"), "ready|reply:ping")

  def test_preserves_expando_properties_on_nodes(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      const state = { ok: true };
      main.__vue__ = state;
      main._internalFlag = 42;
      [
        String(main.__vue__ === state),
        String(main._internalFlag),
        String(main.getAttribute('__vue__')),
        String(main.getAttribute('_internal-flag')),
      ].join('|');
      """
    )

    self.assertEqual(result, "true|42|null|null")

  def test_supports_browser_utility_apis(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      const event = document.createEvent('Event');
      event.initEvent('custom', true, true);
      const controller = new AbortController();
      controller.abort('stop');
      [
        svg.namespaceURI,
        event.type,
        String(event.bubbles),
        String(controller.signal.aborted),
        typeof performance.now,
        typeof window.getSelection,
        String(navigator.onLine),
        String(navigator.webdriver),
        typeof crypto.randomUUID,
        typeof TextEncoder,
      ].join('|');
      """
    )

    self.assertEqual(
      result,
      "http://www.w3.org/2000/svg|custom|true|true|function|function|true|false|function|function",
    )

  def test_supports_crypto_subtle_digest(self) -> None:
    document = self.load_document()

    scheduled = document.execute_script(
      """
      (async () => {
        const bytes = new TextEncoder().encode('abc');
        const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
        document.body.textContent = Array.from(digest.slice(0, 4)).join(',');
      })();
      'scheduled';
      """
    )

    self.assertEqual(scheduled, "scheduled")
    self.assertEqual(document.body_text(), "186,120,22,191")

  def test_event_stop_immediate_propagation_and_composed_path(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      const calls = [];
      main.addEventListener('custom', (event) => {
        calls.push('first');
        event.stopImmediatePropagation();
      });
      main.addEventListener('custom', () => {
        calls.push('second');
      });
      const event = new Event('custom', { bubbles: true, composed: true });
      main.dispatchEvent(event);
      [
        calls.join(','),
        String(event.cancelBubble),
        event.composedPath().map((entry) => entry === window ? 'WINDOW' : entry.nodeName).join('>'),
      ].join('|');
      """
    )

    self.assertEqual(result, "first|true|MAIN>BODY>HTML>#document>WINDOW")

  def test_intersection_observer_invokes_callback(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const target = document.querySelector('main');
      const observer = new IntersectionObserver((entries) => {
        document.body.setAttribute('data-intersecting', String(entries[0].isIntersecting));
      });
      observer.observe(target);
      """
    )

    self.assertEqual(document.body.get("data-intersecting"), "true")

  def test_mutation_observer_receives_attribute_and_child_list_records(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const main = document.querySelector('main');
      const seen = [];
      const observer = new MutationObserver((records) => {
        seen.push(records.map((record) => record.type + ':' + (record.attributeName || '')).join(','));
        document.body.setAttribute('data-mutations', seen.join('|'));
      });
      observer.observe(main, { attributes: true, childList: true });
      main.setAttribute('data-state', 'ready');
      const child = document.createElement('span');
      child.textContent = 'added';
      main.appendChild(child);
      """
    )

    result = document.body.get("data-mutations")
    self.assertIn("attributes:data-state", result)
    self.assertIn("childList:", result)

  def test_node_contains_falls_back_for_node_like_prototype_targets(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const child = document.querySelector('main');
      const target = Object.create(Node.prototype);
      target.childNodes = [child];
      [target.contains(child), target.contains(document.body)].join('|');
      """
    )

    self.assertEqual(result, "true|false")

  def test_supports_attribute_methods_and_matches(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const main = document.querySelector('main');
      main.setAttributeNS(null, 'data-state', 'active');
      const before = String(main.hasAttribute('data-state'));
      const matched = String(main.matches('main[data-state=\"active\"]'));
      main.removeAttributeNS(null, 'data-state');
      [before, matched, String(main.hasChildNodes())].join('|');
      """
    )

    self.assertEqual(result, "true|true|true")

  def test_splits_top_level_js_items_with_regex_and_templates(self) -> None:
    items = _split_top_level_js_items(
      "1,function(){return /a[b,c]/.test(`x,${1+2}`)},'x,y'"
    )

    self.assertEqual(len(items), 3)
    self.assertEqual(items[0], "1")
    self.assertIn("/a[b,c]/", items[1])
    self.assertEqual(items[2], "'x,y'")

  def test_supports_webpack_jsonp_chunk_fallback(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body><main id="app"></main></body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document)

    runtime.eval(
      """
      window.webpackJsonp = [];
      window.webpackJsonp.push = function(payload) {
        const modules = payload[1];
        const module = { exports: {} };
        modules[2](module, module.exports, function() {});
      };
      """
    )
    runtime._eval_webpack_jsonp_bundle(
      """
      (window.webpackJsonp=window.webpackJsonp||[]).push([[7],[,,function(module){
        const target = document.querySelector('#app');
        target.textContent = `loaded,${/a[b,c]/.test('abc')}`;
      }]]);
      """
    )

    self.assertEqual(document.body_text(), "loaded,true")

  def test_eval_with_fallback_handles_webpack_jsonp_stack_underflow_path(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body><main id="app"></main></body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document)

    runtime.eval(
      """
      window.webpackJsonp = [];
      window.webpackJsonp.push = function(payload) {
        const modules = payload[1];
        const module = { exports: {} };
        modules[2](module, module.exports, function() {});
      };
      """
    )

    handled = runtime._eval_with_fallback(
      """
      (window.webpackJsonp=window.webpackJsonp||[]).push([[7],[,,function(module){
        document.querySelector('#app').textContent = 'loaded';
      }]]);
      """,
      source_url=None,
      drain_timers=True,
      error=Exception("InternalError: stack underflow"),
    )

    self.assertTrue(handled)
    self.assertEqual(document.body_text(), "loaded")

  def test_retries_nullish_string_receiver_methods(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body><main id="app"></main></body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document)

    runtime.eval(
      """
      var title;
      document.querySelector('#app').textContent =
        '[' + ''.concat(title.charAt(0).toUpperCase()).concat(title.slice(1)) + ']';
      """
    )

    self.assertEqual(document.body_text(), "[]")

  def test_retries_nullish_string_receiver_methods_in_clean_context_when_dirty_retry_is_poisoned(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body><main id="app"></main></body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document)

    runtime.eval(
      """
      if (!window.__bundleLoaded) {
        window.__bundleLoaded = true;
        var title;
        title.charAt(0);
      } else {
        throw new Error('only one instance of babel-polyfill is allowed');
      }
      document.querySelector('#app').textContent = 'loaded';
      """
    )

    self.assertEqual(document.body_text(), "loaded")

  def test_execute_embedded_scripts_exposes_current_script_src(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      script_path.write_text(
        "document.body.textContent = document.currentScript.src;",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      path = urlparse(document.body_text()).path
      self.assertTrue(path.endswith("/embedded.js"))
      self.assertIn(script_path.parent.name, path)

  def test_execute_embedded_scripts_preemptively_safeguards_external_string_receivers(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      script_path.write_text(
        "window.pickInitial = function(value) { return value.charAt(0); };",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script src="{script_path.name}"></script>
            <script>document.body.textContent = '[' + window.pickInitial(undefined) + ']';</script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body_text(), "[]")

  def test_patch_import_meta_rewrites_url_access(self) -> None:
    rewritten = _patch_import_meta(
      "document.body.textContent = import.meta.url;",
      source_url="https://example.com/assets/app.js",
    )

    self.assertIn("https://example.com/assets/app.js", rewritten)
    self.assertNotIn("import.meta", rewritten)

  def test_execute_embedded_scripts_patches_import_meta_in_external_script(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      script_path.write_text(
        "document.body.textContent = import.meta.url;",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertIn("/embedded.js", document.body_text())

  def test_patch_esm_exports_removes_export_keywords(self) -> None:
    rewritten = _patch_esm_exports(
      "export const answer = 42; export default answer; export { answer };"
    )

    self.assertNotIn("export", rewritten)
    self.assertIn("const answer = 42;", rewritten)

  def test_execute_embedded_scripts_patches_export_in_external_script(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      script_path.write_text(
        "export const answer = 42; document.body.textContent = String(answer);",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body_text(), "42")

  def test_execute_embedded_scripts_loads_external_module_graph(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir_path = Path(tmpdir)
      (tmpdir_path / "dep.js").write_text(
        "export const answer = 42;",
        encoding="utf-8",
      )
      (tmpdir_path / "app.js").write_text(
        'import{answer as a}from"./dep.js";document.body.textContent=String(a);',
        encoding="utf-8",
      )
      resource = Resource(
        source=str(tmpdir_path / "index.html"),
        content="""
        <html>
          <body>
            <script type="module" src="app.js"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body_text(), "42")

  def test_execute_embedded_scripts_supports_dynamic_import_in_external_module(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir_path = Path(tmpdir)
      (tmpdir_path / "dep.js").write_text(
        "const answer=42;export{answer as default};",
        encoding="utf-8",
      )
      (tmpdir_path / "app.js").write_text(
        'import("./dep.js").then((mod)=>{document.body.textContent=String(mod.default);});',
        encoding="utf-8",
      )
      resource = Resource(
        source=str(tmpdir_path / "index.html"),
        content="""
        <html>
          <body>
            <script type="module" src="app.js"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body_text(), "42")

  def test_script_text_content_preserves_raw_json_payload(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <script id="payload" type="application/json">{"message":"hello","items":[1,2,3]}</script>
            </body>
          </html>
          """,
        )
      )
    )
    runtime = QuickJSRuntime(document.document)

    text = runtime.eval(
      "document.getElementById('payload').textContent;",
      drain_timers=False,
    )

    self.assertEqual(text, '{"message":"hello","items":[1,2,3]}')

  def test_script_text_content_can_be_json_parsed_by_runtime_code(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <main id="app"></main>
              <script id="payload" type="application/json">{"message":"hello","items":[1,2,3]}</script>
              <script>
                const payload = JSON.parse(document.getElementById('payload').textContent);
                document.getElementById('app').textContent = payload.message + ':' + payload.items.length;
              </script>
            </body>
          </html>
          """,
        )
      )
    )

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.find("main", attrs={"id": "app"}).text, "hello:3")

  def test_get_elements_by_tag_name_uses_document_fast_path(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <main id="app"></main>
              <section><div>A</div></section>
              <div>B</div>
            </body>
          </html>
          """,
        )
      )
    )
    runtime = QuickJSRuntime(document.document)

    result = runtime.eval(
      """
      const divs = document.getElementsByTagName('div');
      [divs.length, divs[0].textContent, divs[1].textContent].join('|');
      """,
      drain_timers=False,
    )

    self.assertEqual(result, "2|A|B")

  def test_get_elements_by_tag_name_uses_subtree_fast_path(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <main id="app">
                <div>outside</div>
                <section id="scope"><div>inside-one</div><span><div>inside-two</div></span></section>
              </main>
            </body>
          </html>
          """,
        )
      )
    )
    runtime = QuickJSRuntime(document.document)

    result = runtime.eval(
      """
      const scope = document.getElementById('scope');
      const divs = scope.getElementsByTagName('div');
      [divs.length, divs[0].textContent, divs[1].textContent].join('|');
      """,
      drain_timers=False,
    )

    self.assertEqual(result, "2|inside-one|inside-two")

  def test_compare_document_position_marks_detached_nodes_disconnected(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const left = document.createElement('fieldset');
      const right = document.createElement('fieldset');
      String(
        (left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_DISCONNECTED) !== 0
      );
      """
    )

    self.assertEqual(result, "true")

  def test_compare_document_position_preserves_document_order(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const first = document.createElement('section');
      const second = document.createElement('section');
      document.body.appendChild(first);
      document.body.appendChild(second);
      [
        String(first.compareDocumentPosition(second)),
        String(second.compareDocumentPosition(first)),
      ].join('|');
      """
    )

    self.assertEqual(result, "4|2")

  def test_installs_jquery_legacy_load_shorthand_shim(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      window.jQuery = function(target) {
        const instance = Object.create(window.jQuery.fn);
        instance.target = target;
        instance.length = 1;
        return instance;
      };
      window.jQuery.fn = {
        on(eventName, handler) {
          window.__lastOn = [eventName, typeof handler];
          return this;
        },
        trigger(eventName) {
          window.__lastTrigger = eventName;
          return this;
        },
        load(url, params, callback) {
          window.__lastLoad = [typeof url, String(url), typeof callback];
          return this;
        },
      };
      window.$ = window.jQuery;
      """
    )

    event_result = document.execute_script(
      """
      $(window).load(function() {});
      JSON.stringify([window.__lastOn, window.__lastLoad || null, $.fn.__twebLegacyShimsInstalled]);
      """
    )
    ajax_result = document.execute_script(
      """
      $('#header').load('/fragment.html', null, function() {});
      JSON.stringify([window.__lastLoad, window.__lastTrigger || null]);
      """
    )

    self.assertEqual(
      event_result,
      '[[\"load\",\"function\"],null,true]',
    )
    self.assertEqual(
      ajax_result,
      '[[\"string\",\"/fragment.html\",\"function\"],null]',
    )

  def test_exposes_window_named_properties_for_element_ids(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <div id="emergency"></div>
            </body>
          </html>
          """,
        )
      )
    )
 
    result = document.execute_script(
      """
      JSON.stringify([
        typeof emergency,
        window.emergency === document.getElementById('emergency'),
        emergency === document.getElementById('emergency'),
      ]);
      """
    )

    self.assertEqual(result, '["object",true,true]')

  def test_exposes_window_named_properties_for_element_names(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <form name="searchForm"></form>
            </body>
          </html>
          """,
        )
      )
    )

    result = document.execute_script(
      """
      JSON.stringify([
        typeof searchForm,
        window.searchForm === document.getElementsByName('searchForm')[0],
        searchForm === document.getElementsByName('searchForm')[0],
      ]);
      """
    )

    self.assertEqual(result, '["object",true,true]')

  def test_exposes_window_named_properties_on_name_heavy_documents(self) -> None:
    controls = "\n".join(
      f'<input type="hidden" name="field{i}" value="{i}">'
      for i in range(600)
    )
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content=f"""
          <html>
            <body>
              <form name="searchForm"></form>
              {controls}
            </body>
          </html>
          """,
        )
      )
    )

    result = document.execute_script(
      """
      JSON.stringify([
        typeof searchForm,
        searchForm === document.getElementsByName('searchForm')[0],
        field599 === document.getElementsByName('field599')[0],
      ]);
      """
    )

    self.assertEqual(result, '["object",true,true]')

  def test_document_get_elements_by_name_uses_dom_lookup_cache(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)
    message_id = json.loads(runtime._get_elements_by_class_name("message"))[0]
    runtime._set_attribute(message_id, "name", "messageCard")

    first = json.loads(runtime._get_elements_by_name("messageCard"))
    second = json.loads(runtime._get_elements_by_name("messageCard"))
    counts = runtime.performance_summary()["counts"]

    self.assertEqual(second, first)
    self.assertEqual(counts.get("dom_lookup_cache_misses"), 2)
    self.assertEqual(counts.get("dom_lookup_cache_hits"), 1)

  def test_document_forms_and_form_elements_expose_named_controls(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <form id="search-form" name="searchForm">
                <input type="search" name="q" value="hello">
                <button type="submit" name="go" value="1">Go</button>
              </form>
            </body>
          </html>
          """,
        )
      )
    )

    result = document.execute_script(
      """
      const forms = document.forms;
      const form = forms.namedItem('searchForm');
      const elements = form.elements;
      JSON.stringify([
        forms.length,
        form === document.getElementById('search-form'),
        elements.length,
        elements.namedItem('q').value,
        elements.namedItem('go').value,
      ]);
      """
    )

    self.assertEqual(result, '[1,true,2,"hello","1"]')

  def test_select_options_selected_index_and_value_behave_like_dom_collection(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <form>
                <select id="pref">
                  <option value="hokkaido">北海道</option>
                  <option value="tokyo" selected>東京都</option>
                  <option>大阪府</option>
                </select>
              </form>
            </body>
          </html>
          """,
        )
      )
    )

    result = document.execute_script(
      """
      const select = document.getElementById('pref');
      const options = select.options;
      const before = [
        options.length,
        options.item(1).value,
        options.namedItem('pref'),
        select.selectedIndex,
        select.value,
        select.selectedOptions.length,
        select.selectedOptions[0].text,
        options[2].value,
        options[2].index
      ];
      select.value = 'hokkaido';
      const after = [select.selectedIndex, select.selectedOptions[0].value];
      JSON.stringify([before, after, select.form === document.querySelector('form')]);
      """
    )

    self.assertEqual(
      result,
      '[[3,"tokyo",null,1,"tokyo",1,"東京都","大阪府",2],[0,"hokkaido"],true]',
    )

  def test_select_add_and_remove_update_options_and_selected_state(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com/",
          content="""
          <html>
            <body>
              <select id="pref">
                <option value="tokyo">東京都</option>
              </select>
            </body>
          </html>
          """,
        )
      )
    )

    result = document.execute_script(
      """
      const select = document.getElementById('pref');
      const inserted = document.createElement('option');
      inserted.value = 'osaka';
      inserted.text = '大阪府';
      select.add(inserted);
      const first = document.createElement('option');
      first.value = 'hokkaido';
      first.text = '北海道';
      select.add(first, 0);
      select.options[2].selected = true;
      const beforeRemove = [
        select.options.length,
        select.options[0].value,
        select.options[1].value,
        select.options[2].selected,
        select.selectedIndex,
        select.value
      ];
      select.remove(1);
      const afterRemove = [
        select.options.length,
        select.options[0].value,
        select.options[1].value,
        select.selectedIndex,
        select.value
      ];
      JSON.stringify([beforeRemove, afterRemove]);
      """
    )

    self.assertEqual(
      result,
      '[[3,"hokkaido","tokyo",true,2,"osaka"],[2,"hokkaido","osaka",1,"osaka"]]',
    )

  def test_execute_embedded_scripts_delays_module_until_nuxt_payload_and_config_exist(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir_path = Path(tmpdir)
      (tmpdir_path / "app.js").write_text(
        """
        const payload = JSON.parse(document.getElementById('__NUXT_DATA__').textContent);
        const serviceType = window.__NUXT__.config.public.serviceType;
        document.getElementById('app').textContent = payload.path + '|' + serviceType;
        """,
        encoding="utf-8",
      )
      resource = Resource(
        source=str(tmpdir_path / "index.html"),
        content="""
        <html>
          <body>
            <main id="app"></main>
            <script type="module" src="app.js"></script>
            <script id="__NUXT_DATA__" type="application/json">{"path":"/library"}</script>
            <script>
              window.__NUXT__ = {
                config: {
                  public: {
                    serviceType: "hp"
                  }
                }
              };
            </script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.find("main", attrs={"id": "app"}).text, "/library|hp")

  @patch("tweb.js_runtime.subprocess.run")
  def test_external_script_preflight_safe_tolerates_positive_exit_codes(self, mock_run: Mock) -> None:
    mock_run.return_value = Mock(returncode=1)
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    self.assertTrue(runtime.external_script_preflight_safe("window.test = true;"))

  @patch("tweb.js_runtime.subprocess.run")
  def test_external_script_preflight_safe_rejects_signal_termination(self, mock_run: Mock) -> None:
    mock_run.return_value = Mock(returncode=-11)
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    self.assertFalse(runtime.external_script_preflight_safe("window.test = true;"))

  @patch("tweb.js_runtime.subprocess.run")
  def test_script_preflight_safe_rejects_signal_termination(self, mock_run: Mock) -> None:
    mock_run.return_value = Mock(returncode=-11)
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    self.assertFalse(runtime.script_preflight_safe("window.test = true;"))

  @patch("tweb.js_runtime.subprocess.run")
  def test_script_preflight_safe_trims_prior_sources_payload(self, mock_run: Mock) -> None:
    mock_run.return_value = Mock(returncode=0)
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)
    prior_sources = [
      "window.s1 = 'a';",
      "window.s2 = 'b';",
      "window.s3 = 'c';",
      "window.s4 = 'd';",
      "window.s5 = 'e';",
      "window.s6 = 'f';",
    ]

    self.assertTrue(runtime.script_preflight_safe("window.test = true;", prior_sources=prior_sources))

    payload = json.loads(mock_run.call_args.kwargs["input"])
    self.assertEqual(
      payload["prior_sources"],
      [
        "window.s3 = 'c';",
        "window.s4 = 'd';",
        "window.s5 = 'e';",
        "window.s6 = 'f';",
      ],
    )

  @patch("tweb.js_runtime.subprocess.run")
  def test_script_preflight_safe_reuses_cached_result(self, mock_run: Mock) -> None:
    mock_run.return_value = Mock(returncode=0)
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)
    prior_sources = ["window.before = true;"]

    self.assertTrue(runtime.script_preflight_safe("window.test = true;", prior_sources=prior_sources))
    self.assertTrue(runtime.script_preflight_safe("window.test = true;", prior_sources=prior_sources))

    mock_run.assert_called_once()

  @patch.object(QuickJSRuntime, "eval")
  @patch.object(QuickJSRuntime, "script_preflight_safe", return_value=False)
  def test_execute_script_rejects_preflight_crash_risk(
    self,
    _mock_preflight: Mock,
    mock_eval: Mock,
  ) -> None:
    document = self.load_document()

    with self.assertRaisesRegex(JavaScriptRuntimeError, "memory limit exceeded"):
      document.execute_script(
        """
        const chunks = [];
        while (true) {
          chunks.push('x'.repeat(1000));
        }
        """
      )

    mock_eval.assert_not_called()

  @patch.object(QuickJSRuntime, "external_script_preflight_safe", return_value=False)
  def test_execute_embedded_scripts_skips_external_script_when_preflight_detects_crash(self, _mock_preflight: Mock) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      padded_payload = "x" * 5000
      script_path.write_text(
        "const payload = JSON.parse("
        f"'{json.dumps({'note': padded_payload})}'"
        ");\n"
        "document.body.textContent = payload.note || 'should not run';\n",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <p>safe body</p>
            <script src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=True, session=Mock())

      self.assertIn("safe body", document.body_text())
      self.assertNotIn("should not run", document.body_text())
      debug = document.javascript_debug() or {}
      counts = dict(debug.get("counts", {}))
      self.assertEqual(counts.get("embedded_preflight_skips"), 1)

  @patch.object(QuickJSRuntime, "external_script_preflight_safe", return_value=False)
  def test_execute_embedded_scripts_preflights_medium_large_external_script_before_eval(self, _mock_preflight: Mock) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      script_path.write_text(
        "document.body.setAttribute('data-dangerous', '1');/*" + ("x" * (128 * 1024)) + "*/",
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <p>safe body</p>
            <script src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=True, session=Mock())

      self.assertIn("safe body", document.body_text())
      self.assertIsNone(document.body.get("data-dangerous"))
      debug = document.javascript_debug() or {}
      counts = dict(debug.get("counts", {}))
      self.assertEqual(counts.get("embedded_preflight_skips"), 1)

  def test_anchor_element_exposes_resolved_url_parts(self) -> None:
    resource = Resource(
      source="https://example.com/article/detail/?id=42",
      content="""
      <html>
        <body></body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document)

    result = json.loads(
      runtime.eval(
        """
        (function() {
          const link = document.createElement('a');
          link.href = '/json_svc/catari_detail/?topics_id=17815#body';
          return JSON.stringify({
            href: link.href,
            protocol: link.protocol,
            host: link.host,
            hostname: link.hostname,
            pathname: link.pathname,
            search: link.search,
            hash: link.hash,
            origin: link.origin,
          });
        })()
        """,
        drain_timers=False,
      )
    )

    self.assertEqual(result["href"], "https://example.com/json_svc/catari_detail/?topics_id=17815#body")
    self.assertEqual(result["protocol"], "https:")
    self.assertEqual(result["host"], "example.com")
    self.assertEqual(result["hostname"], "example.com")
    self.assertEqual(result["pathname"], "/json_svc/catari_detail/")
    self.assertEqual(result["search"], "?topics_id=17815")
    self.assertEqual(result["hash"], "#body")
    self.assertEqual(result["origin"], "https://example.com")

  def test_execute_embedded_scripts_shares_global_state(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>window.sharedCounter = 41;</script>
          <script>document.body.textContent = String(window.sharedCounter + 1);</script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body_text(), "42")

  def test_execute_embedded_scripts_dispatches_dom_content_loaded_after_scripts(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            document.addEventListener('DOMContentLoaded', () => {
              document.body.setAttribute('data-ready', window.sharedCounter + ':' + document.readyState);
            });
          </script>
          <script>
            window.sharedCounter = 'ready';
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body.get("data-ready"), "ready:interactive")

  def test_dispatch_page_events_short_circuits_without_post_dom_lifecycle_interest(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            document.addEventListener('DOMContentLoaded', () => {
              document.body.setAttribute('data-ready', document.readyState);
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document)
    runtime.eval(
      """
      document.addEventListener('DOMContentLoaded', () => {
        document.body.setAttribute('data-ready', document.readyState);
      });
      """,
      drain_timers=False,
    )

    with patch.object(runtime, "_drain_async_work", wraps=runtime._drain_async_work) as mock_drain:
      runtime.dispatch_page_events()

    self.assertEqual(document.body.get("data-ready"), "interactive")
    self.assertEqual(runtime.eval("document.readyState"), "complete")
    self.assertEqual(mock_drain.call_count, 1)

  def test_dispatch_dom_content_loaded_short_circuits_without_listener_interest(self) -> None:
    document = TWebDocument(
      parse_document(Resource(source="inline", content="<html><body><main>content</main></body></html>"))
    )
    runtime = QuickJSRuntime(document.document)

    with patch.object(runtime, "_drain_async_work", wraps=runtime._drain_async_work) as mock_drain:
      runtime.dispatch_dom_content_loaded()

    self.assertEqual(runtime.eval("document.readyState"), "interactive")
    self.assertEqual(mock_drain.call_count, 0)

  def test_dispatch_page_events_reuses_lifecycle_interest_snapshot(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="inline",
          content="""
          <html>
            <body>
              <script>
                document.addEventListener('DOMContentLoaded', () => {
                  document.body.setAttribute('data-ready', document.readyState);
                });
              </script>
            </body>
          </html>
          """,
        )
      )
    )
    runtime = QuickJSRuntime(document.document)
    runtime.eval(
      """
      document.addEventListener('DOMContentLoaded', () => {
        document.body.setAttribute('data-ready', document.readyState);
      });
      """,
      drain_timers=False,
    )

    with patch.object(runtime, "lifecycle_event_interest", wraps=runtime.lifecycle_event_interest) as mock_interest:
      runtime.dispatch_page_events()

    self.assertEqual(document.body.get("data-ready"), "interactive")
    self.assertEqual(runtime.eval("document.readyState"), "complete")
    self.assertEqual(mock_interest.call_count, 1)

  def test_execute_embedded_scripts_does_not_stop_after_two_stable_timers(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            setTimeout(() => {}, 0);
            setTimeout(() => {}, 0);
            setTimeout(() => {}, 0);
            setTimeout(() => { document.body.setAttribute('data-after-stable-timers', 'loaded'); }, 0);
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body.get("data-after-stable-timers"), "loaded")

  def test_async_drain_stops_after_unbounded_stable_timers(self) -> None:
    document = TWebDocument(
      parse_document(
        Resource(
          source="https://example.com",
          content="<html><body><main>before</main></body></html>",
        )
      )
    )
    runtime = QuickJSRuntime(document.document)
    runtime._ctx = Mock()
    timer_calls = {"count": 0}

    def fake_eval(source: str):
      if "__twebGetCurrentTime();" in source:
        return 0
      if "__twebRunNextTimer(" in source:
        timer_calls["count"] += 1
        return timer_calls["count"] <= ASYNC_DRAIN_STABLE_TIMER_EARLY_STOP_STEPS
      return False

    runtime._ctx.eval = Mock(side_effect=fake_eval)
    runtime._execute_pending_job = Mock(return_value=False)

    runtime._drain_async_work()

    self.assertEqual(timer_calls["count"], ASYNC_DRAIN_STABLE_TIMER_EARLY_STOP_STEPS)
    self.assertEqual(runtime.performance_summary()["counts"]["async_drain_early_stops"], 1)

  def test_execute_embedded_scripts_loads_appended_external_script_once(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      dynamic_path = Path(tmpdir) / "dynamic.js"
      dynamic_path.write_text(
        """
        window.dynamicLoadCount = (window.dynamicLoadCount || 0) + 1;
        document.body.setAttribute('data-dynamic-load-count', String(window.dynamicLoadCount));
        """,
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script>
              const script = document.createElement('script');
              script.src = '{dynamic_path.name}';
              document.body.appendChild(script);
            </script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body.get("data-dynamic-load-count"), "1")

  @patch("tweb.js_runtime.fetch_resource")
  def test_execute_embedded_scripts_skips_appended_third_party_external_script(self, mock_fetch_resource: Mock) -> None:
    resource = Resource(
      source="https://example.com/index.html",
      content="""
      <html>
        <body>
          <script>
            const script = document.createElement('script');
            script.src = 'https://thirdparty.example.net/dynamic.js';
            document.body.appendChild(script);
            document.body.setAttribute('data-finished', '1');
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    mock_fetch_resource.assert_not_called()
    self.assertEqual(document.body.get("data-finished"), "1")

  @patch("tweb.js_runtime.fetch_resource")
  def test_execute_embedded_scripts_keeps_appended_same_site_external_script(self, mock_fetch_resource: Mock) -> None:
    mock_fetch_resource.return_value = Resource(
      source="https://cdn.example.co.jp/dynamic.js",
      content="document.body.setAttribute('data-dynamic', 'same-site');",
    )
    resource = Resource(
      source="https://example.co.jp/index.html",
      content="""
      <html>
        <body>
          <script>
            const script = document.createElement('script');
            script.src = 'https://cdn.example.co.jp/dynamic.js';
            document.body.appendChild(script);
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    mock_fetch_resource.assert_called_once_with(
      "https://cdn.example.co.jp/dynamic.js",
      session=ANY,
      request_headers=None,
    )
    self.assertEqual(document.body.get("data-dynamic"), "same-site")

  def test_dom_content_loaded_listener_uses_document_as_this(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            document.addEventListener('DOMContentLoaded', function () {
              document.body.setAttribute('data-this-is-document', String(this === document));
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body.get("data-this-is-document"), "true")

  def test_dom_content_loaded_error_includes_callback_label(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            document.addEventListener('DOMContentLoaded', () => {
              throw new Error('boom');
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    with self.assertRaisesRegex(JavaScriptRuntimeError, r"boom \[callback=event:DOMContentLoaded\]"):
      document.execute_embedded_scripts(ignore_errors=False)

  def test_execute_embedded_scripts_ignores_interrupted_page_event_when_allowed(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            document.addEventListener('DOMContentLoaded', () => {
              document.body.setAttribute('data-started', '1');
              for (let i = 0; i < 1e9; i += 1) {}
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    with patch("tweb.js_runtime.PAGE_EVENT_TIME_LIMIT_SECONDS", 0.01):
      document.execute_embedded_scripts(ignore_errors=True)

    self.assertIsNotNone(document.body)

  def test_dispatch_page_events_can_continue_after_callback_error(self) -> None:
    document = TWebDocument(
      parse_document(Resource(source="inline", content="<html><body></body></html>"))
    )
    runtime = QuickJSRuntime(document.document)
    runtime.eval(
      """
      document.addEventListener('DOMContentLoaded', () => {
        document.body.setAttribute('data-first', '1');
        throw new Error('boom');
      });
      document.addEventListener('DOMContentLoaded', () => {
        document.body.setAttribute('data-second', '1');
      });
      window.addEventListener('load', () => {
        document.body.setAttribute('data-load', '1');
      });
      """,
      drain_timers=False,
    )

    runtime.dispatch_page_events(continue_on_event_callback_error=True)

    self.assertEqual(document.body.get("data-first"), "1")
    self.assertEqual(document.body.get("data-second"), "1")
    self.assertEqual(document.body.get("data-load"), "1")
    self.assertEqual(runtime.eval("document.readyState"), "complete")
    self.assertEqual(runtime._stats.counters.get("ignored_event_callback_errors"), 1)

  def test_execute_embedded_scripts_continues_lifecycle_callbacks_when_ignoring_errors(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            document.addEventListener('DOMContentLoaded', () => {
              const missing = document.getElementById('missing');
              missing.innerHTML = 'boom';
            });
            document.addEventListener('DOMContentLoaded', () => {
              document.body.setAttribute('data-recovered', '1');
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=True)

    self.assertEqual(document.body.get("data-recovered"), "1")

  def test_execute_embedded_scripts_dispatches_readystatechange(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            document.addEventListener('readystatechange', () => {
              document.body.setAttribute('data-state', document.readyState);
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body.get("data-state"), "complete")

  def test_execute_embedded_scripts_dispatches_pageshow_without_spurious_focus_or_visibilitychange(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head><title>Initial Title</title></head>
        <body>
          <script>
            document.addEventListener('visibilitychange', () => {
              document.title = 'Visible Title';
            });
            window.addEventListener('focus', () => {
              document.title = 'Focused Title';
            });
            window.addEventListener('pageshow', () => {
              document.body.setAttribute('data-pageshow', '1');
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body.get("data-pageshow"), "1")
    self.assertEqual(document.title, "Initial Title")

  def test_tracks_event_interest_for_lifecycle_events(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    before = runtime.eval(
      """
      [
        String(__twebTargetHasEventInterest(document, 'DOMContentLoaded')),
        String(__twebTargetHasEventInterest(window, 'pageshow')),
        String(__twebTargetHasEventInterest(document, 'readystatechange'))
      ].join('|');
      """
    )
    runtime.eval(
      """
      document.addEventListener('DOMContentLoaded', () => {});
      window.onpageshow = () => {};
      document.onreadystatechange = () => {};
      """
    )
    after = runtime.eval(
      """
      [
        String(__twebTargetHasEventInterest(document, 'DOMContentLoaded')),
        String(__twebTargetHasEventInterest(window, 'pageshow')),
        String(__twebTargetHasEventInterest(document, 'readystatechange'))
      ].join('|');
      """
    )

    self.assertEqual(before, "false|false|false")
    self.assertEqual(after, "true|true|true")

  def test_lifecycle_event_interest_summary(self) -> None:
    document = self.load_document()
    runtime = QuickJSRuntime(document.document)

    runtime.eval(
      """
      document.addEventListener('DOMContentLoaded', () => {});
      document.addEventListener('load', () => {});
      window.addEventListener('load', () => {});
      window.onpageshow = () => {};
      document.onreadystatechange = () => {};
      """,
      drain_timers=False,
    )

    self.assertEqual(
      runtime.lifecycle_event_interest(),
      {
        "dom_content_loaded": True,
        "document_load": True,
        "window_load": True,
        "pageshow": True,
        "readystatechange": True,
      },
    )

  def test_execute_embedded_scripts_does_not_run_load_timers_during_initial_dispatch(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <head><title>Initial Title</title></head>
        <body>
          <script>
            window.addEventListener('load', () => {
              setTimeout(() => {
                document.title = 'Timer Title';
              }, 0);
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.title, "Initial Title")

  def test_has_pending_timer_detects_ready_post_load_timeout(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            window.addEventListener('load', () => {
              setTimeout(() => {
                document.body.setAttribute('data-post-load', '1');
              }, 0);
            });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document)
    runtime.eval(
      """
      window.addEventListener('load', () => {
        setTimeout(() => {
          document.body.setAttribute('data-post-load', '1');
        }, 0);
      });
      """,
      drain_timers=False,
    )

    runtime.dispatch_page_events()

    self.assertTrue(runtime.has_pending_timer(max_time_advance_ms=250))
    self.assertEqual(runtime.next_pending_timer_delay_ms(), 0)
    self.assertIsNone(document.body.get("data-post-load"))

  def test_dom_content_loaded_limits_recursive_timer_drain(self) -> None:
    links = "".join(f'<a href="/item-{index}">Item {index}</a>' for index in range(300))
    document = TWebDocument(
      parse_document(Resource(source="inline", content=f"<html><body>{links}</body></html>"))
    )
    runtime = QuickJSRuntime(document.document)
    runtime.eval(
      """
      document.addEventListener('DOMContentLoaded', () => {
        let remaining = 30;
        const run = () => {
          document.body.setAttribute('data-timer-count', String(30 - remaining));
          remaining -= 1;
          if (remaining > 0) setTimeout(run, 0);
        };
        setTimeout(run, 0);
      });
      """,
      drain_timers=False,
    )

    runtime.dispatch_dom_content_loaded()

    self.assertEqual(document.body.get("data-timer-count"), "7")
    self.assertTrue(runtime.has_pending_timer(max_time_advance_ms=50))

  def test_execute_embedded_scripts_avoids_draining_far_future_timers(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            setTimeout(() => {
              document.body.setAttribute('data-soon', '1');
            }, 0);
            setTimeout(() => {
              document.body.setAttribute('data-late', '1');
            }, 5000);
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body.get("data-soon"), "1")
    self.assertIsNone(document.body.get("data-late"))

  def test_execute_embedded_scripts_drains_short_idle_callback_chains(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            let runs = 0;
            function pump() {
              runs += 1;
              if (runs < 3) {
                requestIdleCallback(pump);
                return;
              }
              document.body.setAttribute('data-idle-chain', String(runs));
            }
            requestIdleCallback(pump);
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertEqual(document.body.get("data-idle-chain"), "3")

  def test_execute_embedded_scripts_respects_idle_callback_timeout(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <script>
            requestIdleCallback(() => {
              document.body.setAttribute('data-idle-timeout-fired', '1');
            }, { timeout: 5000 });
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    self.assertIsNone(document.body.get("data-idle-timeout-fired"))

  def test_augments_sparse_body_from_hydration_state(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main id="content"></main>
          <script>
            window.__NUXT__ = {
              state: {
                page: {
                  title: 'Hydrated Title',
                  description: 'Hydrated description',
                  topics: [{ name: 'Topic A' }, { name: 'Topic B' }],
                  banner: {
                    title: 'Hydrated Link',
                    url: '/hydrated-link'
                  },
                  grouped: {
                    title: 'Hydrated Group',
                    entries: [{ title: 'Topic A' }, { title: 'Topic B' }]
                  },
                  categoryGroup: {
                    title: 'Hydrated Categories',
                    subCategories: [
                      { title: 'Linked Topic', engName: 'linked/topic' },
                      { title: 'Second Topic', engName: 'second-topic' }
                    ]
                  }
                }
              }
            };
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    text = document.body_text()
    self.assertIn("Hydration Data", text)
    self.assertIn("Hydrated Title", text)
    self.assertIn("Hydrated Group", text)
    self.assertIn("Topic A", text)
    main = document.find("main", attrs={"id": "content"})
    self.assertIsNotNone(main)
    self.assertIn("Hydration Data", main.text)
    headings = [element.text for element in main.find_all("h3")]
    self.assertIn("Hydrated Group", headings)
    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("### Hydrated Group", rendered)
    links = document.links()
    self.assertTrue(any(link.text == "Hydrated Link" and link.href == "/hydrated-link" for link in links))
    self.assertTrue(any(link.text == "Linked Topic" and link.href == "/topic/linked/topic" for link in links))

  def test_replaces_loading_placeholder_inside_main_with_hydration_content(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main class="page">
            <div class="feed-body">
              <div class="loading-dots">
                <div class="loading-dot"></div>
              </div>
            </div>
          </main>
          <script>
            window.__NUXT__ = {
              state: {
                pageData: {
                  title: 'Hydrated Title',
                  categorySections: [
                    {
                      title: 'Hydrated Group',
                      items: [
                        { title: 'Topic A', href: '/topic-a' },
                        { title: 'Topic B', href: '/topic-b' }
                      ]
                    }
                  ]
                }
              }
            };
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    main = document.find("main", attrs={"class": "page"})
    self.assertIsNotNone(main)
    self.assertEqual([child.tag for child in main.node.children if hasattr(child, "tag")], ["div"])
    feed_body = document.find("div", attrs={"class": "feed-body"})
    self.assertIsNotNone(feed_body)
    self.assertNotIn("Hydration Data", feed_body.text)
    headings = [element.text for element in feed_body.find_all("h3")]
    self.assertEqual(headings, ["Hydrated Group"])
    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("### Hydrated Group", rendered)

  def test_splits_navigation_sections_from_loading_body_placeholder(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main class="page">
            <div class="nav-panel"></div>
            <div class="feed-body">
              <div class="loading-dots">
                <div class="loading-dot"></div>
              </div>
            </div>
          </main>
          <script>
            window.__NUXT__ = {
              state: {
                pageData: {
                  title: 'Hydrated Title',
                  featured: [
                    { title: 'Featured A', href: '/featured-a' },
                    { title: 'Featured B', href: '/featured-b' }
                  ],
                  categorySections: [
                    {
                      title: 'Hydrated Group',
                      items: [
                        { title: 'Topic A', href: '/topic-a' },
                        { title: 'Topic B', href: '/topic-b' }
                      ]
                    }
                  ]
                }
              }
            };
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    nav_panel = document.find("div", attrs={"class": "nav-panel"})
    self.assertIsNotNone(nav_panel)
    self.assertIn("Hydrated Group", nav_panel.text)
    self.assertIn("Hydrated Group", [element.text for element in nav_panel.find_all("h3")])
    feed_body = document.find("div", attrs={"class": "feed-body"})
    self.assertIsNotNone(feed_body)
    self.assertNotIn("Hydrated Group", feed_body.text)
    self.assertIn("Featured A", feed_body.text)
    rendered = render_normal(document.document, width=80, text_styles=False)
    self.assertIn("### Hydrated Group", rendered)

  def test_augments_client_script_failure_with_filtered_hydration_state(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <div id="react-root">
            <div>
              <span>Something went wrong, but don’t fret — let’s give it another shot.</span>
              <button>Try again</button>
              <span>Some privacy related extensions may cause issues on x.com.</span>
              <span>Please enable JavaScript or switch to a supported browser to continue.</span>
            </div>
          </div>
          <script>
            window.__INITIAL_STATE__ = {
              timeline: {
                sections: [
                  { title: 'Top Stories' },
                  { title: 'For You' },
                  { title: 'Adobe Firefly' },
                ],
              },
              noise: {
                requestId: 'BF5FA6C8-9668-4AF9-AFA2-E362F56E5B71',
                color: 'rgba(0, 0, 0, 0.5)',
                tween: 'cubic-bezier(0.25, 0.1, 0.25, 1)',
                campaign: '01:twcamp^share|twsrc^android|twgr^sms',
              },
            };
          </script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_embedded_scripts(ignore_errors=False)

    text = document.body_text()
    self.assertIn("Hydration Data", text)
    self.assertIn("Top Stories", text)
    self.assertIn("For You", text)
    self.assertNotIn("BF5FA6C8-9668-4AF9-AFA2-E362F56E5B71", text)
    self.assertNotIn("rgba(0, 0, 0, 0.5)", text)
    self.assertNotIn("01:twcamp^share|twsrc^android|twgr^sms", text)

  def test_supports_existing_dataset_attributes(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main id="app" data-fetch-key="server-value"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_script(
      """
      document.body.textContent = document.getElementById('app').dataset.fetchKey;
      """
    )

    self.assertEqual(document.body_text(), "server-value")

  def test_exposes_dom_exception(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const error = new DOMException('Not allowed', 'SecurityError');
      [error.name, error.message, String(error instanceof Error)].join('|');
      """
    )

    self.assertEqual(result, "SecurityError|Not allowed|true")

  def test_event_exposes_touch_collections(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const event = new Event('touchstart', {
        changedTouches: [{ identifier: 7, clientX: 10, clientY: 20, pageX: 10, pageY: 20 }],
      });
      [
        String(Array.isArray(event.changedTouches)),
        String(Array.isArray(event.touches)),
        String(event.touches.length),
        String(event.targetTouches.length)
      ].join('|');
      """
    )

    self.assertEqual(result, "true|true|1|1")

  def test_exposes_pointer_event(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const event = new PointerEvent('pointerdown', {
        pointerId: 3,
        pointerType: 'mouse',
        clientX: 12,
        clientY: 34,
        isPrimary: true,
      });
      [
        String(event instanceof MouseEvent),
        String(event.pointerId),
        event.pointerType,
        String(event.clientX),
        String(event.isPrimary),
        String(typeof window.PointerEvent)
      ].join('|');
      """
    )

    self.assertEqual(result, "true|3|mouse|12|true|function")

  def test_supports_style_sheet_insert_rule(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const style = document.createElement('style');
      style.appendChild(document.createTextNode('body { margin: 0; }'));
      document.head.appendChild(style);
      style.sheet.insertRule('main { display: flex; }', style.sheet.cssRules.length);
      [
        String(style.sheet.cssRules.length),
        style.sheet.cssRules[0].selectorText,
        style.sheet.cssRules[1].selectorText,
        style.styleSheet.cssText.includes('display: flex')
      ].join('|');
      """
    )

    self.assertEqual(result, "2|body|main|true")

  def test_supports_document_cookie(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      document.cookie = 'guest_id=v1%3A123; Path=/; Domain=.x.com';
      document.cookie = 'lang=en';
      document.cookie;
      """
    )

    self.assertEqual(result, "guest_id=v1%3A123; lang=en")

  def test_document_cookie_persists_scoped_cookies_in_http_session(self) -> None:
    session = Session()
    document = TWebDocument(parse_document(Resource(source="https://example.com/news/article", content="<html></html>")))
    document.execute_script("""
      document.cookie = 'challenge=ok; Path=/news; Secure';
      document.cookie = 'foreign=bad; Domain=other.example';
    """, session=session)
    self.assertEqual(session.cookies.get("challenge"), "ok")
    self.assertIsNone(session.cookies.get("foreign"))
    from requests import Request
    self.assertIn("challenge=ok", session.prepare_request(Request("GET", "https://example.com/news/next")).headers.get("Cookie", ""))
    for target in ["https://example.com/elsewhere", "https://other.example/news/", "http://example.com/news/"]:
      self.assertNotIn("challenge=ok", session.prepare_request(Request("GET", target)).headers.get("Cookie", ""))
    document.execute_script("document.cookie = 'challenge=; Path=/news; Max-Age=0';", session=session)
    self.assertIsNone(session.cookies.get("challenge"))

  def test_seeds_document_cookie_from_session(self) -> None:
    session = Session()
    session.cookies.set("guest_id", "v1%3A123", domain="x.com", path="/")
    resource = Resource(
      source="https://x.com/",
      content="""
      <html>
        <body></body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    runtime = QuickJSRuntime(document.document, session=session)

    self.assertEqual(runtime.eval("document.cookie", drain_timers=False), "guest_id=v1%3A123")

  def test_exposes_intl_locale(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const locale = new Intl.Locale('ar');
      [locale.language, locale.maximize().script, new Intl.PluralRules().select(2)].join('|');
      """
    )

    self.assertEqual(result, "ar|Arab|other")

  def test_exposes_base64_helpers(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      [btoa('hi'), atob('aGk=')].join('|');
      """
    )

    self.assertEqual(result, "aGk=|hi")

  def test_respects_timer_delay_order(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const steps = [];
      setTimeout(() => steps.push('late'), 100);
      setTimeout(() => steps.push('early'), 0);
      Promise.resolve().then(() => steps.push('microtask'));
      setTimeout(() => steps.push('mid'), 10);
      setTimeout(() => {
        document.body.textContent = steps.join('|');
      }, 150);
      """
    )

    self.assertEqual(document.body_text(), "microtask|early|mid|late")

  def test_exposes_dom_methods_on_prototypes(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const section = document.createElement('section');
      const append = Node.prototype.appendChild;
      append.call(document.body, section);
      Element.prototype.setAttribute.call(section, 'data-ready', 'yes');
      [
        String(typeof Node.prototype.appendChild),
        String(typeof Element.prototype.setAttribute),
        String(document.querySelector('section') !== null),
        section.getAttribute('data-ready')
      ].join('|');
      """
    )

    self.assertEqual(result, "function|function|true|yes")

  def test_supports_storage_and_history_globals(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      localStorage.setItem('greeting', 'hello');
      history.replaceState({ page: 2 }, '', '/next');
      document.body.textContent = localStorage.getItem('greeting') + ':' + String(history.state.page);
      """
    )

    self.assertEqual(document.body_text(), "hello:2")

  def test_supports_indexed_db_basics(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const request = indexedDB.open('localforage', 2);
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains('keyvaluepairs')) {
          db.createObjectStore('keyvaluepairs');
        }
      };
      request.onsuccess = (event) => {
        const db = event.target.result;
        const transaction = db.transaction('keyvaluepairs', 'readwrite');
        const store = transaction.objectStore('keyvaluepairs');
        const putRequest = store.put('value', 'key');
        putRequest.onsuccess = () => {
          const getRequest = store.get('key');
          getRequest.onsuccess = () => {
            document.body.textContent = String(getRequest.result);
          };
        };
      };
      typeof indexedDB.open;
      """
    )

    self.assertEqual(result, "function")
    self.assertEqual(document.body_text(), "value")

  def test_indexed_db_transaction_completes_after_chained_requests(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const request = indexedDB.open('localforage', 2);
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains('keyvaluepairs')) {
          db.createObjectStore('keyvaluepairs');
        }
      };
      request.onsuccess = (event) => {
        const db = event.target.result;
        const transaction = db.transaction('keyvaluepairs', 'readwrite');
        const store = transaction.objectStore('keyvaluepairs');
        const parts = [];
        store.put('value', 'key').onsuccess = () => {
          parts.push('put');
          store.get('key').onsuccess = () => {
            parts.push('get');
          };
        };
        transaction.oncomplete = () => {
          parts.push('complete');
          document.body.textContent = parts.join('|');
        };
      };
      """
    )

    self.assertEqual(document.body_text(), "put|get|complete")

  def test_supports_basic_match_media_queries(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      document.body.textContent = [
        String(matchMedia('(min-width: 1024px)').matches),
        String(matchMedia('(max-width: 1023px)').matches),
        String(matchMedia('(orientation: landscape)').matches),
      ].join('|');
      """
    )

    self.assertEqual(document.body_text(), "true|false|true")

  def test_exposes_service_worker_container(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      navigator.serviceWorker.ready.then((registration) => {
        document.body.textContent = [
          String('serviceWorker' in navigator),
          String(typeof navigator.serviceWorker.getRegistrations),
          String(typeof registration.showNotification),
          String(typeof registration.pushManager.getSubscription),
        ].join('|');
      });
      """
    )

    self.assertEqual(
      document.body_text(),
      "true|function|function|function",
    )

  def test_response_array_buffer_preserves_raw_bytes(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      const response = new Response(new Uint8Array([0, 255, 65]));
      response.arrayBuffer().then((buffer) => {
        const bytes = Array.from(new Uint8Array(buffer));
        document.body.textContent = bytes.join('|');
      });
      'ok';
      """
    )

    self.assertEqual(result, "ok")
    self.assertEqual(document.body_text(), "0|255|65")

  def test_exposes_browser_metadata_globals(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      document.body.textContent = [
        navigator.language,
        navigator.platform,
        String(document.hidden),
        String(window.devicePixelRatio),
        String(navigator.plugins.length),
        String(navigator.mimeTypes.length),
        String(typeof navigator.permissions.query),
        String(typeof navigator.storage.getDirectory),
        String(typeof navigator.clipboard.writeText),
        String(typeof navigator.sendBeacon),
        String(Notification.permission),
      ].join('|');
      """
    )

    self.assertEqual(
      document.body_text(),
      "ja-JP|MacIntel|false|1|1|1|function|function|function|function|default",
    )

  def test_polyfilled_array_methods_are_not_enumerable(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const seen = [];
      for (const key in navigator.languages) {
        seen.push(key + ':' + typeof navigator.languages[key]);
      }
      document.body.textContent = [
        String(Object.prototype.propertyIsEnumerable.call(Array.prototype, 'at')),
        seen.join('|'),
      ].join('||');
      """
    )

    self.assertEqual(document.body_text(), "false||0:string|1:string")

  def test_execute_embedded_scripts_handles_wikipedia_style_language_probe(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      script_path = Path(tmpdir) / "embedded.js"
      script_path.write_text(
        """
        function getIso639(value) {
          value = value && value.match(/^\\w+/);
          if (value && !((value = value[0]).length > 3)) {
            return value;
          }
        }
        let langs = [];
        function remember(value) {
          value = getIso639(value);
          if (value && !langs.includes(value)) {
            langs.push(value);
          }
        }
        for (var key in navigator.languages) {
          remember(navigator.languages[key]);
        }
        document.body.textContent = langs.join('|');
        """,
        encoding="utf-8",
      )
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content=f"""
        <html>
          <body>
            <script src="{script_path.name}"></script>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_embedded_scripts(ignore_errors=False, session=Mock())

      self.assertEqual(document.body_text(), "ja")

  def test_reflects_unknown_properties_to_attributes(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <label id="label" for="email" lang="ja"></label>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_script(
      """
      const label = document.getElementById('label');
      label.textContent = [label.htmlFor, label.lang].join('|');
      """
    )

    self.assertEqual(document.body_text(), "email|ja")

  def test_returns_empty_string_for_missing_reflected_property(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      document.body.textContent = document.querySelector('main').placeholder;
      """
    )

    self.assertEqual(document.body_text(), "")

  def test_body_text_ignores_script_text(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <p>Visible text</p>
          <script>window.hiddenPayload = 'ignore me';</script>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    self.assertEqual(document.body_text(), "Visible text")

  def test_create_element_falls_back_for_empty_tag_name(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const node = document.createElement('');
      node.textContent = 'fallback';
      document.body.appendChild(node);
      """
    )

    self.assertIn("fallback", document.body_text())

  def test_unsupported_selector_returns_empty_result(self) -> None:
    document = self.load_document()

    result = document.execute_script(
      """
      String(document.querySelector('div > span') === null) + '|' +
      String(document.querySelectorAll('div > span').length);
      """
    )

    self.assertEqual(result, "true|0")

  def test_supports_get_element_by_id_with_leading_underscore(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main id="__layout"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_script(
      """
      document.getElementById('__layout').textContent = 'found layout';
      """
    )

    self.assertEqual(document.body_text(), "found layout")

  def test_exposes_node_constants(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      document.body.textContent = String(Node.ELEMENT_NODE) + ':' + String(Node.TEXT_NODE);
      """
    )

    self.assertEqual(document.body_text(), "1:3")

  def test_defers_timeout_until_after_current_script(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      window.steps = [];
      setTimeout(() => {
        window.steps.push('timeout');
        document.body.textContent = window.steps.join(',');
      }, 0);
      window.steps.push('sync');
      document.body.textContent = window.steps.join(',');
      """
    )

    self.assertEqual(document.body_text(), "sync,timeout")

  def test_supports_fetch_promise_for_local_resources(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      data_path = Path(tmpdir) / "data.txt"
      data_path.write_text("fetched text", encoding="utf-8")
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body>
            <main id="app"></main>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_script(
        """
        fetch('data.txt')
          .then((response) => response.text())
          .then((text) => {
            document.querySelector('#app').textContent = text;
          });
        """
      )

      self.assertIn("fetched text", document.body_text())

  def test_supports_url_search_params_mutation_helpers(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      const params = new URLSearchParams('a=1&a=2&b=3');
      params.delete('a', '1');
      params.set('b', '4');
      document.querySelector('#title').textContent =
        `${params.get('a')}|${params.getAll('a').length}|${params.has('a', '2')}|${params.get('b')}`;
      """
    )

    self.assertIn("2|1|true|4", document.body_text())

  def test_supports_response_body_stream(self) -> None:
    resource = Resource(
      source="inline",
      content="""
      <html>
        <body>
          <main id="app"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))

    document.execute_script(
      """
      const response = new Response('stream body');
      document.querySelector('#app').textContent = String(typeof response.body.getReader === 'function');
      """
    )

    self.assertIn("true", document.body_text())

  def test_supports_xml_http_request_for_local_resources(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      data_path = Path(tmpdir) / "data.json"
      data_path.write_text('{"message":"hello xhr"}', encoding="utf-8")
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body>
            <main id="app"></main>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      document.execute_script(
        """
        const xhr = new XMLHttpRequest();
        xhr.open('GET', 'data.json');
        xhr.onload = function() {
          const data = JSON.parse(xhr.responseText);
          document.querySelector('#app').textContent = data.message;
        };
        xhr.send();
        """
      )

      self.assertIn("hello xhr", document.body_text())

  def test_supports_xml_http_request_response_type_headers_and_events(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      data_path = Path(tmpdir) / "data.json"
      data_path.write_text('{"message":"hello json xhr"}', encoding="utf-8")
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body>
            <main id="app"></main>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      result = document.execute_script(
        """
        const events = [];
        const xhr = new XMLHttpRequest();
        xhr.responseType = 'json';
        xhr.addEventListener('load', () => events.push('load'));
        xhr.addEventListener('loadend', () => {
          events.push('loadend');
          document.body.textContent = [
            xhr.status,
            xhr.statusText,
            xhr.response.message,
            xhr.getAllResponseHeaders(),
            events.join(',')
          ].join('|');
        });
        xhr.open('GET', 'data.json');
        xhr.send();
        'scheduled';
        """
      )

      self.assertEqual(result, "scheduled")
      self.assertEqual(document.body_text(), "200|OK|hello json xhr||load,loadend")

  def test_supports_xml_http_request_document_response_and_override_mime_type(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
      data_path = Path(tmpdir) / "fragment.html"
      data_path.write_text('<html><body><div id="loaded">ok</div></body></html>', encoding="utf-8")
      resource = Resource(
        source=str(Path(tmpdir) / "index.html"),
        content="""
        <html>
          <body>
            <main id="app"></main>
          </body>
        </html>
        """,
      )
      document = TWebDocument(parse_document(resource))

      result = document.execute_script(
        """
        const xhr = new XMLHttpRequest();
        xhr.open('GET', 'fragment.html');
        xhr.responseType = 'document';
        xhr.overrideMimeType('text/html;charset=UTF-8');
        xhr.onload = function() {
          const loaded = xhr.responseXML.getElementById('loaded');
          document.querySelector('#app').textContent = loaded ? loaded.textContent : 'missing';
        };
        xhr.send();
        'scheduled';
        """
      )

      self.assertEqual(result, "scheduled")
      self.assertEqual(document.body_text(), "ok")

  def test_fetch_reports_redirected_response_and_final_url(self) -> None:
    resource = Resource(
      source="https://example.com/index.html",
      content="""
      <html>
        <body>
          <main id="app"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    session = Session()

    def request(method: str, url: str, *args, **kwargs):
      redirect = Mock()
      redirect.status_code = 302
      redirect.url = url
      response = Mock()
      response.url = "https://example.com/landing"
      response.status_code = 200
      response.reason = "OK"
      response.ok = True
      response.text = "done"
      response.headers = {"Content-Type": "text/plain"}
      response.history = [redirect]
      response.close = Mock()
      return response

    session.request = Mock(side_effect=request)

    result = document.execute_script(
      """
      fetch('/login', { method: 'POST' })
        .then((response) => {
          document.querySelector('#app').textContent = [
            String(response.redirected),
            response.url,
            String(response.status)
          ].join('|');
        });
      'scheduled';
      """,
      session=session,
    )

    self.assertEqual(result, "scheduled")
    self.assertEqual(document.body_text(), "true|https://example.com/landing|200")

  def test_xml_http_request_exposes_final_response_url_after_redirect(self) -> None:
    resource = Resource(
      source="https://example.com/index.html",
      content="""
      <html>
        <body>
          <main id="app"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    session = Session()

    def request(method: str, url: str, *args, **kwargs):
      redirect = Mock()
      redirect.status_code = 303
      redirect.url = url
      response = Mock()
      response.url = "https://example.com/welcome"
      response.status_code = 200
      response.reason = "OK"
      response.ok = True
      response.text = "ok"
      response.headers = {"Content-Type": "text/plain"}
      response.history = [redirect]
      response.close = Mock()
      return response

    session.request = Mock(side_effect=request)

    result = document.execute_script(
      """
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/login');
      xhr.onload = function() {
        document.querySelector('#app').textContent = [
          xhr.status,
          xhr.responseURL
        ].join('|');
      };
      xhr.send('');
      'scheduled';
      """,
      session=session,
    )

    self.assertEqual(result, "scheduled")
    self.assertEqual(document.body_text(), "200|https://example.com/welcome")

  def test_fetch_and_xml_http_request_send_runtime_cookies(self) -> None:
    resource = Resource(
      source="https://example.com/index.html",
      content="""
      <html>
        <body>
          <main id="app"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    session = Session()
    session.cookies.set("sessionid", "abc123", domain="example.com", path="/")

    captured_headers: list[dict[str, str]] = []

    def request(method: str, url: str, *args, **kwargs):
      headers = dict(kwargs.get("headers") or {})
      captured_headers.append(headers)
      response = Mock()
      response.url = url
      response.status_code = 200
      response.reason = "OK"
      response.text = '{"ok":true}'
      response.headers = {"Content-Type": "application/json"}
      response.close = Mock()
      return response

    session.request = Mock(side_effect=request)

    document.execute_script(
      """
      document.cookie = 'sessionid=abc123';
      fetch('/api/test', { headers: { 'x-test': '1' } });
      const xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/xhr');
      xhr.send();
      """,
      session=session,
    )

    self.assertEqual(len(captured_headers), 2)
    self.assertEqual(captured_headers[0].get("cookie"), "sessionid=abc123")
    self.assertEqual(captured_headers[1].get("cookie"), "sessionid=abc123")

  def test_xml_http_request_document_response_decodes_utf8_body_when_override_mime_type_requests_it(
    self,
  ) -> None:
    resource = Resource(
      source="https://example.com/index.html",
      content="""
      <html>
        <body>
          <main id="app"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    session = Session()
    html = (
      "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body>"
      "<div id=\"loaded\">警察庁について</div>"
      "</body></html>"
    )
    body = html.encode("utf-8")

    def request(method: str, url: str, *args, **kwargs):
      response = Mock()
      response.url = url
      response.status_code = 200
      response.reason = "OK"
      response.headers = {"Content-Type": "text/html"}
      response.content = body
      response.text = body.decode("latin1")
      response.apparent_encoding = "utf-8"
      response.close = Mock()
      return response

    session.request = Mock(side_effect=request)

    document.execute_script(
      """
      const xhr = new XMLHttpRequest();
      xhr.open('GET', '/fragment.html');
      xhr.responseType = 'document';
      xhr.overrideMimeType('text/html;charset=UTF-8');
      xhr.onload = function() {
        const loaded = xhr.responseXML.getElementById('loaded');
        document.querySelector('#app').textContent = loaded ? loaded.textContent : 'missing';
      };
      xhr.send();
      """,
      session=session,
    )

    self.assertEqual(document.body_text(), "警察庁について")

  def test_xml_http_request_document_response_normalizes_windows_31j_override_mime_type(
    self,
  ) -> None:
    resource = Resource(
      source="https://example.com/index.html",
      content="""
      <html>
        <body>
          <main id="app"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    session = Session()
    html = "<!DOCTYPE html><html><body><div id=\"loaded\">日本語</div></body></html>"
    body = html.encode("cp932")

    def request(method: str, url: str, *args, **kwargs):
      response = Mock()
      response.url = url
      response.status_code = 200
      response.reason = "OK"
      response.headers = {"Content-Type": "text/html"}
      response.content = body
      response.text = body.decode("latin1")
      response.apparent_encoding = "utf-8"
      response.close = Mock()
      return response

    session.request = Mock(side_effect=request)

    document.execute_script(
      """
      const xhr = new XMLHttpRequest();
      xhr.open('GET', '/fragment.html');
      xhr.responseType = 'document';
      xhr.overrideMimeType('text/html;charset=Windows-31J');
      xhr.onload = function() {
        const loaded = xhr.responseXML.getElementById('loaded');
        document.querySelector('#app').textContent = loaded ? loaded.textContent : 'missing';
      };
      xhr.send();
      """,
      session=session,
    )

    self.assertEqual(document.body_text(), "日本語")

  def test_fetch_xhr_and_send_beacon_serialize_blob_like_bodies(self) -> None:
    resource = Resource(
      source="https://example.com/index.html",
      content="""
      <html>
        <body>
          <main id="app"></main>
        </body>
      </html>
      """,
    )
    document = TWebDocument(parse_document(resource))
    session = Session()

    captured_requests: list[dict[str, object]] = []

    def request(method: str, url: str, *args, **kwargs):
      captured_requests.append(
        {
          "method": method,
          "url": url,
          "data": kwargs.get("data"),
          "headers": dict(kwargs.get("headers") or {}),
        }
      )
      response = Mock()
      response.url = url
      response.status_code = 200
      response.reason = "OK"
      response.text = "ok"
      response.headers = {}
      response.close = Mock()
      return response

    session.request = Mock(side_effect=request)

    document.execute_script(
      """
      fetch('/api/blob', {
        method: 'POST',
        body: new Blob(['alpha=1&beta=2'], {
          type: 'application/x-www-form-urlencoded; charset=UTF-8'
        })
      });
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/xhr');
      xhr.send(new Blob(['hello xhr'], { type: 'text/plain' }));
      navigator.sendBeacon('/api/beacon', new Blob(['ping=1'], {
        type: 'application/x-www-form-urlencoded; charset=UTF-8'
      }));
      """,
      session=session,
    )

    self.assertEqual(
      captured_requests,
      [
        {
          "method": "POST",
          "url": "https://example.com/api/blob",
          "data": "alpha=1&beta=2",
          "headers": {
            "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            "origin": "https://example.com",
            "referer": "https://example.com/index.html",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": (
              "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36"
            ),
          },
        },
        {
          "method": "POST",
          "url": "https://example.com/api/xhr",
          "data": "hello xhr",
          "headers": {
            "content-type": "text/plain",
            "origin": "https://example.com",
            "referer": "https://example.com/index.html",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": (
              "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36"
            ),
          },
        },
        {
          "method": "POST",
          "url": "https://example.com/api/beacon",
          "data": "ping=1",
          "headers": {
            "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            "origin": "https://example.com",
            "referer": "https://example.com/index.html",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": (
              "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36"
            ),
          },
        },
      ],
    )

  def test_transform_stream_resolves_pending_reads(self) -> None:
    document = self.load_document()

    document.execute_script(
      """
      (async () => {
        const stream = new TransformStream({
          transform(chunk, controller) {
            controller.enqueue(chunk.toUpperCase());
          }
        });
        const reader = stream.readable.getReader();
        const pending = reader.read();
        const writer = stream.writable.getWriter();
        await writer.write('hello');
        await writer.close();
        const first = await pending;
        const second = await reader.read();
        document.querySelector('#title').textContent =
          [first.value, first.done, String(second.done)].join('|');
      })()
      """,
    )

    self.assertIn("HELLO|false|true", document.body_text())


if __name__ == "__main__":
  unittest.main()
