[English](AGENTS.md) | [日本語](AGENTS.ja.md)

# AGENTS.md

## Editing Rules

- Keep this document and related documents up to date.
- Keep English `.md` and Japanese `.ja.md` counterparts synchronized, including the language links at the top. References to documentation should stay in the current language where a counterpart exists.
- Do not revert the user's uncommitted changes without permission.
- In a sandbox, `uv run` is prone to permission errors involving `~/.cache/uv`. When Codex needs to run similar commands, use an appropriately authorized execution mode from the outset rather than repeating the same failure.
- When `uv run` must run without elevated permissions in a sandbox or remote environment, set `UV_CACHE_DIR` and `PYTHONPYCACHEPREFIX` to directories under `/private/tmp/...` to avoid known cache permission errors.
- When fixing crashes or segfaults, also add debug logs that record the reproducing input, the last processing stage, and exception details to support the next investigation.
- When an audit or performance rerun changes cohort status, update both the relevant rows in `performance.md` and `active_site_ids` plus the cohort description in `tweb/data/quickjs_audit_sites.json` in the same change. Keep the active table and manifest synchronized.

## Repository Notes

- Use Python 3 for the main implementation.
- Use quick.js for JavaScript processing.
- Use Textual for the TUI.
- Indent with 2 spaces; do not use tabs.
- Base keyboard controls on Emacs conventions close to standard macOS text editing.
- Prefer existing libraries for HTTP/HTTPS access, using `requests` as the standard implementation.
- Keep the fetching layer generic; do not add fetches that supplement HTML or APIs for individual sites.
- Minimize site-specific code. First consider whether generic runtime, DOM, hydration, or interaction support can address the issue.
- If site-specific code is unavoidable, aim to make the content readable on the QuickJS side. Do not treat it as a permanent substitute for Chrome fallback.

## Related Documents

- README.md: Application purpose and usage
- docs/DEVELOPMENT.md: Development workflow, tests, and key commands
- docs/API.md: Python library API
- docs/PLAN.md: Phased implementation plan for the goals in README.md
- docs/performance.md: Quality audits, performance measurements, canonical audit sites, and execution records
- docs/DOM.md: Separate DOM output policies for human summaries and AI inspection
- docs/CSS.md: How CSS semantics are reflected in text output
- docs/JS.md: JavaScript implementation status and policy
- docs/TUI.md: Textual TUI behavior
- docs/SECURITY.md: Outstanding security features expected of a general browser
