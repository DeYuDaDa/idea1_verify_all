#!/usr/bin/env python3
"""Prepare/inspect the pinned AI2-THOR CloudRendering build using stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

COMMIT = "f0825767cd50d69f666c7f282e54abfe58f1e917"
BUILD = f"thor-CloudRendering-{COMMIT}"
EXPECTED_SIZE = 835983275


def layout(data_root: Path) -> tuple[Path, Path]:
    target = data_root / "unity_cache" / "releases" / BUILD
    return target, data_root / "thor_build_receipts" / f"{BUILD}.json"


def valid_tree(target: Path) -> tuple[bool, str]:
    exe = target / BUILD
    data = target / f"{BUILD}_Data"
    if not target.is_dir():
        return False, "build directory is absent"
    if exe.is_symlink() or not exe.is_file() or exe.stat().st_size <= 0 or not os.access(exe, os.X_OK):
        return False, f"executable is absent, empty, or not executable: {exe}"
    if data.is_symlink() or not data.is_dir() or not any(data.iterdir()):
        return False, f"non-empty Unity Data directory is absent: {data}"
    return True, "executable and non-empty Data directory are present"


def report_cache(data_root: Path) -> int:
    target, receipt = layout(data_root)
    ok, why = valid_tree(target)
    result = {"cache_valid": ok, "cache_dir": str(target), "reason": why,
              "receipt": str(receipt), "commit": COMMIT}
    if receipt.is_file():
        try:
            result["receipt_record"] = json.loads(receipt.read_text(encoding="utf-8"))
        except Exception as exc:
            result["receipt_warning"] = f"receipt unreadable: {exc}"
    else:
        result["receipt_warning"] = "No local verification receipt; structural check only."
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if ok else 1


def parse_sha(path: Path) -> str:
    text = path.read_text(encoding="ascii").strip()
    match = re.fullmatch(r"\s*([0-9a-fA-F]{64})(?:\s+\*?[^\s]+)?\s*", text)
    if not match:
        raise ValueError(f"Expected an official SHA-256 sidecar (64 hex characters): {path}")
    return match.group(1).lower()


def verify_hash(archive: Path, expected: str) -> str:
    if archive.stat().st_size != EXPECTED_SIZE:
        raise ValueError(f"Archive size mismatch: got {archive.stat().st_size}, expected {EXPECTED_SIZE} bytes")
    digest = hashlib.sha256()
    total = archive.stat().st_size
    done = 0
    last = time.monotonic()
    with archive.open("rb") as stream:
        while True:
            block = stream.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
            done += len(block)
            if time.monotonic() - last >= 5:
                print(f"SHA-256 progress: {done}/{total} bytes ({done * 100 // total}%)", flush=True)
                last = time.monotonic()
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch: got {actual}, expected {expected}")
    print(f"Archive size and SHA-256 verified: {actual}", flush=True)
    return actual


def safe_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = zf.infolist()
    names: set[str] = set()
    total_size = 0
    if not members:
        raise ValueError("ZIP has no entries")
    for info in members:
        raw = info.filename
        if "\\" in raw or "\x00" in raw:
            raise ValueError(f"Unsafe ZIP member path: {raw!r}")
        trimmed = raw[:-1] if raw.endswith("/") else raw
        components = trimmed.split("/")
        path = PurePosixPath(raw)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in components):
            raise ValueError(f"Unsafe ZIP member path: {raw!r}")
        if re.match(r"^[A-Za-z]:", raw):
            raise ValueError(f"Drive-qualified ZIP member path: {raw!r}")
        normalized = path.as_posix().rstrip("/")
        if normalized in names:
            raise ValueError(f"Duplicate ZIP member path: {raw!r}")
        names.add(normalized)
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise ValueError(f"ZIP symlinks are not accepted: {raw!r}")
        if info.flag_bits & 0x1:
            raise ValueError(f"Encrypted ZIP member is not accepted: {raw!r}")
        total_size += info.file_size
        if total_size > 20 * 1024**3:
            raise ValueError("ZIP uncompressed content exceeds the 20 GiB safety limit")
    return members


def extract_checked(archive: Path, staging: Path, build: str) -> None:
    staging.mkdir(parents=True, exist_ok=False)
    last = time.monotonic()
    written = 0
    with zipfile.ZipFile(archive) as zf:
        members = safe_members(zf)
        print(f"ZIP layout checked: {len(members)} entries; extracting with CRC verification.", flush=True)
        for index, info in enumerate(members, 1):
            relative = PurePosixPath(info.filename)
            dest = staging.joinpath(*relative.parts)
            resolved_parent = dest.parent.resolve()
            if staging.resolve() not in (resolved_parent, *resolved_parent.parents):
                raise ValueError(f"ZIP member escapes staging directory: {info.filename!r}")
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            mode = (info.external_attr >> 16) & 0o777
            with zf.open(info, "r") as source, dest.open("xb") as output:
                while True:
                    block = source.read(8 * 1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    written += len(block)
                    if time.monotonic() - last >= 5:
                        print(f"Extract progress: {index}/{len(members)} entries; {written} bytes written", flush=True)
                        last = time.monotonic()
            if mode:
                dest.chmod(mode & 0o755)
        # Exact layout is used by AI2-THOR Build.download for this pinned build.
        if not (staging / build).is_file() or not (staging / f"{build}_Data").is_dir():
            raise ValueError("ZIP does not contain the expected root-level Unity executable and *_Data directory")
    exe = staging / build
    exe.chmod(exe.stat().st_mode | 0o111)
    ok, why = valid_tree(staging)
    if not ok:
        raise ValueError(f"Extracted build failed structural check: {why}")


def install(archive: Path, sha_file: Path, data_root: Path, stage_dir: Path) -> int:
    target, receipt = layout(data_root)
    if target.exists():
        ok, why = valid_tree(target)
        if ok:
            print(f"A structurally valid build already exists; leaving it unchanged: {target}", flush=True)
            return 0
        raise FileExistsError(f"Cache path exists but is incomplete/invalid; preserving it: {target} ({why})")
    expected = parse_sha(sha_file)
    digest = verify_hash(archive, expected)
    unpacked = stage_dir / "unpacked"
    extract_checked(archive, unpacked, BUILD)
    releases = target.parent
    releases.mkdir(parents=True, exist_ok=True)
    # DATA_ROOT contains both staging and cache, so moving the fully checked tree
    # gives an atomic same-filesystem install without duplicating the large build.
    ok, why = valid_tree(unpacked)
    if not ok:
        raise ValueError(f"External staging failed structural check: {why}")
    if target.exists():
        raise FileExistsError(f"Cache path appeared during install; preserving both trees: {target}")
    os.rename(unpacked, target)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    payload = {"commit": COMMIT, "platform": "CloudRendering", "archive_name": archive.name,
               "archive_size_bytes": archive.stat().st_size, "sha256": digest,
               "sha256_sidecar": str(sha_file.resolve()), "installed_cache": str(target),
               "verification": "official-sidecar SHA-256, ZIP CRC during extraction, and Unity layout"}
    temp_receipt = receipt.with_suffix(receipt.suffix + f".tmp-{os.getpid()}")
    temp_receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_receipt, receipt)
    print(f"Build installed atomically: {target}", flush=True)
    print(f"Verification receipt: {receipt}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-cache", action="store_true")
    mode.add_argument("--check-sha", action="store_true")
    mode.add_argument("--install", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--sha256-file", type=Path)
    parser.add_argument("--stage-dir", type=Path)
    args = parser.parse_args()
    try:
        root = args.data_root.expanduser().resolve()
        if args.check_cache:
            return report_cache(root)
        if args.check_sha:
            if not args.sha256_file:
                parser.error("--check-sha requires --sha256-file")
            print(json.dumps({"sha256": parse_sha(args.sha256_file), "sidecar_format_valid": True}), flush=True)
            return 0
        if not args.archive or not args.sha256_file or not args.stage_dir:
            parser.error("--install requires --archive, --sha256-file, and --stage-dir")
        archive = args.archive.expanduser().resolve(strict=True)
        sha_file = args.sha256_file.expanduser().resolve(strict=True)
        stage_dir = args.stage_dir.expanduser().resolve(strict=True)
        return install(archive, sha_file, root, stage_dir)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
