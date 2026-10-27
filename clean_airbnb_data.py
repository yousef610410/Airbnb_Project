"""
Clean the scraped Airbnb data  (step after airbnb_scraper.py)
=============================================================
Input : scraped_data/Airbnb_Scraped_Data.csv
Output: scraped_data/Airbnb_Clean_All.csv     (every row + quality flags, nothing deleted except duplicates)
        scraped_data/Airbnb_Clean_Final.csv   (rows that satisfy the project rules -> use this for the EDA)
 
Usage:  python clean_airbnb_data.py
        python clean_airbnb_data.py --input scraped_data/Airbnb_Scraped_Data.csv
"""
 
import argparse
import os
from datetime import date
from urllib.parse import urlparse, parse_qs
 
import numpy as np
import pandas as pd
 
REQ_CHECKIN = "2026-12-04"     # the stay we asked for in the scraper
REQ_CHECKOUT = "2026-12-07"
REQ_BEDROOMS = 2
 
 
def stay_from_url(url):
    """Airbnb sometimes shows other dates when ours are not available.
    The real dates are inside the listing URL."""
    try:
        q = parse_qs(urlparse(url).query)
        return q.get("check_in", [None])[0], q.get("check_out", [None])[0]
    except Exception:
        return None, None
 
 
def nights_between(ci, co):
    try:
        return (date.fromisoformat(co) - date.fromisoformat(ci)).days
    except Exception:
        return np.nan
 
 
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=os.path.join("scraped_data", "Airbnb_Scraped_Data.csv"))
    ap.add_argument("--outdir", default="scraped_data")
    args = ap.parse_args()
 
    df = pd.read_csv(args.input, dtype={"room_id": str})
    n0 = len(df)
    print(f"Rows read: {n0}")
 
    # 1) duplicates
    df = df.drop_duplicates(subset="room_id").copy()
    print(f"Duplicates removed: {n0 - len(df)}")
 
    # 2) real stay dates + nights (fixes Price_per_night for listings shown with other dates)
    stay = df["URL"].apply(stay_from_url)
    df["Check_in"] = stay.apply(lambda t: t[0])
    df["Check_out"] = stay.apply(lambda t: t[1])
    df["Nights"] = [nights_between(a, b) for a, b in zip(df["Check_in"], df["Check_out"])]
    df["Dates_match"] = (df["Check_in"] == REQ_CHECKIN) & (df["Check_out"] == REQ_CHECKOUT)
 
    # 3) prices (Price_value is the TOTAL for the stay shown in the URL, in EUR)
    df["Price_total"] = pd.to_numeric(df["Price_value"], errors="coerce")
    df["Price_per_night"] = (df["Price_total"] / df["Nights"]).round(2)
    df = df.drop(columns=["Price_value"], errors="ignore")
 
    # 4) rating / reviews
    df["Rating"] = pd.to_numeric(df["Rating"], errors="coerce")        # 'New' / 'N/A' -> NaN
    df["Is_new_listing"] = df["Reviews"].fillna(0).astype(float).eq(0)
    df.loc[(df["Rating"] > 5) | (df["Rating"] < 1), "Rating"] = np.nan  # impossible values = parse errors
    df["Reviews"] = pd.to_numeric(df["Reviews"], errors="coerce").fillna(0).astype(int)
 
    # 5) yes/no columns -> 1/0
    df["Superhost"] = df["Superhost"].map({"Yes": 1, "No": 0}).astype("Int64")
    df["is_fav"] = pd.to_numeric(df["is_fav"], errors="coerce").astype("Int64")
 
    # 6) quality flags
    df["Bedrooms_ok"] = df["Bedrooms_found"].eq(REQ_BEDROOMS)
    df["Bedrooms_unknown"] = df["Bedrooms_found"].isna()
    df["Suspect_rating_reviews"] = (
        (df["Reviews"] > 5000) | ((df["Rating"] < 3) & (df["Reviews"] > 100))
    )
    q1 = df.groupby("city")["Price_per_night"].transform(lambda s: s.quantile(0.25))
    q3 = df.groupby("city")["Price_per_night"].transform(lambda s: s.quantile(0.75))
    iqr = q3 - q1
    df["Price_outlier"] = (df["Price_per_night"] > q3 + 1.5 * iqr) | (df["Price_per_night"] < q1 - 1.5 * iqr)
 
    cols = ["room_id", "Name", "city", "Price_total", "Nights", "Price_per_night", "Currency",
            "Superhost", "is_fav", "Rating", "Reviews", "Is_new_listing", "Bedrooms_found",
            "Min_stay_flag", "Check_in", "Check_out", "Dates_match", "Bedrooms_ok",
            "Bedrooms_unknown", "Suspect_rating_reviews", "Price_outlier", "URL", "scraped_at"]
    df = df[[c for c in cols if c in df.columns]]
 
    os.makedirs(args.outdir, exist_ok=True)
    all_path = os.path.join(args.outdir, "Airbnb_Clean_All.csv")
    df.to_csv(all_path, index=False)
 
    # 7) final dataset: the project rules (same stay, exactly 2 bedrooms, no suspicious values)
    final = df[df["Dates_match"] & df["Bedrooms_ok"] & ~df["Suspect_rating_reviews"]
               & df["Price_per_night"].notna()].copy()
    final_path = os.path.join(args.outdir, "Airbnb_Clean_Final.csv")
    final.to_csv(final_path, index=False)
 
    # ---- report
    print("\n=== Quality report ===")
    print(f"Rows after de-duplication : {len(df)}")
    print(f"Different dates than asked: {(~df['Dates_match']).sum()}")
    print(f"Bedrooms unknown          : {df['Bedrooms_unknown'].sum()}")
    print(f"Bedrooms != {REQ_BEDROOMS}           : {(~df['Bedrooms_ok'] & ~df['Bedrooms_unknown']).sum()}")
    print(f"Suspect rating/reviews    : {df['Suspect_rating_reviews'].sum()}")
    print(f"Listings without rating   : {df['Rating'].isna().sum()}")
    print(f"Price outliers (flag only): {df['Price_outlier'].sum()}")
    print(f"Min-stay flagged          : {int((df['Min_stay_flag'] == 1).sum())}")
    print(f"\nFINAL rows: {len(final)}  -> {final_path}")
    summary = pd.DataFrame({
        "all_rows": df.groupby("city").size(),
        "final_rows": final.groupby("city").size(),
        "median_price_per_night": final.groupby("city")["Price_per_night"].median().round(1),
        "superhost_%": (final.groupby("city")["Superhost"].mean() * 100).round(0),
    }).fillna(0)
    print("\n" + summary.to_string())
    print(f"\nAll rows with flags saved -> {all_path}")
 
 
if __name__ == "__main__":
    main()
 