[English](JS.md) | [日本語](JS.ja.md)

# JS.md

This document describes JavaScript implementation status and policy in `tweb`. See `README.md` for CLI/TUI usage and `SECURITY.md` for security TODOs.

## Basic policy

- JavaScript execution engine uses quick.js
- Reuse the existing `requests`-based fetching implementation; do not add a separate site-specific fetching path for JavaScript.
- For JS compatibility, we prioritize "minimum browser compatibility to read general pages without breaking them" and do not aim for full browser compatibility from the beginning.
- Gradually expand DOM manipulation, embedded script execution, minimal network API, and re-render consistency
- Do not add site-specific HTML supplementation or direct API calls to the fetching layer. Use JavaScript execution results or generic fallback when needed.
- Synchronize user-visible behavior and permission-boundary changes with `README.md`, `PLAN.md`, and `SECURITY.md`.

## Current implementation status

`tweb` currently supports a broad range of behavior for a lightweight quick.js environment, but it is not equivalent to a real browser. Some supported APIs are only minimal shims.

### Supported

#### Execution paths

- Have quick.js based runtime on `tweb/js_runtime.py`
- You can use `TWebDocument.execute_script()`, `execute_inline_scripts()`, `execute_embedded_scripts()` in Python API
- In CLI, you can apply JavaScript and re-render with `--script` / `--script-file`
- In the normal TUI/CLI route, the embedded script is executed and then displayed.
- When specifying `--browser-render auto|always`, you can use browser-render fallback for remote pages that break with just quick.js.
- `auto` is subject to fallback not only when `main` disappears or clear client-render failure, but also when loading placeholder remains even after quick.js execution
- browser-render fetcher currently implements `chrome` provider and can be replaced and injected with `execute_embedded_scripts(..., browser_render_fetcher=...)`
- The browser-render fetcher injection side uses `BrowserRenderRequest(target, provider, timeout)` and `BrowserRenderResult(content, source, headers, status_code)` as a common contract, and handles cookie bridge, timeout, and empty DOM judgment all at once in the fetch layer.
- The debug log's `browser-render decision` includes `trigger=auto-fallback|manual-retry` and `failure_class=...`, making it easier to identify why fallback was used.
- The quick.js runtime has a default memory limit and reports violations as an explicit `JavaScriptRuntimeError`.
- `tweb.audit` uses browser-render fallback specifically for diagnostics, mechanically comparing `never` and `always` on 20 representative sites.
- Audit rendering runs in isolated subprocesses, allowing remaining sites to continue after QuickJS crashes/segfaults recorded as `quickjs_error`. Internal render subprocesses write their last phase, such as `fetch` / `parse` / `execute_embedded_scripts` / `snapshot`, to stderr so even `exit -11` failures can be localized.
- Collect large inline hydration scripts, especially root payloads such as `window.__data = JSON.parse("...")`, directly from raw HTML first. Do not `JSON.stringify` the same root again in the runtime collector.
- When webpackJsonp bundles hit quick.js compile-time `stack underflow` errors, locally preprocess only problematic modules, replace only remaining failing object entries with no-ops, and continue executing the rest of the bundle.
- Leniently extract webpackJsonp `[` / `{` boundaries even in large bundles containing regexes, template literals, and comments, continuing module registration as long as the overall bundle remains readable.

#### Basic DOM operations

- `document.title` / `document.body` / `document.documentElement` / `document.currentScript`
- `querySelector` / `querySelectorAll` / `matches` / `closest`
- `getElementById` / `getElementsByTagName` / `getElementsByClassName`
- `textContent` / `innerHTML` / `outerHTML`
- Attribute access and updates, `classList`, `dataset`
- `createElement` / `createElementNS` / `createTextNode` / `createComment` / `createDocumentFragment`
- `appendChild` / `append` / `prepend` / `insertBefore` / `replaceChildren` / `replaceWith` / `remove`
- `cloneNode` / `contains` / `isEqualNode` / `getRootNode()`
- Minimum implementation of `createRange` / `createTreeWalker` / `getSelection`
- Minimum implementation of `getComputedStyle()`

#### Script execution and events

