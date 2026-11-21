[English](CSS.md) | [日本語](CSS.ja.md)

# CSS.md

## Purpose

CSS support reflects the semantics needed for text reading and AI interaction rather than reproducing a GUI browser's appearance completely.

Use CSS to capture visibility, emphasis, and semantic hints rather than reproducing pixels.

## Basic policy

- Do not aim to reproduce layouts completely.
- Reflect only differences meaningful to text output.
- Prioritize visible state to prevent AI from accidentally manipulating invisible elements
- Make CSS interpretation results reusable in both normal mode and `dom-ai`.
- Share declaration-to-`StyleProperties` conversion between normal and simplified parsing.
- Full and partial normal rendering share the same internals. With `main_only=True`, content selection and rendering share CSS analysis within a render; rebuild it on the next render to reflect DOM/CSS changes.

## What is reproduced

In Phase 6, the following will be prioritized:

### 1. Visibility

- `display: none`
- `visibility: hidden`
- `hidden` attribute

Handle these first. Normal mode omits hidden elements. `dom-ai` may retain the nodes and allow visibility states such as `visible=false` to be attached later.

### 2. Text emphasis

- `font-weight: bold`
- `font-style: italic`
- `text-decoration: underline`
- `text-decoration: line-through`

These map readily to text representations. The renderer API applies them to normal mode as follows.

- Bold: terminal ANSI bold
- Italic: `_text_`
- Underline: explicit markers or attribute information
- Strikethrough: `~~text~~`

Render heading text in bold alongside `#` markers. For list items directly containing headings, use the list marker and bold without adding `#` again. Ordered lists share numbering across normal items, heading items, and nesting, respecting `start`, `reversed`, and `li[value]`. Separate body content using blank lines and indentation based on number width. Limit decoration to preserve readability. CLI `--mode text` produces plain text without control characters for pipes, files, and other tools; the TUI applies decoration in its display layer.

### 3. Block behavior

- `display: block`
- `display: inline`
- `display: inline-block`
- `display: list-item`
- `display: flex`
- `display: inline-flex`
- `flex-direction: column`
- `flex`
- `flex-basis`
- `display: grid`
- `grid-template-columns`
- `width`

Use this to inform line breaks and list interpretation rather than exact layout reproduction.

`display:flex` is treated as a "horizontal container" in normal mode, and its direct child elements are folded into the same context. Maintain normal block stacking only when `flex-direction: column`. `inline-flex` should be treated as inline.

When there are exactly 2 direct block children and width ratios can be derived from their `width` / `flex-basis` / `flex`, normal mode may approximate them as 2 side-by-side columns. This includes main-page layouts such as Wikipedia's `#mp-left` / `#mp-right`.

`display:grid` is not reproduced fully, but simple containers with 2-column `grid-template-columns` may be approximated as side-by-side columns in normal mode.

Keep the 2-column separator `|` at the same position on paragraph blank lines and after content in either column ends, so it remains continuous within the columns.

## What is not reproduced

At least initially, do not reproduce the following.

- Positioning
  - `position`
  - `top`
  - `left`
  - `z-index`
- Pixel dimensions
  - `width`
  - `height`
  - `margin`
  - `padding`
- Complex layouts
  - Grid with 3 or more columns
  - Float
  - Multi-column
- Reproducing colors themselves
  - `color`
  - `background`
  - `border`
- Animation
  - `transition`
  - `animation`

Although important in GUI browsers, these features provide little value when transferred directly to text output.

## Application order

CSS interpretations are applied in the following order:

1. HTML attributes
   - `hidden`
2. External CSS / embedded `<style>`
   - Compare selector specificity.
   - For equal specificity, the later rule wins.
3. `style` attribute

In Phase 6, we will not go as far as to completely reproduce `!important` and inheritance, but will limit it to the minimum cascade for common use between normal mode and `dom-ai`.

## Handling of `@media`

