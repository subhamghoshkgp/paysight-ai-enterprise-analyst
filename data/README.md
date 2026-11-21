# PaySight synthetic payments dataset

[Download the complete dataset as a ZIP (3.4 MiB)](https://github.com/subhamghoshkgp/paysight-ai-enterprise-analyst/raw/refs/heads/main/data/paysight-payments-v2.zip)

PaySight uses simulated payment attempts covering **16 November 2025 through 15 November 2026**. The project’s Python generator created every record, merchant and bank. Pine Labs and its customers supplied no records. The archive contains the three source tables used to build the app’s SQLite snapshot. Extract it to open the CSVs in Excel, pandas or a SQL tool.

| CSV | Rows | Fields and meaning |
|---|---:|---|
| `raw_transactions.csv` | 364,290 | `id` identifies a payment attempt. `day` is an ISO date. `bank_id` and `merchant_id` join to the dimension tables. `method` is the payment method, `status` is SUCCESS, FAILED or PENDING, `paise` is the amount in integer paise (100 paise = ₹1), and `reason` is the recorded failure reason. |
| `merchants.csv` | 48 | `id`, `name`, `category`, `region`. Region describes the merchant’s location. |
| `banks.csv` | 4 | `id`, `name`. Bank names are fictional. |

Payments use UPI, Credit Card, Debit Card, Net Banking or Wallet. The file preserves ingestion order, so use the `day` column to sort by date. For example, attempt 1 is a successful Wallet payment of ₹1,034.42 on 5 October 2026. Its `bank_id` of 0 maps to Meridian and its `merchant_id` of 6 maps to Merchant 07.

## How the app counts attempts

1. Keep the first occurrence of each transaction `id`. The raw CSV includes 24 duplicate copies, leaving **364,266 unique attempts**.
2. Exclude **5,498 pending attempts** when computing success or failure rates. The denominator across the full year is **358,768 eligible attempts**.
3. Count each eligible SUCCESS in the numerator. Blank reasons are expected for successful and pending payments. Among failures, **15** have a blank reason. They still count as failures and appear under **Unknown** in the reason breakdown.

After extracting the ZIP, run this from the folder containing the CSVs to reproduce the two demo weeks:

```python
import pandas as pd

raw = pd.read_csv("raw_transactions.csv")
attempts = raw.drop_duplicates("id", keep="first")
eligible = attempts[attempts["status"].isin(["SUCCESS", "FAILED"])]

for start, end in [("2026-11-02", "2026-11-08"), ("2026-11-09", "2026-11-15")]:
    week = eligible[eligible["day"].between(start, end)]
    successes = week["status"].eq("SUCCESS").sum()
    print(start, end, successes, len(week), f"{100 * successes / len(week):.2f}%")
```

| Window | Successful | Eligible | Success rate |
|---|---:|---:|---:|
| 2–8 Nov 2026 | 6,354 | 6,744 | 94.22% |
| 9–15 Nov 2026 | 6,044 | 6,980 | 86.59% |

## How the dataset was created

The final week intentionally has more UPI traffic and a higher simulated failure probability at Northstar. These choices give reviewers a known change in transaction mix and a separate within-segment change to investigate. The original six weeks use seed 412 and the earlier history uses seed 413. The data contains payment attempts and dimensions only. [Generator and SQLite schema](../paysight/data.py)

Run `python -m paysight.export_data` from the repository root to build the snapshot if needed and export the three source tables. The app derives its deduplicated attempts and eligible analysis view from these tables. [Export code](../paysight/export_data.py)

Published ZIP SHA-256: `c7046a82746900fdd38c59487d832ba8f7f8bf2fc5ede322a9928768a230a8da`