- Execute inline scripts in order.
- External script loading is supported.
- Support loading dynamically inserted `<script src=...>`.
- `async` / `defer` / `type="module"` have minimal scheduling support that runs them after immediate inline scripts.
- Share `window` global state across scripts.
- Minimally dispatch `DOMContentLoaded` / `readystatechange` / `load` / `pageshow` / `visibilitychange` / `focus`
- For static portals with sufficient body content, links, and controls, skip `load` / `pageshow` and run through `DOMContentLoaded`, preserving fetches inside jQuery ready callbacks. For extremely dense pages with at least 400 links, also skip ready timers.
- `setTimeout` / `clearTimeout` / `setInterval` / `clearInterval`
- `requestAnimationFrame` / `requestIdleCallback` / `queueMicrotask`
- Drain near-term timers/microtasks without waiting indefinitely for distant future timers.

#### External script cache policy

- External script caching is a performance option, but full browser-grade persistent HTTP caching is not an initial assumption.
- Store the external script cache in `diskcache` to avoid fetching the same script again across processes.
- The cache key is based on `URL`, and the variant is separated based on the request condition only when the response returns `Vary`.
- Avoid long-lived caches that ignore `Cache-Control` / `ETag` / `Last-Modified` as they run the risk of continuing to use old bundle and deploy switches.
- Initially limit the cache to `GET` external scripts; do not extend it to general runtime `fetch` / XHR JSON responses.
- `--debug` allows you to track hit / miss / revalidate / bypass of script cache, improving speed and making it easier to isolate behavior differences.
- Provide a bypass such as `--no-script-cache` if needed, allowing forced refetches during live reproduction and diagnosis.

#### Performance aspects added in Phase 12

