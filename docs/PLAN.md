[English](PLAN.md) | [日本語](PLAN.ja.md)

# PLAN.md

## Purpose of this document

This document tracks the work plan for implementing the goals described in README.md.
Leave usage and current specifications to README.md / TUI.md / DOM.md / CSS.md / SECURITY.md, and prioritize the following 3 points here.

- What is complete
- What remains in progress
- What to work on next

## Goals

- Captures and parses HTML and displays it stably in human-readable normal mode.
- Provide human-facing DOM summaries and detailed AI DOM output from the same fetched content.
- Gradually expand the minimum implementation of CSS/JavaScript to improve reading quality and operability
- Textual-based TUI provides Emacs-compliant keyboard operations similar to standard text editing on macOS
- Create a BeautifulSoup compatible API and interface for future AI operations
- Support semi-automatic transfer of credentials or sessions to authenticated pages while preserving safety boundaries with external credential managers.
- Continuously manage security requirements in `SECURITY.md` and refine them alongside feature additions.

## Assumptions

- Use Python 3 for the main implementation.
- Use quick.js for JS execution
- TUI infrastructure uses Textual
- Prioritize existing libraries for HTTP/HTTPS acquisition and use `requests` for standard implementation
- Base keyboard controls on Emacs conventions close to standard macOS text editing.
- Initially prioritize readability and structures convenient for AI agents over full web compatibility.

## Current status

- Completed phases:
  Phase 1 to Phase 12, Phase 14 to Phase 16. Basic acquisition, normal display, DOM display, BeautifulSoup compatible API, CSS, quick.js execution, Textual TUI, browser-render fallback, snapshot / preflight / mutate API for AI, generic runtime data collector, JS runtime measurement / cache infrastructure, renderer metadata integration, interactive metadata fallback removal, measurement of TUI page construction, and cache reuse when switching panes.
- Not-started phases:
  Phase 13 (external credential manager linkage), Phase 18, Phase 19. Phase 13 has existing infrastructure for cookie import and password editing, but input flow from external commands has not been implemented.
- Partially implemented phases:
  Phase 17. In addition to body-only output with `--mode text --main-only`, generic unnecessary-request classification, body-stable post-load async drain termination, and debug decision reasons are implemented. Real JS-heavy site comparisons and classification/stability extensions continue.
- Phases in progress:
  Cross-cutting security. Although the basic boundaries of APIs for AI have been solidified, the details of same-origin, credential injection, and external authentication flows continue to be refined.
- Next primary phase:
  Phase 17. Evaluate unnecessary-request suppression and body-stable termination on real JS-heavy sites, checking early termination, excessive waiting, and missing content.
- Next design question:
  After Phase 18, we will work out session management using MCP surfaces, authorization models, and how much observable debug surfaces can be integrated into a common API.
- Later backlog:
  Phase 19. Recombine the current token-based wrapping to a break-opportunity base based on Unicode line breaking / CSS Text, and create a text layout foundation that can be extended not only to Japanese but also to mixed-script / CJK / dictionary-required scripts.
- Parallel quality loop:
  Audit representative sites with `tweb.audit`, comparing QuickJS against Chrome. Keep 44 sites in a unified JP/EN manifest and focus on 20 sites, primarily with unresolved differences, through `active_site_ids`. Filter with `--tag jp` / `--tag en` when needed. Track differences as QuickJS backlog rather than treating browser-render as a permanent solution. Retain `quickjs_error` cases with stable raw fetches in the canonical manifest even when comparison is expensive.
- Current capabilities:
  There is `requests` base acquisition, `dom` / `dom-ai` display, BeautifulSoup compatible read API, quick.js execution, Textual TUI, form submit and JS button classification, and fallback operation of `--browser-render never|auto|always` and default `auto`.
- Other improvements:
  Improve the text-editing screen.

## Immediate priorities

1. Phase 9:
   Complete. Organized `snapshot()`, `debug_control()`, and `agent_actions()` into 3 read/preflight/mutate layers, fixing the result contract including `AgentActionResult.status` / `reason` / `available_actions` / `requires_confirmation`.
2. Security:
   Align the JS button / fetch / navigation / credential injection permission model to `SECURITY.md` and `API.md` and further refine the range of default denial.
3. Phase 16:
   Complete. Implemented phase timings for renderer/controls and links/page build/viewport, pane-detection gates for static-rich/hidden subtrees, and buffer/render-metadata reuse on pane switches. Record measurements in `docs/performance.md`.
4. Phase 17:
   Generic unnecessary-request classification and body-stable post-load async drain termination are implemented. Expand real-site comparisons and refine classification/termination while checking missing content and probe overhead.
5. Phase 18:
   Add MCP server as a thin adapter while preserving the existing boundaries of `snapshot()` / `debug_control()` / `agent_actions()`. Initially, limit read / preflight / mutate in units of 1 page/session, and do not assume TUI or internal DOM implementation to be MCP.
