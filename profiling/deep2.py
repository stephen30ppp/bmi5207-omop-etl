import sys, glob, os, pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_columns',30); pd.set_option('display.max_rows',100)
root=sys.argv[1]
def load(t):
    fs=sorted(glob.glob(os.path.join(root,'*',f'{t}_*.xlsx'))); return pd.concat([pd.read_excel(f) for f in fs],ignore_index=True)
cv,lab,med=[load(t) for t in ['case visit','lab results','medication order']]
w=cv.drop_duplicates('Case_No')[['Patient_No','Case_No','Adm_DateTime','Dis_DateTime']]
print("lab Case_No per patient:",lab.groupby('Patient_No').Case_No.unique().to_dict())
m=lab.merge(w,on='Patient_No',suffixes=('_lab','_cv')); m=m[(m.Result_Test_Date>=m.Adm_DateTime)&(m.Result_Test_Date<=m.Dis_DateTime)]
hits=m.groupby(lab.index.name or 'Result_Test_Date').size()
lab['n_visit_windows']=lab.apply(lambda r: ((w.Patient_No==r.Patient_No)&(w.Adm_DateTime<=r.Result_Test_Date)&(w.Dis_DateTime>=r.Result_Test_Date)).sum(),axis=1)
print("lab rows by #matching visit windows of same patient:",lab.n_visit_windows.value_counts().to_dict())
print(lab.groupby(['Patient_No','Case_No']).Result_Test_Date.agg(['min','max','count']))
print(w.sort_values(['Patient_No','Adm_DateTime']).to_string())
mm=med.merge(w,on=['Case_No','Patient_No']); o=mm[(mm.Order_Creation_Date<mm.Adm_DateTime)|(mm.Order_Creation_Date>mm.Dis_DateTime)]
o=o.assign(before_adm_h=((o.Adm_DateTime-o.Order_Creation_Date).dt.total_seconds()/3600).round(1),after_dis_h=((o.Order_Creation_Date-o.Dis_DateTime).dt.total_seconds()/3600).round(1))
print("\nmed out-of-window:\n",o[['Case_No','Order_Creation_Date','Adm_DateTime','Dis_DateTime','before_adm_h','after_dis_h','Medication_Order_Component_Text']].to_string())
med['n_win']=med.apply(lambda r: ((w.Patient_No==r.Patient_No)&(w.Adm_DateTime<=r.Order_Creation_Date)&(w.Dis_DateTime>=r.Order_Creation_Date)).sum(),axis=1)
print("med out-of-window rows that fall into ANOTHER visit of same patient:",int(med.loc[o.index.intersection(med.index),'n_win'].gt(0).sum()) if len(o) else 0)
print(med[med.Dosage_Ordered.astype(str).str.contains('2022|0 - 2')][['Medication_Order_Component_Text','Dosage_Ordered','Dosage_Ordered_Unit','Dosage_Form']])
print("visits per patient overlapping? ")
for p,g in w.sort_values('Adm_DateTime').groupby('Patient_No'):
    g=g.reset_index(drop=True); ov=[(g.Case_No[i],g.Case_No[i+1]) for i in range(len(g)-1) if g.Adm_DateTime[i+1]<g.Dis_DateTime[i]]
    if ov: print(p,ov)