- `document.execute_embedded_scripts()` records phase timings/counts in `javascript_debug()` and debug logs for script evaluation, page events, async drain, style rebuilding, hydration, and browser-render comparison. `slow_scripts` lists the slowest scripts, helping determine whether 1 large bundle dominates total time on a live site.
- `querySelector` / `querySelectorAll` / subtree selector has a cache for each mutation epoch, which reduces the fixed cost of bundles that repeat the same selector in the same DOM state. Hit/miss is left in `javascript_debug()` as `selector_query_cache_hits` / `selector_query_cache_misses`
- `getElementById` / `getElementsByTagName` / `getElementsByClassName` use dedicated bridge tree-traversal fast paths rather than falling back to `querySelector` / `querySelectorAll`. jQuery/jQuery UI bundles call these 3 APIs frequently, so avoiding repeated selector-engine calls provides consistent gains.
- `compareDocumentPosition()` compares based on ancestor/sibling instead of flattening the entire document, and easily returns `DOCUMENT_POSITION_DISCONNECTED` between detached nodes. If jQuery 3's support probe stops here, the entire subsequent bundle will not proceed, so it will be absorbed first as basic DOM compatibility.
- After jQuery loads, automatically apply a legacy shorthand shim that routes old event shorthand such as `$(window).load(fn)` to `on('load', fn)`. Preserve the Ajax form `$('#node').load('/fragment.html', ...)`.
- When rebuilding QuickJS after an ignorable external-script error, rerun the successfully loaded jQuery core like constant bootstraps. Restore library globals in the clean runtime so subsequent scripts do not fail in succession with `$ is not defined`. Do not extend replay to jQuery plugins or DOM-mutating scripts.
- Synchronize window named properties derived from `id` before and after script execution, allowing legacy scripts to reference `<div id="emergency">` as `window.emergency` or bare `emergency`. Do not overwrite built-ins or explicitly assigned globals.
- A custom-element search placeholder like `gcse:searchbox-only` appears as a synthetic form control even though the runtime cannot yet insert an actual `<input>` / submit button. Even on pages where the search UI is delayed due to remote script dependence, such as Google Custom Search, it is difficult to lose the input system control for audit purposes.
- `document.write()` / `document.writeln()` can insert an HTML fragment immediately after the script being executed. The external script inside the inserted fragment gets the source as parser-blocking and evaluates it synchronously in the current QuickJS context. Failure to obtain and evaluate individual scripts does not stop subsequent parser-inserted scripts, and connects Google CSE placeholders and legacy dependency chains to subsequent visible DOM collection.
- Detached documents and `iframe.contentDocument` support `open()` / `write()` / `writeln()` / `close()` so bootstraps that write ad or analytics markup into temporary documents can continue.
- `Node.prototype.contains()` can fallback to self/descendant traversal even if prototype target does not have an individual method and continue node containment check of MutationObserver callback.
- On pages already containing sufficient visible content, prune standalone `Loading...` / `NOTICE Loading...` placeholders after embedded scripts. This prevents leftover client shells from causing `alternate_content_branch` classification.
- `XMLHttpRequest` has `overrideMimeType()` and `responseXML` in addition to `responseType='document'`, making it difficult to stop callbacks from government sites that load the same-origin partial HTML and insert header / footer / topics.
- `responseText` of XHR is restored from bytes to charset-aware, and `overrideMimeType('...;charset=UTF-8')` and meta charset are respected even in partial HTML where `text/html` is returned without charset to avoid garbled characters.
- Protect page event dispatch with existing async drain budgets, preflight, and pending-job limits rather than QuickJS's `set_time_limit()`. Callbacks such as `querySelectorAll` that use the Python bridge are incompatible with time limits and would interrupt hydration on normal audit paths.
- Skip expensive page event dispatch not only on pages with many delayed scripts, but also on static portals whose raw HTML already contains sufficient body content, links, and controls. Preserving available content and avoiding timeouts improves both quality and performance compared with waiting for UI polish or animation after `load` / `pageshow`.
- The `parentNode` / `removeChild` / `insertBefore` series after DOM mutation retains `_tweb_parent` to prevent it from falling into a full tree search. Even sites that often search for parent elements in page events and jQuery callbacks can reduce the fixed costs of mutation-heavy paths.
- Text-only mutations such as updating the contents of `TextNode` or detaching a text node do not drop the selector query cache epoch and style context cache. Avoid discarding the result of `querySelector(All)` every time just by replacing the body unrelated to selector/style, and reduce the fixed cost of mutation-heavy app bundle
- In carousel, which adds `visibility:hidden` only before mounting, like Splide, text-rich and uninitialized containers are not simply treated as hidden. Avoid the entire body being judged as invisible due to initial CSS
- External scripts use a persistent `diskcache`-based cache in the default user cache directory. Use `URL` as the base key and separate request variants only when `Vary` is present.
- cache entry looks at `Cache-Control` / `ETag` / `Last-Modified` and does a short revalidation, but does not keep `no-store`
- Reuse quickjs crash-safety preflight results under identical conditions within the runtime. Limit prior scripts passed to the probe to a few recent scripts and a character budget to avoid oversized payloads.
- `_drain_async_work()` stops early when only timer progress without DOM/network changes continues, reducing unnecessary waits
- For static-rich pages with at least 200 raw links, limit 1 async drain to 8 timers. Log the step and DOM mutation count immediately before timer execution to identify the last stage before a native crash.
- For pages whose body remains extremely sparse after load, drain pending timers through the staged horizons `250ms -> 1s -> 5s -> 10s`, isolating callback compatibility errors before proceeding. Even on dynamic pages with readable content, perform a short additional drain capped at `1s` only when DOM mutations and ready timers remain.
- The visible text of closed `select` uses only the selected option, the unspecified single-select uses the first option, and the multiple-select uses only the explicit `selected` as the body.
- Suppress restoration of the initial body after hydration when the mounted DOM has at least 3 more form controls than the initial shell. This avoids mistaking apps such as Vue, which replace `el` itself with a rendered root and remove its original ID, for client failures and reverting a working search UI to an empty shell.
- Style caches still rebuild globally, but invalidation/rebuild measurements now support quantitative comparison of future localized improvements.
- Reuse the document metrics cache per phase not only for delayed-script and expensive-event skipping, but also for pruning post-script loading placeholders and client-failure shells. Avoid repeatedly aggregating visible body/link/control metrics on large DOMs and reduce generic cleanup costs.
- Even when substantial body content is readable, pages with runtime/hidden-content hints and few visible links can lazily reuse long raw-HTML anchors in a `Recovered Links` section. This lighter alternative to full hidden-DOM restoration fills feed/discovery link gaps, including minor gaps on `jaxa-home` / `yahoo-news-jp-home`.

