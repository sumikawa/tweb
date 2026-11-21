[English](DEVELOPMENT.md) | [日本語](DEVELOPMENT.ja.md)

# DEVELOPMENT.md

This document is the entry point for developing, investigating, and maintaining `tweb`. See `README.md` for user-facing usage and the `docs/*.md` documents for feature-specific policies.

## `uv run` and cache

Codex and sandbox environments are prone to `~/.cache/uv` permission errors. Set temporary cache directories from the outset for commands requiring `uv run`.

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m unittest tests.test_cli
```

The full suite can also be run with `make test` using the same temporary cache settings.

If there is a conflict with the symlink of `.venv` during Dropbox synchronization, specify `UV_PROJECT_ENVIRONMENT=/private/tmp/tweb-dev-venv` and also exclude the virtual environment from being synchronized. If the Python selection depends on the environment, specify it like `uv run --python 3.12 python -m unittest ...`.

## Common development commands

Normal output:

```bash
tw https://example.com --mode text
tw ./page.html --mode text
tw https://example.com/article --mode text --main-only
```

`--main-only` checks visibility, including ancestors, and prioritizes visible `<main>` / `<article>` elements. Otherwise, infer body content from visible `div` / `section` elements. Aggregate candidate character, paragraph, heading, and link counts in a single bottom-up traversal.

DOM / DOM-AI:

```bash
tw https://example.com --mode dom
tw https://example.com --mode dom-ai
```

TUI:

```bash
tw https://example.com
```

Apply additional scripts:

```bash
tw https://example.com --script "document.querySelector('h1').textContent = 'CLI Title';" --mode text
tw https://example.com --script-file ./patch.js --mode text
```

Cookie / browser-render:

```bash
tw https://example.com/private --cookie-file cookies.txt
tw https://example.com/private --cookie-from-browser firefox --cookie-domain example.com
tw https://example.com/app --browser-render auto
tw https://example.com/app --browser-render always
```

Debug logs:

```bash
tw https://example.com --debug
tw https://example.com --debug-log /tmp/tweb-debug.log
```

## Tests

Start with focused unittests closest to the affected functionality.

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m unittest tests.test_cli tests.test_document_api
```

Full test suite:

```bash
make test
```

Representative test areas:

- `tests/test_cli.py`: CLI options and configuration files
- `tests/test_document_api.py`: Title, body, links, API behavior. Note topic's runtime probe test mocks additional retrieval on the Python side and does not depend on the real site's response.
- `tests/test_fetcher.py`: Fetching layer, cookies, sessions
- `tests/test_normal_renderer.py`: Normal-view renderer
- `tests/test_dom_renderer.py`: DOM / DOM-AI display
- `tests/test_js_runtime.py`: QuickJS runtime and DOM bridge
- `tests/test_render_efficiency.py`: Phase 17 request classification, body-stable termination, debug limits, and fetch/XHR preservation
- `tests/test_tui.py`: Textual TUI

## Audits and performance measurement

A differential audit of QuickJS and browser-render is done with `tweb.audit`.

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m tweb.audit
```

JSON output:

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m tweb.audit --json > /tmp/tweb-audit.json
```

Run selected targets:

```bash
UV_CACHE_DIR=/private/tmp/tweb-uv-cache \
PYTHONPYCACHEPREFIX=/private/tmp/tweb-pycache \
uv run python3 -m tweb.audit --tag en
```

- canonical manifest is `tweb/data/quickjs_audit_sites.json`
- Execution records and decisions are tracked in `docs/performance.md`.
- If you change the cohort status, update manifest and `docs/performance.md` with the same changes.

## Repository structure

Main code:

- `tweb/cli.py`: `tw` CLI entry point
- `tweb/fetcher.py`: URL/local file fetching, session/cookie initialization
- `tweb/parser.py`: HTML parsing
- `tweb/dom.py`: DOM abstraction
- `tweb/css.py`: CSS interpretation
- `tweb/js_runtime.py`: QuickJS runtime public entry point
- `tweb/js_runtime_bridge.py`: DOM/browser bridge injected into QuickJS
- `tweb/api.py`: `TWebDocument` and BeautifulSoup style API
- `tweb/runtime_data.py`: runtime data / hydration collector
- `tweb/hydration_targets.py`: HTML / ARIA / Structure-based body/navigation area and section role determination
- `tweb/apollo.py`: Common reference resolution of Apollo normalized cache and limited read of runtime entity
- `tweb/site_specific.py`: Residual of Kakuyomu's table of contents schema / episode URL (note-only fetch has been deleted)
- `tweb/tui.py`: Textual TUI
- `tweb/renderers/normal.py`: Normal-view renderer
- `tweb/renderers/dom.py`: DOM / DOM-AI renderer

## Documentation responsibilities

- `README.md`: User-facing usage
- `docs/DEVELOPMENT.md`: Development flow, commands, configuration
- `docs/API.md`: Python API
- `docs/DOM.md`: DOM / DOM-AI policy
- `docs/CSS.md`: CSS interpretation policy
- `docs/JS.md`: QuickJS, hydration, browser-render
- `docs/TUI.md`: TUI operation specifications
- `docs/SECURITY.md`: Security policy and TODO
- `docs/PLAN.md`: Step-by-step development plan
- `docs/performance.md`: Quality audit and performance record
