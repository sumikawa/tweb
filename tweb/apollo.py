from __future__ import annotations

import json
from typing import Callable


_MAX_DEPTH = 16
_MAX_NODES = 10_000
_MAX_ENTITY_CHARS = 200_000
_ROOT_NAMES = ("ROOT_QUERY", "ROOT_MUTATION", "ROOT_SUBSCRIPTION")


def resolve_apollo_references(
  value: object,
  lookup: Callable[[str], object],
  *,
  max_depth: int = _MAX_DEPTH,
  max_nodes: int = _MAX_NODES,
) -> object:
  """Expand normalized cache references without mutating the cache or following cycles."""
  remaining = max_nodes
  entities: dict[str, object] = {}
  resolving: set[str] = set()

  def resolve(entry: object, depth: int) -> object:
    nonlocal remaining
    if remaining <= 0 or depth > max_depth:
      return None
    remaining -= 1
    if isinstance(entry, dict):
      ref = entry.get("__ref")
      if len(entry) == 1 and isinstance(ref, str):
        if ref in resolving:
          return None
        if ref not in entities:
          entities[ref] = lookup(ref)
        resolving.add(ref)
        try:
          return resolve(entities[ref], depth + 1)
        finally:
          resolving.remove(ref)
      result = {}
      for key, child in entry.items():
        if remaining <= 0:
          break
        result[key] = resolve(child, depth + 1)
      return result
    if isinstance(entry, list):
      result = []
      for child in entry:
        if remaining <= 0:
          break
        result.append(resolve(child, depth + 1))
      return result
    return entry

  return resolve(value, 0)


def expand_apollo_payload(payload: object, *, is_apollo_state: bool = False) -> object:
  """Find explicitly named Apollo caches, including those nested in bootstrap data."""
  remaining = _MAX_NODES

  def visit(value: object, depth: int, named_cache: bool = False) -> object:
    nonlocal remaining
    if remaining <= 0 or depth > _MAX_DEPTH:
      return value
    remaining -= 1
    if isinstance(value, dict):
      if named_cache or any(isinstance(value.get(name), dict) for name in _ROOT_NAMES):
        root = value.get("ROOT_QUERY", value)
        return resolve_apollo_references(root, value.get)
      result = value
      for key, child in value.items():
        if remaining <= 0:
          break
        expanded = visit(child, depth + 1, key == "__APOLLO_STATE__")
        if expanded is not child:
          if result is value:
            result = dict(value)
          result[key] = expanded
      return result
    if isinstance(value, list):
      result = value
      for index, child in enumerate(value):
        if remaining <= 0:
          break
        expanded = visit(child, depth + 1)
        if expanded is not child:
          if result is value:
            result = list(value)
          result[index] = expanded
      return result
    return value

  return visit(payload, 0, is_apollo_state)


def read_runtime_apollo_value(
  runtime,
  *,
  state_path: tuple[str, ...],
  key: str,
  fields: tuple[str, ...] | None = None,
) -> object:
  """Read only the entities reachable from one runtime cache key, using bounded lookups."""
  def lookup(ref: str) -> object:
    raw = runtime.eval(
      """
      (function() {
        try {
          let state = window;
          for (const part of %s) {
            if (!state || !Object.prototype.hasOwnProperty.call(state, part)) return 'null';
            state = state[part];
          }
          const key = %s;
          if (!state || !Object.prototype.hasOwnProperty.call(state, key)) return 'null';
          let value = state[key];
          const fields = %s;
          if (fields && value && typeof value === 'object' && !Array.isArray(value)) {
            const selected = Object.create(null);
            for (const field of fields) {
              if (Object.prototype.hasOwnProperty.call(value, field)) selected[field] = value[field];
            }
            value = selected;
          }
          const raw = JSON.stringify(value);
          return typeof raw === 'string' && raw.length <= %s ? raw : 'null';
        } catch (_error) {
          return 'null';
        }
      })()
      """
      % (json.dumps(state_path), json.dumps(ref), json.dumps(fields), _MAX_ENTITY_CHARS),
      drain_timers=False,
    )
    if not isinstance(raw, str) or len(raw) > _MAX_ENTITY_CHARS:
      return None
    try:
      return json.loads(raw)
    except json.JSONDecodeError:
      return None

  return resolve_apollo_references({"__ref": key}, lookup)
