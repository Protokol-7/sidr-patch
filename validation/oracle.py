"""Independent oracle: rebuild the database as of every committed WAL transaction
(using SQLite itself to read each snapshot) and list every (WorkId, ColumnId, value)
that existed at some point but is not in the final state."""
import os, sqlite3, struct, sys, tempfile, shutil

case = sys.argv[1]
db = os.path.join(case, "Windows.db")
wal = db + "-wal"

def triples(path):
    c = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    r = set()
    for w, col, v in c.execute("select WorkId, ColumnId, Value from SystemIndex_1_PropertyStore"):
        r.add((w, col, type(v).__name__, v if not isinstance(v, bytes) else bytes(v)))
    c.close()
    return r

base = open(db, "rb").read()
psz = struct.unpack(">H", base[16:18])[0]
psz = 65536 if psz == 1 else psz
data = open(wal, "rb").read()
magic, ver, wpsz, ckpt, s1, s2, c1, c2 = struct.unpack(">8I", data[:32])
be = magic & 1
def cks(b, s):
    s0, s1_ = s
    fmt = ">" if be else "<"
    for i in range(0, len(b), 8):
        x0, x1 = struct.unpack(fmt + "2I", b[i:i + 8])
        s0 = (s0 + x0 + s1_) & 0xffffffff
        s1_ = (s1_ + x1 + s0) & 0xffffffff
    return (s0, s1_)
ck = cks(data[:24], (0, 0))
assert ck == (c1, c2)
fs = 24 + psz
frames = []
for i in range((len(data) - 32) // fs):
    off = 32 + i * fs
    pg, commit, fs1, fs2, k1, k2 = struct.unpack(">6I", data[off:off + 24])
    if (fs1, fs2) != (s1, s2):
        break
    ck2 = cks(data[off + 24:off + fs], cks(data[off:off + 8], ck))
    if ck2 != (k1, k2):
        break
    ck = ck2
    frames.append((pg, commit, data[off + 24:off + fs]))

tmp = tempfile.mkdtemp()
img = bytearray(base)
snaps = [triples(db)]  # transaction 0: database file alone
for pg, commit, page in frames:
    end = pg * psz
    if len(img) < end:
        img.extend(b"\0" * (end - len(img)))
    img[(pg - 1) * psz:end] = page
    if commit:
        p = os.path.join(tmp, "snap.db")
        open(p, "wb").write(bytes(img[:commit * psz]))
        snaps.append(triples(p))
final = snaps[-1]
hist = set().union(*snaps) - final
shutil.rmtree(tmp)
print(f"commits={len(snaps)-1} frames_valid={len(frames)} historical={len(hist)}")
import pickle
pickle.dump({"hist": hist, "final": final}, open(os.path.join(case, "..", "oracle.pkl"), "wb"))
