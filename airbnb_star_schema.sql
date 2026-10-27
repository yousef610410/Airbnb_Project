/* =====================================================================
   AIRBNB PRICE LAB - Star schema in SQL Server
   Layers: bronze (raw text) -> silver (typed, clean) -> gold (star schema + views)
   Source: airbnb_gold_source.csv  (354 listings, 10 cities, 4-7 Dec 2026)
   Run each STEP (highlight, F5) in order. Change the file path in STEP 2.
   ===================================================================== */

/* ---------- STEP 1: database + schemas ---------- */
IF DB_ID('AirbnbProject') IS NULL CREATE DATABASE AirbnbProject;
GO
USE AirbnbProject;
GO
IF SCHEMA_ID('bronze') IS NULL EXEC('CREATE SCHEMA bronze');
IF SCHEMA_ID('silver') IS NULL EXEC('CREATE SCHEMA silver');
IF SCHEMA_ID('gold')   IS NULL EXEC('CREATE SCHEMA gold');
GO

/* ---------- STEP 2: bronze = raw import ---------- */
DROP TABLE IF EXISTS bronze.listings_raw;
CREATE TABLE bronze.listings_raw (
    room_id NVARCHAR(40), Name NVARCHAR(300), city NVARCHAR(50),
    Price_total NVARCHAR(20), Nights NVARCHAR(10), Price_per_night NVARCHAR(20),
    Currency NVARCHAR(10), Superhost NVARCHAR(5), is_fav NVARCHAR(5),
    Rating NVARCHAR(10), Reviews NVARCHAR(10), Bedrooms_found NVARCHAR(10),
    Check_in NVARCHAR(20), Check_out NVARCHAR(20), URL NVARCHAR(500)
);
GO
BULK INSERT bronze.listings_raw
FROM 'C:\Users\maro\Downloads\Course (Intern)\archive (8)\airbnb_gold_source.csv'   -- <== change path if needed
WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',',
      ROWTERMINATOR = '0x0a', CODEPAGE = '65001', TABLOCK);
GO
SELECT COUNT(*) AS bronze_rows FROM bronze.listings_raw;          -- expected 354
GO

/* ---------- STEP 3: silver = typed + cleaned + quality checks ---------- */
DROP TABLE IF EXISTS silver.listings;
CREATE TABLE silver.listings (
    listing_id BIGINT PRIMARY KEY, listing_name NVARCHAR(300), city NVARCHAR(50),
    price_total DECIMAL(10,2), stay_nights INT, price_per_night DECIMAL(10,2),
    currency NVARCHAR(10), is_superhost BIT, is_guest_favorite BIT,
    rating DECIMAL(3,2) NULL, reviews_count INT, bedrooms INT NULL,
    check_in DATE, check_out DATE, listing_url NVARCHAR(500)
);
INSERT INTO silver.listings
SELECT TRY_CAST(room_id AS BIGINT), LTRIM(RTRIM(Name)), LTRIM(RTRIM(city)),
       TRY_CAST(Price_total AS DECIMAL(10,2)), TRY_CAST(Nights AS INT), TRY_CAST(Price_per_night AS DECIMAL(10,2)),
       Currency, TRY_CAST(Superhost AS BIT), TRY_CAST(is_fav AS BIT),
       TRY_CAST(NULLIF(LTRIM(RTRIM(Rating)), '') AS DECIMAL(3,2)), TRY_CAST(Reviews AS INT),
       TRY_CAST(TRY_CAST(NULLIF(LTRIM(RTRIM(Bedrooms_found)), '') AS DECIMAL(4,1)) AS INT),
       TRY_CAST(Check_in AS DATE), TRY_CAST(Check_out AS DATE), URL
FROM bronze.listings_raw;
GO
-- quality checks: every value below should be 0
SELECT SUM(CASE WHEN listing_id IS NULL THEN 1 ELSE 0 END)        AS bad_ids,
       SUM(CASE WHEN price_per_night IS NULL OR price_per_night <= 0 THEN 1 ELSE 0 END) AS bad_prices,
       SUM(CASE WHEN rating < 1 OR rating > 5 THEN 1 ELSE 0 END)  AS bad_ratings,
       SUM(CASE WHEN check_in IS NULL OR check_out IS NULL THEN 1 ELSE 0 END) AS bad_dates
