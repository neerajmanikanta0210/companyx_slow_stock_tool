"""Smoke tests against the synthetic case-study workbook.
Run: python test_calculations.py
"""
import pandas as pd
from data_cleaning import validate_and_clean
from calculations import run_analysis

path='sample_data/Case_Data_Technology_and_Data_Management_All_Sheets.xlsx'
sheets={name:pd.read_excel(path,sheet_name=name) for name in ['Item_Master','Stock_Aging','Sales_Lines','Customers']}
clean,problems=validate_and_clean(sheets)
r=run_analysis(clean)
counts=r['summary'].set_index('Classification')['Items'].to_dict()
assert counts == {'Red List':7,'No Action':13,'Push':18}, counts
assert r['push_aged_value'] == 163841.0, r['push_aged_value']
items=r['items'].set_index('SKU')
assert items.loc['SKU1001','Classification']=='No Action'
assert items.loc['SKU1006','Classification']=='Push'
assert items.loc['SKU1019','Classification']=='Push'
t=r['targets'].query("SKU == 'SKU1005'").head(3)
assert t.CustomerID.tolist()==['C220','C224','C214'], t.CustomerID.tolist()
assert t.Bucket.tolist()==[1,1,2], t.Bucket.tolist()
print('PASS: classification counts, Push aged value, specified SKU classes, and SKU1005 top-three targets.')
