#!/usr/bin/env python3
"""Apply Synology wizard selections to a first-install or finalized config."""

import copy
import json
import os
import sys
import tempfile


def _log(message):
    print(f"### [postinst] {message}", file=sys.stderr)


def resolve_share(name, shares_root):
    """Return the symlink target only when DSM's share link points to a directory."""
    link = os.path.join(shares_root, name)
    if not os.path.islink(link) or not os.path.isdir(link):
        _log(f"共用資料夾找不到或無權限：{name}")
        return None  # no symlink: skip, never guess a volume
    return os.readlink(link)


def pick_paths(env, mapping, resolve):
    """Put the library first, followed by selected extras in mapping order."""
    name = env.get("wizard_library_share", "")
    if not name:
        return []
    paths = []
    library = resolve(name)
    if library is not None:
        paths.append(library)
    paths.extend(path for key, path in mapping.items()
                 if str(env.get(key, "")).lower() in ("true", "1", "yes", "on"))
    return paths


def _path(item):
    return item["path"] if isinstance(item, dict) else item


def merge_directories(cfg, paths):
    """Preserve every existing entry and append only new normalized paths."""
    result = copy.deepcopy(cfg)
    gallery = result.setdefault("gallery", {})
    existing = gallery.get("directories", [])
    merged = list(existing)
    seen = {_path(item).rstrip("/") for item in existing}
    for path in paths:
        normalized = path.rstrip("/")
        if normalized not in seen:
            merged.append({"path": path, "readonly": False, "output_path": ""})
            seen.add(normalized)
    gallery["directories"] = merged
    return result


def _write_atomic(path, cfg):
    directory = os.path.dirname(path) or "."
    fd, temporary = tempfile.mkstemp(prefix=".config-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(cfg, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(config_path, paths):
    """Merge and atomically replace an existing JSON object config."""
    with open(config_path, encoding="utf-8") as stream:
        cfg = json.load(stream)
    if not isinstance(cfg, dict):
        raise ValueError("config is not a JSON object")
    _write_atomic(config_path, merge_directories(cfg, paths))


def _read_mapping(mapping_path):
    try:
        with open(mapping_path, encoding="utf-8") as stream:
            mapping = json.load(stream)
        if not isinstance(mapping, dict):
            raise ValueError("mapping is not a JSON object")
        return mapping
    except (OSError, ValueError) as exc:
        _log(f"沒有精靈對照檔（{exc}）")
        return {}


def _seed_legacy(default_cfg, legacy_cfg, paths):
    with open(default_cfg, encoding="utf-8") as stream:
        cfg = json.load(stream)
    if not isinstance(cfg, dict):
        raise ValueError("default config is not a JSON object")
    cfg.setdefault("general", {})["server_mode"] = True
    merged = merge_directories(cfg, paths)
    _write_atomic(legacy_cfg, merged)
    _log(f"seed legacy config: server_mode=True directories={merged['gallery']['directories']}")


def run(env, *, data_dir, legacy_cfg, default_cfg, mapping_path, shares_root):
    """Apply wizard selections without ever failing package installation."""
    try:
        finalized = os.path.isfile(os.path.join(data_dir, ".layout.json"))
        active = bool(env.get("wizard_library_share", ""))
        if env.get("SYNOPKG_OLD_PKGVER", ""):
            active = False
        if finalized and not active:
            return 0
        mapping = _read_mapping(mapping_path) if active else {}
        paths = pick_paths(env, mapping, lambda name: resolve_share(name, shares_root)) if active else []
        if os.path.isfile(os.path.join(data_dir, ".layout.json")):
            config_path = os.path.join(data_dir, "config.json")
            if not os.path.isfile(config_path):
                _log(f"資料設定找不到或無權限：{config_path}")
                return 0
            apply(config_path, paths)
        else:
            _seed_legacy(default_cfg, legacy_cfg, paths)
    except Exception as exc:
        _log(f"套用精靈來源失敗：{exc}")
    return 0


def main():
    if len(sys.argv) != 6:
        _log("套用精靈來源失敗：路徑參數不足")
        return 0
    return run(os.environ, data_dir=sys.argv[1], legacy_cfg=sys.argv[2],
               default_cfg=sys.argv[3], mapping_path=sys.argv[4], shares_root=sys.argv[5])


if __name__ == "__main__":
    sys.exit(main())
