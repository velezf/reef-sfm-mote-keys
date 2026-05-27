"""
USGS data acquisition for the reef-sfm-mote-keys project.

This module talks to the USGS ScienceBase REST API (which is what the IDS
viewer at cmgds.marine.usgs.gov is built on) to enumerate and download a
*subset* of the P1WHKTRD image release — by default, EasternDryRocks only.
The full release is 39,840 TIFs across 11 sites; we want one site (~5 GB).

Two access paths are supported:

  1.  DOI-driven enumeration (default).
      Resolve DOI → root item → child items → filter children by site name
      → enumerate files → download.  Robust to changes in IDS viewer UI but
      sensitive to changes in ScienceBase's parent/child layout.

  2.  Manifest-driven enumeration (fallback).
      Accept a CSV that the IDS viewer's download cart exports, with at
      minimum a `url` column and ideally `name` and `size` columns.  Use
      this when the DOI walk doesn't find the expected structure.

Both paths land in the same on-disk shape:

    <data_root>/raw/P1WHKTRD/<site>/<filename>.tif
    <data_root>/raw/P1WHKTRD/<site>/_provenance.json

The provenance JSON records, for every file: source URL, SHA-256, byte size,
download timestamp, and the ScienceBase item ID it came from.  That file is
the input to the QC validator (`validation.py`) and, later, the processing
manifest (Chat 6).

This module has no Metashape, GDAL, or GPU dependencies.  It uses only
`requests` and the standard library so it can be run from the MacBook for
dry runs and from EC2 for the real pull.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import hashlib
import http.client
import json
import logging
import os
import threading
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: ScienceBase REST root.  Items are addressable by their alphanumeric ID at
#: /catalog/item/<id> and queryable at /catalog/items?filter=...
SCIENCEBASE_API = "https://www.sciencebase.gov/catalog"

#: Default DOIs the project cares about.  We hardcode them so the CLI has
#: sensible defaults; everything is overridable at runtime.
DOI_IMAGES = "10.5066/P1WHKTRD"        # Johnson et al. 2025 — raw image release
DOI_PRODUCTS = "10.5066/P13HMEON"      # Toth et al. 2025a — SfM products release

#: Site name we want from P1WHKTRD.  The data release uses the site label
#: "EasternDryRocks" (no space) in child item titles.  We match
#: case-insensitively against both that and "Eastern Dry Rocks" to be safe.
DEFAULT_SITE = "EasternDryRocks"
SITE_ALIASES = {
    "easterndryrocks": "EasternDryRocks",
    "eastern dry rocks": "EasternDryRocks",
    "eastern_dry_rocks": "EasternDryRocks",
}

#: Bytes to read per chunk when streaming a download.  1 MiB strikes a
#: reasonable balance between syscall overhead and memory footprint, and
#: matches the buffer size NICE DCV / SSH tunnels typically prefer.
CHUNK_BYTES = 1 << 20

#: How often the streaming hasher logs progress, in chunks.
PROGRESS_LOG_EVERY = 64

#: User-Agent identifying this client to USGS.  Polite, attributable, and
#: lets their ops team grep for our traffic if they ever need to.
USER_AGENT = (
    "reef-sfm-mote-keys/0.1 (provenance acquisition layer; "
    "github.com/velezf/reef-sfm-mote-keys)"
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RemoteFile:
    """A single file we plan to (or did) download from ScienceBase.

    `url`, `name`, and `size` are the minimum needed to download and verify
    arrival.  `parent_item_id` lets the QC report attribute each image to
    its ScienceBase parent item (typically one per site), which is the
    granularity at which USGS publishes its metadata.
    """

    url: str
    name: str
    size: int | None  # ScienceBase exposes this; manifest CSVs may not
    parent_item_id: str | None
    content_type: str | None = None


@dataclasses.dataclass
class DownloadResult:
    """The provenance record for one downloaded file.

    Written verbatim (one record per file) into the per-site
    _provenance.json catalog at the end of an acquisition run.
    """

    name: str
    relpath: str
    url: str
    sha256: str
    size_bytes: int
    downloaded_at_utc: str
    parent_item_id: str | None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# ScienceBase client
# ---------------------------------------------------------------------------


class ScienceBaseClient:
    """Thin REST client.  We deliberately do not depend on `sciencebasepy`.

    Two reasons: (1) we only need read-only public endpoints, which are a
    handful of HTTP calls; (2) `sciencebasepy` pulls in auth machinery we
    don't need and would have to audit.  The full surface here is ~50 lines.

    All methods retry on 5xx and on `requests.ConnectionError` with simple
    exponential backoff.  We do not retry on 4xx — those are our bugs and
    should fail loudly.
    """

    def __init__(
        self,
        api_root: str = SCIENCEBASE_API,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        max_retries: int = 4,
    ):
        self.api_root = api_root.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.session.headers.setdefault("Accept", "application/json")

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                backoff = min(30, 2**attempt)
                log.warning("GET %s attempt %d failed: %s; sleeping %ds", url, attempt, exc, backoff)
                time.sleep(backoff)
                continue
            if resp.status_code >= 500:
                last_exc = requests.HTTPError(f"{resp.status_code} from {url}")
                backoff = min(30, 2**attempt)
                log.warning("GET %s returned %d; sleeping %ds", url, resp.status_code, backoff)
                time.sleep(backoff)
                continue
            resp.raise_for_status()
            return resp.json()
        assert last_exc is not None
        raise last_exc

    # -- High-level queries -------------------------------------------------

    def find_item_by_doi(self, doi: str) -> dict[str, Any]:
        """Resolve a DOI like "10.5066/P1WHKTRD" to its ScienceBase item.

        .. deprecated::
            This method is no longer the supported acquisition path.

            Two compounding failures drove this decision (2026-05-27):

            1. **API breakage.** The DOI filter syntax documented at
               usgs.gov/sciencebase-instructions-and-documentation/building-search-queries
               (`filter=itemIdentifier={type:DOI,key:doi:...}`) returns HTTP 400
               for the EasternDryRocks data release — even when the service is up.
            2. **Full outage.** sciencebase.gov was completely down on 2026-05-27
               morning (empty response bodies confirmed from both EC2 and a local
               MacBook; google.com returned 200 from the same hosts).

            The supported path is now the IDS viewer CSV export, reshaped by
            ``scripts/manifest_from_ids_export.py`` and consumed via::

                reef-sfm acquire --manifest path/to/manifest.csv

            See ADR-0008 for the full decision record.
        """
        # ScienceBase's query string uses a JSON-ish filter syntax that is
        # NOT URL-safe-escaped JSON; it's literally `filter=itemIdentifier=
        # {type:DOI,key:doi:10.5066/P1WHKTRD}`.  Build it as a raw string.
        filter_str = f"itemIdentifier={{type:DOI,key:doi:{doi}}}"
        url = f"{self.api_root}/items"
        params = {"filter": filter_str, "format": "json", "max": 5}
        payload = self._get(url, params=params)
        items = payload.get("items") or []
        if not items:
            raise LookupError(f"No ScienceBase item resolved for DOI {doi!r}")
        if len(items) > 1:
            log.warning("DOI %s resolved to %d items; using first", doi, len(items))
        return self.fetch_item(items[0]["id"])

    def fetch_item(self, item_id: str) -> dict[str, Any]:
        """Fetch a single ScienceBase item by its alphanumeric ID."""
        return self._get(f"{self.api_root}/item/{item_id}", params={"format": "json"})

    def fetch_children(self, parent_id: str) -> Iterator[dict[str, Any]]:
        """Yield every child item of a parent, paged.

        Paging is by `offset` + `max`.  Most reef sites have under 50 files
        per child item, and per-site child counts are small, so a max=100
        page size is comfortable.
        """
        offset = 0
        page = 100
        while True:
            payload = self._get(
                f"{self.api_root}/items",
                params={
                    "parentId": parent_id,
                    "format": "json",
                    "max": page,
                    "offset": offset,
                    # Expand `files` and `title` so we don't need a follow-up
                    # call per child.  `fields` is a ScienceBase convention.
                    "fields": "title,files,parentId,identifiers",
                },
            )
            items = payload.get("items") or []
            if not items:
                return
            for it in items:
                yield it
            if len(items) < page:
                return
            offset += len(items)


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------


def _normalize_site(name: str) -> str:
    key = name.strip().lower()
    return SITE_ALIASES.get(key, name)


def _looks_like_site(child_title: str, target: str) -> bool:
    """Match a child item title to the target site name, tolerantly.

    USGS child item titles in this release vary in punctuation between
    `"EasternDryRocks"`, `"Eastern Dry Rocks"`, and `"Eastern_Dry_Rocks"`.
    We collapse whitespace, underscores, and case before comparing.
    """
    def squash(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())
    return squash(target) in squash(child_title)


def enumerate_files_for_site(
    client: ScienceBaseClient,
    site: str = DEFAULT_SITE,
    doi: str = DOI_IMAGES,
    extensions: tuple[str, ...] = (".tif", ".tiff"),
) -> list[RemoteFile]:
    """Walk a USGS data release and return the files for one site.

    The P1WHKTRD release is laid out as one root item with several children
    (one per site, generally).  Each child item lists its files in `files[]`.
    Each file dict has at least `name`, `url`, and `size`.
    """
    root = client.find_item_by_doi(doi)
    log.info("Resolved DOI %s to ScienceBase item %s (%r)", doi, root["id"], root.get("title", "?"))

    files: list[RemoteFile] = []
    matched_children = 0
    for child in client.fetch_children(root["id"]):
        title = child.get("title") or ""
        if not _looks_like_site(title, site):
            continue
        matched_children += 1
        log.info("Matched site child: %s (id=%s)", title, child.get("id"))
        for f in child.get("files") or []:
            name = f.get("name") or ""
            if not name.lower().endswith(extensions):
                continue
            url = f.get("url") or f.get("downloadUri")
            if not url:
                log.warning("File %r has no URL; skipping", name)
                continue
            files.append(
                RemoteFile(
                    url=url,
                    name=name,
                    size=f.get("size"),
                    parent_item_id=child.get("id"),
                    content_type=f.get("contentType"),
                )
            )
    if matched_children == 0:
        raise LookupError(
            f"No child items of {doi} matched site {site!r}; "
            f"check the site name or pass a manifest CSV instead."
        )
    log.info("Enumerated %d %s files across %d child item(s)", len(files), site, matched_children)
    return files


def read_manifest_csv(csv_path: Path) -> list[RemoteFile]:
    """Read a manifest CSV (e.g. an IDS-viewer download-cart export).

    Required column: `url`.  Optional: `name`, `size`, `parent_item_id`.
    Unknown columns are tolerated.  This is the escape hatch for when
    enumerate_files_for_site() can't find what we want via the API.
    """
    files: list[RemoteFile] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "url" not in reader.fieldnames:
            raise ValueError(f"Manifest CSV {csv_path} must have a 'url' column")
        for row in reader:
            url = row["url"].strip()
            if not url:
                continue
            files.append(
                RemoteFile(
                    url=url,
                    name=(row.get("name") or url.rsplit("/", 1)[-1]).strip(),
                    size=int(row["size"]) if row.get("size") else None,
                    parent_item_id=(row.get("parent_item_id") or None),
                )
            )
    log.info("Read %d files from manifest %s", len(files), csv_path)
    return files


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _stream_download(
    session: requests.Session,
    remote: RemoteFile,
    dest: Path,
    timeout: float = 60.0,
    max_attempts: int = 3,
) -> tuple[str, int]:
    """Stream a single file to disk and return (sha256, bytes_written).

    The hash is computed during streaming to avoid a second read pass.
    Three robustness measures over the naive implementation:

    1. Retry on ChunkedEncodingError / IncompleteRead — USGS CDN streams
       occasionally drop mid-file; bounded backoff (2 s / 4 s / 8 s).
    2. Post-download size check before rename — catches truncated downloads
       that finished without a transport error.
    3. Rename race guard — if two workers somehow target the same dest and
       the other worker already won the race, treat as success rather than
       raising FileNotFoundError on the missing .part file.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.parent.mkdir(parents=True, exist_ok=True)

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        h = hashlib.sha256()
        written = 0
        try:
            with session.get(remote.url, stream=True, timeout=timeout) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as out:
                    for i, chunk in enumerate(resp.iter_content(chunk_size=CHUNK_BYTES)):
                        if not chunk:
                            continue
                        out.write(chunk)
                        h.update(chunk)
                        written += len(chunk)
                        if i and i % PROGRESS_LOG_EVERY == 0:
                            log.debug("%s: %.1f MB", remote.name, written / (1 << 20))
        except (requests.exceptions.ChunkedEncodingError, http.client.IncompleteRead) as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = 2 ** attempt  # 2 s, 4 s, 8 s
                log.warning(
                    "%s: stream interrupted (attempt %d/%d): %s; retry in %ds",
                    remote.name, attempt, max_attempts, exc, delay,
                )
                time.sleep(delay)
                continue
            raise

        # Verify byte count before committing the rename.
        if remote.size is not None and written != remote.size:
            last_exc = ValueError(
                f"{remote.name}: wrote {written} bytes but manifest says {remote.size}"
            )
            if attempt < max_attempts:
                delay = 2 ** attempt
                log.warning(
                    "%s size mismatch (attempt %d/%d): %s; retry in %ds",
                    remote.name, attempt, max_attempts, last_exc, delay,
                )
                time.sleep(delay)
                continue
            raise last_exc

        # Atomic rename; tolerate a parallel worker that already won the race.
        try:
            tmp.replace(dest)
        except FileNotFoundError:
            if dest.exists():
                log.debug("%s: rename raced; dest already present — OK", remote.name)
            else:
                raise

        return h.hexdigest(), written

    assert last_exc is not None  # loop always returns or raises before here
    raise last_exc