6. MCP design details:
   Define session lifetimes, tool-schema backward compatibility, debug exposure, and secret-confirmation handling so they stay synchronized with `API.md` / `SECURITY.md`.
7. QuickJS quality audit:
  The unified 44 sites of `tweb/data/quickjs_audit_sites.json` are kept as canonical inventory, and the 20 sites of `active_site_ids` are continuously compared. While also using `--tag jp` / `--tag en`, prioritize `major_gap` and `quickjs_error` and decompose them into the lack of generic runtime / DOM / hydration / interaction.
8. Phase 19 design notes:
  Move line wrapping from fitting word tokens to a width toward enumerating Unicode line-break opportunities and then choosing the final break positions. Respect Japanese punctuation and small-kana restrictions, while supporting mixed Latin/CJK text and eventually dictionary-required scripts such as Thai/Khmer.

## Phased plan

### Phase 1: Project foundation

Status: Complete

- Package structure and CLI entry point are implemented.
- Execution methods and separation of the main documentation are established.

### Phase 2: Acquisition and HTML parsing

Status: Complete

- Implemented acquisition layer to handle HTTP/local file input
- Complete scheme-less host inputs with `http://`; preserve local files as paths.
- Implemented retrieval with cookies and continuation of the same session
- Converts HTML to internal DOM and implements title, body, and link extraction
- Minimal resilience to malformed HTML is implemented.

### Phase 3: Normal mode display

Status: Complete

- Basic headings, paragraphs, links, and lists are implemented.
- Display basic HTML tables as column-aligned text tables.
- Basic line-wrapping and link-display policies are implemented.
- Implemented `--link-style none|inline` switching

Possible future extensions:

- Improve table colspan/rowspan and complex nesting support.
- Improved presentation of `select` / `option`

### Phase 4: DOM mode display

Status: Complete

- Implemented role separation for `dom` and `dom-ai`
- Support separate depth-limited inspection output and detailed AI output.

Possible future extensions:

- Enhanced correspondence between TUI selection targets and operation API and `dom-ai`

### Phase 5: BeautifulSoup compatible API

Status: Complete

- Implemented basic operations for `find` / `find_all` / `select` / `get_text` / `attrs` / `text`
- A format that can be imported as a Python API separately from the CLI has been prepared.

Possible future extensions:

- Clarification of return value format that is easy to handle from AI
- Separate responsibilities when adding action APIs.

### Phase 6: CSS compatible

Status: Complete

Completed:

- Minimal visibility interpretation
- Partial reflection of `font-weight` / `font-style` / `text-decoration`
- Basic correspondence between `style` attributes and embedded CSS
- Minimal external stylesheet loading
- Minimal cascade respecting selector precedence
- Basic selectors, including descendants and `>`
- Minimum interpretation of `display:flex` / `inline-flex` for normal mode
- 2-column approximation of `display:grid`
- `StyleContext` reusable across normal mode / `dom-ai` / TUI

Completion criteria:

- Basic CSS reasonably changes output, and supported behavior is documented.

### Phase 7: JavaScript compatible

Status: Complete

Completed:

- Minimal DOM operation bridge through quick.js
- `querySelector` / `querySelectorAll` / `document.title` / `document.body` / `document.documentElement`
- `textContent` / `innerHTML` / Attribute reference and update
- Running `--script` / `--script-file` from CLI
- Organized the browser-render fallback usage policy into `never` / `auto` / `always`, and clarified the default as `auto`.
- Added a default memory limit to the quick.js runtime.
- Clarify memory-limit errors and synchronize documented limitations.
- Sync re-render consistency and implementation limits after JS execution to `JS.md` / `SECURITY.md` / `README.md`

Completion criteria:

- Lightweight DOM mutations run reliably, with documented support and limitations.

### Phase 8: Keyboard Browsing / TUI

Status: Complete

Completed:

- Textual-based minimal TUI
- Foundation for reading content, following links, and history navigation
- Switching between normal and DOM summary views
- Opening/closing checkbox/label based dropdown
- Minimal form operations for text input/password input/textarea/select/radio/checkbox/submit
- A platform that separates `type="button"` from submit and treats JS-driven button as a separate operation.
- Added API and TUI linkage equivalent to `click_button_control()`, and enabled click to update DOM with `type="button"`
- Background loading and cancellation
- Emacs-compliant major navigation operations, long page scrolling, search, open-location, shortcut help
- Status-line link/submission destinations, JS button policy, and click results
- TUI/API boundaries that handle JS-driven buttons with stage permissions of `off` / `dom-only` / `network`
- Reflect JS-driven button click results in UI/API as `dom_updated` / `navigation_requested` / `network_requested` / `javascript_required`

Completion criteria:

- Browse pages and follow links without a mouse, with consistent primary navigation controls.
- Make the difference between form submission and JS-driven clicks clear in both the UI and API.

