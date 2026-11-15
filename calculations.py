"""Business-rule calculations for the Company X slow-stock review."""
from __future__ import annotations
import pandas as pd
import numpy as np
from data_cleaning import norm_text

STOCK_COLS=["Qty 0-30 days","Qty 31-60 days","Qty 61-90 days","Qty 91-180 days","Qty 180+ days"]

def build_switch_map(items: pd.DataFrame):
    name_to_sku={norm_text(r["Item Name"]).casefold():r.SKU for _,r in items.iterrows()}
    old_to_new={}
    for _,r in items.iterrows():
        if str(r["Alternate Flag"]).upper()=="SWITCH" and pd.notna(r["Alternate Item (name)"]):
            target=name_to_sku.get(norm_text(r["Alternate Item (name)"]).casefold())
            if target:
                if target==r.SKU: raise ValueError(f"Switch for {r.SKU} points to itself")
                if target in old_to_new: raise ValueError(f"Multiple switch sources point to {target}; resolve master data")
                old_to_new[r.SKU]=target
    # Resolve chains; detect cycles.
    def canonical(sku):
        seen=set(); cur=sku
        while cur in old_to_new:
            if cur in seen: raise ValueError(f"Cycle in SWITCH mapping involving {sku}")
            seen.add(cur); cur=old_to_new[cur]
        return cur
    return {sku:canonical(sku) for sku in items.SKU}, old_to_new