Even in a text-based environment, treat `@media` as a condition determining which CSS rules apply.

### Initial support

- `@media screen`
- `@media all`
- `@media print`
- `@media (max-width: ...px)`
- `@media (min-width: ...px)`

Use the following initial policy.

- `screen` is true by default
- `all` is always true
- `print` is false by default

Thus, normal browsing treats `@media screen` as active.

### Evaluating width conditions

`max-width` / `min-width` is evaluated using the virtual viewport width derived from the terminal width, not the actual browser pixel width.

Use the following criteria.

- Use current terminal columns when running TUI
- In CLI, give priority to `--width` if it exists
- Otherwise, use the default width.

Internally, use `viewport_width_px` with the following initial approximation.

- `1 column = 8px`

Example:

- 80 columns -> `640px`
- 100 columns -> `800px`

Use this virtual width to evaluate conditions such as `@media (max-width: 768px)`.

### Design rationale

- Changing terminal width also changes media-query evaluation.
- Easy to follow TUI resizing
- Reproducibility can be achieved by specifying `--width` in CLI
- Common CSS breakpoints can be used as is to some extent

### Limitations

- These are approximate values, not actual CSS pixels.
- Font differences and full-width character widths are not modeled precisely.
- The goal is deciding which rules apply rather than reproducing layouts completely.

## Application to normal mode

Normal mode prioritizes the following.

- Omit hidden elements.
- Apply only minimal emphasis formatting.
- Reflect a limited subset of CSS `display` in block-element line-breaking rules.
- `display:flex` / `inline-flex` usually only reflects the order of direct child elements, and does not reproduce complete placement or stretching calculations.

Normal mode is formatted text for reading, so avoid exposing large amounts of raw CSS information.

## Application to `dom-ai`

For `dom-ai`, it is important to be able to use CSS results for operational decisions.

Plan to attach information such as the following to each node in the future.

- `visible=true/false`
- `display=block|inline|none`
- `flex_direction=row|column`
- `font_weight=bold`
- `font_style=italic`
- `text_decoration=underline|line-through`

Prioritize whether a node is an interaction target over visual decoration.

## Implementation policy

Phase 6 will proceed in the following order.

1. Create a parser for the `style` attribute
2. Reflect `hidden` / `display:none` / `visibility:hidden` to normal mode
3. Expose the same decisions through `dom-ai`.
4. Add minimal interpretation of embedded `<style>`.
5. Load external CSS and reuse it through a file cache respecting `Cache-Control` / `ETag` / `Last-Modified`.

Preload `rel=preload as=style` as external stylesheets in addition to normal `rel=stylesheet`, applying styles before link load callbacks. Integrate `aria-hidden=true` into the same visible-subtree checks as `hidden` / `display:none` / `visibility:hidden` so cheap probes and the final `StyleContext` agree.

Current minimal selector policy:

- Simple selectors
  - `tag`
  - `.class`
  - `#id`
  - `[attr]`
  - `[attr=value]`
  - `[attr=value][other=value]`
- Combinators
  - `.wrapper .item`
  - `figure figcaption`
- `main > p`
- Pseudo-classes
  - `:root`

Defer the following for now.

- `+`
- `~`
- `:not(...)`
- Pseudo-elements

### Minimal specificity policy

In Phase 6, compare specificity in the following order:

1. inline style
2. `#id`
3. `.class` / `[attr]` / `:root`
4. `tag`

For equal specificity, prefer the later rule. This keeps basic CSS precedence consistent between normal mode and `dom-ai`.

## Completion criteria

The minimum requirements for Phase 6 are as follows.

- `hidden`, `display:none`, `visibility:hidden` works in normal mode
- You can check the visibility status from `dom-ai`
- Some emphasis properties are available as text representations or attribute information.

## Non-goals

- CSS rendering on par with Chrome and Safari
- CSSOM fully compatible
- Responsive layout reproduction
- Pixel-exact positioning
