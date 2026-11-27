#!/usr/bin/env python3
"""Add or update an entry in the ESE corpus manifest (../manifest.json).

Given an extracted ESE database (optionally gzip-compressed) plus source
metadata, this script:

* computes SHA-256 and size of the database (of the decompressed bytes for .gz)
  and, optionally, of the source image and of sidecar files (.log/.jrs/.chk/.jfm);
* reads the ESE file header (page 0):
    offset   4  signature   ef cd ab 89
    offset   8  format version     (uint32 LE)
    offset  12  file type          (0 = database, 1 = streaming file)
    offset  52  database state     (1 JustCreated, 2 DirtyShutdown, 3 CleanShutdown,
                                    4 BeingConverted, 5 ForceDetach)
    offset 232  format revision    (uint32 LE)
    offset 236  page size          (uint32 LE; 0 in very old files = 4096)
* optionally copies the database (and sidecars) into files/redist/<id>/ or
  files/local/<id>/;
* appends the entry, or updates the one with the same id (fields not given on
  the command line are kept).

Standard library only. Examples:

    python tools/add_to_manifest.py work/SRUDB.dat --id cfreds-leakage-srudb \
        --artifact-type SRUDB.dat --source-name "NIST CFReDS Data Leakage Case" \
        --source-url https://cfreds-archive.nist.gov/data_leakage_case/data-leakage-case.html \
        --licence "US Government work (public domain in the US)" \
        --image-sha256 <sha256> --image-name cfreds_2015_data_leakage_pc.E01 \
        --path-in-image C:/Windows/System32/sru/SRUDB.dat \
        --windows-version "Windows 7 Ultimate SP1" --copy-to local --no-redistributable

    python tools/add_to_manifest.py --verify        # re-hash every entry that is present
    python tools/add_to_manifest.py --header-only some.edb   # just print the header
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

CORPUS_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = CORPUS_ROOT / "manifest.json"

ARTIFACT_TYPES = ["SRUDB.dat", "WebCacheV01.dat", "Windows.edb", "ntds.dit", "other"]
DB_STATES = {1: "JustCreated", 2: "DirtyShutdown", 3: "CleanShutdown",
             4: "BeingConverted", 5: "ForceDetach"}
SIDECAR_SUFFIXES = (".log", ".jrs", ".chk", ".jfm", ".pat")
ESE_SIGNATURE = b"\xef\xcd\xab\x89"
REDIST_SIZE_WARN = 10 * 1024 * 1024  # warn when committing something bigger


# --------------------------------------------------------------------------- io
def _open(path: Path) -> BinaryIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rb")  # type: ignore[return-value]
    return open(path, "rb")


def hash_file(path: Path) -> tuple[str, int]:
    """SHA-256 and size of the (decompressed, for .gz) content."""
    h = hashlib.sha256()
    size = 0
    with _open(path) as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def read_header(path: Path) -> dict[str, Any]:
    with _open(path) as f:
        hdr = f.read(240)
    if len(hdr) < 240:
        raise ValueError(f"{path}: only {len(hdr)} bytes, too short for an ESE header")
    u32 = lambda off: struct.unpack_from("<I", hdr, off)[0]  # noqa: E731
    page_raw = u32(236)
    state = u32(52)
    return {
        "signature_ok": hdr[4:8] == ESE_SIGNATURE,
        "file_type": u32(12),
        "format_version": hex(u32(8)),
        "format_revision": hex(u32(232)),
        "page_size": page_raw or 4096,
        "page_size_raw": page_raw,
        "db_state": state,
        "db_state_name": DB_STATES.get(state, "unknown"),
    }


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(CORPUS_ROOT).as_posix()
    except ValueError:
        raise SystemExit(
            f"error: {path} is outside the corpus root {CORPUS_ROOT}; "
            "use --copy-to redist|local or move it under files/ first")


def find_sidecars(db: Path) -> list[Path]:
    return sorted(p for p in db.parent.iterdir()
                  if p.is_file() and p != db and p.suffix.lower() in SIDECAR_SUFFIXES)


# --------------------------------------------------------------------- manifest
def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"$schema": "./manifest.schema.json", "manifest_version": 1, "databases": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("manifest_version") != 1:
        raise SystemExit(f"error: unsupported manifest_version in {path}")
    return data


def save_manifest(path: Path, data: dict[str, Any]) -> None:
    data["databases"].sort(key=lambda e: e["id"])
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".manifest.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------- actions
def cmd_add(args: argparse.Namespace) -> int:
    src = Path(args.file)
    if not src.is_file():
        raise SystemExit(f"error: {src} not found")

    header = read_header(src)
    if not header["signature_ok"] and not args.force:
        raise SystemExit(f"error: {src} has no ESE signature at offset 4 (use --force to add anyway)")
    if header["file_type"] != 0:
        print(f"warning: file type {header['file_type']} (not a database)", file=sys.stderr)

    manifest_path = Path(args.manifest)
    data = load_manifest(manifest_path)
    existing = next((e for e in data["databases"] if e["id"] == args.id), None)
    if existing is None and (args.artifact_type is None or args.source_name is None
                             or args.licence is None or args.redistributable is None):
        raise SystemExit("error: a new entry needs --artifact-type, --source-name, --licence "
                         "and --redistributable/--no-redistributable")

    redistributable = args.redistributable if args.redistributable is not None \
        else existing["redistributable"]
    sidecar_srcs = find_sidecars(src) if args.with_sidecars else []

    # Place the files inside the corpus.
    db = src
    sidecars = sidecar_srcs
    if args.copy_to:
        if args.copy_to == "redist" and not redistributable:
            raise SystemExit("error: --copy-to redist with a non-redistributable source")
        dest_dir = CORPUS_ROOT / "files" / args.copy_to / args.id
        dest_dir.mkdir(parents=True, exist_ok=True)
        db = dest_dir / src.name
        if db.resolve() != src.resolve():
            shutil.copy2(src, db)
        sidecars = []
        for s in sidecar_srcs:
            d = dest_dir / s.name
            if d.resolve() != s.resolve():
                shutil.copy2(s, d)
            sidecars.append(d)
    db_rel = rel(db)
    if db_rel.startswith("files/redist/") and not redistributable:
        raise SystemExit("error: non-redistributable file under files/redist/ would be committed")

    sha, size = hash_file(db)
    if db_rel.startswith("files/redist/") and db.stat().st_size > REDIST_SIZE_WARN:
        print(f"warning: {db_rel} is {db.stat().st_size} bytes on disk; gzip it or keep it local",
              file=sys.stderr)

    file_entry: dict[str, Any] = {"path": db_rel, "sha256": sha, "size": size}
    if db.suffix.lower() == ".gz":
        file_entry["compressed_as"] = "gzip"
    if sidecars:
        file_entry["sidecars"] = []
        for s in sidecars:
            s_sha, s_size = hash_file(s)
            file_entry["sidecars"].append({"path": rel(s), "sha256": s_sha, "size": s_size})
    elif existing and "sidecars" in existing.get("file", {}) and not args.with_sidecars:
        file_entry["sidecars"] = existing["file"]["sidecars"]

    image_sha = args.image_sha256
    if args.image:
        print(f"hashing image {args.image} ...", file=sys.stderr)
        image_sha, _ = _hash_raw(Path(args.image))
    source_upd = _drop_none({
        "name": args.source_name,
        "url": args.source_url,
        "licence": args.licence,
        "terms_url": args.terms_url,
        "image_name": args.image_name or (Path(args.image).name if args.image else None),
        "image_sha256": image_sha.lower() if image_sha else None,
        "path_in_image": args.path_in_image,
        "retrieved": args.retrieved,
    })

    entry: dict[str, Any] = dict(existing) if existing else {"id": args.id}
    entry["artifact_type"] = args.artifact_type or entry.get("artifact_type")
    if args.artifact_detail is not None:
        entry["artifact_detail"] = args.artifact_detail
    entry["redistributable"] = redistributable
    entry["file"] = file_entry
    entry["source"] = {**entry.get("source", {}), **source_upd}
    if args.windows_version is not None:
        entry["windows_version"] = args.windows_version
    entry["header"] = header
    if args.reference_json:
        with open(args.reference_json, encoding="utf-8") as f:
            tables = json.load(f)
        if not isinstance(tables, dict) or not all(isinstance(v, int) for v in tables.values()):
            raise SystemExit("error: --reference-json must be a JSON object {table: row_count}")
        if not args.reference_tool:
            raise SystemExit("error: --reference-json needs --reference-tool")
        entry["reference"] = {"tool": args.reference_tool,
                              "generated": _dt.date.today().isoformat(),
                              "tables": dict(sorted(tables.items()))}
    if args.tag:
        entry["tags"] = sorted(set(entry.get("tags", [])) | set(args.tag))
    auto_tags = set()
    if header["db_state"] == 2:
        auto_tags.add("dirty")
    if sidecars:
        auto_tags.add("has-logs")
    if auto_tags:
        entry["tags"] = sorted(set(entry.get("tags", [])) | auto_tags)
    if args.notes is not None:
        entry["notes"] = args.notes

    if existing:
        data["databases"][data["databases"].index(existing)] = entry
    else:
        data["databases"].append(entry)
    save_manifest(manifest_path, data)
    print(f"{'updated' if existing else 'added'} {args.id}: {db_rel} sha256={sha} "
          f"page={header['page_size']} state={header['db_state_name']} "
          f"ver={header['format_version']}/{header['format_revision']}")
    return 0


def _hash_raw(path: Path) -> tuple[str, int]:
    """Hash a file's bytes as stored (no gzip decoding) - for source images."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def cmd_verify(args: argparse.Namespace) -> int:
    data = load_manifest(Path(args.manifest))
    bad = 0
    for e in data["databases"]:
        files = [e["file"]] + e["file"].get("sidecars", [])
        for fe in files:
            p = CORPUS_ROOT / fe["path"]
            if not p.exists():
                status = "missing" + ("" if e["redistributable"] else " (local-only, download it)")
            else:
                sha, size = hash_file(p)
                status = "ok" if (sha, size) == (fe["sha256"], fe["size"]) else "MISMATCH"
                bad += status == "MISMATCH"
            print(f"{status:10} {e['id']:30} {fe['path']}")
    return 1 if bad else 0


