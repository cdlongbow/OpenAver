"""readonly_producer — T-1 skeleton: dataclasses + listing + incremental skip.

Pure backend module. NO API, NO UI, NO frontend. (feature/88b)

Canonical Decisions enforced here:
  CD-88b-1: listing via fast_scan_directory only (CD-88b-1).
  CD-88b-2: get_cover_index() is the additive read-only bulk query added to
             VideoRepository; no shape change to get_mtime_index().
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from core.gallery_scanner import fast_scan_directory
from core.logger import get_logger
from core.organizer import (
    _detect_suffixes,
    _detect_vr_cluster,
    _strip_num_prefixes,
    format_string,
    sanitize_filename,
    truncate_title,
    truncate_to_chars,
)
from core.path_utils import is_path_under_dir, normalize_path, uri_to_fs_path
from core.scraper import normalize_number

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


# ---------------------------------------------------------------------------
# T-2: naming + collision-avoidance helpers (pure functions, no I/O except
#       Path.exists for orphan detection in _movie_dir)
# ---------------------------------------------------------------------------

def _format_data(meta: dict, source_fs_path: str, config: dict) -> dict:
    """Build format_data dict from scraped meta (off-mode flavour).

    Replicates organizer.py:859-877 (off branch):
    - strip number prefixes from title
    - truncate title to max_title_length
    - detect suffix once (off: unfiltered suffix_keywords)

    The same truncated title feeds both _folder_parts and _build_basename
    so the two never drift (CD-88b-3 / Codex P2).
    """
    number = meta['number']
    title = _strip_num_prefixes(meta.get('title', ''), number)
    title = truncate_title(title, config.get('max_title_length', 50))
    fd: dict = {
        'number': number,
        'title': title,
        'actors': meta.get('actors', []),
        'maker': meta.get('maker', ''),
        'date': meta.get('date', ''),
    }
    fd['suffix'] = _detect_suffixes(
        os.path.basename(source_fs_path),
        config.get('suffix_keywords', []),
    )
    return fd


def _folder_parts(format_data: dict, config: dict) -> list:
    """Return folder layer strings (max 3) replicating organizer.py:915-933."""
    layers = config.get('folder_layers') or [
        p.strip()
        for p in config.get('folder_format', '{num}').replace('\\', '/').split('/')
        if p.strip()
    ]
    max_chars = min(config.get('max_filename_length', 60), 120)
    parts = []
    for layer in layers[:3]:
        part = truncate_to_chars(format_string(layer, format_data, use_fallback=True), max_chars)
        if part:
            parts.append(part)
    return parts


def _build_basename(format_data: dict, source_fs_path: str, config: dict) -> str:
    """Build filename stem (no extension) replicating organizer off-mode filename block.

    Replicates organizer.py:936-971 (off branch):
    - suffix taken from format_data['suffix'] (not recomputed)
    - {suffix} two-pass protection when token present in template
    - vr_tail appended last
    - final cap to max_chars
    - NO multipart / part_tail (off is no-op, CD-88b-3)
    """
    original_filename = os.path.basename(source_fs_path)
    original_ext = os.path.splitext(source_fs_path)[1]

    vr_cluster = _detect_vr_cluster(original_filename)
    vr_tail = f'_{vr_cluster}' if vr_cluster else ''

    # off mode: part_tail always ''
    reserve = len(vr_tail)

    max_filename_chars = min(config.get('max_filename_length', 60), 120)
    max_chars = max_filename_chars - len(original_ext)

    filename_template = config.get('filename_format', '{num} {title}')
    suffix = format_data.get('suffix', '')

    if suffix and '{suffix}' in filename_template:
        no_suffix_data = dict(format_data, suffix='')
        base_without_suffix = format_string(filename_template, no_suffix_data)
        base_budget = max(0, max_chars - len(suffix) - reserve)
        if base_budget == 0:
            filename_base = truncate_to_chars(suffix, max(0, max_chars - reserve))
        else:
            base_without_suffix = truncate_to_chars(base_without_suffix, base_budget)
            filename_base = base_without_suffix + suffix
    else:
        filename_base = format_string(filename_template, format_data)
        filename_base = truncate_to_chars(filename_base, max(0, max_chars - reserve))

    filename_base = filename_base + vr_tail
    filename_base = truncate_to_chars(filename_base, max_chars)
    return filename_base


def _build_owners(cover_index: dict) -> dict:
    """Build owners map {movie_dir_str: source_uri} from cover_index.

    cover_index is {source_uri: cover_uri}. The parent of the cover file
    is the movie_dir owned by that source. (plan §4.2)
    """
    owners: dict = {}
    for src, cover in cover_index.items():
        if cover:
            movie_dir = str(Path(uri_to_fs_path(cover)).parent)
            owners[movie_dir] = src
    return owners


def _movie_leaf_base(number: str, source_uri: str) -> str:
    """Return the leaf directory name for a single movie. (plan §4.2 / card §5)

    Four branches:
    1. no stem          → number
    2. stem IS number   → number   (normalised comparison)
    3. stem CONTAINS number (case-insensitive) → stem   (already includes disambiguator)
    4. otherwise        → "{number}-{stem}"
    """
    stem = sanitize_filename(Path(uri_to_fs_path(source_uri)).stem)
    if not stem:
        return number
    if normalize_number(stem) == number:
        return number
    if number and number.upper() in stem.upper():
        return stem
    return f"{number}-{stem}"


def _movie_dir(
    output_root: str,
    format_data: dict,
    source_uri: str,
    config: dict,
    owners: dict,
) -> Path:
    """Return the per-movie directory Path, registering source_uri in owners.

    Collision avoidance (CD-88b-4 / P2b):
    - If candidate is already owned by a DIFFERENT source → append SHA-1 hash suffix.
    - If candidate exists on disk but is not in owners → treat as foreign, hash.
    - Idempotent: same source_uri → same dir (owner == source_uri → no hash).
    - owners is mutated in-place; callers pass a persistent dict across calls.
    """
    parts = _folder_parts(format_data, config)
    leaf = _movie_leaf_base(format_data['number'], source_uri)
    candidate = Path(output_root, *parts, leaf)

    owner = owners.get(str(candidate))
    if owner is None and candidate.exists():
        owner = "<foreign>"        # disk-orphan: not in owners but exists on disk

    if owner not in (None, source_uri):
        h = hashlib.sha1(source_uri.encode()).hexdigest()[:8]
        leaf = f"{leaf}-{h}"
        candidate = Path(output_root, *parts, leaf)

    owners[str(candidate)] = source_uri
    return candidate
