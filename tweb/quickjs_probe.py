from __future__ import annotations

import json
import sys

import quickjs

from .fetcher import Resource
from .js_runtime import QuickJSRuntime
from .parser import parse_document


def main() -> int:
  raw = sys.stdin.read()
  if not raw.strip():
    return 0
  payload = json.loads(raw)
  page_source = str(payload.get("page_source") or "about:blank")
  prior_sources = payload.get("prior_sources") or []
  source = str(payload.get("source") or "")
  document = parse_document(Resource(source=page_source, content="<html><body></body></html>"))
  runtime = QuickJSRuntime(document)
  try:
    for entry in prior_sources:
      if isinstance(entry, str) and entry.strip():
        runtime.eval(entry, drain_timers=False)
    if source.strip():
      runtime.eval(source, drain_timers=False)
  except quickjs.JSException:
    return 0
  except Exception:
    return 0
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