#### Phase 17 execution efficiency

- `execute_embedded_scripts(render_efficiency=True)` uses a generic resource policy by default. `navigator.sendBeacon` will be blocked regardless of the destination. Block communications with `telemetry` / `beacon` / `analytics` in the URL path segment and fetch/XHR with known extensions for images, videos, audio, and fonts before fetching.
- Prioritize body fetching: preserve fetch/XHR requests with `api` segments or `.json` / `.html` / `.htm` extensions, and allow unknown URLs as content candidates. Do not block scripts based only on media extensions. Apply telemetry classification at the fetching boundary before cache lookup, including prefetch. Do not classify before fetching solely from MIME types or claim to detect arbitrary tracking traffic.
- During post-load async drain, inspect the body, links, and input state in visible `main` / `article` / `role=main` every 8 timers. Finish with `body-stable` when there are at least 200 characters and paragraph/heading structure, state remains stable for at least 500ms of virtual time, and content-candidate requests do not increase. Process microtasks and currently runnable timers first.
- Limit probes to 20,000 nodes / 200,000 characters; exceeding the limit must not count as stable. Use CSS visibility and do not finish early for content under hidden ancestors or loading-only content. Inferred body-region termination, forced interruption of normal script evaluation, and early completion of all hydration remain outside scope.
- Leave the resource judgment and async drain termination reason in `javascript_debug()["render_efficiency"]` and debug log. Text candidates are not classifications that guarantee actual text contributions. Existing button communication authority takes priority, and permission denial is not canceled even with `render_efficiency=False`
- Pause efficiency optimizations during explicit button operations; do not suppress requests permitted by `network`. Preserve `dom` network denial.
- While verifying fetch/XHR preservation, also fixed an existing issue where a NUL byte appended to responses with base64 padding caused `Response.json()` to fail.

#### Fetching and data APIs

- `fetch`
- `XMLHttpRequest`
- `Request` / `Response` / `Headers`
- `URL` / `URLSearchParams`
- `FormData`
- `Blob` / `File` / `FileReader`
- `ReadableStream` / `WritableStream` / `TransformStream`
- `TextEncoder` / `TextDecoder`
- `document.cookie`: Reflect the assignment in the HTTP(S) document to the CookieJar of the requests session and carry it over to reacquisition according to domain / path / Secure / expiration date

#### Supporting APIs

- `window` / `location` / `navigator` / `history` / `navigation` / `console`
- After initial script/timer `location.reload()` calls, refetch with GET using the same session and execute the new document's scripts. Limit refetches to 3 per 1 page load and log when the limit is reached. Button-click reloads follow the existing navigation policy.
- Major event types such as `EventTarget` / `Event` / `CustomEvent` / `MouseEvent` / `KeyboardEvent` / `PointerEvent`
- `localStorage` / `sessionStorage`
- Minimum implementation of `indexedDB`
- `matchMedia`
- Minimum implementation of `MutationObserver` / `IntersectionObserver`
- Part of `Intl`

#### Hydration data fallback

