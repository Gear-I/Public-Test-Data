# ESE (JET Blue) test corpus

A corpus of **synthetic and publicly published** Extensible Storage Engine
databases (`SRUDB.dat`, `WebCacheV01.dat`, `Windows.edb`, `ntds.dit`, UAL
`*.mdb`, …) for checking ESE parsers against many Windows versions, page sizes,
format revisions and shutdown states.

It was set up to check the robustness of the pure-Python ESE parser for the
Crush forensics workbench, which itself only ships small synthetic fixtures. It
is kept **outside** that repository on purpose: the files here are large, come
from third parties under various terms, and some may not be redistributed.

> **Never add real system databases from your own or anyone else's machine.**
> `SRUDB.dat`, `WebCacheV01.dat` and `Windows.edb` record a user's activity
> (apps, network use, browsing, indexed file content). Only synthetic files
> (made in a throwaway VM, see below) and files from published DFIR datasets
> belong here.

## Layout

```
ese/
├── README.md                 this file
├── manifest.json             one entry per database (committed, always)
├── manifest.schema.json      JSON Schema for manifest.json
├── .gitignore
├── tools/
│   └── add_to_manifest.py    hash + read header + add/update a manifest entry
├── files/
│   ├── redist/<id>/          small, redistributable databases (committed, gzip them)
│   └── local/<id>/           non-redistributable or large (git-ignored)
├── images/                   downloaded source images / archives (git-ignored)
└── work/                     scratch: mounted images, esentutl copies (git-ignored)
```

`manifest.json` is always committed, including entries whose file is
local-only. Someone with the same source image can rebuild the local file and
check it against the recorded SHA-256 (`python tools/add_to_manifest.py --verify`).

## Using the corpus from a test

A consumer (e.g. an opt-in Crush test) points an environment variable such as
`CRUSH_ESE_CORPUS` at this `ese/` folder and then:

1. reads `manifest.json`;
2. for each entry, resolves `file.path` relative to the folder (gunzip when
   `file.compressed_as == "gzip"`), **skips** entries whose file is missing
   (local-only files not downloaded on this machine) and checks `file.sha256`;
3. compares its own output with `reference.tables` (table name → row count),
   which was produced separately by an independent tool such as `esedbexport`
   (libesedb) or `dissect.database`, named in `reference.tool`;
4. can select subsets with `artifact_type`, `header.page_size`,
   `header.db_state_name` or `tags` (`dirty`, `has-logs`, `synthetic`, …).

Dirty databases (`db_state` 2) should be read as-is (that is what an examiner
gets); the matching `.log` files are listed in `file.sidecars`, so a test can
also replay them with `esentutl /r` on a copy and compare.

## Manifest format

See [`manifest.schema.json`](manifest.schema.json). Per entry:

| Field | Meaning |
|---|---|
| `id` | stable slug, also the folder name under `files/<area>/` |
| `artifact_type` | `SRUDB.dat`, `WebCacheV01.dat`, `Windows.edb`, `ntds.dit` or `other` (+ `artifact_detail`) |
| `redistributable` | `true` only if the source terms allow redistribution |
| `file.path`, `file.sha256`, `file.size` | extracted database relative to `ese/`; hash/size of the decompressed bytes |
| `file.compressed_as` | `gzip` when stored as `.gz` |
| `file.sidecars[]` | `.log`/`.jrs`/`.chk`/`.jfm` files extracted with it |
| `source.name`, `source.url`, `source.licence`, `source.terms_url` | where it came from and under which terms |
| `source.image_name`, `source.image_sha256`, `source.path_in_image` | the image it was extracted from (null image hash for synthetic files) |
| `source.retrieved` | date downloaded / generated |
| `windows_version` | e.g. `Windows 7 Ultimate SP1`, `Windows 10 1909`, `Windows Server 2019` |
| `header.*` | read from page 0: signature (offset 4), format version (8), file type (12), state (52), format revision (232), page size (236) |
| `reference` | `{tool, generated, tables: {name: rows}}` from an independent tool |
| `tags`, `notes` | free form; `dirty` and `has-logs` are added automatically |

