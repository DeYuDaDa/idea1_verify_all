#!/usr/bin/env python3
"""Expose intact cached wheel bodies in a data-disk find-links directory."""
import argparse
import email
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path


def safe_component(value):
    return re.sub(r"[-_.]+", "_", value.strip())


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cache", type=Path)
    parser.add_argument("wheelhouse", type=Path)
    args = parser.parse_args()
    try:
        args.wheelhouse.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(json.dumps({"source_cache": str(args.cache), "wheelhouse": str(args.wheelhouse),
                          "wheel_files_recovered": 0, "cache_entries_skipped": 0,
                          "destination_conflicts": 0, "entry_error_types": [type(exc).__name__],
                          "source_cache_modified": False, "ok": False}, indent=2))
        raise SystemExit(1)
    found = 0
    skipped = 0
    identical = 0
    conflicts = []
    errors = []
    try:
        bodies = list(args.cache.rglob("*.body"))
    except Exception as exc:
        bodies = []
        errors.append(type(exc).__name__)
    for body in bodies:
        try:
            with zipfile.ZipFile(body) as archive:
                names = archive.namelist()
                meta_name = next(x for x in names if x.endswith(".dist-info/METADATA"))
                wheel_name = meta_name[:-len("METADATA")] + "WHEEL"
                metadata = email.message_from_bytes(archive.read(meta_name))
                wheel_text = archive.read(wheel_name).decode("utf-8", "replace")
                pkg = metadata.get("Name")
                version = metadata.get("Version")
                tags = re.findall(r"^Tag:\s*(\S+)\s*$", wheel_text, re.M)
                if not (pkg and re.fullmatch(r"[A-Za-z0-9_.-]+", pkg)
                        and version and re.fullmatch(r"[A-Za-z0-9_.+!]+", version) and tags):
                    skipped += 1
                    continue
                if any(not re.fullmatch(r"[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+", tag) for tag in tags):
                    skipped += 1
                    continue
                stem = f"{safe_component(pkg)}-{version}"
                for tag in tags:
                    name = f"{stem}-{tag}.whl"
                    destination = args.wheelhouse / name
                    if destination.exists() or destination.is_symlink():
                        if destination.is_file() and not destination.is_symlink() and digest(destination) == digest(body):
                            identical += 1
                        else:
                            conflicts.append(name)
                        continue
                    fd, temp_name = tempfile.mkstemp(prefix=".wheel-", dir=args.wheelhouse)
                    os.close(fd)
                    temp = Path(temp_name)
                    try:
                        temp.unlink()
                        try:
                            os.link(body, temp)
                        except OSError:
                            shutil.copyfile(body, temp)
                        os.replace(temp, destination)
                    finally:
                        temp.unlink(missing_ok=True)
                    found += 1
        except Exception as exc:
            skipped += 1
            errors.append(type(exc).__name__)
    summary = {"source_cache": str(args.cache), "wheelhouse": str(args.wheelhouse),
               "wheel_files_recovered": found, "existing_identical_wheels": identical,
               "destination_conflicts": len(conflicts), "cache_entries_skipped": skipped,
               "entry_error_types": sorted(set(errors)), "source_cache_modified": False,
               "ok": not conflicts}
    if conflicts:
        summary["conflicting_wheel_names"] = conflicts[:20]
    print(json.dumps(summary, indent=2))
    if conflicts:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
