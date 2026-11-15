from __future__ import annotations
import io
import pandas as pd
import streamlit as st
import plotly.express as px
from data_cleaning import validate_and_clean, REQUIRED
from calculations import run_analysis

st.set_page_config(page_title="Company X | Slow Stock Review", page_icon="📦", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.6rem;padding-bottom:2rem;max-width:1500px}
[data-testid="stMetric"]{background:var(--secondary-background);padding:14px 16px;border-radius:12px}
.small-note{color:var(--text-color);opacity:.72;font-size:.88rem}
</style>""",unsafe_allow_html=True)

st.title("📦 Company X — Slow Stock Review")
st.caption("Monthly inventory intelligence · Upload the exports, validate the data, and generate a sales action list")

with st.sidebar:
    st.header("Monthly review")
    st.write("Upload either the combined workbook or all four individual Excel exports.")
    uploads=st.file_uploader("Excel file(s)",type=["xlsx","xls"],accept_multiple_files=True)
    run=st.button("Run review",type="primary",use_container_width=True,disabled=not uploads)
    st.divider()
    st.caption("Review period: April–September 2026")
    st.caption("Classification and targeting follow the supplied case-study rules.")

@st.cache_data(show_spinner=False)
def read_uploads(files):
    by_name={f.name.lower():f for f in files}
    # Combined workbook: identify by presence of all required sheet names.
    for f in files:
        xls=pd.ExcelFile(f)
        if all(s in xls.sheet_names for s in REQUIRED):
            return {s:pd.read_excel(f,sheet_name=s) for s in REQUIRED}, f"Combined workbook: {f.name}"
    aliases={
        "item_master":["item_master"],"stock_aging":["stock_aging"],
        "sales_lines":["sales_lines"],"customers":["customers"]}
    found={}
    for key,names in aliases.items():
        match=next((f for f in files if any(n in f.name.lower() for n in names)),None)
        if match: found[key]=pd.read_excel(match)
    if len(found)!=4:
        missing=[x for x in aliases if x not in found]
        raise ValueError("Upload one combined workbook or all four individual files. Missing: "+", ".join(missing))
    return {"Item_Master":found["item_master"],"Stock_Aging":found["stock_aging"],"Sales_Lines":found["sales_lines"],"Customers":found["customers"]}, "Four individual files"

def make_excel(result, problems):
    output=io.BytesIO()
    with pd.ExcelWriter(output,engine="openpyxl") as writer:
        result["summary"].to_excel(writer,index=False,sheet_name="Summary")
        result["items"].to_excel(writer,index=False,sheet_name="Item Analysis")
        result["items"].query("Classification == 'Red List'").to_excel(writer,index=False,sheet_name="Red List")
        result["items"].query("Classification == 'Push'").to_excel(writer,index=False,sheet_name="Push Items")
        result["targets"].to_excel(writer,index=False,sheet_name="Customer Targets")
        pd.DataFrame(problems,columns=["Severity","Problem","Handling","Source fix"]).to_excel(writer,index=False,sheet_name="Data Quality")
        result["inactive_stock"].to_excel(writer,index=False,sheet_name="Inactive Stock")
        result["top10"].to_excel(writer,index=False,sheet_name="Top 10 Push")
    output.seek(0); return output

if run:
    try:
        with st.spinner("Reading and validating the files…"):
            raw,source=read_uploads(uploads)
            cleaned,problems=validate_and_clean(raw)
            if any(p["Severity"]=="Error" and "Duplicate" in p["Problem"] for p in problems):
                st.error("Duplicate master/stock/customer keys make the analysis ambiguous. Correct the source files and upload again.")
                st.stop()
            result=run_analysis(cleaned)
            st.session_state["review"]={"result":result,"problems":problems,"source":source}
    except Exception as e:
        st.error(f"Could not run the review: {e}")
        st.stop()

if "review" not in st.session_state:
    st.info("👈 Upload the combined workbook or all four individual files, then select **Run review**.")
    st.markdown("**Expected inputs:** Item_Master, Stock_Aging, Sales_Lines and Customers. The application checks the required columns before calculating.")
    st.stop()

review=st.session_state["review"]; r=review["result"]; problems=review["problems"]
st.success(f"Review completed · {review['source']} · {len(r['items'])} active reporting items")

tabs=st.tabs(["Executive Summary","Item Analysis","Customer Targets","Data Quality","Export"])
with tabs[0]:
    counts=r["summary"].set_index("Classification")["Items"].to_dict()
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Active reporting items",f"{len(r['items']):,}")
    c2.metric("Red List",f"{counts.get('Red List',0):,}")
    c3.metric("No Action",f"{counts.get('No Action',0):,}")
    c4.metric("Push",f"{counts.get('Push',0):,}")
    st.metric("Total aged value in Push items",f"₹{r['push_aged_value']:,.0f}")
    left,right=st.columns([1,1.4])
    with left:
        fig=px.pie(r["summary"],names="Classification",values="Items",hole=.55,title="Items by classification")
        st.plotly_chart(fig,use_container_width=True)
    with right:
        st.subheader("Top 10 Push items by aged value")
        top=r["top10"].copy()
        if not top.empty:
            top["Aged Value"]=top["Aged Value"].map(lambda x:f"₹{x:,.0f}")
            st.dataframe(top,use_container_width=True,hide_index=True)
        else: st.info("No Push items found.")
    if not r["inactive_stock"].empty:
        st.warning("Inactive items still holding stock: "+", ".join(r["inactive_stock"].SKU.tolist()))
with tabs[1]:
    st.subheader("Item-level review")
    a,b=st.columns(2)
    classes=["All"]+r["items"].Classification.dropna().drop_duplicates().tolist()
    cats=["All"]+sorted(r["items"].Category.dropna().unique().tolist())
    cl=a.selectbox("Classification",classes)
    cat=b.selectbox("Category",cats)
    view=r["items"].copy()
    if cl!="All": view=view[view.Classification.eq(cl)]
    if cat!="All": view=view[view.Category.eq(cat)]
    st.caption(f"Showing {len(view)} items")
    st.dataframe(view[["SKU","Item Name","Category","Master Pack Qty","Total Stock","Aged Qty","Unit Cost (Rs)","Aged Value","Total Sales Qty","Average Monthly Sales","Months to Clear","Classification"]],use_container_width=True,hide_index=True)
with tabs[2]:
    st.subheader("Customer call list")
    push_skus=r["items"].loc[r["items"].Classification.eq("Push"),"SKU"].tolist()
    if not push_skus: st.info("No Push items to target.")
    else:
        selected=st.selectbox("Select a Push item",push_skus,format_func=lambda x:f"{x} — "+str(r["items"].set_index("SKU").loc[x,"Item Name"]))
        item=r["items"].set_index("SKU").loc[selected]
        x,y,z=st.columns(3); x.metric("Aged quantity",f"{item['Aged Qty']:,.0f}"); y.metric("Aged value",f"₹{item['Aged Value']:,.0f}"); z.metric("Months to clear", "∞" if pd.isna(item["Months to Clear"]) or item["Months to Clear"]==float("inf") else f"{item['Months to Clear']:.2f}")
        targets=r["targets"].query("SKU == @selected").copy()
        if targets.empty: st.info("No eligible customers matched the targeting rules (purchase value must be greater than ₹1,00,000).")
        else:
            targets.insert(0,"Call Priority",range(1,len(targets)+1))
            targets["Customer Purchase Value"]=targets["Customer Purchase Value"].map(lambda x:f"₹{x:,.0f}")
            st.dataframe(targets[["Call Priority","CustomerName","CustomerID","Industry","Area","Customer Purchase Value","Bucket","Bucket Name"]],use_container_width=True,hide_index=True)
            st.download_button("Download this call list (CSV)",targets.to_csv(index=False).encode("utf-8-sig"),file_name=f"{selected}_customer_targets.csv",mime="text/csv")
with tabs[3]:
    st.subheader("Data quality and handling log")
    if problems:
        pdf=pd.DataFrame(problems)
        st.caption(f"{len(pdf)} data-quality observations")
        st.dataframe(pdf,use_container_width=True,hide_index=True)
    else: st.success("No data-quality issues detected by the configured checks.")
    if not r["inactive_stock"].empty:
        st.subheader("Inactive items excluded but holding stock")
        st.dataframe(r["inactive_stock"][["SKU","Item Name","Status","Total Stock"]],use_container_width=True,hide_index=True)
with tabs[4]:
    st.subheader("Download complete review")
    st.write("The workbook includes summary, item analysis, Red List, Push items, customer targets, data quality, inactive stock and top 10 Push items.")
    st.download_button("⬇ Download Excel report",make_excel(r,problems),file_name="CompanyX_Slow_Stock_Review.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",type="primary")
    st.caption("Keep the original uploaded exports unchanged. The report records the review calculations and data-quality observations.")

st.divider()
st.caption("Company X · Management Trainee Case Study · Synthetic illustrative data")
