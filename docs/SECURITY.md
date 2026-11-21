[English](SECURITY.md) | [日本語](SECURITY.ja.md)

# SECURITY.md

This document lists security features generally required when implementing `tweb` as a browser. Implemented features are marked explicitly; missing features are tracked as TODOs.

## Assumptions

- `tweb` handles both local files and HTTP/HTTPS
- Gradually extend JavaScript execution, DOM manipulation, form submission, and TUI manipulation
- Expose capabilities with restrictions from the outset rather than adding dangerous features and blocking them afterward.

## Currently implemented items

- [x] Fetching currently supports only `http` / `https` / local files; other schemes are not passed directly to network fetching.
- [x] HTTPS acquisition uses `requests` standard certificate verification and is not disabled independently.
- [x] A 30 second timeout is set for HTTP/HTTPS acquisition.
- [x] The JavaScript execution environment exposes DOM reference/update, minimal web API, and minimal network API via the quick.js bridge.
- [x] `fetch` / XHR from JavaScript has a minimal implementation that passes through the existing acquisition layer
- [x] A general-purpose API that directly calls Python functions or OS functions from JavaScript is not currently available.
- [x] Fetching accepts cancellation events and provides at least a fetch-interruption path.
- [x] Limit runtime supplementation debug output to source summaries/confidence; do not expose entire fetched payloads through the default API.
- [x] The browser-render fallback is organized into the `BrowserRenderRequest` / `BrowserRenderResult` contract, and cookie bridge, provider timeout, and empty DOM judgment are commonly handled in the fetch layer.
- [x] When executing embedded scripts in QuickJS, suppress beacons, explicit telemetry paths, and known image/video/font communication before retrieval. Give priority to body candidates such as API/HTML/JSON, and leave judgments to debug with a limit on the number of cases. This is for execution efficiency and does not replace same-origin/CORS/SSRF privilege boundaries.

## High-priority TODOs

### 1. Origin separation and URL boundaries

- [ ] Define the basic same-origin policy model.
- [ ] Treat `http` / `https` / `file` and future custom schemes as separate origins.
- [ ] Do not mix `file://` equally with regular web origins
- [x] Track the final URL after redirects in `response.url`.
- [ ] Manage boundaries consistently, including origin checks.
- [ ] Handle the base URL consistently when resolving relative URLs.

### 2. Local file access control

- [ ] Decide on a policy to enable `file://` reading only when explicitly permitted.
- [x] API for reading arbitrary local files from JavaScript on a web page is not currently available.
- [ ] Allow control over external network access from local HTML.
- [ ] Prevent path traversal and unintended absolute-path resolution.

### 3. JavaScript Sandbox

- [x] APIs exposed to quick.js are limited to a minimal DOM/Web API subset rather than full browser compatibility.
- [x] JavaScript cannot directly call arbitrary Python functions or OS features.
- [x] Add a default memory limit and fail oversized object creation with `JavaScriptRuntimeError`.
- [ ] Add script execution time limits.
- [x] Add memory usage limits.
- [ ] Prevent infinite loops or oversized object creation from freezing the entire TUI/CLI.
- [ ] Treat it as equivalent to `eval` and clarify the permitted range of dynamic code execution

### 4. Network access control

- [x] There is a minimum implementation of `fetch` / XHR as an additional communication function from JavaScript.
- [ ] Specify under what conditions additional communication functions from JavaScript are permitted.
- [ ] `fetch` / XHR will be redesigned assuming same-origin and CORS
- [ ] Add controls to prevent SSRF in server-side execution environments.
- [ ] Define access control policies to `localhost`, RFC1918, link-local, metadata endpoint, etc.
- [ ] Also check redirects reaching prohibited destinations.
- [ ] Document observed network responses used by the runtime data collector, including collection scope, retention counts, and size limits.

For efficiency in Phase 17, resource judgment history is limited to the most recent 64 cases, and async drain termination reasons are limited to the most recent 32 cases. Do not leave queries, fragments, URL credentials, request bodies, or authentication headers in resource determination. `render_efficiency=False` disables only this optimization and does not extend the button's network permissions. Pause efficiency during explicit button operations and follow existing `dom` / `network` permissions. There is not yet a function to re-inspect normal HTTP redirect destinations using this classification, and it is not treated as an SSRF countermeasure.

### 5. Cookies/Session/Credentials

- [ ] If you implement cookies, separate jars by origin.
- [ ] Reflect the basic rules of `Secure`, `HttpOnly`, `SameSite`
- [ ] Define storage locations and protection if data is persisted.
- [ ] Do not send authorization header or authentication information to another origin by mistake
- [ ] Define browser-render Cookie bridge policies covering same-origin rules, public suffixes, and origins after redirects.
- [ ] Strictly define when authentication headers may be forwarded on redirects.
- [ ] Make explicit which origins/forms/submissions may use credentials received from external secret managers.
- [ ] Separate permissions for password injection, Cookie import, and bearer-token use.
- [ ] Disable automatic submission by default and confirm input assistance separately from submission.
- [x] The mutate API for AI rejects value injection to password input by default, returns `requires_confirmation`, and separates it into re-execution with explicit confirmation.