Example entry:

```json
{
  "id": "cfreds-leakage-pc-srudb",
  "artifact_type": "SRUDB.dat",
  "redistributable": false,
  "file": { "path": "files/local/cfreds-leakage-pc-srudb/SRUDB.dat", "sha256": "…", "size": 1048576 },
  "source": {
    "name": "NIST CFReDS Data Leakage Case",
    "url": "https://cfreds-archive.nist.gov/data_leakage_case/data-leakage-case.html",
    "licence": "US Government work; no explicit licence stated",
    "image_name": "cfreds_2015_data_leakage_pc.E01",
    "image_sha256": null,
    "path_in_image": "C:/Windows/System32/sru/SRUDB.dat",
    "retrieved": "2026-11-27"
  },
  "windows_version": "Windows 7 Ultimate SP1",
  "header": { "signature_ok": true, "file_type": 0, "format_version": "0x620", "format_revision": "0x11",
              "page_size": 32768, "page_size_raw": 32768, "db_state": 3, "db_state_name": "CleanShutdown" },
  "reference": { "tool": "esedbexport 20240420", "generated": "2026-11-28", "tables": { "MSysObjects": 123 } },
  "tags": [],
  "notes": "…"
}
```

(Values are illustrative. Windows 7 has no SRUM; the real Data Leakage
image gives you `Windows.edb` and possibly WebCache instead.)

## Adding a file

1. Download the source image into `images/` and check its published hash.
2. Mount or open it read-only (Arsenal Image Mounter, FTK Imager, `ewfmount`,
   7-Zip for VHD/VMDK) and copy the database **and** any `.log`/`.chk`/`.jrs`
   files from the same folder into `work/<something>/`. Do not run
   `esentutl /r` or `/p` on the copy you register; the corpus keeps files in
   the state they were found.