- The generic collector for `tweb/runtime_data.py` is the known root for `window.__NUXT__` / `__NEXT_DATA__` / `__INITIAL_STATE__` / `__APOLLO_STATE__` / `__PRELOADED_STATE__`, inline JSON script, chunk arrays such as `__next_f`, and `fetch` / XHR JSON during runtime. Normalize responses to the same exit
- `__ref` of Apollo normalized cache is commonly resolved with `tweb/apollo.py`. Targets caches with roots such as known `__APOLLO_STATE__` root, cache with the same name in bootstrap, and `ROOT_QUERY`, and does not interpret fields with the same name in normal JSON as references. If `ROOT_QUERY` exists, use the data that arrives from there and do not mix irrelevant cache entries with the main text. Circular reference/reference break shall be `None`, and shall be terminated at depth 16 and 10,000 values to be processed. Do not change input cache
- The generic collector also reads directly embedded JSON literals and `[{type,value,children}]` text fragments from inline scripts, inserting recovered text into short shell pages.
- This is a common form of embedded web state, not a concept specific to `tweb`.
- The `tweb`-specific behavior is a fallback that extracts heading, link, and section candidates from embedded state and inserts them as supplementary content when the body is empty or contains only loading placeholders.
- This processing is generic structural extraction into `HydrationSection` / `HydrationLink` / supplementary text, rather than site-specific behavior.
- Do not trigger supplementation from low-signal hydration values such as UUIDs, internal URLs, dates, or short UI labels when sufficient body content is already available.
- After supplementation, use `document.hydration_debug()` to inspect selected sources, `confidence`, and whether site-specific fallback was used.
- A compact functional UI with links and input controls, even if it is less than 1000 characters, takes precedence over undisplayed hydration values and does not replace app mounts.
- Supplement links using explicit payload URL/path/pathname fields or existing DOM anchors uniquely matching a label. Do not construct site-specific routes from `urlname` / `key` / `engName` / `parentDir` / `slug`. Do not guess when identical labels point to different URLs.
- Items without URLs are retained as text, and sections with multiple long article titles are collected as recovered text. A section with a navigation role is placed after the body text candidates, and the article candidates are displayed first even if there is no navigation-specific insertion destination. Do not mix CSS class / style values or Flight property reference strings into supplementary text
- Determine body/navigation supplementation targets in `tweb/hydration_targets.py`. Use `main` / `article` / `nav`, ARIA `main` / `feed` / `tabpanel` / `navigation`, headed lists, and link density; do not infer purpose from classes such as `timeline__body` or URL patterns `/topic/` / `/n/`.
- Prioritize explicit section roles. Without a role, use navigation-region `aria-label` / `aria-labelledby` and correspondence with headings/existing links. Keep unclassified sections in body content, and do not duplicate navigation items as unstructured body links.
- Supplement explicit empty body regions or a uniquely identifiable empty region beside navigation. For unknown empty divs, equally ranked candidates, or large structurally ambiguous candidates, append to `main` / `role=main` (or body) without replacing existing content. Limit structural inference to 256 nodes and 64 children per node.
- Do not select hidden candidates under `hidden` / `aria-hidden` / inline styles, header/footer/ARIA banner/contentinfo navigation, or existing/new input UIs as empty supplementation targets. These checks do not guarantee full external-CSS visibility calculation or semantic inference of ambiguous panes.
- Read note.com's home/topic pages through the generic collector using inline Flight, known roots, and the page's own fetch/XHR responses. Removed fixed API endpoint synthesis, dedicated probes/polling/retries, and Python API refetches. Handle page-issued requests and async work through existing runtime/session/drain paths.
- A class static block that QuickJS cannot interpret is converted to an arrow initializer of a private static field in the same position and executed. Maintains initialization order and lexical `this` / `super` and invisibility from the outside, and does not convert the text of strings, comments, and regular expressions. You can check whether there is conversion with `class_static_block_rewrite_scripts` and debug log
- Generically restore the initial layout when `main` with sufficient initial content disappears and leaves only a short header/footer. Do not restore on this basis when a new input UI or sufficient alternative content exists.

#### Current position of `site_specific.py`

- `tweb/site_specific.py` does not continue to be a "site name-based exception collection", but is treated as a temporary location for residuals that have not been promoted to the generic side yet.
- Only selecting Kakuyomu works from the Apollo cache, converting table-of-contents schemas into sections, and generating episode URLs remain site-specific. Apollo reference resolution and disclosure injection are generic. There is no dedicated note.com fetch/data-conversion path.

#### Current residual issues by failure class

- disclosure / accordion:
  Use generic disclosure completion to insert `HydrationSection` into hidden panel or button with `aria-controls` by matching the heading. In addition to site-specific sections, sections extracted by the generic collector are also complemented using the same route. Panels with existing text, input fields, links, and media and empty sections are excluded from completion.
  When readable body content is sufficient and all previously collected sections have been placed in corresponding panels, skip further generic collection regardless of URL. Continue normal collection if unmatched sections remain. Removed the previous Kakuyomu-episode-URL condition and use debug reason `body-already-readable-with-disclosure-sections`. Moved Kakuyomu Apollo reference resolution to `tweb/apollo.py`, leaving table-of-contents schema interpretation and episode URL generation site-specific. Read only necessary fields of entities reachable from the target work; limit transfers to 200,000 characters per 1 entity. Ambiguous-candidate resolution and role-based target selection remain future work.