FROM silver.listings;
GO

USE AirbnbProject;
GO
DROP TABLE IF EXISTS gold.Fact_Listing_Observation;
DROP TABLE IF EXISTS gold.Dim_Property, gold.Dim_Status;
GO

/* ---------- STEP 4: gold dimensions ---------- */
DROP VIEW  IF EXISTS gold.vw_city_summary, gold.vw_badge_effect, gold.vw_best_value, gold.vw_rating_vs_price;
DROP TABLE IF EXISTS gold.fact_listing_price;
DROP TABLE IF EXISTS gold.dim_city, gold.dim_listing, gold.dim_host_badge, gold.dim_review_profile,
                     gold.dim_price_band, gold.dim_date;
GO

CREATE TABLE gold.dim_city (
    city_key INT IDENTITY(1,1) PRIMARY KEY, city_name NVARCHAR(50) NOT NULL,
    country NVARCHAR(50) NOT NULL, region NVARCHAR(30) NOT NULL
);
INSERT INTO gold.dim_city (city_name, country, region)
SELECT DISTINCT city,
  CASE city WHEN 'Amsterdam' THEN 'Netherlands' WHEN 'Athens' THEN 'Greece' WHEN 'Barcelona' THEN 'Spain'
            WHEN 'Berlin' THEN 'Germany' WHEN 'Budapest' THEN 'Hungary' WHEN 'Lisbon' THEN 'Portugal'
            WHEN 'London' THEN 'United Kingdom' WHEN 'Paris' THEN 'France' WHEN 'Rome' THEN 'Italy'
            WHEN 'Vienna' THEN 'Austria' ELSE 'Unknown' END,
  CASE WHEN city IN ('Amsterdam','London','Paris') THEN 'Western Europe'
       WHEN city IN ('Athens','Barcelona','Lisbon','Rome') THEN 'Southern Europe'
       ELSE 'Central Europe' END
FROM silver.listings;

CREATE TABLE gold.dim_listing (
    listing_key INT IDENTITY(1,1) PRIMARY KEY, listing_id BIGINT NOT NULL, listing_name NVARCHAR(300),
    room_type NVARCHAR(30), bedrooms INT NULL, listing_url NVARCHAR(500)
);
INSERT INTO gold.dim_listing (listing_id, listing_name, room_type, bedrooms, listing_url)
SELECT listing_id, listing_name, 'Entire home/apt', bedrooms, listing_url FROM silver.listings;

CREATE TABLE gold.dim_host_badge (
    badge_key INT PRIMARY KEY, host_type NVARCHAR(20), guest_favorite NVARCHAR(20), badge_combo NVARCHAR(50)
);
INSERT INTO gold.dim_host_badge VALUES
 (1,'Superhost','Guest favorite','Superhost + Guest favorite'),
 (2,'Superhost','Not guest favorite','Superhost only'),
 (3,'Regular host','Guest favorite','Guest favorite only'),
 (4,'Regular host','Not guest favorite','No badge');

CREATE TABLE gold.dim_review_profile (
    review_profile_key INT PRIMARY KEY, rating_band NVARCHAR(20), rating_sort INT,
    reviews_band NVARCHAR(20), reviews_sort INT
);
INSERT INTO gold.dim_review_profile
SELECT ROW_NUMBER() OVER (ORDER BY r.rating_sort, v.reviews_sort), r.rating_band, r.rating_sort, v.reviews_band, v.reviews_sort
FROM (VALUES ('No rating',0),('Below 4.80',1),('4.80-4.89',2),('4.90-5.00',3)) AS r(rating_band, rating_sort)
CROSS JOIN (VALUES ('0 reviews',0),('1-9',1),('10-49',2),('50-199',3),('200+',4)) AS v(reviews_band, reviews_sort);

