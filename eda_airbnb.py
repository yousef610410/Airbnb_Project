"""
EDA - Airbnb prices in European cities
======================================
Input : scraped_data/Airbnb_Clean_Final.csv   (output of clean_airbnb_data.py)
Output: eda_output/*.png          charts
        eda_output/*.csv          summary tables
        eda_output/EDA_report.md  findings written automatically from the numbers

Usage:
    pip install pandas matplotlib scipy
    python eda_airbnb.py
"""
    
import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 10})
C1, C2, C3 = "#2E86AB", "#E4572E", "#9AA5B1"


# ----------------------------------------------------------------------------- helpers
def spearman(x, y):
    m = x.notna() & y.notna()
    if m.sum() < 5:
        return np.nan, np.nan, int(m.sum())
    r, p = stats.spearmanr(x[m], y[m])
    return r, p, int(m.sum())


def strength(r):
    a = abs(r)
    return "negligible" if a < 0.1 else "weak" if a < 0.3 else "moderate" if a < 0.5 else "strong"


def mannwhitney(a, b):
    if len(a) < 3 or len(b) < 3:
        return np.nan
    return stats.mannwhitneyu(a, b, alternative="two-sided").pvalue


def fmt_p(p):
    return "n/a" if pd.isna(p) else ("<0.001" if p < 0.001 else f"{p:.3f}")