def run_analysis(sheets: dict[str,pd.DataFrame]):
    items=sheets["Item_Master"].copy(); stock=sheets["Stock_Aging"].copy(); sales=sheets["Sales_Lines"].copy(); customers=sheets["Customers"].copy()
    # Only the six months specified by the case are included.
    if "MonthDate" in sales:
        sales=sales[sales.MonthDate.between(pd.Timestamp("2026-04-01"),pd.Timestamp("2026-09-30"))].copy()
    canonical, old_to_new=build_switch_map(items)
    items["Canonical SKU"]=items.SKU.map(canonical)
    stock["Canonical SKU"]=stock.SKU.map(canonical).fillna(stock.SKU)
    sales["Canonical SKU"]=sales.SKU.map(canonical).fillna(sales.SKU)
    # Aggregate stock age buckets and sales quantities/value to the replacement SKU.
    stock_agg=stock.groupby("Canonical SKU",dropna=False)[STOCK_COLS].sum(min_count=1).reset_index()
    sales_agg=sales.groupby("Canonical SKU").agg(**{"Total Sales Qty":("Qty","sum"),"Item Sales Value":("Value (Rs)","sum")}).reset_index()
    active=items[items.Status.str.lower().eq("active")].copy()
    # Keep only canonical/new rows for switch groups; all standalone active rows remain.
    active=active[active.SKU.eq(active["Canonical SKU"])].drop(columns=["Canonical SKU"]).copy()
    result=active.merge(stock_agg,left_on="SKU",right_on="Canonical SKU",how="left").drop(columns=["Canonical SKU"],errors="ignore")
    result=result.merge(sales_agg,left_on="SKU",right_on="Canonical SKU",how="left").drop(columns=["Canonical SKU"],errors="ignore")
    for c in STOCK_COLS+ ["Total Sales Qty","Item Sales Value"]: result[c]=result[c].fillna(0)
    result["Total Stock"]=result[STOCK_COLS].sum(axis=1)
    result["Aged Qty"]=result["Qty 91-180 days"]+result["Qty 180+ days"]
    result["Aged Value"]=result["Aged Qty"]*result["Unit Cost (Rs)"]
    result["Average Monthly Sales"]=result["Total Sales Qty"]/6
    result["Months to Clear"]=np.where(result["Average Monthly Sales"]>0,result["Total Stock"]/result["Average Monthly Sales"],np.inf)
    result["Classification"]=np.select(
        [result["Total Sales Qty"]<result["Master Pack Qty"],(result["Aged Qty"]==0)|(result["Months to Clear"]<3)],
        ["Red List","No Action"],default="Push")
    # customer-level six-month total purchase value; item buying history uses canonical SKU.
    cust_sales=sales.groupby("CustomerID").agg(**{"Customer Purchase Value":("Value (Rs)","sum"),"Customer Sales Qty":("Qty","sum")}).reset_index()
    cust_profile=customers.merge(cust_sales,on="CustomerID",how="left")
    cust_profile[["Customer Purchase Value","Customer Sales Qty"]]=cust_profile[["Customer Purchase Value","Customer Sales Qty"]].fillna(0)
    # Buyer industries for each canonical item, based on customer master (not free-text line industry).
    sales_c=sales.merge(customers[["CustomerID","Industry"]],on="CustomerID",how="left",suffixes=("_line","_master"))
    sales_c["Resolved Industry"]=sales_c["Industry_master"].replace("",pd.NA).fillna(sales_c["Industry_line"].replace("",pd.NA))
    sales_c["Resolved Industry"]=sales_c["Resolved Industry"].fillna("")
    # A missing customer-master industry is not eligible to define a similar-business industry.
    sales_c=sales_c.merge(customers[["CustomerID","Industry"]].rename(columns={"Industry":"Master Industry"}),on="CustomerID",how="left")
    sales_c["Resolved Industry"]=sales_c["Master Industry"].replace("",pd.NA).fillna("")
    # Canonical sales customer sets and category purchase sets.
    customer_item=set(zip(sales_c.CustomerID,sales_c["Canonical SKU"]))
    buyer_industries={}
    for sku,g in sales_c.groupby("Canonical SKU"):
        buyer_industries[sku]={x for x in g["Resolved Industry"].unique() if x}
    category_by_sku=active.set_index("SKU")["Category"].to_dict()
    cat_customers={}
    for sku,cat in category_by_sku.items():
        bought=set(sales_c.loc[sales_c["Canonical SKU"].eq(sku),"CustomerID"])
        cat_customers[cat]=cat_customers.get(cat,set()) | bought
    targets=[]
    eligible=cust_profile[cust_profile["Customer Purchase Value"]>100000].copy()
    for _,item in result[result.Classification.eq("Push")].iterrows():
        sku=item.SKU; cat=item.Category
        # Bucket 1 includes all old switch partner SKUs through canonical mapping.
        buyers={cid for cid,cs in customer_item if cs==sku}
        industries=buyer_industries.get(sku,set())
        category_buyers=cat_customers.get(cat,set())
        for _,c in eligible.iterrows():
            cid=c.CustomerID
            if cid in buyers: bucket=1; label="Bought before"
            elif c.Industry and c.Industry in industries: bucket=2; label="Similar business"
            elif cid in category_buyers: bucket=3; label="Same category"
            else: continue
            targets.append({"SKU":sku,"Item Name":item["Item Name"],"CustomerID":cid,"CustomerName":c.CustomerName,"Industry":c.Industry,"Area":c.Area,"Customer Purchase Value":c["Customer Purchase Value"],"Bucket":bucket,"Bucket Name":label})
    target_df=pd.DataFrame(targets,columns=["SKU","Item Name","CustomerID","CustomerName","Industry","Area","Customer Purchase Value","Bucket","Bucket Name"])
    if not target_df.empty: target_df=target_df.sort_values(["SKU","Bucket","Customer Purchase Value"],ascending=[True,True,False]).reset_index(drop=True)
    # Inactive items holding stock are explicitly reported, not included in analysis.
    inactive=items[items.Status.str.lower().eq("inactive")].merge(stock,on="SKU",how="left")
    if not inactive.empty:
        inactive["Total Stock"] = inactive[STOCK_COLS].fillna(0).sum(axis=1)
        inactive=inactive[inactive["Total Stock"]!=0]
    else: inactive["Total Stock"]=pd.Series(dtype=float)
    summary=result.groupby("Classification").size().reindex(["Red List","No Action","Push"],fill_value=0).rename("Items").reset_index()
    push_value=float(result.loc[result.Classification.eq("Push"),"Aged Value"].sum())
    top10=result[result.Classification.eq("Push")].nlargest(10,"Aged Value")[["SKU","Item Name","Category","Aged Qty","Aged Value","Total Stock","Total Sales Qty","Months to Clear"]]
    return {"items":result,"targets":target_df,"customer_profile":cust_profile,"summary":summary,"push_aged_value":push_value,"top10":top10,"inactive_stock":inactive,"switch_map":old_to_new}
