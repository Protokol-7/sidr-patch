"""Compare SIDR's History_Report against the snapshot oracle."""
import csv, glob, os, pickle, sqlite3, struct, sys, datetime

case_root = sys.argv[1]           # e.g. cases/A
out_dir = sys.argv[2]
o = pickle.load(open(os.path.join(case_root, "oracle.pkl"), "rb"))
db = os.path.join(case_root, "case", "Windows.db")
c = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
meta = {i: (n, st) for i, n, st in c.execute("select Id, Name, StorageType from SystemIndex_1_PropertyStore_Metadata")}

def ft(n):
    secs, rem = divmod(n, 10_000_000)
    d = datetime.datetime(1601, 1, 1) + datetime.timedelta(seconds=secs)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + f".{rem:07d}Z"

def rust_float(f):
    return str(int(f)) if f == int(f) and abs(f) < 1e16 else repr(f)

def render(v, name, st):
    is_date = "Date" in name or "Time" in name
    if st == 12 and isinstance(v, int):
        return ft(v & 0xFFFFFFFFFFFFFFFF) if is_date else str(v)
    if st == 12 and isinstance(v, bytes):
        if 1 <= len(v) <= 8:
            n = int.from_bytes(v, "little")
            if is_date and len(v) == 8:
                return ft(n)
            if not is_date:
                return str(n)
        return v.hex()
    if isinstance(v, int): return str(v)
    if isinstance(v, float): return rust_float(v)
    if isinstance(v, str): return v
    if st == 11: return v.decode("utf-8", "replace")
    return v.hex()

oracle = set()
for w, col, t, v in o["hist"]:
    n, st = meta[col]
    oracle.add((w, n, render(v, n, st)))

csv.field_size_limit(10**9)
rows = list(csv.DictReader(open(glob.glob(os.path.join(out_dir, "*Recovered_Values_Report*.csv"))[0], newline="", encoding="utf-8")))
def key(r):
    return (int(r["WorkId"]), r["Property"], r["HistoricalValue"].replace("\\n", "\n").replace("\\r", "\r"))
rall = {key(r) for r in rows}
rcommitted = {key(r) for r in rows if "WAL committed" in r["Source"] or "DB page replaced by WAL" in r["Source"]}
missing = oracle - rall
extra = rcommitted - oracle
print(f"oracle historical values: {len(oracle)}; report rows: {len(rows)}; from committed WAL/replaced DB pages: {len(rcommitted)}")
print(f"oracle values missing from report: {len(missing)}")
for m in list(missing)[:10]: print("  MISSING", m[:2], m[2][:80])
print(f"committed-source rows not in oracle: {len(extra)}")
for m in list(extra)[:10]: print("  EXTRA", m[:2], m[2][:80])
from collections import Counter
print("rows by source:", Counter(r["Source"] for r in rows).most_common())
print("rows by status:", Counter(r["Status"] for r in rows).most_common())
