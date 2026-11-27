#!/usr/bin/env python3
"""Fill manifest `reference` row counts using dissect.database (fox-it).

For every manifest entry whose file is present, opens the database with
dissect.database's ESE parser, counts the records of each table in the catalog
and writes {"tool", "generated", "tables", "notes"} into the entry's
`reference`. Tables dissect cannot read are left out of `tables` and named in
`reference.notes`, so a consumer only compares what the reference tool could
read. Databases dissect cannot open at all keep their old `reference`.

Run it with a Python that has dissect.database installed, e.g.

    python -m venv work/venv
    work/venv/Scripts/python -m pip install dissect.database
    work/venv/Scripts/python tools/reference_counts.py            # all entries
    work/venv/Scripts/python tools/reference_counts.py --id go-ese-srudb
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import io
import sys
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_to_manifest import CORPUS_ROOT, DEFAULT_MANIFEST, load_manifest, save_manifest  # noqa: E402

from dissect.database.ese import ESE  # noqa: E402
from dissect.database.ese.c_ese import TAG_FLAG  # noqa: E402


def open_bytes(path: Path) -> io.BytesIO:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as f:
            return io.BytesIO(f.read())
    return io.BytesIO(path.read_bytes())


def count_tables(path: Path) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """Live rows per table, deleted-flagged leaf nodes per table, unreadable tables.

    Leaf nodes with the fNDDeleted tag flag are records deleted but not yet
    cleaned up. libesedb/esedbexport skip them, so they are not counted as rows.
    """
    db = ESE(open_bytes(path))
    counts: dict[str, int] = {}
    deleted: dict[str, int] = {}
    errors: list[str] = []
    for table in db.tables():
        try:
            live = dead = 0
            for node in table.root.iter_leaf_nodes():
                if node.tag.flags & TAG_FLAG.Deleted:
                    dead += 1
                else:
                    live += 1
            counts[table.name] = live
            if dead:
                deleted[table.name] = dead
        except Exception as e:  # noqa: BLE001 - record and continue
            errors.append(f"{table.name}: {type(e).__name__}: {e}"[:200])
    return dict(sorted(counts.items())), deleted, errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p.add_argument("--id", action="append", help="only these entries (repeatable)")
    args = p.parse_args(argv)

    tool = f"dissect.database {version('dissect.database')}"
    today = _dt.date.today().isoformat()
    manifest_path = Path(args.manifest)
    data = load_manifest(manifest_path)
    failed = 0
    for entry in data["databases"]:
        if args.id and entry["id"] not in args.id:
            continue
        path = CORPUS_ROOT / entry["file"]["path"]
        if not path.exists():
            print(f"skip     {entry['id']}: file not present")
            continue
        try:
            counts, deleted, errors = count_tables(path)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAILED   {entry['id']}: {type(e).__name__}: {e}")
            continue
        ref = {"tool": tool, "generated": today, "tables": counts}
        notes = ("Row counts = leaf nodes of each table's data tree without the fNDDeleted flag "
                 "(live records as stored, no log replay).")
        if deleted:
            notes += " Deleted-flagged nodes not counted: " + ", ".join(
                f"{k}={v}" for k, v in sorted(deleted.items())) + "."
        if errors:
            notes += " Tables dissect could not read (omitted): " + "; ".join(errors)
        ref["notes"] = notes
        entry["reference"] = ref
        print(f"{'partial' if errors else 'ok':8} {entry['id']}: {len(counts)} tables, "
              f"{sum(counts.values())} rows" + (f", {len(errors)} unreadable" if errors else ""))
    save_manifest(manifest_path, data)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