3. Register it:

   ```powershell
   python tools/add_to_manifest.py work/leakage/Windows.edb `
       --id cfreds-leakage-pc-windows-edb --artifact-type Windows.edb `
       --source-name "NIST CFReDS Data Leakage Case" `
       --source-url https://cfreds-archive.nist.gov/data_leakage_case/data-leakage-case.html `
       --licence "US Government work; no explicit licence stated" `
       --image images/cfreds_2015_data_leakage_pc.E01 `
       --path-in-image "C:/ProgramData/Microsoft/Search/Data/Applications/Windows/Windows.edb" `
       --windows-version "Windows 7 Ultimate SP1" `
       --no-redistributable --copy-to local --with-sidecars
   ```

   `--image` hashes the whole image (slow); use `--image-sha256` to paste a
   published hash instead. Run with only `--id` and the changed options to
   update an entry later; other fields are kept.
4. Produce reference row counts with a separate tool, save them as
   `{"Table": rows, …}` and attach them:
   `--reference-json work/leakage/counts.json --reference-tool "esedbexport 20240420"`.
5. Commit `manifest.json` (and the `.gz` under `files/redist/` if redistributable).

`--header-only FILE` prints the header without touching the manifest;
`--verify` re-hashes every entry that is present.

## Licence rules

* **Allowed:** (a) synthetic databases you made yourself in a throwaway VM with
  no personal data, (b) databases extracted from **publicly published DFIR
  datasets** (CTF images, tool-testing corpora, open-source test data).
* **Record the terms** of every source in `source.licence` / `source.terms_url`.
  If no licence is stated, say so; that is not permission to redistribute.
* **Redistributable** (`redistributable: true`, under `files/redist/`, committed)
  only if the terms clearly allow it (CC0, public domain, Apache-2.0/MIT/BSD
  with the notice kept, or your own synthetic files).
* **Everything else** (no stated licence, "all rights reserved", copyleft you do
  not want to pull into this repo, or files over about 10 MiB compressed) goes
  to `files/local/`, which is git-ignored. Only the manifest entry is committed.
* This repository as a whole is GPL-3.0. Third-party files keep their own
  terms; note them per entry.
* Even public CTF images contain made-up "personal" data of fictional people.
  That is fine for local testing but is another reason to keep their files local.

## Candidate sources

Checked on 2026-11-27. Nothing here has been downloaded. All large images are
left for you to download.

| Source | What / Windows version | Expected ESE files | Size | Terms |
|---|---|---|---|---|
| **NIST CFReDS – Data Leakage Case** ([page](https://cfreds-archive.nist.gov/data_leakage_case/data-leakage-case.html), [hashes](https://cfreds-archive.nist.gov/data_leakage_case/hash_values.html)) | PC image, Windows 7 Ultimate SP1, 20 GB disk; DD (7-Zip, 5.05 GB) or E01 (7.28 GB) | `Windows.edb` (Windows Search), IE10/11 `WebCacheV01.dat` if IE was updated (the case uses IE). No SRUM (Windows 8+ only). | ~5–7 GB | NIST/US-government work, no explicit licence on the page → **local** |
| **NIST CFReDS portal** ([cfreds.nist.gov](https://cfreds.nist.gov/), [Magnet uploads](https://cfreds.nist.gov/all/MagnetForensics)) | Many datasets incl. newer Magnet CTF images (2023+ Windows 10/11, Windows Server) | SRUDB.dat, WebCacheV01.dat, Windows.edb (Windows 11 22H2+ uses `Windows.db` SQLite instead), possibly ntds.dit on server images | 10–50 GB each | Per dataset; check each page → default **local** |
| **Digital Corpora – Magnet CTF images** ([listing](https://downloads.digitalcorpora.org/corpora/scenarios/magnet/), [terms](https://digitalcorpora.org/terms-of-use/)) | `2019 CTF - Windows-Desktop.zip` (9.9 GiB), `2020 CTF - Windows.zip` (27 GiB), `2022 CTF - Windows.zip` (35 GiB, Windows 11). The 2018 Windows zips are only ~2 KB (pointers, not images). | Windows 10/11: SRUDB.dat, WebCacheV01.dat, Windows.edb; Edge/IE WebCache | 10–35 GB | Digital Corpora's own material is CC0, but its terms say content inside images that claims copyright is excluded. Images are by Magnet Forensics → **local** |
| **Digital Corpora – M57 / scenario images** ([M57-Patents](https://digitalcorpora.org/corpora/scenarios/m57-patents-scenario/), [disk images](https://digitalcorpora.org/corpora/disk-images/)) | Windows XP era (2008–2009) | Pre-Vista ESE is rare on XP desktops; useful mainly for old-format ESE if any app used it (e.g. Windows Update `DataStore.edb` on XP SP2+). | GBs | CC0 for DC content (same caveat) |
| **Magnet Forensics CTF posts** ([Weekly CTF 2020](https://www.magnetforensics.com/blog/magnet-weekly-ctf-2020-images-and-questions/), [MVS 2024](https://www.magnetforensics.com/blog/2024-magnet-virtual-summit-ctf-winners-and-another-chance-to-play), [MVS 2025](https://magnetforensics.com/blog/announcing-the-winners-of-the-2025-magnet-virtual-summit-ctf), [MVS 2026](https://www.magnetforensics.com/blog/announcing-the-winners-of-the-2026-magnet-virtual-summit-ctf/)) | Windows 10/11 (and Server) images; 2025 Windows 11 image; newer sets hosted on CFReDS | SRUDB.dat, WebCacheV01.dat, Windows.edb | 10–50 GB | No licence stated; free for training → **local** |
| **DEF CON DFIR CTF** ([forum thread with image links](https://forum.defcon.org/node/7233), [HR-server write-up](https://mjdepuy.github.io/posts/defcon_ctf_hr_server.html)) | Windows Server / desktop images from the DEF CON DFIR CTF (built with Champlain students via Magnet) | Server: possibly ntds.dit (if a DC), Windows.edb, UAL `Current.mdb`/`SystemIdentity.mdb`, SRUM on 2016+ | GBs | No licence stated → **local**. Links not verified to be live; check the thread. |
| **Ali Hadi – Digital Forensic Challenge Images** ([ashemery.com/dfir.html](https://www.ashemery.com/dfir.html)) | 11 challenges: #1 Web Server Case, #2 User Policy Violation, #3 Mystery Hacked System, #5 BSides Amman Windows workshop, #6 Browser Policy Violation, #7 SysInternals, #9 Encrypt Them All, … Windows 7/8/10 systems; archive.org mirrors linked | Windows.edb (challenge #2 covers "Windows Search"), WebCacheV01.dat (#6), SRUDB.dat on Windows 8/10 images | 1–20 GB | "Copyright © 2011–2025, Ali Hadi"; free for training, no redistribution grant → **local** |
| **Velocidex/go-ese testdata** ([repo](https://github.com/Velocidex/go-ese/tree/master/testdata)) | `Samples/WebCacheV01.dat` (26 MB), `Samples/Windows.edb` (50 MB), `Samples/ntds.dit` (21 MB), `SRUM/SRUDB.dat` (3.3 MB), `Sample_UAL/*/*.mdb` (1 MB each) | as named; UAL files are from brimorlabs/KStrike | 1–50 MB | Repo is Apache-2.0, but `testdata/README.md` says the UAL samples were taken from KStrike (below); provenance of the others is not stated → **local** until checked |
| **brimorlabs/KStrike** ([repo](https://github.com/brimorlabs/KStrike)) | `Sample_UAL/` – User Access Logging `Current.mdb`, `SystemIdentity.mdb`, `{GUID}.mdb` (Windows Server) | UAL ESE databases | ~1 MB each | Custom licence "All rights reserved", as-is → **local** |
| **Velocidex/velociraptor test files** ([folder](https://github.com/Velocidex/velociraptor/tree/master/artifacts/testdata/files)) | UAL `Current.mdb` (288 KB), `SystemIdentity.mdb`, `{GUID}.mdb` | UAL | ≤1 MB | AGPL-3.0 repo → **local** |
| **fox-it/dissect.esedb `tests/_data`** ([repo](https://github.com/fox-it/dissect.esedb/tree/main/tests/_data), archived Nov 2025) | `basic/binary/default/index/large/multi/text.edb.gz` (synthetic), `SRUDB.dat.gz` (53 KB), `Current.mdb.gz` (UAL), `Windows.edb.gz` (7 MB) | as named | 10 KB – 7 MB gz | **Apache-2.0** (not AGPL any more; dissect was relicensed). Synthetic ones could be redistributed with the notice; SRUDB/Windows.edb provenance unknown → **local** |
| **fox-it/dissect.database `tests/_data/ese`** ([repo](https://github.com/fox-it/dissect.database), successor of dissect.esedb) | Same synthetic set plus `ntds/{adam,fve,goad,large}/ntds.dit.gz`, `tools/CertLog.edb.gz`, `tools/Current.mdb.gz`, `tools/SRUDB.dat.gz` | ntds.dit (AD LDS, BitLocker keys, GOAD lab DC), CertLog.edb (AD CS) | stored in Git LFS (clone with `git lfs pull`) | Apache-2.0; GOAD is a public lab, so `goad/ntds.dit` is lab data → still **local** by default |
| **libyal/libesedb** ([repo](https://github.com/libyal/libesedb)) | No sample databases in the repo; the reference tool (`esedbexport`, `esedbinfo`) | – | – | LGPL-3.0; use as the reference tool |

Small open-source samples (go-ese, KStrike, dissect) are only a few MB and
could be fetched with `git clone --depth 1` / `gh api` once you approve it.

## Making synthetic databases

### Clean, redistributable databases from a throwaway VM

Goal: real Windows-written `SRUDB.dat`, `WebCacheV01.dat`, `Windows.edb`
(and `ntds.dit` from a lab DC) with no real personal data.

1. Create a new VM from Microsoft's evaluation media (Windows 10/11 Enterprise
   evaluation, Windows Server evaluation). Use a **local account** with a
   made-up name (`testuser`), no Microsoft account, no sync, no real network
   credentials. Use evaluation ISOs from different releases to cover versions
   (Windows 10 1809/21H2, Windows 11 21H2/23H2/24H2, Server 2016/2019/2022/2025).
2. Create activity with scripted, fake content only: open a few known websites
   in Edge/IE mode (for WebCache), create text files with made-up content in
   the profile (indexed into `Windows.edb`), run some apps and use the network
   for an hour or more (SRUM writes roughly hourly). For `ntds.dit`, promote a
   Server VM to a DC of a fake domain (`corp.test`) and add fake users.
3. Get clean copies. These files are locked while Windows runs. Either:
   * shut the VM down cleanly and copy the files from the offline disk
     (mount the VHDX on the host read-only), or
   * take a VSS snapshot inside the VM and copy from it, then copy the
     `.log`/`.chk` files too (the copy is then usually *dirty*, see below).
   * For a clean-shutdown copy of a dirty one: `esentutl /r <base> /d` on a
     **copy** (base name `sru` for SRUM, `V01` for WebCache, `MSS` for Windows
     Search, `edb` for ntds).
4. Before registering, check the VM only had made-up data. Record the Windows
   build (`winver`) in `--windows-version`, use
   `--source-name "synthetic (throwaway VM)" --licence CC0-1.0 --redistributable`,
   gzip the file and use `--copy-to redist` if it is small, otherwise `local`.

Page sizes differ by artifact and Windows version (SRUM and WebCache commonly
32 KiB, `ntds.dit` 8 KiB unless the Server 2025 32k-page optional feature is
enabled). Do not assume: read them with `esentutl /mh <file>` or
`python tools/add_to_manifest.py --header-only <file>`, and aim for a mix.

### Dirty-shutdown databases with real `.log` files via esent.dll

The Crush fixture generator (`crush/tests/fixtures/generate_ese_fixtures.py`
in the Crush repository) already drives esent.dll through ctypes with
`JET_paramRecovery = "Off"`. For dirty databases, use the same approach with
logging on and kill the process before `JetTerm`:

1. In a scratch folder, set `JET_paramSystemPath`, `JET_paramLogFilePath`,
   `JET_paramTempPath` to that folder, `JET_paramBaseName = "edb"`,
   **`JET_paramRecovery = "On"`**, and optionally `JET_paramCircularLog = 0`
   (keep all log generations) and a small `JET_paramLogFileSize` so you get
   several `edbNNNNN.log` files.
2. `JetInit` → `JetBeginSession` → `JetCreateDatabase` → create tables and
   insert rows in transactions (`JetBeginTransaction` / `JetCommitTransaction`).
   Commit some transactions with `JET_bitCommitLazyFlush` so their changes are
   only in the log, and leave the last transaction **uncommitted**.
3. Do **not** call `JetDetachDatabase`, `JetEndSession` or `JetTerm`. Write
   the expected values (committed rows only, plus a note which rows are only
   in the log) to a JSON file, flush it, then end the process hard:
   `os._exit(1)` or `ctypes.windll.kernel32.TerminateProcess(GetCurrentProcess(), 1)`.
   Running the writer as a child process and killing it from the parent
   (`proc.kill()`) after a "ready" line works too.
4. The folder now has `<name>.edb` with header state 2 (DirtyShutdown),
   `edb.chk`, `edb.log` / `edbNNNNN.log`, `edbres00001.jrs`, `edbres00002.jrs`
   (and `.jfm` on newer Windows). `esentutl /mh <name>.edb` shows
   `State: Dirty Shutdown` and the required log range.
5. Register the `.edb` with `--with-sidecars` (logs are recorded and copied
   too) and `--tag synthetic`. The tool adds the `dirty` and `has-logs` tags.
6. Optional: make a recovered twin. Copy the folder, run
   `esentutl /r edb /l . /s . /d .` in the copy, and register the result as a
   second entry (state 3, now containing the lazy-flushed rows). Comparing the
   two shows what a parser misses without log replay.

Vary page size (`JET_paramDatabasePageSize` 4096/8192/16384/32768, a global
parameter set before `JetInit`) and run on different Windows versions to get
different format revisions.