CREATE TABLE gold.dim_price_band (
    price_band_key INT PRIMARY KEY, band_name NVARCHAR(20), min_price DECIMAL(8,2), max_price DECIMAL(8,2)
);
INSERT INTO gold.dim_price_band VALUES
 (1,'Under 100',0,100),(2,'100-149',100,150),(3,'150-199',150,200),(4,'200-249',200,250),
 (5,'250-299',250,300),(6,'300-399',300,400),(7,'400+',400,100000);

CREATE TABLE gold.dim_date (
    date_key INT PRIMARY KEY, full_date DATE, calendar_year INT, calendar_quarter INT,
    calendar_month INT, month_name NVARCHAR(20), day_of_month INT, day_name NVARCHAR(20)
);
WITH d AS (SELECT CAST('2026-12-01' AS DATE) AS dt UNION ALL SELECT DATEADD(DAY, 1, dt) FROM d WHERE dt < '2026-12-31')
INSERT INTO gold.dim_date
SELECT CONVERT(INT, FORMAT(dt,'yyyyMMdd')), dt, YEAR(dt), DATEPART(QUARTER, dt), MONTH(dt),
       DATENAME(MONTH, dt), DAY(dt), DATENAME(WEEKDAY, dt)
FROM d;
GO

/* ---------- STEP 5: gold fact (with city median, price index, outlier flag) ---------- */
CREATE TABLE gold.fact_listing_price (
    fact_id INT IDENTITY(1,1) PRIMARY KEY,
    city_key INT NOT NULL REFERENCES gold.dim_city(city_key),
    listing_key INT NOT NULL REFERENCES gold.dim_listing(listing_key),
    badge_key INT NOT NULL REFERENCES gold.dim_host_badge(badge_key),
    review_profile_key INT NOT NULL REFERENCES gold.dim_review_profile(review_profile_key),
    price_band_key INT NOT NULL REFERENCES gold.dim_price_band(price_band_key),
    check_in_date_key INT NOT NULL REFERENCES gold.dim_date(date_key),
    check_out_date_key INT NOT NULL REFERENCES gold.dim_date(date_key),
    adults INT, currency NVARCHAR(10), price_total DECIMAL(10,2), stay_nights INT,
    price_per_night DECIMAL(10,2), rating DECIMAL(3,2) NULL, reviews_count INT,
    city_median_price DECIMAL(10,2), price_index DECIMAL(6,3), is_price_outlier BIT
);
WITH s AS (
    SELECT l.*,
           PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY price_per_night) OVER (PARTITION BY city) AS med,
           PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_per_night) OVER (PARTITION BY city) AS q1,
           PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_per_night) OVER (PARTITION BY city) AS q3
    FROM silver.listings l)
INSERT INTO gold.fact_listing_price
    (city_key, listing_key, badge_key, review_profile_key, price_band_key, check_in_date_key, check_out_date_key,
     adults, currency, price_total, stay_nights, price_per_night, rating, reviews_count,
     city_median_price, price_index, is_price_outlier)
SELECT c.city_key, li.listing_key,
       CASE WHEN s.is_superhost = 1 AND s.is_guest_favorite = 1 THEN 1
            WHEN s.is_superhost = 1 THEN 2 WHEN s.is_guest_favorite = 1 THEN 3 ELSE 4 END,
       rp.review_profile_key, pb.price_band_key,
       CONVERT(INT, FORMAT(s.check_in,'yyyyMMdd')), CONVERT(INT, FORMAT(s.check_out,'yyyyMMdd')),
       2, s.currency, s.price_total, s.stay_nights, s.price_per_night, s.rating, s.reviews_count,
       s.med, s.price_per_night / NULLIF(s.med, 0),
       CASE WHEN s.price_per_night > s.q3 + 1.5 * (s.q3 - s.q1) OR s.price_per_night < s.q1 - 1.5 * (s.q3 - s.q1) THEN 1 ELSE 0 END