def save(fig, outdir, name):
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, name), bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=os.path.join("scraped_data", "Airbnb_Clean_Final.csv"))
    ap.add_argument("--outdir", default="eda_output")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    df = pd.read_csv(args.input, dtype={"room_id": str})
    df["Reviews_log"] = np.log1p(df["Reviews"])
    df["city_median"] = df.groupby("city")["Price_per_night"].transform("median")
    df["Price_rel"] = df["Price_per_night"] / df["city_median"]      # 1.0 = typical for its city
    n = len(df)

    order = df.groupby("city")["Price_per_night"].median().sort_values().index.tolist()
    rep = []   # report lines
    rep.append("# EDA report - Airbnb prices in 10 European cities\n")
    rep.append(f"Dataset: **{n} listings**, entire homes with exactly 2 bedrooms, same 3-night stay "
               f"(prices are the total for the stay including fees, converted to EUR per night).\n")

    # 1) city summary -----------------------------------------------------------------
    g = df.groupby("city")["Price_per_night"]
    city_sum = pd.DataFrame({
        "listings": g.size(), "median": g.median().round(1), "mean": g.mean().round(1),
        "q1": g.quantile(.25).round(1), "q3": g.quantile(.75).round(1),
        "min": g.min().round(1), "max": g.max().round(1),
    }).loc[order[::-1]]
    city_sum.to_csv(os.path.join(args.outdir, "city_summary.csv"))

    groups = [df.loc[df.city == c, "Price_per_night"] for c in order if (df.city == c).sum() >= 3]
    kw_p = stats.kruskal(*groups).pvalue if len(groups) > 1 else np.nan
    sst = ((df["Price_per_night"] - df["Price_per_night"].mean()) ** 2).sum()
    city_mean = df.groupby("city")["Price_per_night"].transform("mean")
    sse = ((df["Price_per_night"] - city_mean) ** 2).sum()
    r2_city = 1 - sse / sst

    cheap, dear = order[0], order[-1]
    rep.append("## 1. Prices by city\n")
    rep.append(f"- Cheapest city (median): **{cheap}** at EUR {city_sum.loc[cheap, 'median']}/night; "
               f"most expensive: **{dear}** at EUR {city_sum.loc[dear, 'median']}/night "
               f"({city_sum.loc[dear, 'median'] / city_sum.loc[cheap, 'median']:.1f}x).")
    rep.append(f"- Differences between cities are statistically significant (Kruskal-Wallis p {fmt_p(kw_p)}).")
    rep.append(f"- **City alone explains about {r2_city * 100:.0f}% of the variation in price** "
               f"(share of variance explained by city averages).")
    rep.append("- The median is used instead of the mean because prices are right-skewed (a few luxury listings).\n")

    # chart 1: boxplot
    fig, ax = plt.subplots(figsize=(9, 5))
    data = [df.loc[df.city == c, "Price_per_night"] for c in order]
    bp = ax.boxplot(data, patch_artist=True, medianprops=dict(color="black"))
    for b in bp["boxes"]:
        b.set_facecolor(C1); b.set_alpha(.6)
    ax.set_xticks(range(1, len(order) + 1)); ax.set_xticklabels(order, rotation=30)
    ax.set_ylabel("Price per night (EUR)"); ax.set_title("Price per night by city (sorted by median)")
    save(fig, args.outdir, "01_price_by_city_boxplot.png")

    # chart 2: median bars
    fig, ax = plt.subplots(figsize=(9, 5))
    meds = city_sum.loc[order, "median"]
    bars = ax.bar(order, meds, color=C1)
    for b, c in zip(bars, order):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 3, f"n={city_sum.loc[c, 'listings']}",
                ha="center", fontsize=8)
    ax.set_ylabel("Median price per night (EUR)"); ax.set_title("Median price per night by city")
    plt.setp(ax.get_xticklabels(), rotation=30)
    save(fig, args.outdir, "02_median_price_by_city.png")

    # 2) Superhost & Guest favorite ------------------------------------------------------
    rows = []
    rep.append("## 2. Do host status and Guest Favorite badge change the price?\n")
    rep.append("Prices are compared **within each city** (price divided by the city median, 1.00 = typical), "
               "so a badge is not rewarded just for being common in an expensive city.\n")
    for col, label in (("Superhost", "Superhost"), ("is_fav", "Guest Favorite")):
        a, b = df[df[col] == 1], df[df[col] == 0]
        p = mannwhitney(a["Price_rel"], b["Price_rel"])
        rows.append({"feature": label, "yes_n": len(a), "no_n": len(b),
                     "yes_median_eur": round(a["Price_per_night"].median(), 1),
                     "no_median_eur": round(b["Price_per_night"].median(), 1),
                     "yes_rel_median": round(a["Price_rel"].median(), 3),
                     "no_rel_median": round(b["Price_rel"].median(), 3), "p_value": p})
        diff = (a["Price_rel"].median() / b["Price_rel"].median() - 1) * 100
        sig = "statistically significant" if (not pd.isna(p) and p < 0.05) else "not statistically significant"
        rep.append(f"- **{label}**: {len(a)} yes / {len(b)} no. Typical price is "
                   f"{diff:+.1f}% for {label} listings after adjusting for city "
                   f"(Mann-Whitney p {fmt_p(p)}, {sig}).")
    pd.DataFrame(rows).to_csv(os.path.join(args.outdir, "badge_comparison.csv"), index=False)
    rep.append("")

    for col, label, fname in (("Superhost", "Superhost", "03_superhost_price_by_city.png"),
                              ("is_fav", "Guest Favorite", "04_guest_favorite_price_by_city.png")):
        pv = df.pivot_table(index="city", columns=col, values="Price_per_night", aggfunc="median").reindex(order)
        fig, ax = plt.subplots(figsize=(9, 5))
        x = np.arange(len(order)); w = .38
        ax.bar(x - w / 2, pv.get(0, pd.Series(index=order, dtype=float)), w, label=f"Not {label}", color=C3)
        ax.bar(x + w / 2, pv.get(1, pd.Series(index=order, dtype=float)), w, label=label, color=C2)
        ax.set_xticks(x); ax.set_xticklabels(order, rotation=30)
        ax.set_ylabel("Median price per night (EUR)"); ax.set_title(f"{label} vs not, by city")
        ax.legend()
        save(fig, args.outdir, fname)

    # 3) Rating & reviews --------------------------------------------------------------
    rep.append("## 3. Are price and the other features correlated?\n")
    rated = df[df["Rating"].notna()]
    est = rated[rated["Reviews"] >= 10]
    corr_rows = []
    for name, sub, xcol in (("Rating (all rated listings)", rated, "Rating"),
                            ("Rating (listings with 10+ reviews)", est, "Rating"),
                            ("Number of reviews (log)", df, "Reviews_log")):
        r_raw, p_raw, n_raw = spearman(sub["Price_per_night"], sub[xcol])
        r_rel, p_rel, n_rel = spearman(sub["Price_rel"], sub[xcol])
        corr_rows.append({"feature": name, "n": n_raw, "spearman_vs_price": round(r_raw, 3),
                          "p_raw": p_raw, "spearman_vs_price_within_city": round(r_rel, 3), "p_within_city": p_rel})
        rep.append(f"- **{name}** (n={n_raw}): Spearman rho = {r_raw:+.2f} ({strength(r_raw)}, p {fmt_p(p_raw)}); "
                   f"within city rho = {r_rel:+.2f} ({strength(r_rel)}, p {fmt_p(p_rel)}).")
    pd.DataFrame(corr_rows).to_csv(os.path.join(args.outdir, "correlations.csv"), index=False)

    # chart: rating vs price (within city)
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.scatter(est["Rating"], est["Price_rel"], alpha=.55, color=C1, s=22)
    ax.axhline(1, color="grey", lw=.8, ls="--")
    ax.set_xlabel("Rating"); ax.set_ylabel("Price relative to city median (1.0 = typical)")
    ax.set_title("Rating vs price (listings with 10+ reviews)")
    save(fig, args.outdir, "05_rating_vs_price.png")

    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.scatter(df["Reviews"] + 1, df["Price_rel"], alpha=.55, color=C2, s=22)
    ax.set_xscale("log"); ax.axhline(1, color="grey", lw=.8, ls="--")
    ax.set_xlabel("Number of reviews + 1 (log scale)"); ax.set_ylabel("Price relative to city median")
    ax.set_title("Number of reviews vs price")
    save(fig, args.outdir, "06_reviews_vs_price.png")

    # heatmap
    cols = ["Price_per_night", "Price_rel", "Rating", "Reviews_log", "Superhost", "is_fav", "Min_stay_flag"]
    cm = df[cols].astype(float).corr(method="spearman")
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols, rotation=45, ha="right")
    ax.set_yticks(range(len(cols))); ax.set_yticklabels(cols)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{cm.iloc[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=.8); ax.set_title("Spearman correlation matrix")
    save(fig, args.outdir, "07_correlation_heatmap.png")
    cm.round(3).to_csv(os.path.join(args.outdir, "correlation_matrix.csv"))

    all_weak = all(abs(r["spearman_vs_price_within_city"]) < 0.3 for r in corr_rows if not pd.isna(r["spearman_vs_price_within_city"]))
    rep.append("")
    if all_weak:
        rep.append("**Conclusion:** within a city, rating, number of reviews and the badges have only a weak "
                   "relationship with price. Location (the city) is by far the strongest driver in this data. "
                   "This matches the project hint that the original features correlate weakly with price, and "
                   "the scraped features did not change that picture much.\n")
    else:
        rep.append("**Conclusion:** at least one scraped feature shows a noticeable relationship with price "
                   "inside cities (see the table above), on top of the strong city effect.\n")

    # 4) new listings ------------------------------------------------------------------
    new = df[df["Is_new_listing"].astype(str).str.lower() == "true"]
    old = df[df["Is_new_listing"].astype(str).str.lower() != "true"]
    rep.append("## 4. New listings (no reviews yet)\n")
    if len(new) >= 3:
        p = mannwhitney(new["Price_rel"], old["Price_rel"])
        rep.append(f"- {len(new)} listings have no reviews. Their typical relative price is "
                   f"{new['Price_rel'].median():.2f} vs {old['Price_rel'].median():.2f} for reviewed listings "
                   f"(p {fmt_p(p)}).\n")
    else:
        rep.append("- Too few new listings to compare.\n")

    # 5) outliers ----------------------------------------------------------------------
    rep.append("## 5. Outliers\n")
    top = df.sort_values("Price_per_night", ascending=False).head(10)[
        ["city", "Name", "Price_per_night", "Rating", "Reviews", "URL"]]
    top.to_csv(os.path.join(args.outdir, "top10_most_expensive.csv"), index=False)
    n_out = int(df["Price_outlier"].sum()) if "Price_outlier" in df else 0
    rep.append(f"- {n_out} listings are price outliers inside their city (IQR rule). They were **kept** and "
               f"flagged; medians are used so a few luxury listings do not distort the comparison.")
    rep.append("- The 10 most expensive listings are saved in `top10_most_expensive.csv`.\n")

    # 6) limitations -------------------------------------------------------------------
    rep.append("## 6. Limitations to mention in the report\n")
    rep.append("- Single snapshot: one 3-night stay in December 2026, so seasonality is not captured.")
    rep.append("- Listings are what Airbnb returned for the filters; some cities returned fewer than 50 "
               "(Lisbon, Budapest) so their numbers are less reliable.")
    rep.append("- Some listings are in nearby towns (e.g. Haarlem, Volendam, Schwechat), not the city centre.")
    rep.append("- Prices include all fees and any discount shown at scrape time.")
    rep.append("- Scraping is for this educational project only; do not redistribute the data.\n")

    with open(os.path.join(args.outdir, "EDA_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep))

    print("\n".join(rep))
    print(f"\nCharts + tables saved in: {os.path.abspath(args.outdir)}")


if __name__ == "__main__":
    main()
