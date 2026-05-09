# Documentation Screenshots

Store project screenshots used for docs, plans, and verification here instead of the repository root.

Create subfolders only when a screenshot is referenced by a canonical document
or PR-ready evidence note. Historical debug/demo screenshots were removed once
their docs stopped referencing them.

Rules:
- Do not place screenshots in the repository root.
- Put stable documentation screenshots in the closest matching folder above.
- Use `tmp/` for short-lived captures while debugging or validating UI work.
- If a new feature needs many screenshots, create a new subfolder here rather than adding files at the top level.
- Desktop capture scripts should write temporary output into `tmp/`, then promote files into a stable folder only if they are worth keeping.
