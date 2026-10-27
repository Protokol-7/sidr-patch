# sidr-patch: changes from SIDR v0.9.2

Base: https://github.com/strozfriedberg/sidr, v0.9.2 (commit 5bde8e8).
License: Apache License 2.0 (unchanged, see LICENSE). The modified files say so in a
notice at the end of each file. `sidr-patch.patch` holds the full diff against v0.9.2.

Builds as `sidr_patch.exe`. Rust release builds are not bit-for-bit reproducible, so a
rebuild of this source will have a different SHA-256 than any previously distributed
build, even from identical source (see BUILD-PATCH.md).

## Fixes for Windows 11 24H2/25H2 databases

| Problem in v0.9.2 | Change | File |
|---|---|---|
| `no such collation sequence: UNICODE_en-US` (custom collations defined only inside Windows Search) | A case-insensitive stand-in is registered for any collation SQLite asks for (`sqlite3_collation_needed`) | `src/lib.rs`, `src/sqlite.rs` |
| Panic `TryFromSliceError` in `ese_parser.rs:530` when a storage-type-12 value is not exactly 8 bytes | Non-panicking decoding (`le_bytes_to_u64`). Dates of unexpected length are written as hex | `src/sqlite.rs`, `src/lib.rs`, `src/utils.rs` |
| Storage-type-12 values stored as native SQLite integers were read as their decimal text | Read as integers, then decoded as before | `src/sqlite.rs`, `src/lib.rs` |

The File, Internet History and Activity History reports are byte-identical to v0.9.2
on databases v0.9.2 can read (checked on SIDR's own sample `.edb` and `.db`).

## New option `--history` (Windows.db only)

New module `src/carve.rs`, wired in through `src/main.rs` and `src/sqlite.rs`. It writes an extra
`<HOST>_Recovered_Values_Report_<time>` with older, removed and deleted property values
recovered from:

- the WAL: committed frames, the uncommitted tail of the last transaction (including frames
  whose salt and checksum fields are still zero), and frames left over from earlier WAL cycles;
- Windows.db pages that the WAL has replaced, and unused pages.

It reads the files directly, byte by byte, and opens them read-only. It decodes index b-tree pages and follows
overflow chains using the page versions valid at that point in the WAL. Pages that currently
belong to other tables are excluded. Old `SystemIndex_1_Properties` records are labelled
"Not file data" rather than mixed in with file records. Column descriptions and limits
are in README-PATCH.txt.

## Validation

See `validation/README.md`. In summary:

- On generated databases with known edit histories, the report contains exactly the older
  values that SQLite can see when each committed WAL transaction is rebuilt as its own snapshot.
- Deleted records in freed pages: 4,104 of 4,320 values recovered, all exact.
- On a real 25H2 database, an independent SQLECmd-based decode matched the File and Internet
  History reports. Every WorkId was accounted for, and every difference found was traced to the comparison
  pipeline, not SIDR.
