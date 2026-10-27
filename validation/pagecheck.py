import sqlite3, struct, sys, collections
SET={0,1,100,200,201,202,203,204,301}
def varint(b,p):
    v=0
    for i in range(9):
        c=b[p+i]
        if i==8: return (v<<8)|c, p+9
        v=(v<<7)|(c&0x7f)
        if not c&0x80: return v,p+i+1
def cells(page,pgno,U):
    h=100 if pgno==1 else 0; t=page[h]
    if t not in (2,10): return None
    n=struct.unpack(">H",page[h+3:h+5])[0]; hl=12 if t==2 else 8; out=[]
    for i in range(n):
        p=struct.unpack(">H",page[h+hl+2*i:h+hl+2*i+2])[0]
        if p>=U: continue
        if t==2: p+=4
        try:
            plen,p=varint(page,p); hs,q=varint(page,p); end=p+hs; types=[]
            while q<end: tt,q=varint(page,q); types.append(tt)
            if len(types)!=3: continue
            body=p+hs
            sz=lambda t:{0:0,1:1,2:2,3:3,4:4,5:6,6:8,7:8,8:0,9:0}.get(t,(t-12)//2 if t>=12 else 0)
            def iv(t,o):
                if t==8: return 0
                if t==9: return 1
                return int.from_bytes(page[o:o+sz(t)],"big",signed=True)
            w=iv(types[0],body); col=iv(types[1],body+sz(types[0]))
            kind="blob" if types[2]>=12 and types[2]%2==0 else "text" if types[2]>=13 else "real" if types[2]==7 else "int"
            out.append((w,col,kind))
        except Exception: pass
    return out
def check(db, label, only_tree="SystemIndex_1_PropertyStore", pages_filter=None):
    c=sqlite3.connect(f"file:{db}?mode=ro&immutable=1",uri=True)
    U=c.execute("pragma page_size").fetchone()[0]
    try: tree={r[0] for r in c.execute("select pageno from dbstat where name=?",(only_tree,))}
    except Exception as e: print("no dbstat",e); return
    data=open(db,"rb").read()
    text_type={i for (i,) in c.execute("select Id from SystemIndex_1_PropertyStore_Metadata where StorageType=11")}|{0}
    old=new=total=0; mincells=collections.Counter()
    for pg in sorted(tree if pages_filter is None else pages_filter):
        page=data[(pg-1)*U:pg*U]; cs=cells(page,pg,U)
        if not cs: continue
        total+=1; mincells[min(len(cs),10)]+=1
        if all(col in SET for _,col,_ in cs): old+=1
        if all(col in SET for _,col,_ in cs) and all(k=="blob" for *_,k in cs) and any(col in text_type for _,col,_ in cs): new+=1
    print(f"{label}: property-store pages checked={total}, matching key numbers only={old}, matching the full 'Not file data' rule={new}; cells/page histogram (10=10+): {sorted(mincells.items())}")
    return c
check(sys.argv[1], "sample DB (live pages)")
check(sys.argv[2], "large test DB (live pages)")