### Phase 9: Preparation of AI operation interface

Status: Complete

Purpose:

- Define an API that allows AI to safely read pages today
- Define operations for node lookup, link extraction, and form-candidate inspection.
- Separate the 3 read, preflight, and mutation layers.
- Prefer structured data over ambiguous strings.

Completed:

- `TWebDocument.snapshot()` added a foundation that allows you to obtain links, forms, and DOM nodes in a structure that is easy to convert into JSON.
- We will maintain BeautifulSoup compatibility such as `find` / `find_all` / `select` / `get_text`, and move forward with the policy of bringing changes to `agent_actions()` side.
- Added read-only search aid to `AgentPageSnapshot`, allowing link / form control / DOM node to be narrowed down directly from ID or condition on `snapshot`
- `debug_control()` / `debug_controls()` can now return structured debug information that can be used to pre-check button clicks and form submits.
- Added `AgentSnapshotControl.supported_actions` and `AgentActionRequest` / `AgentActionResult` / `agent_actions().invoke()`, and structured and clarified the boundaries between read-only judgment and change-capable invoke.
- `snapshot` / `debug_control()` / `agent_actions().invoke()` has been clarified as 3 layers of read / preflight / mutate in `API.md` / `DOM.md`
- Added `status` / `reason` / `available_actions` / `requires_confirmation` to `AgentActionResult` so that not-found / unsupported / blocked / requires-confirmation can be returned as a structured result instead of an exception.
- Password injection is denied by default in the mutate API and requires an explicit retry with `confirmed=True`.
- Block of button click policy can now be expressed not only on `blocked_by_policy` but also on mutation API, and only cases where interaction itself is stopped are applied to `status="blocked"` / `reason="blocked_by_policy"`

Completion criteria:

- Page analysis and basic operation calls from AI are stable and permission boundaries are clear.

### Phase 10: Runtime Data / Hydration Generalization

Status: Complete

Purpose:

- Create a runtime data collector that can collect not only known roots such as `window.__NUXT__` and `__NEXT_DATA__`, but also chunk columns and delayed input data.
- Infer headed sections, card lists, and navigation candidates from array/object shapes without depending on site-specific module IDs or URL patterns.
- Reconstruct hrefs from runtime data using a generic resolver based on the base URL, existing DOM, and relative-link rules rather than site-specific branches.
- Organize DOM reconciliation of missing `main` / `aside` / loading placeholders after script execution as generic container inference rather than site-specific checks.
- Provide debug information and confidence assessments that explain which supplementation results were used and why browser-render fallback was selected.

Completed:

- Added `tweb/runtime_data.py` so that 4 known systems on `window`, including hydration root, inline JSON script, chunk array, and `fetch` / XHR response, can be sent to the same normalization interface.
- The generic collector now reads JSON literals and text-fragment dictionaries embedded directly in inline scripts and uses them to supplement short shell pages with recovered text.
- The generic collector normalizes data into `HydrationSection` / `HydrationLink` / supplementary text, using `title + item list + role` as a shared output.
- Use explicit URL/path/pathname fields or existing DOM anchors uniquely matching a label. Removed site-dependent URL inference from `urlname` / `key` / `engName` / `parentDir` / `slug`; retain unsupported items as text.
- Generic runtime data supplementation runs before browser-render fallback, with results traceable through `confidence` and source summaries from `hydration_debug()`.
- Added regression for inline JSON, `__next_f`, network JSON response, and loading shell replacement to `tests.test_document_api` / `tests.test_js_runtime`
- Regarding `__next_f`, include not only the array on runtime but also the `push(...)` string in inline script as a regression target, check `inline-chunk` in source summary and prevent recurrence of categories / subCategories in note.com topic sidebar
- Removed note.com's fixed API probes, retries, and Python refetches. Collect JSON from page-issued requests through the existing runtime network collector. Implemented class static block syntax compatibility and restoration of missing main content while preserving the footer, without site-name checks.
- Consolidated body/navigation classification into `tweb/hydration_targets.py` and removed purpose inference based on URL formats and specific classes. Use HTML/ARIA, correspondence with headings/existing links, list structure, link density, and unique empty regions adjacent to navigation. Append ambiguous candidates to main content without replacing existing DOM.

Remaining issues:

- Interpretation of Kakuyomu work/table-of-contents schemas and episode URL generation rules
- Generalize fine-grained restoration by pane/disclosure/tab rather than replacing the entire shell.
- Disclosure recovery now provides generic heading-based supplementation, but resolving multiple ambiguous candidates and selecting targets by section role remain open.

Completion criteria:

- `tweb/site_specific.py` becomes a thin fallback that handles "only the residuals that cannot be obtained with general-purpose extraction"
- Recover a useful amount of section content on new script-heavy sites without individual regexes or module IDs.
- You can try generic runtime data completion before browser-render fallback and explain its success or failure with tests and debug output.
- `JS.md` / `README.md` / `SECURITY.md` organizes where generic runtime completion ends and site-specific fallback begins.

