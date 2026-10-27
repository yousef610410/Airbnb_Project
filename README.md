# Airbnb_Project

What do 2-bedroom Airbnb stays cost across 10 European cities, and do Superhost and Guest Favorite badges change the price?

Built during the Data Training Program at Instant Software Solutions.

## Pipeline

1. **Scraping** (`scraper/`): Selenium scraper for 10 cities, same 3-night stay (4-7 Dec 2026), with checkpointing, retries, and logging. 404 raw listings.
2. **Cleaning** (`cleaning/`): removed duplicates, 48 listings shown with different dates, and 2 with illogical rating/review values. Missing ratings kept as missing; price outliers flagged, not deleted. Final: 354 listings.
3. **Warehouse** (`sql/`): SQL Server Bronze / Silver / Gold layers. Gold is a star schema (1 fact table, 6 dimensions) with validation checks and analysis views.
4. **EDA** (`eda/`): median-based comparisons, price index per city, statistical tests.
5. **Dashboard** (`images/`): 6-page Power BI report with slicers, DAX measures, and drill-through.

## Key findings

- Paris is the most expensive (median about EUR 325/night), Athens the cheapest (about EUR 98): 3.3x.
- City alone explains about 57% of price variation.
- After adjusting for city, badges show no statistically significant effect on price.

## Limitations

- One date window, so seasonality is not captured.
- Sample of Airbnb search results, not the full market.
- Lisbon and Budapest have fewer than 20 listings.
- Educational project. Raw scraped data is not included.

## Run it

```
pip install selenium webdriver-manager pandas numpy scipy matplotlib seaborn
python scraper/airbnb_scraper.py
python cleaning/clean_airbnb_data.py
python eda/eda_airbnb.py
```
Then run `sql/airbnb_star_schema.sql` in SQL Server and connect Power BI to the Gold layer.
