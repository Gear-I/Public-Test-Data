#!/bin/sh
# Cross-check row counts with libesedb (esedbexport + pyesedb). Run inside WSL/Linux with
# libesedb-utils and python3-libesedb installed, in a folder of decompressed <id>.edb files:
#   sh /path/to/ese/tools/count_libesedb.sh
# Writes <id>.libesedb.json: {"export": {table: lines-1}, "api": {table: number_of_records}, "rc": N}
for f in *.edb; do
  id=${f%.edb}; rm -rf "$id.export"
  esedbexport -t "$id" "$f" >/dev/null 2>"$id.err"; rc=$?
  python3 - "$id" "$f" "$rc" <<'PY'
import json, os, sys, pyesedb
id_, f, rc = sys.argv[1], sys.argv[2], int(sys.argv[3])
exp = {}
d = id_ + ".export"
if os.path.isdir(d):
    for n in os.listdir(d):
        with open(os.path.join(d, n), "rb") as fh:
            exp[n.rsplit(".", 1)[0]] = sum(1 for _ in fh) - 1
api, err = {}, {}
db = pyesedb.file(); db.open(f)
for i in range(db.number_of_tables):
    t = db.get_table(i)
    try: api[t.name] = t.number_of_records
    except Exception as e: err[t.name] = str(e)[:200]
json.dump({"rc": rc, "export": exp, "api": api, "api_errors": err}, open(id_ + ".libesedb.json", "w"), indent=1, sort_keys=True)
print(id_, "rc", rc, "export tables", len(exp), "api tables", len(api), "api errors", len(err))
PY
done