### 6. TLS/Certificate Validation

- [x] HTTPS uses `requests` standard certificate validation and is not explicitly disabled
- [ ] Define certificate-error presentation and failure behavior.
- [ ] Distinguish hostname verification failures, expired certificates, and self-signed certificates.
- [ ] If exceptions are allowed later, limit them to the session and require explicit confirmation.

### 7. Safe resource loading

- [ ] Define loading policies for external CSS, external JS, images, and iframe-like content.
- [ ] Define separate handling for data URLs, `javascript:` URLs, and `blob:`-like behavior.
- [ ] Disable URLs leading to automatic downloads or execution by default.
- [ ] Decide how to handle mismatches between MIME type and actual content

### 8. Content separation and DOM pollution countermeasures

- [ ] Separate renderer-internal metadata from page-provided data.
- [ ] Safely handle attributes and text during DOM reconstruction
- [ ] Do not confuse display text with executable code fragments.
- [ ] If HTML re-emission or UI embedding is added, inspect possible XSS-like injection paths.

### 9. Form submission security

- [x] Expose submission destination URLs, methods, and encodings.
- [ ] When implementing `file` input, disable sending without explicit selection
- [ ] Suppress or expose automatic submissions and hidden JS navigation.
- [ ] Handle credential fields more carefully than ordinary text inputs.
- [x] Handle HTML submit semantics and JS-driven button click differently so they are not mistakenly treated as submit.
- [x] JS-driven button click results are categorized and visualized as `dom_updated` / `navigation_requested` / `network_requested` / `javascript_required`
- [x] `dom-only` permission is limited to DOM updates by `onclick`, and fetch / XHR / `location` changes are separated into separate permissions.
- [x] In `agent_actions().invoke()` for AI, cases where interaction itself is stopped by policy are structured and returned as `status="blocked"` / `reason="blocked_by_policy"`, and cases where only network is stopped and DOM update is established are treated separately.
- [ ] Do not automate high-privilege flows such as reCAPTCHA or external authentication as ordinary form submissions.

### 10. Download and external application linkage

- [ ] Make the destination explicit if download support is added.
- [ ] Do not automatically execute or open downloaded files.
- [ ] When adding `mailto:`, external application scheme, and OS linkage, include confirmation.
- [ ] External credential-tool integration is unimplemented (Phase 13). When adding calls to tools such as the `op` CLI or 1Password, show the target origin and requested secret before explicit execution.
- [ ] Even if you use browser extensions or secret manager APIs in the future, do not create a route directly from the page JavaScript.

## Additional TODOs

### 11. CORS/CSP/Security Header

- [ ] When implementing CORS, organize basic rules including preflight
- [ ] Leave Content Security Policy at least open to interpretation as a limiting factor
- [ ] Organize the handling of `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, etc.
- [ ] Allows you to control Referrer sending policies

### 12. iframe/embedded content

- [ ] Preserve parent/child origin separation if iframe support is implemented.
- [ ] Sort out the need for constraints equivalent to the `sandbox` attribute
- [ ] Control embedded-document navigation permissions.

### 13. History/cache/state management

- [ ] Define storage conditions for authenticated responses if caching is implemented.
- [ ] Separate persistence scopes for browsing history, form history, Cookies, and local state.
- [ ] Consider whether a private-browsing mode is needed.

### 14. Viewing and logging sensitive information

- [x] Prevent confidential information from queries and fragments contained in URLs from being output to logs without limit
- [x] Mask authorization header, cookies, CSRF token, and personal information from debug output
- [x] Do not display unmasked confidential information in exceptions.
- [ ] Define how much of secret-manager command strings, vault item names, and field names may appear in logs.
- [ ] Do not redisplay injected passwords or imported tokens in history or recent values.

### 15. Clickjacking/Spoofing/UI Safety

- [x] Display the actual transition destination and destination on the TUI in a way that makes it easy to understand
- [ ] Make discrepancies between displayed labels and actual URLs easy to inspect.
- [ ] Require confirmation for dangerous schemes or privilege-elevating operations.

### 16. DoS resistance

- [ ] Set limits on oversized HTML, excessively deep DOMs, and extremely long attribute values.
- [ ] Avoid excessive CPU usage in pathological cases of CSS/JS
- [x] Fetching can be interrupted by a cancellation event.
- [ ] Make the entire pipeline cancellable, including rendering, parsing, and script execution.
- [x] The fetching layer has a 30-second timeout.
- [ ] Add response-size and per-stage limits.

## Implementation principles

- Use default deny.
- Make capabilities requiring explicit permission clear in the CLI/TUI.
- Allow separate permissions for local files, networking, JavaScript, and form submission.
- Allow separate permissions for external command execution, input assistance, submission, and persistence in secret-manager integrations.
- Share the same safety boundaries between human-facing output and AI APIs.
- Test prohibited cases explicitly as well as successful ones.
- `type="button"` and JS handler-based operations are not treated with the same success conditions as HTML form submit.

## Documentation coordination TODOs

- [x] Added security policy summary and link to `SECURITY.md` to README.md
- [x] Added security implementation phase or cross-cutting tasks to PLAN.md
- [ ] Update this document every time you extend JS / fetch / form / file access