def download_all(
    files: Iterable[RemoteFile],
    out_dir: Path,
    *,
    skip_existing_with_matching_hash: bool = True,
    expected_hashes: dict[str, str] | None = None,
    session: requests.Session | None = None,
    max_workers: int = 8,
) -> list[DownloadResult]:
    """Download every file in `files` into `out_dir`.

    `out_dir` is the per-site directory, e.g.
    `<data_root>/raw/P1WHKTRD/EasternDryRocks/`.

    If `skip_existing_with_matching_hash` is True (default), a file that
    already exists on disk and either (a) matches a known expected hash or
    (b) has the same byte size as the remote `size` field gets re-hashed
    and skipped.  This is what makes the download resumable across SSH
    sessions or instance restarts.

    `expected_hashes` is a dict of {filename: sha256} from a prior
    _provenance.json; pass it on resume to re-verify in O(read).

    Downloads are issued concurrently using `max_workers` threads (default 8).
    The bottleneck on cmgds.marine.usgs.gov is per-connection latency rather
    than bandwidth, so parallelism gives a near-linear speedup up to ~8 flows.
    Results are always returned in the same order as the input `files` list.
    """
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", USER_AGENT)

    out_dir.mkdir(parents=True, exist_ok=True)
    files_list = list(files)
    total = len(files_list)
    log.info("Downloading %d files into %s (max_workers=%d)", total, out_dir, max_workers)

    counter_lock = threading.Lock()
    completed = 0

    def _one(pos: int, remote: RemoteFile) -> DownloadResult:
        nonlocal completed
        dest = out_dir / remote.name
        skipped = False
        size_mismatch_note: str | None = None
        sha: str
        size: int

        if skip_existing_with_matching_hash and dest.exists():
            existing_size = dest.stat().st_size
            if remote.size is not None and existing_size != remote.size:
                size_mismatch_note = (
                    f"on-disk size {existing_size} != remote {remote.size}; re-downloading"
                )
            else:
                sha = _sha256_of_file(dest)
                expected = (expected_hashes or {}).get(remote.name)
                if expected is None or sha == expected:
                    skipped = True
                    size = existing_size

        with counter_lock:
            completed += 1
            n = completed

        if skipped:
            log.info("[%d/%d] %s: present (sha256=%s, %d bytes); skipping",
                     n, total, remote.name, sha[:12], size)
        else:
            if size_mismatch_note:
                log.info("[%d/%d] %s: %s", n, total, remote.name, size_mismatch_note)
            log.info("[%d/%d] %s → %s", n, total, remote.name, dest.relative_to(out_dir.parent))
            sha, size = _stream_download(sess, remote, dest)

        return DownloadResult(
            name=remote.name,
            relpath=str(dest.relative_to(out_dir.parent)),
            url=remote.url,
            sha256=sha,
            size_bytes=size,
            downloaded_at_utc=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            parent_item_id=remote.parent_item_id,
            notes="resumed" if skipped else "downloaded",
        )

    results: list[DownloadResult] = [None] * total  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_pos = {executor.submit(_one, i, f): i for i, f in enumerate(files_list)}
        for future in as_completed(future_to_pos):
            results[future_to_pos[future]] = future.result()

    return results


