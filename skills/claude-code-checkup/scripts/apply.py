#!/usr/bin/env python3
"""Apply selected checkup actions to Claude Code settings, with a backup first.

Only settings-level changes are automated (skillOverrides, enabledPlugins,
permission rules). Actions marked manual in the snapshot are skipped and
reported. Every touched file is copied to <backup-dir> before writing.

Usage:
  python apply.py --data snapshot.json --ids id1,id2 --backup-dir DIR [--dry-run]
  python apply.py --backup-files FILE [FILE ...] --backup-dir DIR   (before manual edits)
  python apply.py --restore DIR
"""
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def load(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def user_settings(snap):
    return next(s["path"] for s in snap["settings"] if s["scope"] == "user")


def plan_changes(snap, ids):
    """Return {file: [(kind, payload)]} plus the list of skipped (manual/unknown) ids."""
    by_id = {a["id"]: a for a in snap["actions"]}
    changes, skipped = {}, []
    target = user_settings(snap)
    for i in ids:
        a = by_id.get(i)
        if not a or not a.get("apply"):
            skipped.append(i)
            continue
        ap = a["apply"]
        if ap["type"] == "skill_override":
            changes.setdefault(target, []).append(("override", {ap["name"]: ap["state"]}))
        elif ap["type"] == "skill_override_many":
            changes.setdefault(target, []).append(("override", {n: ap["state"] for n in ap["names"]}))
        elif ap["type"] == "plugin_disable":
            changes.setdefault(target, []).append(("plugin", {ap["key"]: False}))
        elif ap["type"] == "permission_remove":
            for r in ap["rules"]:
                changes.setdefault(r["file"], []).append(("perm_remove", r))
        else:
            skipped.append(i)
    return changes, skipped


def apply_to(data, ops):
    log = []
    for kind, payload in ops:
        if kind == "override":
            cur = data.setdefault("skillOverrides", {})
            for k, v in payload.items():
                if cur.get(k, "on") != v:
                    log.append(f"skillOverrides.{k}: {cur.get(k, 'on')} -> {v}")
                cur[k] = v
        elif kind == "plugin":
            cur = data.setdefault("enabledPlugins", {})
            for k, v in payload.items():
                if cur.get(k) is not v:
                    log.append(f"enabledPlugins.{k}: {cur.get(k)} -> {v}")
                cur[k] = v
        elif kind == "perm_remove":
            lst = (data.get("permissions") or {}).get(payload["list"]) or []
            if payload["rule"] in lst:
                lst.remove(payload["rule"])
                log.append(f"permissions.{payload['list']} - {payload['rule'][:120]}")
    return log


def backup_file(path, backup, manifest):
    """Copy one file into the backup folder once and record it in the manifest."""
    path = str(Path(path).resolve())
    if any(f["path"] == path for f in manifest["files"]):
        return
    existed = Path(path).exists()
    copy = f'{len(manifest["files"])}-{Path(path).name}'
    if existed:
        shutil.copy2(path, backup / copy)
    manifest["files"].append({"path": path, "copy": copy, "existed": existed})


def load_manifest(backup):
    m = load(backup / "manifest.json")
    return m if m.get("files") is not None else {"created": datetime.now().isoformat(timespec="seconds"), "files": []}


def restore(backup_dir):
    manifest = load(Path(backup_dir) / "manifest.json")
    for item in manifest.get("files", []):
        if item["existed"]:
            shutil.copy2(Path(backup_dir) / item["copy"], item["path"])
        else:
            Path(item["path"]).unlink(missing_ok=True)
        print(f"restored {item['path']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data")
    ap.add_argument("--ids", help="comma-separated action ids")
    ap.add_argument("--backup-dir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", metavar="DIR")
    ap.add_argument("--backup-files", nargs="+", metavar="FILE", help="only back up these files (before manual edits)")
    a = ap.parse_args()
    if a.restore:
        restore(a.restore)
        return
    if a.backup_files:
        if not a.backup_dir:
            ap.error("--backup-dir is required")
        backup = Path(a.backup_dir)
        backup.mkdir(parents=True, exist_ok=True)
        manifest = load_manifest(backup)
        for f in a.backup_files:
            backup_file(f, backup, manifest)
        save(backup / "manifest.json", manifest)
        print(json.dumps({"backed_up": a.backup_files, "backup_dir": str(backup)}, ensure_ascii=False))
        return
    if not (a.data and a.ids and a.backup_dir):
        ap.error("--data, --ids and --backup-dir are required")
    snap = load(a.data)
    ids = [i.strip() for i in a.ids.split(",") if i.strip()]
    changes, skipped = plan_changes(snap, ids)

    backup = Path(a.backup_dir)
    manifest = load_manifest(backup)
    manifest.setdefault("ids", []).extend(ids)
    report = {"dry_run": a.dry_run, "backup_dir": str(backup), "changes": {}, "skipped_manual": skipped}
    if not a.dry_run:
        backup.mkdir(parents=True, exist_ok=True)
    for path, ops in changes.items():
        data = load(path)
        log = apply_to(data, ops)
        report["changes"][path] = log
        if a.dry_run or not log:
            continue
        backup_file(path, backup, manifest)
        save(path, data)
    if not a.dry_run:
        save(backup / "manifest.json", manifest)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