### Phase 11: Optional Browser-Render Strategy

Status: Complete

Purpose:

- TUI maintains the normal display based on quick.js, but has a UI that allows browser-render retry by explicit operation only when necessary.
- Extract the Chrome-direct implementation into a fetch layer abstraction so that it can be replaced with a different provider or invalidation implementation in the future.
- Sort out the gaps around DOM API / timer / fetch that should be filled on the quick.js side and reduce them gradually so that you don't have to rely on browser-render fallback.

Already implemented:

- `--browser-render never|auto|always` allows explicit control of fallback policy
- Remote URLs have a fetching layer using a browser-render provider. The current provider is `chrome`, with an injection point for replacements.
- `r` appears as manual retry in TUI, and title/status distinguishes `Chrome manual retry` and `Chrome auto fallback`
- `browser-render decision ...` The trigger and failure class appear in the debug log, so you can track auto fallback / manual retry / provider unavailable later.
- In the Python API, optional components can be injected with `execute_embedded_scripts(..., browser_render_fetcher=...)`
- The provider injection surface uses the `BrowserRenderRequest` / `BrowserRenderResult` contract, with shared Cookie bridging, timeout, and empty-DOM checks in the fetching layer.
- Default `auto` fallback and explicit retries are distinguished in both UI and debug output.

Next items:

- Continuously collect the types of real pages that were required by browser-render and update the priority order of DOM / event / network gap that should be absorbed by QuickJS side
- Take the worst offenders from a constant comparison like `tweb.audit` and put them in order of improvement by failure class instead of a single site-specific fix request.
- When adding providers, replace only the devtools/CDP-dependent implementation under the existing contract, and further define Cookie bridge origin boundaries and post-redirect handling.

Completion criteria:

- Keep normal usage independent of Chrome while allowing explicit fallback when needed.
- The browser-render implementation is separated as an optional component, leaving room for future replacement.
- Continuously reduce the need for browser-render by extending quick.js support.

### Phase 12: JS Runtime Performance and Cost Control

Status: Complete

Purpose:

- Create measurement and improvement aspects that can continuously reduce the execution costs that dominate JS-heavy pages without compromising QuickJS-based reading quality.
- Target shared costs in script loading, event dispatch, async drain, DOM/style recalculation, and runtime supplementation rather than site-specific speed fixes.
- Use the browser-render fallback as a comparison target in terms of performance so that you can determine which bottlenecks should be shortened as a priority on the QuickJS side.

Completed:

- Third-party script skipping, the `StyleContext` cache, and shorter post-load async drains already improve real pages.
- Added phase-specific timing/count to `javascript_debug()` and debug log, allowing you to follow script eval / page event dispatch / async drain / style rebuild / hydration / browser-render comparison.
- Reuse external scripts through a shared file cache across processes, using `URL` as the base key and varying by request conditions only when `Vary` is present.
- Added a short revalidation that looked at `Cache-Control` / `ETag` / `Last-Modified` and implemented a minimum policy that does not hold `no-store`
- `_drain_async_work()` now stops early when only timer progress without DOM/network changes continues, reducing unnecessary waiting.
- You can disable cache with `--no-script-cache` and distinguish between hit / miss / revalidate / bypass when debugging.
- Added unittest regressions for script-cache reuse/bypass and the debug surface.

Known residual issues after completion:

- Style cache invalidation still rebuilds globally rather than recalculating locally by attribute/class/style. This is future optimization work, not a missing requirement blocking Phase 12 completion.
- Continuous real-page performance benchmark fixtures remain limited, and more live reproductions are needed. Continue building this observation coverage after Phase 12 completion.

Completion criteria:

- Debug logs explain which processing stages dominate on JS-heavy pages.
- Document minimal policies against variant mix-ups and persistent stale bundles when introducing external script caching.
- Reduce waiting time on representative JS-heavy pages by improving drain budgets and style recalculation.
- Explain new speed improvements as reductions in shared costs rather than site-specific hacks.
- The scope of performance improvement and comparison method are synchronized between `PLAN.md` and `JS.md`.

### Phase 13: Credential manager collaboration

Status: Not started (Cookie import, password editing, and AI API confirmation requests already exist as foundations)

Purpose:

- Assuming an external secret manager such as `1Password`, create a design that does not directly store credentials in `tweb` but passes them explicitly only when necessary.
- Initially use semi-automatic input through external commands such as the `op` CLI. Do not make `tweb` implement a vault or browser-extension compatibility.
- Organize password editing, login-form assistance, and Cookie/session import under the same permission model.
- Define a UI that lets users inspect the origin and submission destination and confirm which credentials will be sent where.
- Do not submit automatically by default; separate input, submission, and persistence permissions.
- Maintain the assumption that secret manager and OS functions cannot be directly touched from JavaScript

