# ADR 0002 — Talk to ScienceBase via raw `requests`, not `sciencebasepy`

Status: Accepted
Date: 2026-05-27
Chat: 4

## Context

The USGS image release P1WHKTRD is hosted in ScienceBase, USGS's Trusted
Digital Repository.  USGS publishes `sciencebasepy`, a Python SDK
(`pip install sciencebasepy`) for programmatic access.  It would be the
"obvious" library choice.

What we actually need: enumerate the children of one public item by DOI,
list each child's files, and stream-download a subset.  No authentication,
no item creation, no permission management, no metadata editing.

`sciencebasepy` covers a much broader surface — auth tokens, item CRUD,
file upload, permission editing — most of which we will never call but
which we would be transitively responsible for if we shipped a fork or
hit a bug.

## Decision

Implement the ScienceBase access we need as a small (~150-line)
`ScienceBaseClient` class in `acquisition.py` using `requests` directly.
Hit only the public read endpoints documented in USGS's
"Building Search Queries" guide:

- `GET /catalog/items?filter=itemIdentifier={type:DOI,key:doi:...}` to
  resolve a DOI to a root item
- `GET /catalog/item/<id>?format=json` to fetch a single item
- `GET /catalog/items?parentId=<id>&fields=title,files,...` to enumerate
  children

The client implements exponential backoff for 5xx and connection errors,
no-retry for 4xx, a User-Agent identifying the project, and pagination.

## Consequences

**Positive.**

- Smaller blast radius: we own ~150 lines, no transitive dependency on a
  library that does much more than we need.
- Auditable in one sitting.  Useful when a Mote or USGS reviewer asks
  "what exactly are you calling on our infrastructure?"
- Easier to drop into other contexts (containers, CI, restoration
  programs reusing the pattern in v2).

**Negative / costs.**

- If ScienceBase changes its query syntax (the `filter=itemIdentifier=
  {type:DOI,key:doi:...}` string is a USGS-specific format, not URL-safe
  escaped JSON), our client breaks before `sciencebasepy` would, because
  the SDK would absorb the change.  Mitigated by the manifest-CSV
  fallback (see ADR-0003).
- We pay the cost of writing our own retry / pagination / User-Agent code
  rather than getting it from a library.  ~30 lines; one-time cost.

#tags: dependencies, sciencebase, http, requests, audit
