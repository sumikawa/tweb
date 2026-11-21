[English](API.md) | [日本語](API.ja.md)

# API.md

`tweb` is available as both a CLI and a Python library. This document covers the public API, BeautifulSoup-style read APIs, structured snapshots for AI agents, and mutation APIs.

## Public imports

```python
from tweb import (
  AgentActionRequest,
  AgentActionResult,
  AgentPageSnapshot,
  AgentSnapshotControl,
  AgentSnapshotLink,
  AgentSnapshotNode,
  AgentSnapshotOption,
  ControlDebugInfo,
  ControlSubmissionPreview,
  JavaScriptRuntimeError,
  QuickJSRuntime,
  TWebAgentActions,
  TWebDocument,
  TWebElement,
  create_session,
  fetch_resource,
  parse_document,
)
```

Normally use `TWebDocument` as the entry point without accessing `QuickJSRuntime` directly.

## Minimal example

```python
from tweb import TWebDocument, fetch_resource, parse_document

resource = fetch_resource("https://example.com")
document = TWebDocument(parse_document(resource))

print(document.title)
print(document.body_text())
for link in document.links():
  print(link.text, link.href)
```

Local files use the same workflow.

```python
from tweb import TWebDocument, fetch_resource, parse_document

resource = fetch_resource("./page.html")
document = TWebDocument(parse_document(resource))
print(document.find("h1").text)
```

## Text rendering

```python
from tweb.renderers.normal import render_normal, render_normal_with_metadata

text = render_normal(document.document, text_styles=False, main_only=True)
result = render_normal_with_metadata(document.document, text_styles=False, main_only=True)
```

`main_only=True` selects visible body-content candidates and shares CSS analysis within that render. By default, the entire page is rendered. `render_normal_with_metadata` returns rendered text together with link and form-control positions.

`include_images=False` omits image placeholders (including alt text) and `<figcaption>` captions. The default is `True`. This is supported by `render_normal`, `render_normal_with_metadata`, and their subtree variants without modifying the original DOM.

```python
text = render_normal(document.document, text_styles=False, main_only=True, include_images=False)
```

## Fetching

`fetch_resource(target, ...)` returns `Resource` from URL or local path.

- Get `http://` / `https://` with `requests`
- Read local files directly.
- Pass `session=` to fetch using cookies.
- Pass `method=` and `form_data=` to fetch a form submission response.

Example of creating a session with cookies:

```python
from requests.cookies import RequestsCookieJar
from tweb import create_session, fetch_resource

jar = RequestsCookieJar()
jar.set("sessionid", "abc123", domain=".example.com", path="/")
session = create_session(jar)

resource = fetch_resource("https://example.com/private", session=session)
session.close()
```

## Parsing and document API

`parse_document(resource)` builds the internal DOM, and `TWebDocument` provides its public interface.

### `TWebDocument`

Main read APIs:

- `title`: Page title
- `html`: `TWebElement` of `<html>`
- `body`: `TWebElement` of `<body>`
- `body_text()`: Body text
- `links()`: List of `Link(text, href)`
- `find(name=None, attrs=None)`: First match
- `find_all(name=None, attrs=None, limit=None)`: List
- `select(selector)`: Simple CSS selector
- `snapshot(...)`: Structured snapshot for AI
- `hydration_debug()`: Source summaries and confidence for runtime data supplementation
- `javascript_debug()`: script eval / async drain / style rebuild / script cache timing/count
- `agent_actions()`: Entry point for mutation APIs
- `debug_control(...)`, `debug_controls()`: Form / button debugging description
- `invoke_agent_action(...)` / `agent_actions().invoke(...)`: Structured basic operation entry

Example:

```python
article = document.find("article")
headings = document.find_all("h2")
primary_links = document.select('main a[href^="/"]')
```

### `TWebElement`

`TWebElement` is used as the return value of `TWebDocument.find()` and `select()`.

Main accessor APIs:

- `name`: Tag name
- `attrs`: Attribute dict
- `text`: Text under element
- `get(key, default=None)`: Get attributes
- `get_text(separator=" ", strip=True)`: Get text
- `find(...)`, `find_all(...)`, `select(...)`: Search on subtrees

Example:

```python
card = document.select(".card")[0]
title = card.find("h3").text
href = card.find("a").get("href")
```

### BeautifulSoup compatibility

Keep a BeautifulSoup-style read API while separating mutations into another object.

