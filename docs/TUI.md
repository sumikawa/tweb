[English](TUI.md) | [日本語](TUI.ja.md)

# TUI.md

## Purpose

This document defines TUI behavior and display policies.

## Page construction performance and measurement

- With `--debug`, `tui timing phase=... elapsed_ms=...` separates renderer, controls/links, page build, source/display buffers, pane detection, pane region merging, focused-pane rendering, and viewport updates. `page_build` totals downstream processing; renderer and viewport are measured separately. Child phases are already included in the total and must not be added again.
- Construction measurements are also stored in `BrowserPage.build_timings_ms`. Pane-detection skip reasons appear in `pane detection skipped reason=lightweight-render|no-layout-candidate`.
- Static-rich pages skip pane detection using the normal renderer's lightweight check. Structural traversal ignores layout hints inside hidden/template subtrees.
- The target of `v` is kept within the boundaries of the detected pane, and even when expanding the target from the first heading, it does not include the adjacent pane. The text matching ignores spaces and line breaks caused by the layout, and identifies the same pane even if the Japanese wrapping position changes.
- `v` reuses the original page's pane target, source/full-page buffer, and text/interactive metadata of the pane subtree. When returning to full display, use the original buffer and maintain the correspondence between links, controls, and blocks.
- Limit cache reuse to pane switches on the same page at the same width and image-display setting. Rebuild on load, rerender after DOM updates, resize, and background rendering.
- Check worker cancellation between page construction stages. Forced interruption within a single running render/CSS operation is outside scope.

## Current implementation

- TUI base is `Textual`
- Start with `tw <target>`
- Even if you specify `tw <target> --mode tui`, the same behavior will occur.
- If `--width` is omitted, the current terminal width is used, and if it cannot be obtained, `80` is used.
- Display only body content.
- `x` allows you to switch between normal display and DOM summary display on the fly
- On multi-pane blocks, `v` hides other panes and rerenders the current pane at a wider width; `v` restores the original view.
- After `v` enters focused-pane view, treat the entire view as 1 block even when the pane contains paragraph blank lines or nested 2-column layouts.
- When panes are detected, prioritize pane boundaries for Shift-Arrow blocks and group subsequent content in the same pane into 1 block.
- Do not split continuous single-column content into extra blocks at paragraph blank lines. For Shift-Arrow, primarily treat grid/pane boundaries as block boundaries.
- Even outside a direct multi-pane row, `v` can focus the content subtree containing the current line when sibling chrome such as top menus can be removed.
- The 1-character cursor can occupy both visible body characters and remaining display whitespace to the right of a line.
- Indicate the cursor by changing the background of exactly 1 character.
- Underline links in the normal view so they are recognizable as clickable.
- Highlight form control tokens and labels in the normal view so users can recognize elements operated with `Enter`.
- Use link/control spans directly from renderer metadata, preserving identical clickable ranges across full-page/focused-pane/subtree output.
- When the cursor is on a link or checkbox/label toggle, give that 1 character a blue background.
- Show the current position as `line X col Y` in the status line.
- When the cursor is on a link, also show its destination in the status line.
- When the cursor is on a submit control, also show `GET` / `POST`, the destination URL, and `enctype` in the status line.
- When the cursor is on `type="button"`, also show the current `button click policy` in the status line.
- During navigation or form-submission fetching, show the current phase, such as `Connecting ...` `Downloading ...` `Parsing ...` `Rendering ...`, in the status line with elapsed seconds equivalent to `(N s)` and a trailing `Esc to cancel`. For links, display the resolved destination rather than raw `href`.
- `checkbox + label`-based menus and dropdowns can be opened and closed with `Enter`
- Minimal form support provides popup editing for text inputs/textareas, masked single-line password editing, select cycling, radio/checkbox selection, and GET/POST submission from submit buttons.
- `type="button"` does not submit a form. The TUI executes its click and classifies `onclick` / `addEventListener("click", ...)` results as `dom_updated` / `navigation_requested` / `network_requested` / `javascript_required`.
- `--button-click-policy off|dom-only|network` controls JS-button permissions. The TUI defaults to `network`, allowing requests and navigation during interactive browsing. `dom-only` allows DOM updates while blocking fetch/XHR/`location` changes and reporting the outcome.
- `--debug-block-colors` assigns a background color to each detected render block, including trailing display whitespace at pane boundaries.
- This policy is needed because submission destinations and methods can be computed in advance, while JS-driven buttons may only update the DOM or may trigger fetch/XHR/`location` changes. The same `Enter` key can therefore have different side effects.
- During editing, open a popup and change the body title to `Editing: ...`.
- Use consistent editing behavior for text inputs/textareas, with only password inputs restricted to masked single-line input.
- `/` opens a popup for in-page search, and you can jump to the next match with Enter.
- With a search term set, `n` / `p` moves to the next/previous match.
- `o` opens a popup where you can enter a URL or local path, allowing you to jump to another page on the spot.
- `h` opens display history, letting users select a previously displayed URL/path and return to its history position. Prefer the page title, when available, to the left of the history list's vertical separator.
- Save display history in `~/.config/tw/history.json` with 1 entry per 1 line and restore it on the next launch. Revisiting a URL/path removes its old entry and retains only the newest position. Exclude the welcome page bundled with `tw`.
- `c` can send the currently displayed rendering result to the macOS copy buffer
- `s` saves the current rendered output as `.txt`.
- The content handled by `c` / `s` uses the current display state itself, and if `x` switches to DOM summary, it targets DOM summary, and if `v` hides other panes, it targets only that pane.
- Open shortcut help with `?` and close with `Esc` or `?`
- Fetch link destinations in a background worker so the UI remains responsive during loading.
- Rerender terminal-width changes in a background worker, retaining the previous screen until new output is ready. Show `Rendering ... (Ns) Esc to cancel` while rerendering.

