sidr_patch.exe - SIDR 0.9.2 with Windows 11 24H2/25H2 fixes and history recovery
Source changes: sidr-patch.patch (apply to https://github.com/strozfriedberg/sidr v0.9.2)

USAGE
  sidr_patch.exe -f csv -o <output folder> <input folder>
  sidr_patch.exe -f csv --history -o <output folder> <input folder>

  Put Windows.db together with Windows.db-wal (and -shm if present) in the input
  folder. All input files are opened read-only and are not modified. If -shm is
  missing, SQLite may create a new one; Windows.db and -wal stay unchanged.

CHANGES FROM STOCK SIDR 0.9.2
  1. Windows Search collations (UNICODE_en-US, ...) are handled internally.
  2. Date/number values (storage type 12) of unexpected length no longer crash
     the tool; such values are written as hex. Values stored as native SQLite
     integers are decoded correctly.
  3. New --history option (below).
  4. Fixed a CSV header bug present in stock SIDR 0.9.2: the header used to be
     fixed to whatever properties the first processed record had, so properties
     like System.Search.AutoSummary or System.FileOwner could be missing from
     the header entirely if the first record in the table didn't have them.
     Every property a report's rows can contain is now registered before any
     row is written, so the header always covers everything that gets written.
  The File, Internet History and Activity History reports carry the same
  per-row data as stock SIDR, but CSV column layout is no longer byte-identical
  because of fix 4 above (tested on SIDR's sample .edb/.db).

--history: <HOST>_Recovered_Values_Report_<time>.csv
  One row per property value that exists physically in the files but differs from
  the current state that the normal reports show.

  WorkId           Search index record ID (same as in the File Report)
  Status           Changed          - record still exists, this property now has another value
                   Property removed - record exists, this property no longer does
                   Record deleted   - record no longer exists in the current index
                   Not file data (SystemIndex_1_Properties)
                                    - old record of an internal Windows Search table with the
                                      same layout; kept for completeness, listed at the end,
                                      WorkId/ItemPath left empty, Property = "IndexID x, PropertyID y"
  Property         Windows property name, e.g. System.ItemPathDisplay
  HistoricalValue  The recovered older value
  CurrentValue     The value in the current index (empty if removed/deleted)
  ItemPath         Current path of the item; for deleted records the recovered old path
  Source           Where the value was found:
                   WAL committed           - older version from a completed write in the WAL
                   DB page replaced by WAL - version in Windows.db that the WAL has replaced
                   WAL uncommitted         - from a write that never finished (not part of
                                             the index state Windows used); treat with care
                   WAL old generation      - leftover from an earlier WAL cycle
                   DB unused page          - leftover in a freed page of Windows.db
                   A page is labelled as SystemIndex_1_Properties only if all its records
                   use that table's few key numbers, all values are blobs, and at least one
                   blob sits under key 0 or a text-type property (never the case for real
                   file records). Nothing is dropped; such rows are labelled instead.
  FirstSeen/LastSeen  Location of the oldest/newest copy (approximate order:
                   old WAL generation, then Windows.db, then WAL in frame order)
  Occurrences      Number of page copies containing this value

LIMITS
  - Only versions that physically survive can be recovered. Data overwritten by a
    later WAL cycle or by page reuse is gone.
  - Deleted cells inside pages that are still in use (SQLite "freeblocks") are not carved.
  - Windows Search may reuse a WorkId for a different item; check ItemPath and dates
    before concluding a "Changed" row is the same file.
  - The ordering of versions is approximate; the WAL holds no timestamps of its own.
    Use the date properties in the recovered values for timing.

VERSION NOTE
  Earlier --history builds reported old SystemIndex_1_Properties records as file data
  ("Property removed" rows for System.Null, System.Contact.PrimaryTelephone,
  System.Contact.HomeAddressCity). This build labels them "Not file data" instead and
  never drops them.

TESTING (on generated databases with known edit histories)
  - Every older value visible in any committed WAL snapshot (rebuilt independently
    with SQLite) was found; no values from committed sources were reported that were
    not in a snapshot.
  - Deleted records in freed pages: 4,104 of 4,320 deleted values recovered, all
    matching the original data exactly.
  - Freed SystemIndex_1_Properties pages: all records listed as "Not file data", none as file data.
  - A deleted file record using only the overlapping property numbers was still reported
    as file data ("Record deleted").
  - Rule applied to all 22,115 live property-store pages of the test databases: 0 matched.
  - 97 MB database, 2.5 million values, 3,000-transaction WAL: about 8 seconds,
    about 210 MB RAM.