def write_provenance(results: list[DownloadResult], out_dir: Path, *, doi: str, site: str) -> Path:
    """Write `_provenance.json` next to the downloaded files.

    Schema is intentionally flat and human-greppable: one envelope dict
    with metadata about the run, plus `files[]` containing one record
    per downloaded file.  Hashes are SHA-256 hex.
    """
    path = out_dir / "_provenance.json"
    envelope = {
        "schema": "reef-sfm-provenance/acquisition/v1",
        "doi": doi,
        "site": site,
        "downloaded_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "hostname": os.uname().nodename,
        "file_count": len(results),
        "total_bytes": sum(r.size_bytes for r in results),
        "files": [r.to_dict() for r in results],
    }
    path.write_text(json.dumps(envelope, indent=2, sort_keys=True))
    log.info("Wrote provenance: %s (%d files, %.2f GiB)",
             path, len(results), envelope["total_bytes"] / (1 << 30))
    return path


def load_provenance(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


__all__ = [
    "ScienceBaseClient",
    "RemoteFile",
    "DownloadResult",
    "enumerate_files_for_site",
    "read_manifest_csv",
    "download_all",
    "write_provenance",
    "load_provenance",
    "DOI_IMAGES",
    "DOI_PRODUCTS",
    "DEFAULT_SITE",
]
