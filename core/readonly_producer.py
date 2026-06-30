"""readonly_producer — T-1 skeleton: dataclasses + listing + incremental skip.

Pure backend module. NO API, NO UI, NO frontend. (feature/88b)

Canonical Decisions enforced here:
  CD-88b-1: listing via fast_scan_directory only (CD-88b-1).
  CD-88b-2: get_cover_index() is the additive read-only bulk query added to
             VideoRepository; no shape change to get_mtime_index().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.gallery_scanner import fast_scan_directory
from core.logger import get_logger
from core.path_utils import is_path_under_dir, normalize_path, uri_to_fs_path

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses (§1.1)
# ---------------------------------------------------------------------------

@dataclass
class ProduceOutcome:
    """Single-video result."""
    source_uri: str
    status: str           # "created" | "skipped" | "failed" | "no_scrape"
    movie_dir: str = ""   # generated per-movie directory (FS path); empty on skip/fail
    number: str = ""
    error: str = ""


@dataclass
class ProduceResult:
    """Aggregate result for one source (used by 88c to build SSE summary)."""
    source_path: str
    output_path: str
    created: int = 0
    skipped: int = 0
    failed: int = 0
    no_scrape: int = 0
    aborted_reason: str = ""
    outcomes: list = field(default_factory=list)  # List[ProduceOutcome]


# ---------------------------------------------------------------------------
# Internal helpers (all independently unit-testable)
# ---------------------------------------------------------------------------

def _min_size_bytes(gallery_config: dict) -> int:
    """Convert gallery.min_size_mb → bytes. Mirrors scanner.py:221."""
    return int(gallery_config.get("min_size_mb", 0)) * 1024 * 1024


def _list_source_videos(source_path: str, extensions: set, min_size_bytes: int) -> list[dict]:
    """List video files under source_path. Delegates to fast_scan_directory (CD-88b-1).

    Returns a list of dicts with keys: path, mtime, size, nfo_mtime.
    nfo_mtime is ignored by this module (guard G1: no source-NFO reads).
    """
    fs_dir = normalize_path(source_path)
    return fast_scan_directory(fs_dir, extensions, min_size_bytes)


def _build_cover_index(repo, output_uri: str) -> dict:
    """Return {source_uri: cover_path} filtered to rows where cover falls under output_uri.

    Calls repo.get_cover_index() (bulk, avoids N+1).
    Empty / None cover entries are excluded here; _should_skip has a redundant guard.
    """
    full = repo.get_cover_index()  # {path: cover_path}
    return {
        p: c
        for p, c in full.items()
        if c and is_path_under_dir(c, output_uri)
    }


def _should_skip(source_uri: str, output_uri: str, cover_index: dict) -> bool:
    """B3/P2a three-condition skip predicate.

    Returns True (skip) only when ALL of:
      1. DB has a row for source_uri with a non-empty cover_path
      2. cover_path falls under output_uri
      3. The cover file actually exists on disk
    Any condition missing → return False (rebuild).
    """
    cover = cover_index.get(source_uri)
    if not cover:
        return False                                        # no row / no cover → rebuild
    if not is_path_under_dir(cover, output_uri):           # double-guard (cover_index already filtered)
        return False
    return Path(uri_to_fs_path(cover)).exists()            # physical file must exist