FROM s
JOIN gold.dim_city c      ON c.city_name = s.city
JOIN gold.dim_listing li  ON li.listing_id = s.listing_id
JOIN gold.dim_review_profile rp
     ON rp.rating_band = CASE WHEN s.rating IS NULL THEN 'No rating' WHEN s.rating >= 4.9 THEN '4.90-5.00'
                              WHEN s.rating >= 4.8 THEN '4.80-4.89' ELSE 'Below 4.80' END
    AND rp.reviews_band = CASE WHEN s.reviews_count = 0 THEN '0 reviews' WHEN s.reviews_count < 10 THEN '1-9'
                               WHEN s.reviews_count < 50 THEN '10-49' WHEN s.reviews_count < 200 THEN '50-199' ELSE '200+' END
JOIN gold.dim_price_band pb ON s.price_per_night >= pb.min_price AND s.price_per_night < pb.max_price;
GO

/* ---------- STEP 6: analysis views (one per dashboard page) ---------- */
CREATE VIEW gold.vw_city_summary AS
SELECT DISTINCT c.city_name, c.country, c.region,
       COUNT(*) OVER (PARTITION BY c.city_name) AS listings,
       CAST(AVG(f.price_per_night) OVER (PARTITION BY c.city_name) AS DECIMAL(8,1)) AS avg_price,
       CAST(f.city_median_price AS DECIMAL(8,1)) AS median_price,
       MIN(f.price_per_night) OVER (PARTITION BY c.city_name) AS min_price,
       MAX(f.price_per_night) OVER (PARTITION BY c.city_name) AS max_price,
       CAST(AVG(f.rating) OVER (PARTITION BY c.city_name) AS DECIMAL(4,2)) AS avg_rating
FROM gold.fact_listing_price f JOIN gold.dim_city c ON c.city_key = f.city_key;
GO
CREATE VIEW gold.vw_badge_effect AS
SELECT b.badge_combo, COUNT(*) AS listings,
       CAST(AVG(f.price_index) AS DECIMAL(5,3)) AS avg_price_index,        -- 1.00 = typical for its city
       CAST(AVG(f.price_per_night) AS DECIMAL(8,1)) AS avg_price
FROM gold.fact_listing_price f JOIN gold.dim_host_badge b ON b.badge_key = f.badge_key
GROUP BY b.badge_combo;
GO
CREATE VIEW gold.vw_best_value AS
SELECT c.city_name, li.listing_name, f.price_per_night, f.city_median_price, f.price_index, f.rating, f.reviews_count, li.listing_url
FROM gold.fact_listing_price f
JOIN gold.dim_city c ON c.city_key = f.city_key
JOIN gold.dim_listing li ON li.listing_key = f.listing_key
WHERE f.rating >= 4.8 AND f.reviews_count >= 10 AND f.price_index <= 0.90;      -- good rating, cheaper than its city's median
GO
CREATE VIEW gold.vw_rating_vs_price AS
SELECT rp.rating_band, rp.rating_sort, COUNT(*) AS listings,
       CAST(AVG(f.price_index) AS DECIMAL(5,3)) AS avg_price_index
FROM gold.fact_listing_price f JOIN gold.dim_review_profile rp ON rp.review_profile_key = f.review_profile_key
GROUP BY rp.rating_band, rp.rating_sort;
GO

/* ---------- STEP 7: checks (compare with the numbers in the report) ---------- */
SELECT (SELECT COUNT(*) FROM gold.fact_listing_price) AS fact_rows,        -- 354
       (SELECT COUNT(*) FROM gold.dim_city)           AS cities,           -- 10
       (SELECT COUNT(*) FROM gold.dim_listing)        AS listings,         -- 354
       (SELECT COUNT(*) FROM gold.dim_price_band)     AS price_bands,      -- 7
       (SELECT COUNT(*) FROM gold.dim_date)           AS dates;            -- 31
SELECT * FROM gold.vw_city_summary ORDER BY median_price DESC;             -- Paris 324.8 ... Athens 98.3
SELECT * FROM gold.vw_badge_effect ORDER BY avg_price_index DESC;
SELECT COUNT(*) AS best_value_listings FROM gold.vw_best_value;
SELECT SUM(CAST(is_price_outlier AS INT)) AS outliers FROM gold.fact_listing_price;
GO