- runtime mount failure:
  Use class static block syntax conversion, restoration of missing main content, and a shared collector for inline Flight and runtime network JSON. Display articles without a supported URL as text rather than generating incorrect links. This does not guarantee successful mounting of all React/Nuxt apps or reproduction of unknown routers.
- pane layout restore:
  Restore the main ancestor path and meaningful shell siblings generically. Move body/navigation selection to HTML/ARIA/structural checks and remove class-name-based region detection. Append ambiguous candidates to the body without selecting one arbitrarily. Detailed pane-level restoration and ambiguous disclosures with identical names remain open.
- inline Flight chunk scan:
  The generic runtime-data collector reads not only the execution result of `window.__next_f` but also the `__next_f.push(...)` string itself in the HTML. Even if you miss the `__next_f` reference in the script execution order or runtime state, you can restore nav data such as categories / subCategories in the topic sidebar.
- Visible client-failure shell cleanup:
  When sufficient visible body text remains but a failure shell such as `申し訳ありません、ただ今障害が発生しております。` hangs off a separate section, remove that shell from the DOM before browser fallback so it does not enter final output.

## Policy to reduce `site_specific`

- Policy 1:
  Classify failures by failure class rather than site name. Use `incomplete section normalization from Flight fragments` or `incomplete interactive disclosure expansion` instead of `note.com support`.
- Policy 2:
  Strengthen a common normalization surface equivalent to `HydrationSection` rather than forcing all extractors into 1 implementation. `__NEXT_DATA__`, `__NUXT__`, Flight, and XHR/`fetch` observations may use different collection methods.
- Policy 3:
  Make supplementation conditions generic. Combine missing `main`, persistent loading shells, sparse content, and missing section roles to decide from page state rather than URLs.
- Policy 4:
  Browser-render fallback is used not only as an escape route but also as a difference measuring device. Calculate the missing DOM API, event, network model, and runtime data from the difference between the QuickJS result and the browser-render result.
- Policy 5:
  Before adding a new branch to `site_specific.py`, write at least the failure class that the branch absorbs, candidates that can be promoted to the generic side, and the reason for leaving it as a residual until the end.

## Regular audit loop

- `python3 -m tweb.audit` uses the unified 44-site inventory in `tweb/data/quickjs_audit_sites.json` by default and ranks differences between QuickJS-only and forced Chrome output. JP/EN share 1 canonical manifest; 20 sites, primarily with unresolved differences, are explicitly focused through `active_site_ids`. Use `--tag jp` or `--tag en` to narrow the selection.
- Measure visible body length, visible/full-body similarity, title match, link count, input-control count, and snapshot DOM-node count, classifying results as `match` / `minor_gap` / `major_gap` / `quickjs_error`.
- Retain raw button/tab counts, but prioritize user-input controls such as text/select/radio/checkbox/submit in audit comparisons to avoid false positives caused by decorative site-chrome buttons.
- `--probe-navigation` fetches 1 representative same-site link and records the next page's title, visible body length, and link/control counts in audit JSON.
- If Chrome and QuickJS differ only in the locale variant of the main text, treat the locale difference as a separate reason and do not add `major_gap` based only on string similarity.
- Prefer `minor_gap` over `major_gap` when titles, links, input controls, and DOM are close and only visible body length is slightly below the threshold. Avoid overstating minor differences from text-rich carousels or delayed cards.
- Since the manifest has tags such as `public`, `service`, `reference`, `research`, `government`, `transport`, `weather`, etc., the same inventory can be continuously monitored by language and category.
- Keep `quickjs_error` / timeout cases with stable raw fetches in the canonical cohort as runtime regression targets, even when comparison is expensive.
- After fixing a new live bug, add its URL to the manifest for recurrence monitoring and regular comparison rather than stopping at a one-off fix.

## Suggested implementation order

