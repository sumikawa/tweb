from __future__ import annotations

import json
import unittest

from tweb.fetcher import Resource
from tweb.js_runtime import QuickJSRuntime
from tweb.js_runtime_helpers import _rewrite_class_static_blocks
from tweb.parser import parse_document


class StaticBlockTest(unittest.TestCase):
  def runtime(self) -> QuickJSRuntime:
    return QuickJSRuntime(parse_document(Resource(source="https://example.org/", content="<body></body>")))

  def test_preserves_static_field_order_private_access_and_super(self) -> None:
    runtime = self.runtime()
    actual = runtime.eval("""
      const log = [];
      class Base {static get value() {return 7}}
      class Child extends Base {
        static #secret = 2;
        static first = log.push('field');
        static {var local = this.#secret; this.total = super.value + local; log.push('block');}
        static second = log.push('last');
        static {log.push(this.total);}
      }
      JSON.stringify([log, Object.keys(Child), typeof local]);
    """)
    self.assertEqual(json.loads(actual), [["field", "block", "last", 9], ["first", "total", "second"], "undefined"])

  def test_anonymous_nested_and_dollar_named_classes(self) -> None:
    runtime = self.runtime()
    self.assertEqual(runtime.eval("""
      const Container = class extends (class {static base = 3}) {
        static {this.Inner = class $Inner {static {this.value = 5}};}
      };
      Container.base + Container.Inner.value;
    """), 8)

  def test_does_not_change_literal_contents_comments_or_methods(self) -> None:
    source = r"""
      const text = "class A {static {boom()}}";
      const pattern = /class A {static {boom}}/;
      const template = `class A {static {boom()}}`;
      // class A {static {boom()}}
      /* class A {static {boom()}} */
      class A {static() {return 3} class() {return 4}}
    """
    self.assertEqual(_rewrite_class_static_blocks(source), source)

  def test_class_in_template_expression_and_comment_between_tokens(self) -> None:
    self.assertEqual(self.runtime().eval("""
      `${(class {static /* comment */ {this.value = 'ok'}}).value}`;
    """), "ok")
    self.assertEqual(self.runtime().eval("""
      (class {static // comment
        {this.value = 2}}).value;
    """), 2)

  def test_generated_private_name_does_not_collide(self) -> None:
    self.assertEqual(self.runtime().eval("""
      class Example {static #__twebStaticBlock0 = 4; static {this.value = this.#__twebStaticBlock0}}
      Example.value;
    """), 4)

  def test_nested_blocks_regex_and_object_literals(self) -> None:
    self.assertEqual(self.runtime().eval(r"""
      class Example {
        static {if (/\{[^}]*\}/.test('{x}')) {this.value = ({item: 5}).item}}
      }
      Example.value;
    """), 5)


if __name__ == "__main__":
  unittest.main()
