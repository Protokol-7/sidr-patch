# Validation scripts for --history

You need Python 3 (standard library only) and a built `sidr_patch` binary. All scripts work on
copies they make themselves. The test cases are generated from SIDR's sample database.

1. **Generate test cases** with a known edit history: renames, a deleted record, a removed
   property, a changed date, a value spanning several pages, an interrupted (uncommitted)
   write, and an old WAL generation.

   ```
   python make_cases.py ../tests/testdata/Windows.db cases
   ```

   This creates `cases/A` (committed and uncommitted history) and `cases/B` (old WAL generation).
   `cases/expect.json` records which WorkIds were changed.

2. **Build the oracle.** This rebuilds the database as of every committed WAL transaction,
   reads each snapshot with SQLite itself, and lists every value that existed at some point
   but not in the final state.

   ```
   python oracle.py cases/A/case
   python oracle.py cases/B/case
   ```

3. **Run SIDR and compare.**

   ```
   sidr_patch -f csv --history -o out_A cases/A/case
   python compare.py cases/A out_A
   sidr_patch -f csv --history -o out_B cases/B/case
   python compare.py cases/B out_B
   ```

   Expected: `oracle values missing from report: 0` and `committed-source rows not in oracle: 0`.

4. **Check the "Not file data" rule against real property-store pages** (optional). This uses
   SQLite's dbstat to list every live property-store page and reports how many would match
   the SystemIndex_1_Properties rule (expected: 0).

   ```
   python pagecheck.py <Windows.db> <another Windows.db>
   ```

## Checking --history on a real case

Copy only `Windows.db`, without `-wal`, to an empty folder. Open it with
`sqlite3 -readonly` or SQLECmd to see the database as it was before the WAL changes.
Every Recovered_Values_Report row whose Source contains "DB page replaced by WAL" should
show its HistoricalValue as the current value in that copy.
