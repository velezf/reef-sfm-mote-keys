# Architecture decision records

Short, dated records of non-obvious technical decisions. One file per
decision. New decisions get the next number; old decisions don't get
deleted or edited in place — if a decision is reversed, the new ADR
references the superseded one and the old file gains a `Status:
Superseded by NNNN` header.

Format follows Michael Nygard's original ADR template: Context,
Decision, Consequences. We add a `Notebook narrative` block at the
bottom that holds the reviewer-facing prose version of the decision —
the same fact restated for a Mote/USGS reader rather than for future
me at 11pm trying to debug a broken bootstrap. That block is what gets
adapted into the Chat 5/6/8 notebooks and the eventual Quarto page.

## Index

| # | Decision | Status |
|---|---|---|
| 0001 | Amazon DCV 2025.0, not legacy NICE DCV | Accepted |
| 0002 | Metashape Pro pinned to 2.3.1 | Accepted |
| 0003 | Trial activation isolated to its own script | Accepted |
| 0004 | QGIS from official LTR repo, not Ubuntu archive | Accepted |
| 0005 | Bundled Metashape Python for headless, not venv import | Accepted |

## When to write a new ADR

Write one whenever a future session would benefit from knowing *why* a
choice was made, not just *what* the choice was. Rough threshold: if
the next chat could plausibly question or reverse the decision without
context, it earns an ADR. Mechanical choices (`apt install jq`) do
not. Choices with consequences across chats (`pin Metashape to 2.3.1`)
do.

## When to update the notebook narrative

Every time an ADR is accepted, add a one-paragraph version to the
`## Methods` or `## Decisions` section of whatever notebook is current
(Chat 4 onward). At Stage 2 — Quarto migration in Chat 8 — these
paragraphs get pulled together into a "Design decisions" subsection of
the writeup. Keeping the notebook narrative current as you go avoids
having to reconstruct the reasoning a month later.
