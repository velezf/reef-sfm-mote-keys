# 0001 — Use Amazon DCV 2025.0, not legacy NICE DCV

- **Status:** Accepted
- **Date:** 2026-05-25
- **Chat:** 3 (EC2 bootstrap)

## Context

The project needs a remote-display protocol to drive the Metashape GUI
(error reduction, marker placement, manual quality review in Chat 5) and
QGIS (annotation in Chat 7) on a headless EC2 instance. Older AWS and
community documentation refers to "NICE DCV"; the product was renamed
to "Amazon DCV" with the 2024.0 release in October 2024. Most blog
posts on the open web still use the old name, and the binary URLs on
`d1uj6qtbmh3dt5.cloudfront.net` still embed `nice-dcv` in the filename
even though the product is officially Amazon DCV.

## Decision

Install Amazon DCV server 2025.0 (latest as of project start) directly
from the official CloudFront distribution. Treat any blog/SO post
mentioning "NICE DCV" as referring to the same product, but verify
version numbers and URLs against `docs.aws.amazon.com/dcv/` rather
than copy-pasting from the post.

## Consequences

- Server-side package names still contain `nice-dcv-*` (e.g.
  `nice-dcv-server`, `nice-xdcv`) even after the rename. Bootstrap
  scripts use those names verbatim — do not "fix" them.
- Client-side, the macOS app is the "Amazon DCV Client" and is
  downloaded from `download.nice-dcv.com`. Same product, mixed
  branding.
- Future bootstrap re-runs that bump `DCV_VERSION` in
  `03_install_dcv.sh` should check the release notes at
  `docs.aws.amazon.com/dcv/latest/adminguide/doc-history.html` first;
  past major releases have changed default ports and protocol
  defaults (e.g. QUIC UDP became default in 2024.0).

## Notebook narrative

> Remote-display work uses Amazon DCV 2025.0 (the AWS-managed remote
> display protocol formerly branded NICE DCV; the 2024.0 release
> renamed the product without changing the protocol). DCV was chosen
> over X11 forwarding because the Metashape GUI work in this project
> involves dense point cloud rendering and OpenGL views that perform
> poorly over X11 even on a low-latency connection. DCV supports
> GPU-accelerated remote OpenGL via the `nice-dcv-gl` package, which
> matters specifically for Metashape's mesh and dense-cloud views.
