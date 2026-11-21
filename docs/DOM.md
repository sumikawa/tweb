[English](DOM.md) | [日本語](DOM.ja.md)

# DOM.md

## Purpose

DOM output has 2 forms.

- `dom`: Summary display for humans to quickly check page structure
- `dom-ai`: Detailed display for AI to identify the operation target

Without this separation, 1 output format would compromise both readability and interaction precision.

## Basic policy

For DOM output intended for AI interaction, prioritize identifiable nodes and reproducible operations.

`dom-ai` therefore prioritizes the following.

- Output stable node IDs.
- Use a format with machine-traceable parent/child relationships.
- Do not omit attributes.
- Do not summarize text.
- Do not prioritize human-oriented simplification.

Keep `dom` as a summary view for people.

## Role of `dom`

- Quickly understand the tree structure.
- Inspect key attributes and text summaries.
- Keep even large pages readable.
- `script` / `style` can be omitted by default

## Role of `dom-ai`

- Let AI identify click candidates, input targets, link destinations, and label associations.
- Provide output that connects readily to downstream action APIs and TUI interaction.
- Make it easier to track previously inspected nodes after reparsing a page.

## Output requirements for `dom-ai`

- Assign each node a unique node ID.
- Assign each node a parent node ID.
- Output complete tag names and attribute lists for element nodes.
- Output text nodes without truncating their content.
- Explicitly indicate truncation when applying depth limits.
- `script` / `style` may be omitted by default, but indicate that they were omitted.

## Current integration points

- The Python API exposes information aligned with `dom-ai` through `snapshot().dom_nodes`.
- `AgentPageSnapshot.node()` / `find_nodes()` allows read-only search using `node_id`, tag name, attribute, visibility status, and parent ID.
- Links and form controls can also be accessed from the same snapshot using `snapshot.link()` / `find_links()` / `control()` / `find_controls()`.
- Form controls expose `supported_actions`, allowing the next action candidates to be chosen from a read-only snapshot alone.

## API layer division

- read: `snapshot()` reads the current page state without side effects.
- preflight: Use `debug_control()` / `debug_controls()` to inspect submission destinations, click hints, and navigation targets.
- mutate: `agent_actions().invoke()` accepts actual changes and returns structured `status` / `reason` / `available_actions` results even on failure.

These 3 layers share the same `control_id` but have separate permission boundaries. AI agents should narrow candidates using `snapshot()` and `debug_control()` before invoking mutation.

## Future extensions

- Add more CSS-derived visibility information to nodes.
- Be able to handle DOM differences after JS execution
- Associate TUI selection with `dom-ai` node ID
- Associate the node reference on the JS runtime side with the node identifier of `dom-ai`
