"""Input validation and data-quality reporting for Company X slow-stock review."""
from __future__ import annotations
import re
import pandas as pd

REQUIRED = {
    "Item_Master": ["SKU", "Item Name", "Category", "Master Pack Qty", "Unit Cost (Rs)", "Alternate Item (name)", "Alternate Flag", "Status"],
    "Stock_Aging": ["SKU", "Qty 0-30 days", "Qty 31-60 days", "Qty 61-90 days", "Qty 91-180 days", "Qty 180+ days"],
    "Sales_Lines": ["Month", "CustomerID", "CustomerName", "Industry", "SKU", "Qty", "Value (Rs)"],
    "Customers": ["CustomerID", "CustomerName", "Industry", "Area"],
}
NUMERIC = {
    "Item_Master": ["Master Pack Qty", "Unit Cost (Rs)"],
    "Stock_Aging": ["Qty 0-30 days", "Qty 31-60 days", "Qty 61-90 days", "Qty 91-180 days", "Qty 180+ days"],
    "Sales_Lines": ["Qty", "Value (Rs)"],
}

def norm_text(s):
    if pd.isna(s): return ""
    return re.sub(r"\s+", " ", str(s)).strip()

def norm_sku(s):
    return norm_text(s).upper()

def validate_and_clean(sheets: dict[str, pd.DataFrame]):
    problems=[]
    missing_sheets=[s for s in REQUIRED if s not in sheets]
    if missing_sheets: raise ValueError("Missing required sheets: " + ", ".join(missing_sheets))
    out={}
    for name, required in REQUIRED.items():
        df=sheets[name].copy()
        missing=[c for c in required if c not in df.columns]
        if missing: raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")
        df=df[required].copy()
        for c in df.select_dtypes(include="object").columns:
            df[c]=df[c].map(norm_text)
        if "SKU" in df:
            original=df["SKU"].astype(str)
            normalized=original.map(norm_sku)
            changed=int((original != normalized).sum())
            if changed: problems.append({"Severity":"Info","Problem":f"{changed} SKU values had case/whitespace inconsistencies in {name}","Handling":"Trimmed whitespace and converted SKUs to uppercase.","Source fix":"Enforce a canonical uppercase SKU format in exports."})
            df["SKU"]=normalized
        if name=="Item_Master":
            df["Status"]=df["Status"].str.strip().str.title()
            df["Alternate Flag"]=df["Alternate Flag"].str.upper().replace("", pd.NA)
            df["Alternate Item (name)"]=df["Alternate Item (name)"].replace("", pd.NA)
        if name=="Customers":
            df["CustomerID"]=df["CustomerID"].map(norm_text).str.upper()
        if name=="Sales_Lines":
            df["CustomerID"]=df["CustomerID"].map(norm_text).str.upper()
            df["Month_original"]=df["Month"]
            parsed=pd.to_datetime(df["Month"], format="%b-%Y", errors="coerce")
            parsed2=pd.to_datetime(df["Month"], format="%Y-%m", errors="coerce")
            parsed=parsed.fillna(parsed2)
            bad=parsed.isna()
            if bad.any(): problems.append({"Severity":"Error","Problem":f"{int(bad.sum())} sales rows have unrecognised Month values","Handling":"Rows retained but excluded from six-month period calculations.","Source fix":"Export month in a consistent YYYY-MM format."})
            changed=int((df["Month_original"] != parsed.dt.strftime("%b-%Y")).sum())
            if changed: problems.append({"Severity":"Info","Problem":f"Mixed month formats detected in Sales_Lines ({changed} values normalised)","Handling":"Converted recognised month values to a common month date.","Source fix":"Standardise month format in the source export."})
            df["MonthDate"]=parsed
            df["Month"]=parsed.dt.strftime("%b-%Y")
        for c in NUMERIC.get(name,[]):
            df[c]=pd.to_numeric(df[c], errors="coerce")
            if df[c].isna().any():
                problems.append({"Severity":"Warning","Problem":f"{int(df[c].isna().sum())} missing/non-numeric values in {name}.{c}","Handling":"Retained as missing; affected calculations are flagged and not silently imputed.","Source fix":"Provide valid numeric values in the export."})
        if df.duplicated().any():
            n=int(df.duplicated().sum())
            if name=="Sales_Lines":
                problems.append({"Severity":"Warning","Problem":f"{n} exact duplicate sales rows", "Handling":"Flagged; retained because no transaction ID exists to prove they are accidental duplicates.","Source fix":"Include a unique invoice/line transaction ID and prevent duplicate export rows."})
            else:
                problems.append({"Severity":"Warning","Problem":f"{n} exact duplicate rows in {name}","Handling":"Flagged for review; not automatically removed.","Source fix":"Enforce unique business keys in the source system."})
        out[name]=df
    # Structural checks
    im=out["Item_Master"]; st=out["Stock_Aging"]; sl=out["Sales_Lines"]; cu=out["Customers"]
    for name,df,key in [("Item_Master",im,"SKU"),("Stock_Aging",st,"SKU"),("Customers",cu,"CustomerID")]:
        dup=df[df.duplicated(key,keep=False)]
        if not dup.empty: problems.append({"Severity":"Error","Problem":f"Duplicate {key} values in {name}: {dup[key].nunique()} keys affected","Handling":"Analysis stops for ambiguous master/stock/customer keys; resolve duplicates before relying on results.","Source fix":f"Maintain one authoritative row per {key}."})
    item_skus=set(im.SKU); customer_ids=set(cu.CustomerID)
    orphan_stock=set(st.SKU)-item_skus
    orphan_sales_sku=set(sl.SKU)-item_skus
    orphan_sales_cust=set(sl.CustomerID)-customer_ids
    for label, vals, handling in [
        ("Stock rows reference unknown SKUs",orphan_stock,"Rows retained in quality report; cannot be attributed to an item."),
        ("Sales rows reference unknown SKUs",orphan_sales_sku,"Rows excluded from item-level analysis."),
        ("Sales rows reference unknown customers",orphan_sales_cust,"Rows retained for value totals only where applicable; no customer recommendation profile is created.")]:
        if vals: problems.append({"Severity":"Warning","Problem":f"{label}: {', '.join(sorted(vals))}","Handling":handling,"Source fix":"Use valid master-data keys and reconcile orphan references."})
    if (im["Master Pack Qty"]<=0).fillna(False).any(): problems.append({"Severity":"Error","Problem":"Non-positive or missing master pack quantities","Handling":"Affected item classifications are flagged; confirm pack quantity before use.","Source fix":"Require positive pack quantities."})
    if (im["Unit Cost (Rs)"]<0).fillna(False).any(): problems.append({"Severity":"Warning","Problem":"Negative unit cost found","Handling":"Affected aged value is flagged.","Source fix":"Validate unit cost values in item master."})
    stock_cols=REQUIRED["Stock_Aging"][1:]
    neg=st[st[stock_cols].lt(0).any(axis=1)]
    if not neg.empty: problems.append({"Severity":"Warning","Problem":"Negative stock quantities: "+", ".join(neg.SKU.tolist()),"Handling":"Original signed quantities retained; negative bucket is visible in the audit report and total stock is not silently floored.","Source fix":"Reconcile inventory movements and correct negative age buckets."})
    inactive=im[im.Status.str.lower().eq("inactive")].merge(st,on="SKU",how="left")
    if not inactive.empty:
        q=inactive[stock_cols].fillna(0).sum(axis=1)
        holding=inactive.loc[q.ne(0),"SKU"].tolist()
        if holding: problems.append({"Severity":"Warning","Problem":"Inactive items still hold stock: "+", ".join(holding),"Handling":"Excluded from active analysis; separately reported for disposition.","Source fix":"Review discontinued stock and update inventory/status records."})
    missing_ind=cu[cu.Industry.eq("")]
    if not missing_ind.empty: problems.append({"Severity":"Info","Problem":"Customer industry missing: "+", ".join(missing_ind.CustomerID.tolist()),"Handling":"Such customers are never assigned to Similar Business (Bucket 2).","Source fix":"Complete customer industry master data."})
    # Alternate references are names in the source, so map exact normalized names.
    name_to_sku={norm_text(r["Item Name"]).casefold():r.SKU for _,r in im.iterrows()}
    for _,r in im[im["Alternate Item (name)"].notna()].iterrows():
        alt=norm_text(r["Alternate Item (name)"]).casefold()
        if alt not in name_to_sku:
            problems.append({"Severity":"Warning","Problem":f"Unresolved alternate item name for {r.SKU}: {r['Alternate Item (name)']}","Handling":"No automatic SKU merge performed.","Source fix":"Store alternate SKU rather than free-text item name."})
        elif str(r["Alternate Flag"]).upper()!="SWITCH":
            problems.append({"Severity":"Info","Problem":f"Alternate reference on {r.SKU} without SWITCH flag ({r['Alternate Flag']})","Handling":"Not merged; only explicit SWITCH records are combined.","Source fix":"Confirm whether alternate reference is informational, excluded, or a genuine pack-size switch."})
    return out, problems