def cmd_header(args: argparse.Namespace) -> int:
    print(json.dumps(read_header(Path(args.file)), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", nargs="?", help="extracted ESE database (.gz allowed)")
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p.add_argument("--verify", action="store_true", help="re-hash all present entries and exit")
    p.add_argument("--header-only", action="store_true", help="print the header fields and exit")
    p.add_argument("--id", help="stable slug, e.g. cfreds-leakage-srudb")
    p.add_argument("--artifact-type", choices=ARTIFACT_TYPES)
    p.add_argument("--artifact-detail")
    red = p.add_mutually_exclusive_group()
    red.add_argument("--redistributable", dest="redistributable", action="store_true", default=None)
    red.add_argument("--no-redistributable", dest="redistributable", action="store_false")
    p.add_argument("--copy-to", choices=["redist", "local"],
                   help="copy the file (and sidecars) into files/<area>/<id>/")
    p.add_argument("--with-sidecars", action="store_true",
                   help="also record .log/.jrs/.chk/.jfm files next to the database")
    p.add_argument("--source-name")
    p.add_argument("--source-url")
    p.add_argument("--licence")
    p.add_argument("--terms-url")
    p.add_argument("--image", help="source image path (SHA-256 is computed; slow for big images)")
    p.add_argument("--image-sha256", help="published SHA-256 of the source image")
    p.add_argument("--image-name")
    p.add_argument("--path-in-image")
    p.add_argument("--retrieved", help="ISO date (default: today for new entries)")
    p.add_argument("--windows-version")
    p.add_argument("--reference-json", help="JSON {table: row_count} from esedbexport/dissect")
    p.add_argument("--reference-tool", help="e.g. 'esedbexport 20240420'")
    p.add_argument("--tag", action="append", help="repeatable")
    p.add_argument("--notes")
    p.add_argument("--force", action="store_true", help="accept a file without ESE signature")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify:
        return cmd_verify(args)
    if not args.file and args.id and not args.copy_to:
        # Metadata-only update of an existing entry: reuse its recorded file.
        prev = next((e for e in load_manifest(Path(args.manifest))["databases"]
                     if e["id"] == args.id), None)
        if prev:
            args.file = str(CORPUS_ROOT / prev["file"]["path"])
    if not args.file:
        raise SystemExit("error: give a database file (or --verify, or --id of an existing entry)")
    if args.header_only:
        return cmd_header(args)
    if not args.id:
        raise SystemExit("error: --id is required")
    if args.retrieved is None and not any(
            e["id"] == args.id for e in load_manifest(Path(args.manifest))["databases"]):
        args.retrieved = _dt.date.today().isoformat()
    return cmd_add(args)


if __name__ == "__main__":
    sys.exit(main())
