[English](README.md) | [日本語](README.ja.md)

# tweb

`tweb` is a text-based browser that displays web pages as readable text and lets you inspect the DOM and JavaScript execution results. Its single CLI command, `tw`, starts the TUI by default.

A Python API provides the same foundation for AI agents and scripts to extract text, list links, inspect the DOM, and fetch pages using forms and cookies.

## Features

- Read page content as formatted text
- Inspect page structure with `dom` / `dom-ai`
- Browse with the keyboard in the `tw` TUI
- Switch between text and DOM output with `tw --mode text|dom|dom-ai`
- Open pages with cookies
- Display content after JavaScript execution
- Suppress unnecessary QuickJS network requests and finish post-load processing early when page content stabilizes (see [API.md](docs/API.md) for details and how to disable this)
- Use browser-render fallback for pages that QuickJS cannot render correctly
- Work with text, links, and the DOM from Python

## Installation

Python 3.12 or later is required.

```bash
uv tool install --from . tweb
```

Or:

```bash
python3 -m pip install .
```

Both methods install `tw`.

## Getting started

Inputs without a URL scheme, such as `example.com`, are treated as `http://example.com`. Pass local files as paths such as `./page.html` or `/tmp/sample.html`. With no arguments, `tw` opens the welcome page in the TUI.

TUI:

```bash
tw https://example.com
tw ./page.html
```

Text output:

```bash
tw https://example.com --mode text
tw https://example.com/article --mode text --main-only
```

DOM summary:

```bash
tw https://example.com --mode dom
```

Detailed DOM for AI agents:

```bash
tw https://example.com --mode dom-ai
```

Without `--width`, the current terminal width is used, or `80` if it cannot be determined. The default `--link-style` is `none`.
In `text` mode, `--main-only` prioritizes visible `<main>` and `<article>` elements. If neither is available, it identifies a likely content container. Elements inside hidden ancestors or `template` elements are excluded. If no candidate is found, the entire `<body>` is rendered.

To extract text without image placeholders (`[alt text]` / `[image]`), use `--no-images`. This also omits `<figcaption>` captions. Body text and links containing text remain; image-only links are omitted. The option also applies to the TUI's normal view and leaves DOM / DOM-AI inspection unchanged. It does not disable page fetching or JavaScript execution.

```bash
tw https://example.com/article --mode text --main-only --no-images
```

## Common options

Use cookies:

```bash
tw https://example.com/private --cookie "sessionid=abc123"
tw https://example.com/private --cookie-file cookies.txt
tw https://example.com/private --cookie-from-browser firefox --cookie-domain example.com
tw https://example.com/private --cookie-from-browser zen --cookie-domain example.com
```

Apply additional JavaScript:

```bash
tw https://example.com --script "document.body.prepend('hello')"
tw https://example.com --script-file ./patch.js
```

Select the browser-render fallback policy:

```bash
tw https://example.com/app --browser-render never
tw https://example.com/app --browser-render auto
tw https://example.com/app --browser-render always
```

Write debug logs:

```bash
tw https://example.com --debug
tw https://example.com --debug-log /tmp/tweb-debug.log
```

`--debug` writes to `debug.log` in the working directory by default. `--debug-log` changes the destination and enables debug logging on its own. Authentication values are masked in logs.

## Configuration

`tw` can read `~/.config/tw/config.yml` at startup. It currently supports `headers.User-Agent` and the top-level `user_agent` setting, applying them to the default HTTP/HTTPS headers.

```yaml
headers:
  User-Agent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
```

Or:

```yaml
user_agent: "My custom agent"
```

To use a different file temporarily, set `TW_CONFIG_PATH=/path/to/config.yml`.

## Python API

Minimal example:

```python
from tweb import TWebDocument, fetch_resource, parse_document

resource = fetch_resource("https://example.com")
document = TWebDocument(parse_document(resource))

print(document.title)
print(document.body_text())
for link in document.links():
  print(link.text, link.href)
```

See [docs/API.md](docs/API.md) for the full API documentation.

## Documentation

- [docs/TUI.md](docs/TUI.md): TUI behavior and key bindings
- [docs/API.md](docs/API.md): Python library API
- [docs/DOM.md](docs/DOM.md): `dom` / `dom-ai` output policies
- [docs/CSS.md](docs/CSS.md): CSS interpretation
- [docs/JS.md](docs/JS.md): JavaScript execution and browser-render fallback
- [docs/SECURITY.md](docs/SECURITY.md): Security policies and outstanding work
- [docs/PLAN.md](docs/PLAN.md): Development plan
- [docs/performance.md](docs/performance.md): Quality audits and performance measurements