- Preserve `find` / `find_all` / `select` / `get_text` as read APIs.
- Route form editing, submission, and JS button clicks through `agent_actions()`.
- `execute_script()` is a powerful feature and should not be treated in the same way as a simple read API.

This also clarifies the boundary between read-only and side-effecting APIs for AI agents.

## Snapshot API for AI agents

`snapshot()` returns key page information as dataclasses that are easy to serialize to JSON.

```python
snapshot = document.snapshot(max_depth=2)

print(snapshot.title)
print(snapshot.body_text)
print(snapshot.links[0].href if snapshot.links else "")
print(snapshot.form_controls[0].control_id if snapshot.form_controls else "")
print(snapshot.to_dict()["dom_nodes"][0]["node_id"] if snapshot.dom_nodes else "")
```

Main fields of the returned `AgentPageSnapshot`:

- `source`: Original URL or local path
- `title`: Page title
- `body_text`: Body text
- `links`: `AgentSnapshotLink`
- `form_controls`: `AgentSnapshotControl`
- `dom_nodes`: `AgentSnapshotNode`

Main arguments:

- `max_depth`: How far to follow the DOM node
- `include_script_like`: Include `script` / `style` in details?
- `viewport_columns`: Width used for CSS visibility evaluation

`AgentPageSnapshot` itself also has a read-only search aid that is easy to use from AI.

```python
snapshot = document.snapshot(max_depth=3)

search_box = snapshot.control("q")
radio_controls = snapshot.find_controls(kind="radio", name="scope")
search_label_nodes = snapshot.find_nodes(node_type="text", text_contains="search")
docs_link = snapshot.link(href="https://example.com/docs")
```

Main helper methods:

- `link(href=None, text=None)`: Return the first matching link
- `find_links(href=None, text=None, text_contains=None, limit=None)`: Filter links
- `control(control_id)`: Return 1 control by ID
- `find_controls(kind=None, name=None, label_contains=None, input_type=None, limit=None)`: Filter form controls
- `node(node_id)`: Return 1 node by ID
- `find_nodes(node_type=None, tag=None, text_contains=None, attrs=None, visible=None, parent_id=None, include_skipped=True, limit=None)`: Filter DOM nodes

Each `AgentSnapshotControl` also has these fields for determining whether actions are available.

- `disabled`
- `readonly`
- `supported_actions`

### `AgentSnapshotLink`

- `text`
- `href`

### `AgentSnapshotControl`

- `control_id`
- `kind`
- `name`
- `label`
- `value`
- `checked`
- `options`
- `input_type`

`options` is returned as an array of `AgentSnapshotOption(value, label, selected)`.

### `AgentSnapshotNode`

`dom_nodes` returns a flat array representing the parent-child relationship as `node_id` / `parent_id`.

Main fields:

- `node_id`
- `parent_id`
- `node_type`: `"element"` or `"text"`
- `tag`
- `text`
- `attrs`
- `visible`
- `hidden_reason`
- `display`
- `flex_direction`
- `grid_template_columns`
- `visibility`
- `font_weight`
- `font_style`
- `text_decoration`
- `skipped`

If you use `snapshot.to_dict()`, it becomes a dict that is easy to JSON serialize as is.

These read-only helpers operate only within `snapshot` and do not modify the DOM or submit forms. Keep side-effecting operations separate in `agent_actions()`.

## Mutation APIs

`agent_actions()` returns `TWebAgentActions`, and operations with side effects such as form editing and submit are called from here.

```python
actions = document.agent_actions()
actions.set_text_control("q", "updated query")
actions.toggle_checkbox("safe")
```

`TWebDocument` itself still has a method with the same name, but we recommend using `agent_actions()` for AI operations.

### Structured action invocation

Individual methods can be called directly, but `invoke()` using `AgentActionRequest` is more stable and convenient for AI agents.

```python
actions = document.agent_actions()

result = actions.invoke(
  AgentActionRequest(
    action="set_text",
    control_id="q",
    value="hogehoge",
  )
)

submit = actions.invoke(
  AgentActionRequest(
    action="submit_form",
    control_id="tweb-button-1",
    current_source="https://example.com/form",
  )
)
```

Main `action` values:

- `set_text`
- `append_text`
- `backspace_text`
- `toggle_checkbox`
- `cycle_select`
- `select_radio`
- `submit_form`
- `click_button`
- `debug_control`

The returned `AgentActionResult` contains `status`, `reason`, `available_actions`, `requires_confirmation`, `changed`, `submission`, `button_click`, and `debug`, allowing both success and failure to be handled as structured results rather than exceptions.

Main `status` values:

