"""Build WAL test cases with a known edit history from SIDR's sample Windows.db."""
import os, shutil, sqlite3, subprocess, sys, json

SRC = sys.argv[1]          # pristine sample Windows.db
OUT = sys.argv[2]          # output root
os.makedirs(OUT, exist_ok=True)

def prep(name):
    d = os.path.join(OUT, name, "work")
    shutil.rmtree(os.path.join(OUT, name), ignore_errors=True)
    os.makedirs(d)
    db = os.path.join(d, "Windows.db")
    shutil.copy(SRC, db)
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=DELETE")
    c.close()
    return d, db

def snapshot(name, db):
    dst = os.path.join(OUT, name, "case")
    os.makedirs(dst, exist_ok=True)
    for sfx in ("", "-wal", "-shm"):
        if os.path.exists(db + sfx):
            shutil.copy(db + sfx, os.path.join(dst, "Windows.db" + sfx))
    return dst

def colid(c, name):
    return c.execute("select Id from SystemIndex_1_PropertyStore_Metadata where Name=?", (name,)).fetchone()[0]

def wids_with(c, col, n, skip=()):
    rows = c.execute("select WorkId from SystemIndex_1_PropertyStore where ColumnId=? order by WorkId", (col,)).fetchall()
    return [r[0] for r in rows if r[0] not in skip][:n]

expect = {}

# ---------------- case A: committed history + uncommitted spill
d, db = prep("A")
c = sqlite3.connect(db)
c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA wal_autocheckpoint=0")
P = colid(c, "System.ItemPathDisplay"); DM = colid(c, "System.DateModified"); N = colid(c, "System.ItemNameDisplay")
A, B, C, D, E = wids_with(c, P, 200)[10:15]
origA = c.execute("select Value from SystemIndex_1_PropertyStore where WorkId=? and ColumnId=?", (A, P)).fetchone()[0]
with c:
    c.execute("update SystemIndex_1_PropertyStore set Value=? where WorkId=? and ColumnId=?", ("C:\\Users\\dino\\Desktop\\secret_plan.docx", A, P))
with c:
    c.execute("update SystemIndex_1_PropertyStore set Value=? where WorkId=? and ColumnId=?", ("C:\\Users\\dino\\Desktop\\holiday.docx", A, P))
pathB = c.execute("select Value from SystemIndex_1_PropertyStore where WorkId=? and ColumnId=?", (B, P)).fetchone()[0]
with c:
    c.execute("delete from SystemIndex_1_PropertyStore where WorkId=?", (B,))
with c:
    c.execute("delete from SystemIndex_1_PropertyStore where WorkId=? and ColumnId=?", (C, N))
with c:
    c.execute("update SystemIndex_1_PropertyStore set Value=? where WorkId=? and ColumnId=?", ((0x01D9000000000000).to_bytes(8, "little"), D, DM))
big = "BIGVALUE-" + "x" * 9000 + "-END"
with c:
    c.execute("update SystemIndex_1_PropertyStore set Value=? where WorkId=? and ColumnId=?", (big, E, P))
with c:
    c.execute("update SystemIndex_1_PropertyStore set Value=? where WorkId=? and ColumnId=?", ("C:\\small.txt", E, P))
# uncommitted: child process spills a big transaction into the WAL, then dies before COMMIT
child = r'''
import sqlite3, os, sys
c = sqlite3.connect(sys.argv[1], isolation_level=None)
c.execute("PRAGMA cache_size=2")
c.execute("BEGIN")
c.execute("update SystemIndex_1_PropertyStore set Value='UNCOMMITTED-'||WorkId where ColumnId=?", (int(sys.argv[2]),))
os._exit(0)
'''
subprocess.run([sys.executable, "-c", child, db, str(N)], check=True)
case = snapshot("A", db)
expect["A"] = dict(A=A, B=B, C=C, D=D, E=E, origA=origA, pathB=pathB, big_len=len(big))
c.close()

# ---------------- case B: old WAL generation left behind after a checkpoint restart
d, db = prep("B")
c = sqlite3.connect(db, isolation_level=None)
c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA wal_autocheckpoint=0")
P = colid(c, "System.ItemPathDisplay")
F = wids_with(c, P, 300)[250]
for i in range(30):
    c.execute("update SystemIndex_1_PropertyStore set Value=? where WorkId=? and ColumnId=?", (f"C:\\gen1\\version{i:02d}.txt", F, P))
c.execute("PRAGMA wal_checkpoint(RESTART)")
c.execute("update SystemIndex_1_PropertyStore set Value=? where WorkId=? and ColumnId=?", ("C:\\gen2\\now.txt", F, P))
case = snapshot("B", db)
expect["B"] = dict(F=F)
c.close()

json.dump(expect, open(os.path.join(OUT, "expect.json"), "w"), indent=1)
print(json.dumps(expect, indent=1)[:600])
