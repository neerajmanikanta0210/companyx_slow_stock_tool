# Company X — Slow Stock Review

A Streamlit application for the Technology & Data Management case study. It reads either the combined workbook or four individual Excel exports, validates the data, applies the supplied stock classification and customer-targeting rules, and exports a multi-sheet Excel report.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Upload format

Upload either:
- One workbook containing `Item_Master`, `Stock_Aging`, `Sales_Lines`, and `Customers`; or
- Four files whose names contain `Item_Master`, `Stock_Aging`, `Sales_Lines`, and `Customers`.

Required columns are defined in `data_cleaning.py`.

## Business-rule implementation

- Only explicit `SWITCH` alternate references are consolidated. Old SKU stock and sales roll into the alternate/new SKU; the new SKU's master pack and unit cost are used.
- Inactive items are excluded from the active item analysis; inactive items holding stock are shown separately.
- Aged quantity = 91–180 day quantity + 180+ day quantity.
- Aged value = aged quantity × reporting SKU unit cost.
- Average monthly sales = six-month sales quantity ÷ 6.
- Months to clear = total stock ÷ average monthly sales; zero sales produces infinity.
- Classification order: Red List (sales quantity < one master pack), then No Action (no aged stock OR months to clear < 3), otherwise Push.
- Only customers with total six-month purchase value strictly greater than ₹1,00,000 are eligible. Bucket priority is Bought before, Similar business, Same category; a customer appears once per Push item.
- Customer purchase values and item history use the six-month sales lines. Similar-business matching uses the customer master industry; blank customer-master industries do not qualify for Bucket 2.

## Data-quality policy

The app normalises whitespace/case for SKU keys and recognised month formats. It flags exact duplicate sales rows but retains them because the provided data has no transaction ID to establish whether repeated lines are accidental. Negative stock quantities are retained and flagged rather than silently changed. Unresolved alternate references are not merged. Master-key duplicates are treated as blocking errors.

## Deploy free with Streamlit Community Cloud

1. Create a GitHub repository and upload `app.py`, `calculations.py`, `data_cleaning.py`, `requirements.txt`, and `README.md`.
2. Do not commit confidential production data or credentials. The supplied case data is synthetic; use it only if appropriate for your submission.
3. Sign in to Streamlit Community Cloud and connect GitHub.
4. Create an app from the repository, selecting `app.py` as the entry point.
5. Deploy, then test the public URL from a private/incognito browser and a phone.
6. Keep the repository and app active for at least 30 days after submission.

## Limitations / points to confirm with the business

- Alternate-item references are free-text names in the source; robust source data should use alternate SKU IDs and explicit effective dates/conversion factors.
- Duplicate sales lines cannot safely be removed without a transaction-line identifier.
- The app follows the case's stated formula and does not convert quantities across different pack sizes. Confirm whether old/new pack units require a conversion factor.
- Negative stock buckets are flagged and retained as supplied; correct the source inventory before operational use.
- The app does not persist uploaded files or historical runs between sessions.