- `ok`: Execution or preflight successful
- `not_found`: Target `control_id` not found
- `unsupported`: That action cannot be used with that control.
- `blocked`: Final effect stopped by policy
- `requires_confirmation`: Additional confirmation required before execution

Main supplementary fields:

- `reason`: Machine judgment code such as `control_not_found` / `action_not_supported_for_control` / `blocked_by_policy` / `password_input_requires_confirmation`
- `available_actions`: List of actions allowed for that control
- `requires_confirmation`: Is it a case to resubmit the same request with reconfirmation?

For example, password inputs return `requires_confirmation` by default and block value injection. Retry with `confirmed=True` only when explicitly permitted.

```python
password_result = actions.invoke(
  AgentActionRequest(
    action="set_text",
    control_id="password",
    value="secret",
  )
)

if password_result.status == "requires_confirmation":
  password_result = actions.invoke(
    AgentActionRequest(
      action="set_text",
      control_id="password",
      value="secret",
      confirmed=True,
    )
  )
```

### Control debugging information

When you want to check button click or form submit, you can get a structured explanation using `debug_control()` / `debug_controls()` before execution.

```python
actions = document.agent_actions()
debug = actions.debug_control("tweb-button-1")

print(debug.kind)
print(debug.click_hint)
print(debug.form_action)
print(debug.submit_preview.url if debug.submit_preview is not None else "")
```

Main fields:

- `kind`: `text` / `textarea` / `select` / `checkbox` / `radio` / `submit` / `button` / `tab`
- `tag`: Real DOM tag name
- `form_action`, `form_method`: Destination if form owner exists
- `submit_preview`: `ControlSubmissionPreview` for submit control
- `click_hint`: `submit` / `disclosure_toggle` / `tab_activation` / `navigation` / `javascript`
- `controlled_target`: Target ID if `aria-controls` is present
- `navigation_target`: URL when transition destination can be estimated in advance using class-based tab etc.

### Listing controls

```python
controls = document.form_controls()
for control in controls:
  print(control.control_id, control.kind, control.name, control.value)
```

If you only want to see the checkbox:

```python
checkboxes = document.checkbox_controls()
```

### Editing text controls

```python
actions.append_text_to_control("q", " more")
actions.backspace_control_text("q")
actions.set_text_control("q", "search term")
```

Mirrored inputs sharing the same `name` are synchronized.

### select / radio / checkbox

```python
actions.cycle_select_control("category")
actions.cycle_select_control("category", reverse=True)
actions.select_radio_control("scope-all")
actions.toggle_checkbox("safe")
```

### Constructing submission data

`submit_form_control(control_id, current_source)` returns submission data as `FormSubmission` without fetching immediately.

```python
submission = actions.submit_form_control("tweb-button-1", "https://example.com/form")
if submission is not None:
  print(submission.method)
  print(submission.action)
  print(submission.url())
  print(submission.form_data())
```

- `url()` is useful for GET form
- In POST form, `form_data()` can be passed as is to `fetch_resource(..., method="post", form_data=...)`

### JavaScript button click

JS-driven buttons like `type="button"` are handled by `click_button_control()`. The default policy for the low-level API is conservatively left at `dom-only`, which is different from the TUI default policy `network`.

```python
result = actions.click_button_control("login-button", policy="dom-only")
print(result.clicked, result.classification, result.dom_changed)
```

`policy`:

- `"off"`: Do not execute
- `"dom-only"`: Only allow DOM updates, block communication and transitions
- `"network"`: Communication and transitions are also allowed.

`invoke(action="click_button", ...)` returns `status="blocked"` and `reason="blocked_by_policy"` if navigation is stopped by `dom-only`. Even if only network requests are stopped, if click and DOM update are established, you can leave `status="ok"` as it is and check `network_requested` with `button_click.blocked_by_policy` and `button_click.classification`.

The returned `ButtonClickResult` exposes information such as the following.

- `clicked`
- `classification`
- `dom_changed`
- `blocked_by_policy`
- `navigation_target`
- `network_requests`

## JavaScript execution

JS execution of `tweb` is based on quick.js and is usually used via `TWebDocument`.

### Run 1 arbitrary script

```python
document.execute_script(
  "document.body.setAttribute('data-ready', '1')"
)
```

- Passing `source_url=` will give you a context equivalent to `document.currentScript.src`
- DOM and interaction information are synchronized after execution.

### Execute embedded scripts

```python
document.execute_embedded_scripts(
  ignore_errors=True,
  session=session,
  browser_render_policy="never",
  use_script_cache=True,
  render_efficiency=True,
)
```

