# sidr-patch

**sidr-patch** is a fork of [strozfriedberg/sidr](https://github.com/strozfriedberg/sidr) (SIDR, Search Index DB Reporter), a Rust tool that parses Windows Search artifacts (`Windows.edb` on Windows 10 and earlier, `Windows.db` on Windows 11) into File, Internet History and Activity History reports.

> Most of this codebase is unmodified upstream SIDR (base commit `5bde8e8`, Apache License 2.0, © 2025 LevelBlue). We only patched it to stop crashing on Windows 11 24H2/25H2/26H2 databases and added the new `--history` recovery option below. We didn't write SIDR itself. See [Copyright](#copyright) and the full diff in [sidr-patch.patch](sidr-patch.patch) for exactly what we changed vs. what's untouched upstream code.

This fork fixes three crashes/decoding bugs that stock SIDR 0.9.2 hits on Windows 11 24H2/25H2 `Windows.db` databases, and adds a `--history` option that recovers older, removed and deleted property values by carving the WAL and unused database pages.

Builds as `sidr_patch.exe`. Full technical write-up of the changes: [CHANGES-PATCH.md](CHANGES-PATCH.md). Full diff against upstream: [sidr-patch.patch](sidr-patch.patch).

### Quick Links

* [Why stock SIDR fails on 24H2/25H2/26H2](#why-stock-sidr-fails-on-24h225h226h2)
* [What was changed](#what-was-changed)
* [Usage](#usage)
* [The --history option](#the---history-option)
* [Building](#building)
* [Copyright](#copyright)

### Why stock SIDR fails on 24H2/25H2/26H2

Windows Search's `Windows.db` is a SQLite database, but newer Windows 11 builds write it using features stock SIDR (and plain SQLite) can't handle:

1. **Custom collations.** The database declares columns collated with `UNICODE_en-US` and similar sequences that only exist inside the Windows Search indexer itself, not in SQLite. Any query against those columns fails outright with `no such collation sequence: UNICODE_en-US`, before SIDR produces any output.
2. **A decoding panic on short values.** SIDR reads "storage type 12" columns (dates/numbers) as an 8-byte blob and converts it with a fixed-size `TryFromSliceError`-panicking conversion. Newer builds sometimes store these values as something other than exactly 8 raw bytes, which crashes the whole run instead of just that one field.
3. **Storage-type-12 values stored as native integers.** Some of these same columns are stored by SQLite as native integers rather than as a blob. Stock SIDR's blob-reading path reads them back out as their decimal text representation (e.g. the literal characters `"133712345600000000"`) instead of decoding them as the date/number they represent.

None of these are specific to a single feature update. They're a consequence of how the Windows Search indexer's database schema evolved from the one stock SIDR was built against. The fixes below address the root cause (the collation isn't resolved vs. SQLite's expectations) rather than special-casing a version number, so they apply the same way on 24H2, 25H2 and 26H2. The 24H2 and 25H2 fixes are validated against real databases (see below); 26H2 hasn't been separately tested but exercises the identical code paths.

### What was changed

| Problem | Fix | File(s) |
|---|---|---|
| `no such collation sequence: UNICODE_en-US` | Registers a case-insensitive stand-in for whatever collation SQLite asks for, via `sqlite3_collation_needed` | `src/lib.rs`, `src/sqlite.rs` |
| Panic on storage-type-12 values that aren't exactly 8 bytes | Non-panicking decode (`le_bytes_to_u64`); values of unexpected length are written as hex instead of crashing | `src/sqlite.rs`, `src/lib.rs`, `src/utils.rs` |
| Storage-type-12 values stored as native SQLite integers read back as decimal text | Read as integers first, then decoded the same way as the blob form | `src/sqlite.rs`, `src/lib.rs` |

The File, Internet History and Activity History reports are byte-identical to stock SIDR 0.9.2 on databases stock SIDR can already read. Full detail, including the validation methodology, is in [CHANGES-PATCH.md](CHANGES-PATCH.md).

### Usage

```
Usage: sidr_patch [OPTIONS] <INPUT>

Arguments:
  <INPUT>
          Path to input directory (which will be recursively scanned for Windows.edb and Windows.db)

Options:
  -f, --format <FORMAT>
          Output report format

          [default: json]
          [possible values: json, csv]

  -r, --report-type <REPORT_TYPE>
          Output results to file or stdout

          [default: to-file]
          [possible values: to-file, to-stdout]

  -o, --outdir <OUTPUT DIRECTORY>
          Path to the directory where reports will be created (will be created if not present). Default is the current directory

      --history
          Also recover older, removed and deleted property values from the -wal file and
          unused database pages into an extra Recovered_Values_Report (Windows 11 Windows.db only)

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
```

#### Example

`> sidr_patch -f csv -o C:\out C:\test`

Scans `C:\test` for `Windows.db`/`Windows.edb`, writes reports to `C:\out`:
`DESKTOP-12345_File_Report_20230307_015244.csv`, `..._Internet_History_Report_...`, `..._Activity_History_Report_...`.

`HOSTNAME` is extracted from the database; filenames follow `HOSTNAME_ReportName_DateTime.json|csv`.

To include a `Windows.db`'s write-ahead log in the scan, put `Windows.db` together with `Windows.db-wal` (and `-shm` if present) in the input folder. All input files are opened read-only and are never modified. If `-shm` is missing, SQLite may create a new one, but `Windows.db` and `-wal` stay unchanged.

### The `--history` option

`sidr_patch -f csv --history -o C:\out C:\test`

Windows.db only (not Windows.edb). In addition to the normal three reports, writes a fourth report, `<HOST>_Recovered_Values_Report_<time>.csv`, with one row per property value that physically exists in the database/WAL files but differs from what the current index shows.

It reads `Windows.db` and `Windows.db-wal` directly, byte by byte, read-only, and recovers values from:

- the WAL: committed frames, the uncommitted tail of the last transaction (including frames whose salt/checksum fields are still zero), and frames left over from earlier WAL cycles;
- `Windows.db` pages that the WAL has since replaced, and unused/freed pages.

It decodes index b-tree pages directly and follows overflow chains using the page versions valid at each point in the WAL. It does not rely on SQLite's own query engine for this part. Old `SystemIndex_1_Properties` records (an internal Windows Search table, not file records) are labelled `Not file data` rather than mixed in with recovered file data.

**Columns:** `WorkId`, `Status` (`Changed` / `Property removed` / `Record deleted` / `Not file data`), `Property`, `HistoricalValue`, `CurrentValue`, `ItemPath`, `Source` (where the value was found: WAL committed/uncommitted/old generation, DB page replaced by WAL, DB unused page), `FirstSeen`/`LastSeen`, `Occurrences`. Full column semantics, limits (what can and can't be recovered), and validation results: [README-PATCH.txt](README-PATCH.txt).

**Caveats:** only versions that physically survive can be recovered. Data overwritten by a later WAL cycle or page reuse is gone. Windows Search can reuse a WorkId for a different item, so cross-check `ItemPath` and dates before treating a `Changed` row as the same file. The WAL has no timestamps of its own, so ordering between recovered values is approximate.

### Building

Requires [Rust](https://rustup.rs) and, on Windows, "Build Tools for Visual Studio" with the "Desktop development with C++" workload (the bundled SQLite is C code and needs a C compiler).

```
$ git clone https://github.com/Protokol-7/sidr-patch.git
$ cd sidr-patch
$ cargo build --release --locked
$ ./target/release/sidr_patch --version
sidr-patch 0.9.2
```

Full build details, including the cross-compiled Linux→Windows build: [BUILD-PATCH.md](BUILD-PATCH.md).

### Running with cargo

`cargo run --bin sidr_patch -- -f csv --report-type to-file /home/<username>/path/to/tests_s`

### Velociraptor Plugin

The `velosidr.yaml` file can be used to configure a Velociraptor plugin that will run SIDR on a target system. It's unmodified from upstream and fetches stock SIDR by default. Update the `url` in the `Tools` section to point at a `sidr_patch` release if you want the plugin to use this fork.

Note: In order to parse the database on the target endpoint, the SIDR plugin must create an empty database and copy the original database to it. Creating the new copy can overwrite multiple gigabytes of data in unallocated clusters, which may result in loss of evidence. Please use the plugin with caution.

### Copyright

Base project copyright 2025, LevelBlue. Licensed under the Apache License, Version 2.0. Modified files carry a notice at the end of the file describing the change; the full diff against upstream v0.9.2 (base commit `5bde8e8`) is in [sidr-patch.patch](sidr-patch.patch).