Already implemented:

- CLI cookie/session import, TUI password editing, AI mutate API password input confirmation have been implemented.
- External secret-manager/command execution and transferring results into inputs are not implemented. Distinguish these from existing manual input and Cookie import.

Incomplete:

- No interaction surface yet defines which UI/API transfers external command results into which fields.
- No specification yet connects origin/submission-destination confirmation with masking the actual values.
- Policies preventing secrets in failure logs and history remain incomplete.
- The initial TUI/CLI/API surface has not been chosen.

Next items:

- Choose 1 initial surface and define a minimal flow from external command output such as `op read ...` into password/text inputs.
- When using TUI as the first surface, decide how to display the target field, target origin, and execution command for operations equivalent to `Fill from command`.
- Organize the file format and scope when handling cookie / bearer token / session import with CLI
- Define masking policies that keep credentials out of logs, history, and exception output.
- Synchronize `README.md` and `SECURITY.md` with what is unimplemented and what is explicitly allowed.

Completion criteria:

- Use credentials from external secret managers without weakening the boundaries between input assistance, submission, and storage.
- Keep origin-level confirmation, log masking, and accidental-disclosure prevention consistent with `SECURITY.md`.
- Specific product names such as 1Password are treated as examples, and implementation can be explained using general-purpose external commands/secret source abstractions.

### Phase 14: Integrating Renderer Metadata and Interactive Span

Status: Complete

Purpose:

- TUI link/control hit tests are based on span metadata with provenance generated by the renderer, rather than subsequent character matches against rendered text.
- Reduce duplicate traversal in `render_normal()` and `collect_visible_links()`, aligning rendered text, interactive spans, and block regions in 1 render pass.
- Use DOM/render-derived positions rather than text collisions for single-character links, accessible labels on empty anchors, overlay card links, and CSS-hidden elements.
- Preserve the correspondence between interactive metadata and rendered text in derived views such as focused-pane, full-page, and save-visible-page.

Completed items:

- Added `render_normal_with_metadata()` / `render_normal_subtree_with_metadata()` so rendered text and link/control span metadata can be returned from the same render pass.
- Generate interactive spans for link/iframe/input/textarea/select/button/tab elements in the renderer and pass them directly to the TUI's `RenderedBuffer`.
- Use the same metadata contract for focused-pane/subtree rendering, with regression tests for both full-page and subtree output.
- TUI's `_build_render_buffer()` prioritizes renderer metadata and organizes only non-metadata cases such as label-based controls and overlay links to use existing fallbacks.
- `TUI.md` reflects the origin and warranty scope of interactive span.

Completion criteria:

- TUI link/control hit test is normal route and does not rely on fuzzy matching of rendered text
- Avoid making incorrect character positions clickable for single-character links or overlapping overlays.
- Keep rendered text and interactive metadata consistent across full-page, focused-pane, and subtree rendering.
- Keep renderer metadata production and TUI consumption responsibilities synchronized in `PLAN.md` / `TUI.md`.

### Phase 15: Removal of Interactive Metadata Fallback

Status: Complete

Purpose:

- Remove the plain text re-search fallback that was temporarily left in Phase 14, and restore TUI's interactive span using only renderer metadata.
- Fully represent cases currently relying on fallback, including overlay links, CSS-hidden anchor text, and label-based controls, in renderer metadata.
- Eliminate double definition of visible text and metadata between `collect_visible_links()` / `collect_visible_links_subtree()` and TUI clickable judgment

Completed items:

- Added `source_kind` to `RenderedControlMetadata` so that not only token span but also clickable range derived from `<label>` / `aria-labelledby` can be returned as renderer metadata.
- Replaced empty row-flex/overlay card anchors with a path that adds link metadata at the visible title position during parent-container rendering, without adding visible text.
- `collect_visible_links()` / `collect_visible_links_subtree()` was added to the adapter derived from renderer metadata, and CSS hidden anchor text, overlay link, and iframe were enumerated from the same span information as TUI.
- Removed plain text re-search for link/control span restoration from `_build_render_buffer()` and organized it to consume only renderer metadata.
- Updated full-page/focused-pane/subtree and direct buffer regressions to assume metadata, verifying Phase 15 completion with `tests.test_normal_renderer` / `tests.test_tui`.

Completion criteria:

- `_build_render_buffer()` does not use plain text research for link/control span restoration
- Build correct clickable spans from metadata alone for overlay card links, CSS-hidden anchor text, single-character links, and label-based controls.
- `collect_visible_links()` / subtree version does not conflict with renderer metadata
- It is clearly stated on TUI.md / PLAN.md that fallback is not a temporary implementation and is no longer needed.

### Phase 16: TUI Rendering Path Performance

Status: Complete (initial scope, 2026-10-19)