## Key bindings

- `Right` / `Ctrl-F`: Move 1 character right
- `Left` / `Ctrl-B`: Move 1 character left
- `Down` / `Ctrl-N`: Move down 1 line
- `Up` / `Ctrl-P`: Move up 1 line
- `Shift-Right` / `Shift-Down`: Move to the beginning of the next block
- `Shift-Left` / `Shift-Up`: Move to the beginning of the previous block
- `Home` / `Ctrl-A`: Move to beginning of line
- `End` / `Ctrl-E`: Move to end of line
- `PageDown` / `Ctrl-V`: Move down 1 page and place the cursor at the new screen's top left
- `PageUp` / `Alt-V`: Move up 1 page and place the cursor at the new screen's top left
  - Some terminals send `Alt-V` as `Esc` followed by `v`; accept that input too.
  - Also accept terminals such as iTerm2 sending `Option-v` as the character `√`.
- `Tab`: Jump to the start of the next link or control
- `Shift-Tab`: Jump to the start of the previous link or control
- `/`: Open in-page search; Enter finds the next match after the cursor, wrapping to the beginning when necessary.
- `n`: Find the next match for the current search term, wrapping to the beginning when necessary.
- `p`: Find the previous match for the current search term, wrapping to the end when necessary.
- `o`: Open input popup for URL or local path and press Enter to open. A host name without URL scheme is treated as `http://`.
- `h`: Open display history popup. Select with `Up` / `Down` and move to that history position with `Enter`. The history here is different from the back/forward stack of `b` / `f`, and records of pages that have been successfully displayed so far are arranged newest first. `*` indicates the current position, each line prioritizes `title | URL/path`, and if there is no title, the last path element is placed on the left as before. If the history exceeds the screen height, scroll the list by following the selected line. Restore the contents from `~/.config/tw/history.json` and save updates to the same file.
- `c`: Send the currently displayed rendering result to `pbcopy` on macOS and put it in the copy buffer
- `s`: Open the save path input popup and press Enter to save the currently displayed rendering result as UTF-8 text.
- After `Esc` `<`: Go to top of page
- `>` after `Esc`: Move to the bottom of the page
- `Enter`: Transition if on a link, open/close if on a checkbox/label based toggle. text input / textarea opens an edit popup, select switches to the next option, radio / checkbox selects, submit button performs GET/POST submit, `type="button"` executes JS click until DOM update
- `x`: Toggle between normal and DOM summary display
- `v`: For blocks drawn as multiple panes, remove the other panes, redraw the current pane with a wider display width, and press it again to restore it. While the focused pane is displayed, the entire display of the Shift-Arrow block movement target is treated as 1 block.
- `r`: Toggle the effective renderer and reload: QuickJS switches to forced Chrome; Chrome fallback switches to forced QuickJS. Even with `--browser-render auto`, 1 press switches based on the renderer actually displayed.
- Editing popup `Enter`: save single-line inputs; insert a newline in `textarea`
- Editing popup `Ctrl-S`: save
- Editing popup `Esc` / `Ctrl-G`: cancel
- Editing popup `Ctrl-C`: quit the app
- `Esc`: Cancel link fetching, rerendering after terminal resize, or additional rendering during `rendering more...`.
- During `rendering more...`, movement, link navigation, view switching, search, and other key input stop additional rendering immediately and operate on the visible partial page. Prioritize input so a later full render cannot interrupt or change the cursor and output.
- `b`: Go back 1 entry in navigation history, which is separate from the `h` list.
- `f`: Go forward 1 entry in navigation history, which is separate from the `h` list.
- `?`: Show shortcut help
- `Ctrl-C`: Quit

## Policy

- TUI body rendering always stays consistent with `text mode --link-style none` given the same width
- Treat renderer metadata as authoritative for interactive span start/end positions; do not fall back to searching plain text again in the TUI.
- Represent overlay links, CSS-hidden anchor text, and control hit areas derived from `<label>` / `aria-labelledby` in renderer metadata, sharing the same spans between `collect_visible_links()` and click detection.
- Use body content and the status line to indicate position, without a separate link-list pane.
- In-page search targets the current rendered output and works consistently in normal and DOM summary views.
- Prefer Emacs-style key bindings close to standard macOS text editing.
- TUI details are summarized in this file instead of README

## Suppressing image display

`tw URL --no-images` omits `[alt text]` / `[image]` placeholders in normal output. Preserve this setting across rerenders, page navigation, and focused-pane views. Also omit `<figcaption>` captions. Keep links containing text and omit image-only links. Image elements remain available for DOM inspection.
