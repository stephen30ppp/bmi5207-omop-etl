import sys, glob, os, pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_columns',50); pd.set_option('display.max_colwidth',40)
root=sys.argv[1]
types=['patient demo','case visit','lab results','medication order','surgical']
for t in types:
    files=sorted(glob.glob(os.path.join(root,'*',f'{t}_*.xlsx')))
    frames=[]
    print(f"\n==================== {t}  ({len(files)} files)")
    for f in files:
        x=pd.ExcelFile(f)
        for sh in x.sheet_names:
            df=x.parse(sh)
            print(f"  {os.path.basename(f)} sheet={sh!r} shape={df.shape} cols={list(df.columns)}")
            df['__file']=os.path.basename(f); frames.append(df)
    m=pd.concat(frames,ignore_index=True)
    print(f"  MERGED rows={len(m)}")
    for c in m.columns:
        if c=='__file': continue
        s=m[c]
        print(f"   - {c!r}: dtype={s.dtype} nulls={s.isna().sum()} distinct={s.nunique()} sample={list(s.dropna().astype(str).unique()[:6])}")