Purpose:

- Be able to explain the difference in latency between `--mode text` and TUI by dividing it into renderer and post-processing.
- Avoid unnecessary pane detection for single-column/static-rich articles while preserving multi-pane `v` behavior.

Implemented:

- Use `tui timing phase=... elapsed_ms=...` in debug logs to measure renderer, controls/links, page build, interactive order, source buffer, pane detection, focused pane, display buffer, pane region merging, and viewport updates. Page construction measurements are also stored in `BrowserPage.build_timings_ms`.
- Pane detection first applies the normal renderer's lightweight check, skipping layout-hint traversal and full CSS construction on matching pages. Structural traversal excludes hidden/template subtrees, reducing false positives from hints that do not contribute to output.
- Save the source buffer, entire display buffer, pane target, and pane subtree `NormalRenderResult` in `BrowserPage`. Reuse the same text/interactive metadata for text matching and focused rendering
- Only the `v` switch explicitly passes the original page cache. Reuse when the same document/source text/width, and create a new one for rerender / resize / background render after load / DOM update
- Check worker cancellation between page construction stages and do not continue canceled downstream processing.

Verification:

- 271 tests of TUI / normal renderer / CLI passed. Includes regression of existing multi-pane focus/restore, links, cursor restore, nested pane, resize, background render breaks
- Added tests for layout hints inside hidden/template content, skipping CSS/traversal on static-rich pages, true multi-pane layouts from external stylesheets, cache reuse, invalidation on resize/DOM updates, phase timings, and cancellation.
- Replayed fetched Python documentation HTML in a Textual headless TUI, verifying keyboard `v` focus/restore and body restoration. This is separate from responsiveness verification in a real terminal.
- API and TUI measurements using the same fetched HTML are recorded in `docs/performance.md`. Wikipedia live fetching could not be verified because of HTTP 403.

Further optimization opportunities:

- Initial multi-pane detection/subtree rendering still reevaluates CSS. A future option is returning renderer style/block/pane data from a single pass.
- The link-count threshold for lightweight detection is unchanged. Decide whether to extend it to articles with fewer links by comparing actual page fetches and output.
- Check cancellation between stages; do not forcibly interrupt individual CSS matching, rendering, or buffer-construction operations.

### Phase 17: WRS-Style Rendering Efficiency

Status: Partially implemented (body display, unnecessary-request classification, post-load body-stable termination, and debug output; broader real-site verification and classification extensions continue)

Purpose:

- Move `tweb` one step further to "minimum renderer necessary for text understanding" rather than "perfect browser reproduction" to improve both the success rate and execution cost of JS-heavy pages
- Further separate fetching, resource selection, JS execution, render completion, and body extraction so debug output can explain where time is spent and failures occur.
- Reduce common wasted resources, excessive waits, and unnecessary networks that can be absorbed on the QuickJS side before browser-render fallback or site-specific completion

Proposed design:

- Actively suppress resources unnecessary for body comprehension, allowing nonessential image/video/font/analytics/beacon/reporting fetches to be dropped by default.
- Move render completion from waiting for the entire page to become quiet toward stopping when main content containers, visible character counts, and heading/paragraph candidates remain stable for a defined interval.
- Do not allow all fetch/XHR requests indiscriminately. Prioritize likely body content such as document/json/html/api, and classify tracking/telemetry traffic for suppression by default.
- Record subresources / XHR / timers that occur during JS execution by phase, and use debug to track which classifications are determined to be allowed, blocked, and with/without text contribution.
- Record categorized render termination reasons such as `body-stable`, `content-converged`, `network-idle-but-no-progress`, and `blocked-nonessential-network` rather than reporting only timeouts.
- Preserve stateless execution while reusing the phase 12 cache foundation to reduce repeated JS/CSS fetching within a run under a body-content-first policy.

Initial scope:

- Introduce default classifications for blocking unnecessary resources.
- Add body-stability-based render termination conditions.
- Add XHR/fetch classification control and debug surfaces
- Make it possible to inspect what the previous render waited for, dropped, and considered relevant to body content.

Implemented execution-efficiency improvements (2026-11-13):

- Default to `execute_embedded_scripts(render_efficiency=True)`, and suppress beacon, telemetry path, and known image/video/font communication before acquisition using general classification. Allow API/HTML/JSON and unknown communication as body candidates
- During post-load async drain, inspect CSS-visible text, links, and input state in explicit body regions. Finish when they remain stable for at least 500ms of virtual time without further content-candidate requests. Probe every 8 timers, subject to node/character limits.
- Return resource judgment and async drain termination reason to `javascript_debug()["render_efficiency"]` with upper limit. `render_efficiency=False` allows comparison with new optimizations disabled
- The display contract for `--main-only` will be maintained. The main text stability judgment is limited to post-load async drain, and does not forcefully terminate script eval or hydration as a whole.