- 1.
  Give each branch in `site_specific.py` a 1-line failure-class description rather than a target-site label.
- 2.
  Enhance common section/link normalization surfaces like `HydrationSection` to force known root, flight, runtime probe, and Python retry to flow to the same exit.
- 3.
  Model disclosure/accordion, tab, and pane expansion through generic interactions rather than individual DOM class names.
- 4.
  Fill in the missing APIs and async execution models on the QuickJS side in order of the number of real page failures.
- 5.
  Remove branches from `site_specific.py` as generic support absorbs them; treat only the remaining cases as residual site-specific behavior.

### Limited support

- `fetch` / `XMLHttpRequest` can be used as API names, but internally they are minimal implementations that synchronously call the existing Python acquisition layer, and are not the actual browser communication model itself.
- Local files and `http` / `https` are supported, but same-origin policy, CORS, SSRF controls, and permissions for additional requests remain undefined.
- If you pass the session held by TUI/CLI, obtain it via that session.
- You can execute JS-driven button clicks from TUI/API and classify DOM updates, communications, and transitions. There are `off` / `dom-only` / `network` stage permissions, low level API default is `dom-only`, TUI default is `network`. Control of communication destinations including same-origin / CORS / SSRF is not yet in place
- `iframe` has a minimal shim with `contentDocument` / `contentWindow`, but does not have independent real page loading or full-fledged frame navigation
- In addition to HTML fragments, `DOMParser` parses XML into Python DOM and handles elements with namespace prefix and `getElementsByTagName()`. `canvas`, `audio`, `dialog`, `Image`, `BroadcastChannel`, etc. are mainly lightweight implementations for compatibility, and do not guarantee drawing, playback, or OS integration.
- `MutationObserver` / `IntersectionObserver` / `matchMedia` / `indexedDB` / `storage` prioritizes minimum operation for real page compatibility
- `Worker` has a constructor but does not execute scripts in a separate thread.
- Although the DOM compatibility required by React-based sites has increased considerably, it is not yet possible to reliably reproduce all SPAs.

### Unsupported

- Full browser compatibility
- Strict limits on JavaScript execution time
- Strict same-origin policy / CORS enforcement
- Real, executable `Worker` / `SharedWorker`
- `ServiceWorker`
- `WebSocket`
- Real-browser-equivalent layout calculation, rendering, painting, and media playback
- Reading every client-rendered SPA without browser-render fallback

## Limitations and open issues

- The quick.js runtime has a default memory limit, but fine-grained CLI/TUI settings and per-page policies are not implemented.
- Page event dispatch has an internal API accepting a time limit, but normal paths call it with `time_limit_seconds=None` to avoid incompatibility with Python bridge callbacks. Async drain budgets exist, but strict wall-clock interruption of general script evaluation or individual callbacks is not implemented.
- Same-origin policy and CORS remain undefined.
- It is necessary to reorganize the extent to which `fetch` / XHR should be allowed by default.
- The external script cache implements persistent `URL`-based storage with `Vary` variants. Broader `Vary` combinations and eviction policies remain future work.
- Some iframe and worker shims exist, but service workers and WebSockets are unsupported.
- JS-driven button click is handled in a different route from submit, and the results are classified into `dom_updated` / `navigation_requested` / `network_requested` / `javascript_required`. Staged permissions are implemented, and the safe boundary of the communication destination is an ongoing issue for `SECURITY.md`.
- Although React-based sites continue to expand compatibility, it is not yet possible to reliably reproduce all client-rendered SPAs.
- Some large bundles use local fallbacks for quick.js compiler-specific failures, prioritizing readable content over full compatibility.

## Implementation decisions

- The runtime's public entry point and `QuickJSRuntime` implementation live in `tweb/js_runtime.py`.
- Bundle preprocessing and syntax assistance on the Python side is `tweb/js_runtime_helpers.py`
- The large JS bridge definition lives in `tweb/js_runtime_bridge.py`.
- Document API calls and hydration fallback enter through `tweb/api.py`.
- Runtime data collection and generic section/link normalization live in `tweb/runtime_data.py`.
- HTML / ARIA / Structure-based completion target/section role determination is `tweb/hydration_targets.py`
- Apollo cache reference resolution and runtime entity limited read is `tweb/apollo.py`
- Residual hydration/interaction supplementation not yet promoted to generic support lives in `tweb/site_specific.py`.
- CLI script loading is `tweb/cli.py`
- TUI script execution flow is `tweb/tui.py`
- Regression tests primarily live in `tests/test_js_runtime.py` and `tests/test_cli.py`.

