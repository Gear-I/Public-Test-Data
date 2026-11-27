# Cross-check: dissect.database vs libesedb on all corpus samples

Date: 2026-11-27

* **Reference:** `tools/reference_counts.py` with dissect.database 1.1. It counts
  live rows: leaf nodes without the `fNDDeleted` tag flag.
* **libesedb:** 20240420 (Kali `libesedb-utils` and `python3-libesedb`, run in
  WSL) via `tools/count_libesedb.sh`. That script takes:
  * `number_of_records` per table from the libesedb API (pyesedb);
  * lines − 1 per table file written by `esedbexport -t`.
* **Input:** the 14 `dissect-*` entries of `manifest.json`, decompressed.

## Result

Every table of all 14 databases has the same row count in dissect and in the
libesedb API. esedbexport's output agrees too, except for one table that it
cannot export.

| Entry | Tables | Live rows | esedbexport |
|---|---:|---:|---|
| dissect-basic | 5 | 190 | ok |
| dissect-binary | 5 | 190 | ok |
| dissect-certlog | 9 | 609 | ok |
| dissect-default | 5 | 201 | ok |
| dissect-index | 5 | 259 | ok |
| dissect-large | 5 | 130166 | **exit 1**: table `large` (16 records) exported 0 rows |
| dissect-multi | 5 | 211 | ok |
| dissect-ntds-adam | 14 | 3072 | ok |
| dissect-ntds-fve | 14 | 7549 | ok |
| dissect-ntds-goad | 14 | 8060 | ok |
| dissect-srudb | 12 | 683 | ok |
| dissect-text | 5 | 220 | ok |
| dissect-ual-current | 8 | 992 | ok |
| dissect-windows-edb | 41 | 5179 | ok |

## Findings

1. **Deleted-flagged nodes.** The first version of `reference_counts.py`
   counted every leaf node, including ones flagged `fNDDeleted`. Those are
   records that were deleted but not yet cleaned up. libesedb skips them, so
   four tables differed: `sdproptable` in ntds-fve (2) and ntds-goad (1), and
   `SystemIndex_PropertyStore` in windows-edb (1). The tool now counts only live
   rows and lists the deleted nodes it skipped in `reference.notes`. Regenerating
   also changed two go-ese entries: `go-ese-ntds` `sdproptable` 1→0, and
   `go-ese-windows-edb` `MSysObjects`/`MSysObjectsShadow` 883→873.
   A parser that is compared against these counts must also skip deleted nodes,
   or must report them separately.
2. **esedbexport cannot export `large.edb` table `large`.** libesedb reports 16
   records, but reading record 0 fails with
   `libesedb_data_definition_read_record: invalid tagged data type offset value
   exceeds next tagged data type offset`. dissect reads the same records. This
   looks like a libesedb limitation with large tagged/long-value data on 32 KiB
   pages (a good robustness case for other parsers). Row counts from esedbexport
   line counts are therefore unreliable for this file; use the API count.
3. Caveat: line counting of esedbexport output would also break on values with
   embedded newlines. None occurred here, since the API and export counts
   matched everywhere else.

## go-ese samples (same tools, same day)

All 10 `go-ese-*` entries also have the same count for every table in dissect,
the libesedb API and esedbexport (exit 0 for all).

| Entry | Tables | Live rows |
|---|---:|---:|
| go-ese-ntds | 14 | 7584 |
| go-ese-srudb | 14 | 7807 |
| go-ese-ual-hyperv-pc-current | 8 | 1018 |
| go-ese-ual-hyperv-pc-guid | 8 | 1018 |
| go-ese-ual-hyperv-pc-systemidentity | 7 | 254 |
| go-ese-ual-nondomain-user-current | 8 | 1023 |
| go-ese-ual-nondomain-user-guid | 8 | 1023 |
| go-ese-ual-nondomain-user-systemidentity | 7 | 254 |
| go-ese-webcache | 7 | 309 |
| go-ese-windows-edb | 38 | 4786 |

This includes the two go-ese tables that were corrected when deleted-flagged
nodes stopped being counted (`go-ese-ntds` `sdproptable` = 0, `go-ese-windows-edb`
`MSysObjects`/`MSysObjectsShadow` = 873). libesedb gives the same values, which
confirms the live-rows rule.

## Coverage

All 24 manifest entries agree between dissect.database 1.1 and libesedb
20240420. The only disagreement left is that esedbexport cannot export table
`large` in `dissect-large`.