Implemented body-display options:

- With CLI `--mode text --main-only` and `main_from_path(..., main_only=True)`, only the main text area can be displayed using the normal renderer.
- Prioritize visible `<main>` / `<article>`; infer content candidates if absent. Fall back to the full page if no candidate exists.
- This option selects content to render. The independent `render_efficiency` setting controls body-stable termination of post-load async drain.

Possible future extensions:

- A dedicated read API returns structured body text, heading boundaries, and main-link candidates without replacing the authoritative renderer/TUI output.

Open questions:

- How should MIME types and redirect-destination checks extend the initial URL-path/initiator classification?
- How should inferred content and layout-block metrics extend the initial visible-body/link/input comparison?
- How safely can requests needed for initial content construction be distinguished from tracking API requests?
- If you want to provide structured extraction in addition to CLI text display, should you use the `snapshot()` series or use an independent read API?

Next items:

- Compare enabled/disabled behavior on known JS-heavy real sites, assessing missing content, excessive waiting, early termination, and probe overhead.
- Consider inferred body regions without explicit main/article, MIME/initiator-based classification extensions, and classification of redirect destinations.
- Track separate regressions for future timers adding body content and continuing content-candidate API requests.
- If adding structured extraction on top of `--main-only`, propose a minimal calling interface and return format for `API.md`.

Completion criteria:

- With JS-heavy pages, you can reduce wasted time due to waiting for unnecessary resources to understand the text.
- Explain render termination and subresource/XHR allow/block decisions through debug output.
- Track body-stable completion through both live reproductions and focused regression tests.
- Keep the implemented `--main-only` opt-in and preserve existing normal-view/TUI contracts when adding efficiency improvements. Consider structured extraction APIs as an additional extension.

### Phase 18: MCP Adapter Surface

Status: Not started

Purpose:

- Enable `tweb` to be handled from MCP client as a "structured browser/document tool" instead of GUI automatic operation
- Map existing `snapshot()` / `debug_control()` / `agent_actions()` read/preflight/mutate boundaries directly to MCP tools without weakening them.
- Add TUI and internal renderer implementations as thin adapters to the Python API instead of making them dependent on MCP
- Start with a minimum surface of 1 page/session and align secret handling and confirmation requirements with the existing security model.

Proposed design:

- Use a standard MCP server transport while keeping the `tweb` core's public interface as the Python API.
- Keep the server in an independent module such as `tweb.mcp`. Use only `TWebDocument` and session helpers rather than accessing internal fetch/parse/runtime/render layers directly.
- Identify sessions with `session_id` and store URL/path, Cookie/session, current document, and recent debug information on the server.
- Limit initial tools to approximately `open_page`, `get_snapshot`, `debug_control`, `list_controls`, `invoke_action`, and `close_session`. Do not expose TUI-style keystrokes or screen-coordinate operations.
- `invoke_action` returns `status` / `reason` / `available_actions` / `requires_confirmation` of existing `AgentActionResult` as is, and re-execution of password and policy block confirmation also matches the existing contract.
- Instead of the raw string output of `dom-ai`, use the structured data equivalent to `snapshot().to_dict()` as the original, and keep text render for humans as a secondary debug surface.
- Optional capabilities such as browser-render fallback, external command, and credential manager are not mixed into the tool surface by default, but are separated later as a capability flag or another tool.

Initial scope:

- Open a local path or HTTP(S) URL and create a session around `TWebDocument`.
- Capable of acquiring snapshots, pre-checking controls, and basic action invocations for 1 session.
- Obtain a fresh snapshot after mutation.
- Normalize errors into structured `code` / `message` / `details` results rather than Python exception strings.

Open questions:

- Decide whether sessions favor stateless reopening or a stateful model spanning multiple tool calls.
- Should Cookie/imported session be received every time as a tool argument or as a resource on the server side?
- Decide whether `requires_confirmation` uses 2 tool calls and how it connects to the MCP client confirmation UI.
- Decide how much hydration/javascript/browser-render information to expose through the debug/log surface.
- Which layer should manage cache, timeouts, and resource cleanup for long-running sessions?

Next items:

- Make the minimum MCP tool schema specific by associating it with `AgentPageSnapshot` / `ControlDebugInfo` / `AgentActionResult`
- Decide on the internal state model of the server that uses `create_session()` and `TWebDocument`, and make only the parts that are insufficient in stateless stateful.
- Specify in `API.md` and `SECURITY.md` that MCP surface is a separate transport of the Python API and is not a new authority boundary.
- Decide whether secret confirmation and browser-render fallback are outside the initial scope or opt-in through capability flags.

Completion criteria:

- From MCP client, minimal round trip of page open, snapshot acquisition, control pre-confirmation, and basic action invoke is possible.
- The division of responsibility between Python API and MCP tool surface is consistent with `PLAN.md` / `API.md` / `SECURITY.md`
- The internal implementation of TUI and renderer can be maintained as a thin adapter without directly exposing it to MCP.
- Keep confirmation requests, credentials, and optional capabilities consistent with the existing security model.