## Future direction

- The main JavaScript execution engine will continue to be quick.js, and the default policy will not be to completely replace it with another engine.
- Even when considering replacement, first assess whether the current quick.js DOM bridge, Python callbacks, and synchronous fetching integration can be preserved.
- When only specific bundles or syntax classes fail in quick.js, consider local preprocessing or limited fallback before replacing the engine entirely.
- Only if failures remain difficult to address in quick.js, consider an auxiliary engine for problematic script execution while keeping quick.js as the default.
- When extending compatibility APIs, prioritize those that directly address failures on real pages.
- Keep fetching generic without site-specific bypasses.
- External scripts have a persistent cache reusable across processes; variant management and eviction remain future work.
- Keep JavaScript execution results consistent with normal mode/DOM mode/TUI display
- Separate network, DOM-update, and navigation permissions explicitly into stages.
- Document differences between security constraints and implemented features in `SECURITY.md`.

## Individual URL verification records

- 2026-10-19: `https://www.kanaloco.jp/electiondata/article-1311506` requires HTTP 307 JavaScript Cookie challenge `location.reload()`. By reflecting the cookie session and implementing reloading, `--browser-render never --mode text` re-fetched HTTP 200 and was able to display the article title and surrounding text. The list of candidates in the preliminary vote count report was unconfirmed at this time. Chrome fallback is not used.
- Regression verification for the same change: 609 of 610 JavaScript/document API/CLI/TUI tests passed. `test_augments_note_topic_sections_from_runtime_probe` failed, but the same failure reproduced on pre-change code extracted from `828d82f` at task start. All 6 newly added Cookie/reload/TUI tests passed.
- After integrating main's `2fab30f`, all 695 JavaScript/document API/CLI/TUI/normal-renderer regression tests passed.
- Additional pre-fix comparison at the same URL: real Chrome and `--browser-render always --mode text` display names, votes, and biographies for 7 candidates, seat count, candidate count, and vote-count progress. QuickJS displays 0 candidates, leaving `v-cloak` and unexpanded `template v-for`. The displayed list consists of `div` generated by Vue 2.6.12 rather than `<table>`.
- The original HTML's inline script contains XML for 7 candidates, so missing data or normal-renderer table support is not the cause. After XML parsing with `DOMParser`, `jQuery(xmlDocument).find('root > places > place')` fails with `TypeError: createElement is not implemented`. QuickJS's `querySelectorAll('root > places > place')` returns 1 item for the same XML, and a simple jQuery `find('place')` also returns 1 item. Missing compatibility in jQuery selector initialization for XML Documents prevented the later Vue mount.
- Candidate-list fix: added node-creation APIs for selector-engine feature probes and document child-node information to XML Documents, preserving XML element case and ownerDocument. jQuery's `find('> candidate')` now returns 7 items. HTML attribute serialization also preserves single quotes inside double quotes, fixing render-function compilation failures caused by `&#x27;` remaining in Vue template expressions. No site-specific fetch or data supplementation was added.
- Post-fix real-URL verification: `--browser-render never --mode text` rendered the candidate list. Against XML in the fetched HTML, both QuickJS and Chrome text output included names, vote counts, and biographies for 7/7 candidates, with matching vote-count progress. Election data changes over time, so this verifies the same retained data. Existing errors in surrounding scripts remain, but candidate-list generation succeeded.
- Candidate-list regression verification: added tests for XML selector-engine feature probes, XML nodeName/ownerDocument, and HTML attribute serialization of template expressions. All 699 JavaScript/document API/CLI/TUI/normal-renderer/parser tests passed.
- After integrating main's `d6ca3c6`, all 706 regressions above passed. Rechecked that QuickJS alone displays all 7 candidates and vote-count progress at the real URL.
