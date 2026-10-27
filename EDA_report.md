# EDA report - Airbnb prices in 10 European cities

Dataset: **354 listings**, entire homes with exactly 2 bedrooms, same 3-night stay (prices are the total for the stay including fees, converted to EUR per night).

## 1. Prices by city

- Cheapest city (median): **Athens** at EUR 98.3/night; most expensive: **Paris** at EUR 324.8/night (3.3x).
- Differences between cities are statistically significant (Kruskal-Wallis p <0.001).
- **City alone explains about 57% of the variation in price** (share of variance explained by city averages).
- The median is used instead of the mean because prices are right-skewed (a few luxury listings).

## 2. Do host status and Guest Favorite badge change the price?

Prices are compared **within each city** (price divided by the city median, 1.00 = typical), so a badge is not rewarded just for being common in an expensive city.

- **Superhost**: 233 yes / 121 no. Typical price is +4.7% for Superhost listings after adjusting for city (Mann-Whitney p 0.166, not statistically significant).
- **Guest Favorite**: 201 yes / 153 no. Typical price is +0.0% for Guest Favorite listings after adjusting for city (Mann-Whitney p 0.427, not statistically significant).

## 3. Are price and the other features correlated?

- **Rating (all rated listings)** (n=343): Spearman rho = -0.09 (negligible, p 0.092); within city rho = +0.11 (weak, p 0.051).
- **Rating (listings with 10+ reviews)** (n=303): Spearman rho = -0.12 (weak, p 0.033); within city rho = +0.09 (negligible, p 0.132).
- **Number of reviews (log)** (n=354): Spearman rho = -0.15 (weak, p 0.004); within city rho = +0.02 (negligible, p 0.771).

**Conclusion:** within a city, rating, number of reviews and the badges have only a weak relationship with price. Location (the city) is by far the strongest driver in this data. This matches the project hint that the original features correlate weakly with price, and the scraped features did not change that picture much.

## 4. New listings (no reviews yet)

- 8 listings have no reviews. Their typical relative price is 0.97 vs 1.00 for reviewed listings (p 0.800).

## 5. Outliers

- 9 listings are price outliers inside their city (IQR rule). They were **kept** and flagged; medians are used so a few luxury listings do not distort the comparison.
- The 10 most expensive listings are saved in `top10_most_expensive.csv`.

## 6. Limitations to mention in the report

- Single snapshot: one 3-night stay in December 2026, so seasonality is not captured.
- Listings are what Airbnb returned for the filters; some cities returned fewer than 50 (Lisbon, Budapest) so their numbers are less reliable.
- Some listings are in nearby towns (e.g. Haarlem, Volendam, Schwechat), not the city centre.
- Prices include all fees and any discount shown at scrape time.
- Scraping is for this educational project only; do not redistribute the data.
