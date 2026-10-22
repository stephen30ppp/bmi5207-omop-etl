import sys, glob, os, re, pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_columns',30); pd.set_option('display.max_colwidth',60); pd.set_option('display.max_rows',300)
root=sys.argv[1]
def load(t):
    fs=sorted(glob.glob(os.path.join(root,'*',f'{t}_*.xlsx')))
    return pd.concat([pd.read_excel(f).assign(__src=os.path.basename(f).split('_patient ')[1][:1]) for f in fs],ignore_index=True)
demo,cv,lab,med,sx=[load(t) for t in ['patient demo','case visit','lab results','medication order','surgical']]
print("DEMO\n",demo.drop(columns='__src'))
print("\nDUP Case_No in case_visit:"); d=cv[cv.Case_No.duplicated(keep=False)]; print(d.T.loc[[c for c in d.columns if d[c].nunique(dropna=False)>1 or c in('Case_No','Patient_No')]])
cvset=set(cv.Case_No)
for n,df in [('lab',lab),('med',med),('surgical',sx)]:
    s=set(df.Case_No); print(f"\n{n}: distinct Case_No={len(s)} in case_visit={len(s&cvset)} missing={sorted(s-cvset)}")
    # patient consistency
    if n!='x':
        m=df.merge(cv[['Case_No','Patient_No']].drop_duplicates(),on='Case_No',how='left',suffixes=('','_cv'))
        print("  patient mismatch rows:",int((m.Patient_No_cv.notna()&(m.Patient_No!=m.Patient_No_cv)).sum()))
print("\nPer-patient case counts:",cv.groupby('Patient_No').Case_No.nunique().to_dict())
print("cv adm range",cv.Adm_DateTime.min(),cv.Adm_DateTime.max(),"; lab",lab.Result_Test_Date.min(),lab.Result_Test_Date.max(),"; med",med.Order_Creation_Date.min(),med.Order_Creation_Date.max(),"; sx",sx.operation_date.min(),sx.operation_date.max())
# events outside visit windows
w=cv[['Case_No','Adm_DateTime','Dis_DateTime']].drop_duplicates('Case_No')
for n,df,col in [('lab',lab,'Result_Test_Date'),('med',med,'Order_Creation_Date'),('sx',sx,'operation_date')]:
    m=df.merge(w,on='Case_No',how='left'); out=m[(m[col]<m.Adm_DateTime)|(m[col]>m.Dis_DateTime)]
    print(f"{n}: rows outside own visit window={len(out)} / unlinked={m.Adm_DateTime.isna().sum()}")
# death vs last event
ev=pd.concat([cv[['Patient_No','Dis_DateTime']].rename(columns={'Dis_DateTime':'t'}),lab[['Patient_No','Result_Test_Date']].rename(columns={'Result_Test_Date':'t'}),med[['Patient_No','Order_Creation_Date']].rename(columns={'Order_Creation_Date':'t'})])
last=ev.groupby('Patient_No').t.agg(['min','max']); print("\nevent span per patient\n",last.join(demo.set_index('Patient_No')[['Patient_DOB','Deceased_Ind','Death_Date']]))
# diagnoses
sec=cv.Secondary_Diagnosis_Codes_Subvention.fillna('').str.split(',')
cnt=sec.apply(lambda x:len([c for c in x if c.strip()]))
print("\nsecondary count == No_of_Secondary_Diagnosis_Subvention:",(cnt==cv.No_of_Secondary_Diagnosis_Subvention).sum(),"/",len(cv), "; == ..._ICD9:",(cnt==cv.No_of_Secondary_Diagnosis_ICD9).sum())
allc=sorted(set(c.strip() for x in sec for c in x if c.strip())|set(cv.Primary_Diagnosis_Code_Mediclaim))
print("distinct dx codes total:",len(allc)," total dx rows (primary+secondary):",len(cv)+cnt.sum())
print("code lengths:",pd.Series([len(c) for c in allc]).value_counts().to_dict()); print("6+ char codes:",[c for c in allc if len(c)>=6]); print("letters:",sorted(set(c[0] for c in allc)))
print("primary codes:",sorted(cv.Primary_Diagnosis_Code_Mediclaim.unique()))
# labs
num=pd.to_numeric(lab.Test_Result,errors='coerce'); print("\nlab non-numeric results:",lab.loc[num.isna(),['Test_Code','Short_Text','Test_Result']].drop_duplicates().to_string())
print("lab null Test_Code rows:\n",lab.loc[lab.Test_Code.isna(),['Short_Text','Test_Result','Panel_Test_Code','Chapter_Description']])
print("lab distinct (Test_Code,Short_Text):",lab[['Test_Code','Short_Text']].drop_duplicates().shape[0])
print("lab codes list:",sorted(lab.Short_Text.unique()))
print("no unit column in labs -> columns:",list(lab.columns))
# meds
print("\nmed Component_Type counts:",med.Component_Type_Code.value_counts().to_dict())
print("med null Order_Text by component type:",med[med.Order_Text.isna()].Component_Type_Code.value_counts().to_dict())
print("med non-numeric Dosage_Ordered:",med.loc[pd.to_numeric(med.Dosage_Ordered,errors='coerce').isna(),'Dosage_Ordered'].unique())
print("med units:",med.Dosage_Ordered_Unit.value_counts().to_dict()); print("forms:",med.Dosage_Form.value_counts(dropna=False).to_dict())
print("distinct Cluster codes:",med.Cluster_Preferred_Name_Code.nunique(),"(MED only:",med[med.Component_Type_Code=='MED'].Cluster_Preferred_Name_Code.nunique(),")")
print("same order multi-component example:\n",med[med.Order_Text.isna()].head(4)[['Case_No','Order_Creation_Date','Order_Text','Medication_Order_Component_Text','Component_Type_Code','Dosage_Ordered','Dosage_Ordered_Unit']])
print(med.head(6)[['Case_No','Order_Creation_Date','Order_Text','Medication_Order_Component_Text','Component_Type_Code','Dosage_Ordered','Dosage_Ordered_Unit','Strength_Unit','Cluster_Preferred_Name_Code']])
print("\nSURGICAL\n",sx.drop(columns='__src'))
print("surgical vs visit adm time equal:",(sx.merge(w,on='Case_No').pipe(lambda m:(m.operation_date==m.Adm_DateTime).sum())))