Main arguments:

- `ignore_errors`: If set to `False`, JS exception will be raised as is.
- `session`: session used for external script and fetch/XHR
- `browser_render_policy`: `"never" | "auto" | "always"`
- `use_script_cache`: Whether to use the persistent `diskcache`-based external-script file cache, keyed by `URL` with variants respecting `Vary`
- `render_efficiency`: Defaults to `True`. Suppress additional beacon, explicit telemetry endpoint, image/video/font requests and allow body-stable termination of post-load async drain. Set `False` for comparison or compatibility investigation. Independent of `--main-only`; applies to normal output and the TUI. Does not change Chrome fallback policy.

Pause this optimization during explicit button operations and use only existing `dom` / `network` permissions for requests. Do not block submissions allowed by `network` through page-loading classifications. Restore the optimization afterward.

Helper APIs:

- `execute_inline_scripts(ignore_errors=True)`: Execute only inline script without reading external script

Catch `JavaScriptRuntimeError` on failure.

```python
from tweb import JavaScriptRuntimeError

try:
  document.execute_embedded_scripts(ignore_errors=False)
except JavaScriptRuntimeError as exc:
  print(exc)
```

Call `hydration_debug()` to inspect runtime data supplementation decisions.

```python
document.execute_embedded_scripts(ignore_errors=True)
debug = document.hydration_debug()
print(debug["confidence"])
print(debug["source_summaries"])
```

If you want to see what's heavy on a JS-heavy page, you can call `javascript_debug()`.

```python
document.execute_embedded_scripts(ignore_errors=True, use_script_cache=False)
debug = document.javascript_debug()
print(debug["timings_ms"])
print(debug["script_cache"])
print(debug["render_efficiency"])
```

`render_efficiency.resource_decisions` returns the most recent 64 classifications, initiators, phases, and permission/blocking reasons. The URL excludes the credentials, query, and fragment, but does not include the request body or authentication header. `async_drain_stops` returns the most recent 32 termination reasons and timer counts, and `body-stable` also includes `quiet_ms` in virtual time. You can check the total number of cases at `counts` and the inspection time for the main text at `timings_ms.body_stability_probe`.

Initial body-stability targets are pages with at least 200 characters and paragraph/heading structure in CSS-visible `main` / `article` / `role=main` regions. Compare body, links, and input state every 8 timers; stop async drain after at least 500ms of virtual time without changes or new content-candidate requests. Do not leave currently runnable timers or microtasks pending. Sparse content, missing explicit body regions, or probe-limit violations use existing budgets. Future timer-generated content is not guaranteed; compare with `render_efficiency=False` if early termination is suspected.

## Recommended workflow

Use the following basic workflow for read-oriented usage.

```python
from tweb import TWebDocument, fetch_resource, parse_document

document = TWebDocument(parse_document(fetch_resource("https://example.com")))
document.execute_embedded_scripts(ignore_errors=True)

print(document.title)
print(document.body_text())
```

If you want structured read results for AI, use snapshot.

```python
snapshot = document.snapshot(max_depth=2)
payload = snapshot.to_dict()
print(payload["title"])
```

Pass a session for authenticated or script-dependent pages.

```python
from requests.cookies import RequestsCookieJar
from tweb import TWebDocument, create_session, fetch_resource, parse_document

jar = RequestsCookieJar()
jar.set("sessionid", "abc123", domain=".example.com", path="/")
session = create_session(jar)

try:
  resource = fetch_resource("https://example.com/app", session=session)
  document = TWebDocument(parse_document(resource))
  document.execute_embedded_scripts(ignore_errors=True, session=session)
finally:
  session.close()
```

## Current boundaries

- The public API centers on `TWebDocument` and `TWebElement`.
- `QuickJSRuntime` is a low-level API, so it is usually not used directly.
- Selectors implement a simple subset rather than full CSS compatibility.
- JS execution is quick.js based and not fully browser compatible
- Form submission primarily constructs the submission data; callers perform navigation and fetching.
- Structured reading for AI is divided into `snapshot()`, and modification with side effects is divided into `agent_actions()`.
- By looking at `snapshot().form_controls[*].supported_actions`, only the read-only side can determine which modification APIs are allowed.

## Related documents

- `README.md`: CLI-centered usage
- `DOM.md`: DOM display policy
- `CSS.md`: CSS interpretation policy
- `JS.md`: JavaScript implementation status and constraints
- `TUI.md`: TUI operation specifications
