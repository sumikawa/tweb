from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import Mock

from tweb.apollo import expand_apollo_payload, read_runtime_apollo_value, resolve_apollo_references
from tweb.fetcher import Resource
from tweb.js_runtime import QuickJSRuntime
from tweb.parser import parse_document


class ApolloTest(unittest.TestCase):
  def test_resolves_shared_entities_once_without_mutating_input(self) -> None:
    entities = {"Item:1": {"title": "One", "url": "/one"}}
    root = [{"__ref": "Item:1"}, {"__ref": "Item:1"}]
    before = copy.deepcopy(root)
    lookup = Mock(side_effect=entities.get)
    self.assertEqual(resolve_apollo_references(root, lookup), [entities["Item:1"]] * 2)
    lookup.assert_called_once_with("Item:1")
    self.assertEqual(root, before)

  def test_cyclic_and_missing_references_preserve_readable_fields(self) -> None:
    entities = {
      "A": {"title": "One", "next": {"__ref": "B"}},
      "B": {"title": "Two", "next": {"__ref": "A"}, "missing": {"__ref": "missing"}},
    }
    result = resolve_apollo_references({"__ref": "A"}, entities.get)
    self.assertEqual(result, {"title": "One", "next": {"title": "Two", "next": None, "missing": None}})

  def test_depth_and_node_budgets_stop_reference_chains(self) -> None:
    def entity(key: str) -> dict:
      return {"next": {"__ref": str(int(key) + 1)}}
    for limits in ({"max_depth": 3}, {"max_nodes": 4}):
      with self.subTest(limits=limits):
        lookup = Mock(side_effect=entity)
        resolve_apollo_references({"__ref": "0"}, lookup, **limits)
        self.assertLessEqual(lookup.call_count, 2)
    result = resolve_apollo_references(list(range(100_000)), lambda key: None, max_nodes=4)
    self.assertEqual(result, [0, 1, 2])

  def test_bootstrap_cache_resolves_only_query_reachable_entities(self) -> None:
    payload = {"props": {"pageProps": {"__APOLLO_STATE__": {
      "ROOT_QUERY": {"items": [{"__ref": "Item:1"}]},
      "Item:1": {"title": "Current article", "href": "/current"},
      "Item:2": {"title": "Stale article", "href": "/stale"},
    }}}}
    before = copy.deepcopy(payload)
    self.assertEqual(expand_apollo_payload(payload), {"props": {"pageProps": {
      "__APOLLO_STATE__": {"items": [{"title": "Current article", "href": "/current"}]},
    }}})
    self.assertEqual(payload, before)

  def test_named_cache_without_query_root_is_resolved(self) -> None:
    payload = {"Collection:1": {"items": [{"__ref": "Item:1"}]}, "Item:1": {"title": "One"}}
    result = expand_apollo_payload(payload, is_apollo_state=True)
    self.assertEqual(result["Collection:1"]["items"], [{"title": "One"}])

  def test_ordinary_json_with_ref_field_is_unchanged(self) -> None:
    payload = {"items": [{"__ref": "Item:1"}], "Item:1": {"title": "One"}}
    self.assertIs(expand_apollo_payload(payload), payload)
    value = {"__ref": "documentation", "title": "Reference guide"}
    self.assertEqual(resolve_apollo_references(value, lambda key: None), value)

  def test_runtime_reads_reachable_entities_without_serializing_entire_cache(self) -> None:
    runtime = QuickJSRuntime(parse_document(Resource(source="https://example.com/", content="<body></body>")))
    state = {
      "Collection:1": {"title": "Chapters", "items": [{"__ref": "Item:1"}, {"__ref": "Item:1"}]},
      "Item:1": {"title": "One", "href": "/one", "parent": {"__ref": "Collection:1"}},
    }
    runtime.eval("window.__APOLLO_STATE__ = " + json.dumps(state))
    runtime.eval("""Object.defineProperty(window.__APOLLO_STATE__, 'unrelated', {
      enumerable: true, get: function() { throw Error('unrelated entity was read'); }
    });""")
    result = read_runtime_apollo_value(runtime, state_path=("__APOLLO_STATE__",), key="Collection:1")
    self.assertEqual(result, {"title": "Chapters", "items": [
      {"title": "One", "href": "/one", "parent": None},
      {"title": "One", "href": "/one", "parent": None},
    ]})
    self.assertIsNone(read_runtime_apollo_value(runtime, state_path=("missing",), key="missing"))

  def test_runtime_rejects_invalid_or_oversized_entity_json(self) -> None:
    for raw in (None, "invalid JSON", json.dumps({"body": "x" * 200_000})):
      with self.subTest(kind=type(raw), size=len(raw) if isinstance(raw, str) else 0):
        runtime = Mock()
        runtime.eval.return_value = raw
        self.assertIsNone(read_runtime_apollo_value(runtime, state_path=("__APOLLO_STATE__",), key="Item:1"))

  def test_runtime_field_selection_does_not_touch_unneeded_fields(self) -> None:
    runtime = QuickJSRuntime(parse_document(Resource(source="https://example.com/", content="<body></body>")))
    runtime.eval('window.__APOLLO_STATE__ = {"Item:1": {title: "One"}};')
    runtime.eval("""Object.defineProperty(window.__APOLLO_STATE__['Item:1'], 'large', {
      enumerable: true, get: function() { throw Error('unneeded field was read'); }
    });""")
    self.assertEqual(read_runtime_apollo_value(
      runtime, state_path=("__APOLLO_STATE__",), key="Item:1", fields=("title",),
    ), {"title": "One"})


if __name__ == "__main__":
  unittest.main()