### Phase 19: Generalization of line breaks and wrapping based on Unicode/CSS Text

Status: Not started

Purpose:

- Replace the normal renderer's token-based wrapping with break opportunities based on Unicode line breaking and CSS Text.
- Use the same framework for mixed-script text, CJK, space-delimited languages, and writing systems requiring dictionary-based segmentation rather than Japanese-only patches.
- Share line break rules between TUI / normal renderer / subtree renderer and create a platform that eliminates the need to increase ad hoc wrap fixes for each live repro

Proposed design:

- Base wrapping on a sequence of grapheme-cluster display units rather than simple non-whitespace tokens.
- Then enumerate line-break opportunities equivalent to UAX #14, distinguishing mandatory breaks, forbidden breaks, and soft-wrap opportunities.
- When `lang` and writing-system estimation can be obtained, use that information to switch CJK strictness and dictionary-required script segmentation policy.
- For Japanese/CJK, handle punctuation, small kana, iteration marks, and prolonged-sound marks under a policy equivalent to `line-break: normal/strict`.
- For space-delimited languages such as English, prioritize spaces, hyphens, and soft hyphens. Use emergency breaks equivalent to `overflow-wrap` only when normal opportunities are exhausted.
- For scripts that require dictionary or language-dependent segmentation such as Thai / Khmer / Lao, make the dictionary-based segmenter an optional capability, and clearly state the fallback when it is not supported.

Initial scope:

- Replace `_wrap_paragraph()` of `tweb/renderers/normal.py` with break-opportunity base
- Lock in normal-renderer and subtree-renderer regressions with `tests.test_normal_renderer`.
- Initial acceptance requires Japanese punctuation restrictions, avoiding premature breaks in mixed Latin/CJK text, and preserving existing space-delimited-language output.

Open questions:

- Decide whether to implement a UAX #14 equivalent or use Python dependencies for segmentation and line-break classes.
- For text runs that cannot get `lang`, how much tailoring can be done using only script judgment?
- Decide whether dictionary-required scripts should fall back to character-by-character emergency breaks or allow visible overflow as unsupported content.
- To what extent is cursor/span metadata on the TUI side affected by line break rule changes?

Next items:

- Organize the required minimum line break class and tailoring range in `tweb` according to UAX #14 / CSS Text
- Inventory current wrapping regressions by failure class and separate them into `token が大きすぎる`, `禁則を破る`, and `dictionary segmentation 不足`.
- Before implementation, document policies for `white-space` / `word-break` / `line-break` / `overflow-wrap` in `CSS.md` or the text-layout documentation.

Completion criteria:

- Explain basic Japanese, English, and mixed-script wrapping through break opportunities rather than accidental token boundaries.
- Lock Japanese line-breaking restrictions into regressions so live reproductions can be resolved without adding ad hoc word heuristics.
- Future dictionary-based language support should be extensible through segmenters/tailoring without rewriting the entire renderer.

### Cross-cutting: Security

Status: Ongoing

- Manage detailed TODOs in `SECURITY.md`.
- Preserve separate permissions for local files, networking, JavaScript, and form submission.
- Update permission models and safety boundaries alongside new features.

Recent questions:

- JavaScript execution time/memory limits
- Loading policy for external CSS, external JS, images, and iframe-like content
- Visualization of transition destinations and destinations on TUI
- Clarify log and Cookie handling.
- Separation of whether to allow JS-driven button click up to DOM update or up to fetch / XHR / navigation
- Clarify which origins and submissions may use credentials obtained from a secret manager.

## Verification policy

- fixture / unit test:
  Provide minimal fixtures per phase and tests with stable expected output. Check normal-mode, DOM-mode, and TUI differences independently. Use `uv run python3 -m unittest ...` as the repository's basic verification surface.
- live repro:
  For changes suspected of regressing real pages, verify through the actual `uv run tw <url>` or `uv run tw <url> --mode text|dom|dom-ai` path. For specific bug reports, reproduce the exact URL and startup options.
- runtime / JS:
  CSS / JavaScript / hydration will be expanded from a small sample, but for changes related to browser-render and site-specific fallback, it is not enough to just use fixtures, and if necessary, also look at live paths.
- AI API:
  APIs for AI such as `snapshot()` and `debug_control()` validate with the assumption of both structured return values and permission boundaries.
- docs sync:
  Update related documentation together when changing user-visible behavior or permission models.

## Update rules

- Update phase status when implementation is complete.
- For ongoing phases, separate completed work from next items.
- Keep detailed specifications in related documents and only work-planning summaries here.
- When changing policies, check consistency with README.md / TUI.md / DOM.md / CSS.md / SECURITY.md.
