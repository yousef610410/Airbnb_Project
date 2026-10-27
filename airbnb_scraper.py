"""
Airbnb Prices in European Cities - Selenium scraper
====================================================
Flow (matches the project requirement):
 1. Get the city names (from the original data, or the default list)
 2. Open Airbnb with Selenium
 3. For each city: search + apply filters (Entire home/apt, 2+ bedrooms, fixed dates)
 4. Collect the listing URLs from the search results
 5. Open each listing page on its own
 6. Extract: name, price, rating, reviews, Superhost, Guest Favorite
 7. Save each listing immediately (checkpoint) -> a crash never means starting over
 8. Repeat until TARGET_PER_CITY listings are collected for the city
 9. Merge all cities into one table
10. Save the final CSV for the EDA
 
Usage:
    pip install selenium webdriver-manager pandas
    python airbnb_scraper.py --cities Amsterdam --target 5          # quick test
    python airbnb_scraper.py                                        # all 10 cities, 50 each
    python airbnb_scraper.py --data-dir "archive (8)" --headless    # read city names from the original data
 
NOTE: Automated scraping may go against Airbnb's Terms of Service. Use it only for
this educational project, with a small sample, slowly, and do not redistribute the data.
"""
 
import argparse
import glob
import logging
import os
import random
import re
import sys
import time
from datetime import date, datetime
 
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
 
# ----------------------------------------------------------------------------
# CONFIG  (edit these)
# ----------------------------------------------------------------------------
DEFAULT_CITIES = ["Amsterdam", "Athens", "Barcelona", "Berlin", "Budapest",
                  "Lisbon", "London", "Paris", "Rome", "Vienna"]
 
TARGET_PER_CITY = 50
CHECKIN = "2026-12-04"    # same 3-night stay for every city (must be a FUTURE date)
CHECKOUT = "2026-12-07"
ADULTS = 2
MIN_BEDROOMS = 2
BEDROOMS_EXACT = 2         # keep only listings with EXACTLY this many bedrooms
CURRENCY = "EUR"           # force prices in euros (Airbnb otherwise uses the currency of your country)
 
OUTPUT_DIR = "scraped_data"
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "airbnb_checkpoint.csv")
FINAL_FILE = os.path.join(OUTPUT_DIR, "Airbnb_Scraped_Data.csv")
LOG_FILE = os.path.join(OUTPUT_DIR, "scraper.log")
 
MAX_RETRIES = 2
MAX_RESULT_PAGES = 15     # safety stop per city
 
NIGHTS = (date.fromisoformat(CHECKOUT) - date.fromisoformat(CHECKIN)).days
CURRENCY_WARNED = False
DEBUG_DUMPS_LEFT = 3      # save page text for the first listings where the price was not found
 
COLUMNS = ["room_id", "Name", "city", "Price", "Price_type", "Price_value",
           "Price_per_night", "Price_total", "Price_source", "Currency",
           "Superhost", "is_fav", "Rating", "Reviews", "Bedrooms_found",
           "Min_stay_flag", "URL", "scraped_at"]
 
log = logging.getLogger("airbnb")
 
 
# ----------------------------------------------------------------------------
# 1) Cities
# ----------------------------------------------------------------------------
def load_cities(data_dir=None, csv_path=None):
    """Original data is used ONLY to learn the city names."""
    if csv_path and os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        if "city" in df.columns:
            return df["city"].dropna().unique().tolist()
    if data_dir and os.path.isdir(data_dir):
        # original files are named like amsterdam_weekdays.csv / amsterdam_weekends.csv
        names = {os.path.basename(p).split("_")[0].title()
                 for p in glob.glob(os.path.join(data_dir, "*_week*.csv"))}
        if names:
            return sorted(names)
    return DEFAULT_CITIES
 
 
# ----------------------------------------------------------------------------
# 2) Driver
# ----------------------------------------------------------------------------
def make_driver(headless=False):
    opts = Options()
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    # stop Chrome's built-in translate pop-up from covering the page
    opts.add_argument("--disable-features=Translate,TranslateUI")
    opts.add_experimental_option("prefs", {
        "intl.accept_languages": "en,en_US",
        "translate_whitelists": {},
        "translate": {"enabled": False},
    })
    if headless:
        opts.add_argument("--headless=new")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)
 
 
def search_url(city):
    q = city.replace(" ", "-")
    return (
        f"https://www.airbnb.com/s/{q}/homes"
        f"?query={q}"
        f"&checkin={CHECKIN}&checkout={CHECKOUT}"
        f"&adults={ADULTS}"
        f"&currency={CURRENCY}"
        f"&min_bedrooms={MIN_BEDROOMS}"
        f"&room_types%5B%5D=Entire%20home%2Fapt"
        f"&search_type=filter_change&update_selected_filters=true"
    )
 
 
def dismiss_popups(driver):
    """Close cookie banner / translation dialog / generic modals if present."""
    xpaths = [
        "//button[contains(., 'Accept all')]",
        "//button[contains(., 'OK')]",
        "//button[contains(., 'Got it')]",
        "//button[@aria-label='Close']",
        "//div[@role='dialog']//button[@aria-label='Close']",
        "//button[contains(., 'Continue in English')]",
    ]
    for xp in xpaths:
        try:
            for b in driver.find_elements(By.XPATH, xp)[:1]:
                if b.is_displayed():
                    driver.execute_script("arguments[0].click();", b)
                    time.sleep(0.5)
        except Exception:
            pass
 
 
def close_dialogs(driver):
    """Close the 'Translation on' pop-up and similar dialogs that cover the page."""
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass
    try:
        driver.execute_script("""
            document.querySelectorAll('[role="dialog"]').forEach(function(d){
              if (/translation|cookie/i.test(d.innerText || '')) { d.remove(); }
            });""")
    except Exception:
        pass
 
 
def blocked(driver):
    """Detect a REAL block using visible text/title only.
    (Searching the raw page source gives false positives: Airbnb's scripts
    always contain the word 'captcha' even when no CAPTCHA is shown.)"""
    try:
        title = (driver.title or "").lower()
        if any(k in title for k in ("captcha", "robot", "access denied", "just a moment")):
            return True
        body = driver.find_element(By.TAG_NAME, "body").text.lower()[:3000]
        return any(k in body for k in ("verify you are human", "unusual traffic",
                                       "are you a robot", "press and hold", "access denied"))
    except Exception:
        return False
 
 
# ----------------------------------------------------------------------------
# 4) Collect listing URLs from a results page
# ----------------------------------------------------------------------------
ROOM_RE = re.compile(r"/rooms/(?:plus/)?(\d+)")
 
 
def collect_listing_urls(driver):
    """Returns {room_id: (url, card_text)}. The card text on the results page
    usually contains the price, which we use as a fallback."""
    urls = {}
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/rooms/']"):
        try:
            href = a.get_attribute("href")
            m = ROOM_RE.search(href or "")
            if not m:
                continue
            rid = m.group(1)
            card_text = ""
            try:
                card = a.find_element(By.XPATH, "./ancestor::div[@data-testid='card-container']")
                card_text = " ".join(card.text.split())
            except Exception:
                pass
            if rid not in urls or (not urls[rid][1] and card_text):
                urls[rid] = (href, card_text)
        except Exception:
            continue
    return urls
 
 
# ----------------------------------------------------------------------------
# 5-6) Scrape one listing page
# ----------------------------------------------------------------------------
CUR = r"(?:ج\.\s?م\.?|EGP|€|£|\$|EUR|GBP|USD|HUF|CHF|SEK|PLN|CZK|DKK|RON)"
NUM = r"(?:\d{1,3}(?:[,\.\s\u00a0\u202f]\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
 
 
def find_price(text, allow_any=False):
    """Return (raw, kind) where kind = 'total' (whole stay) / 'per_night' / 'unknown'."""
    t = " ".join((text or "").split())
    patterns = [
        (rf"({CUR}\s?{NUM})\s*(?:total|for\s+\d+\s+nights?)", "total"),
        (rf"Total[^€£$\d]{{0,40}}({CUR}\s?{NUM})", "total"),
        (rf"({CUR}\s?{NUM})\s*(?:/|per\s)?\s*night", "per_night"),
    ]
    if allow_any:
        patterns.append((rf"({CUR}\s?{NUM})", "unknown"))
    for pat, kind in patterns:
        m = re.search(pat, t, re.I)
        if m:
            return m.group(1).strip(), kind
    return None, None
 
 
def parse_price(text):
    """'€1,234' -> (1234.0, '€')"""
    if not text:
        return None, None
    cur = re.search(CUR, text)
    num = re.search(NUM, text)
    value = None
    if num:
        try:
            value = float(re.sub(r"[,\s\u00a0\u202f]", "", num.group(0)))
        except ValueError:
            pass
    return value, (cur.group(0) if cur else None)
 
 
def get_page_text(driver):
    try:
        return " ".join(driver.find_element(By.TAG_NAME, "body").text.split())
    except Exception:
        return ""
 
 
def extract_price(driver, card_text=""):
    """Wait (up to ~12s) for the price to render on the listing page.
    Fallback: the price shown on the search-results card."""
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            side = driver.find_element(By.CSS_SELECTOR, "[data-plugin-in-point-id='BOOK_IT_SIDEBAR']")
            raw, kind = find_price(side.get_attribute("textContent"))
            if raw:
                return raw, kind, "page"
        except Exception:
            pass
        raw, kind = find_price(get_page_text(driver))
        if raw:
            return raw, kind, "page"
        driver.execute_script("window.scrollBy(0, 300);")
        time.sleep(1)
    raw, kind = find_price(card_text, allow_any=True)
    if raw:
        return raw, kind, "card"
    return None, None, None
 
 
def name_from_card(card_text):
    m = re.search(r"\(\d+\)\s*(.+?)\s+(?:\d+\s+bedrooms?|Studio|\d+\s+beds?)", card_text or "")
    return m.group(1).strip() if m else None
 
 
def get_name(driver, card_text=""):
    for _ in range(8):
        try:
            t = driver.find_element(By.TAG_NAME, "h1").text.strip()
            if t:
                return t
        except Exception:
            pass
        time.sleep(1)
    cn = name_from_card(card_text)
    if cn:
        return cn
    try:
        og = driver.execute_script(
            "var m=document.querySelector('meta[property=\"og:title\"]');return m?m.content:'';")
        if og:
            return og.strip()
    except Exception:
        pass
    t = (driver.title or "").replace("- Airbnb", "").strip()
    return t or "No Title"
 
 
def scrape_listing(driver, wait, room_id, url, city, card_text=""):
    global DEBUG_DUMPS_LEFT
    open_url = url if "currency=" in url else url + ("&" if "?" in url else "?") + f"currency={CURRENCY}"
    driver.get(open_url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
    dismiss_popups(driver)
    close_dialogs(driver)
    driver.execute_script("window.scrollBy(0, 600);")
    time.sleep(1.0)
 
    if blocked(driver):
        raise RuntimeError("BLOCKED")
 
    name = get_name(driver, card_text)
    body = get_page_text(driver)
    top = body[:4000]
 
    # Superhost
    superhost = "Yes" if re.search(r"\bSuperhost\b", body) else "No"
 
    # Guest favorite
    is_fav = 1 if "Guest favorite" in top else 0
 
    # Rating + reviews
    rating, reviews = "N/A", 0
    m = re.search(r"(\d\.\d{1,2})\s*(?:·|\||\s)\s*(\d[\d,]*)\s*reviews?", top, re.I)
    if m:
        rating, reviews = m.group(1), int(m.group(2).replace(",", ""))
    else:
        m_r = re.search(r"(\d[\d,]*)\s*reviews?", top, re.I)
        if m_r:
            reviews = int(m_r.group(1).replace(",", ""))
        m_s = re.search(r"\b(\d\.\d{1,2})\b", top)
        if m_s:
            rating = m_s.group(1)
        if "New" in top[:600] and reviews == 0:
            rating = "New"
 
    # Bedrooms found on the page (to verify the filter really applied)
    bm = re.search(r"(\d+)\s*bedrooms?", top, re.I)
    bedrooms = int(bm.group(1)) if bm else None
 
    # Minimum stay warning
    min_stay = 1 if re.search(r"minimum stay|\d+\s*night minimum", body, re.I) else 0
 
    # Price
    price_raw, price_type, price_source = extract_price(driver, card_text)
    value, cur = parse_price(price_raw)
    per_night = total = None
    if value is not None:
        if price_type == "total":
            total, per_night = value, round(value / NIGHTS, 2)
        elif price_type == "per_night":
            per_night, total = value, round(value * NIGHTS, 2)
 
    if price_raw is None and DEBUG_DUMPS_LEFT > 0:
        DEBUG_DUMPS_LEFT -= 1
        dump = os.path.join(OUTPUT_DIR, f"debug_price_{room_id}.txt")
        with open(dump, "w", encoding="utf-8") as f:
            f.write(url + "\n\nCARD TEXT:\n" + card_text + "\n\nPAGE TEXT:\n" + body[:8000])
        log.warning("Price not found for %s -> page text saved to %s", room_id, dump)
 
    return {
        "room_id": room_id, "Name": name, "city": city,
        "Price": price_raw, "Price_type": price_type, "Price_value": value,
        "Price_per_night": per_night, "Price_total": total,
        "Price_source": price_source, "Currency": cur,
        "Superhost": superhost, "is_fav": is_fav,
        "Rating": rating, "Reviews": reviews,
        "Bedrooms_found": bedrooms, "Min_stay_flag": min_stay,
        "URL": url, "scraped_at": datetime.now().isoformat(timespec="seconds"),
    }
 
 
# ----------------------------------------------------------------------------
# 7) Checkpointing
# ----------------------------------------------------------------------------
def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        return pd.read_csv(CHECKPOINT_FILE, dtype={"room_id": str})
    return pd.DataFrame(columns=COLUMNS)
 
 
def save_row(row):
    df = pd.DataFrame([row], columns=COLUMNS)
    df.to_csv(CHECKPOINT_FILE, mode="a", header=not os.path.exists(CHECKPOINT_FILE), index=False)
 
 
# ----------------------------------------------------------------------------
# 3 + 8) One city
# ----------------------------------------------------------------------------
def scrape_city(driver, city, target, done_ids, already):
    wait = WebDriverWait(driver, 12)
    collected = already
    log.info("=== %s: have %d / %d ===", city, collected, target)
    if collected >= target:
        return collected
 
    driver.get(search_url(city))
    time.sleep(4)
    dismiss_popups(driver)
 
    for page in range(1, MAX_RESULT_PAGES + 1):
        if collected >= target:
            break
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/rooms/']")))
        except Exception:
            shot = os.path.join(OUTPUT_DIR, f"debug_{city}_p{page}.png")
            try:
                driver.save_screenshot(shot)
            except Exception:
                shot = "(screenshot failed)"
            if blocked(driver):
                log.error("Real block / CAPTCHA detected for %s. Screenshot: %s", city, shot)
            else:
                log.warning("No listings found on page %d for %s. Title='%s' Screenshot: %s",
                            page, city, driver.title, shot)
            break
 
        # scroll to load lazy cards
        for _ in range(4):
            driver.execute_script("window.scrollBy(0, 1200);")
            time.sleep(0.6)
 
        listings = collect_listing_urls(driver)
        search_page = driver.current_url
        log.info("%s page %d: %d listing links", city, page, len(listings))
 
        for room_id, (url, card_text) in listings.items():
            if collected >= target:
                break
            if room_id in done_ids:
                continue
            cb = re.search(r"(\d+)\s*bedrooms?", card_text or "", re.I)
            if cb and int(cb.group(1)) != BEDROOMS_EXACT:
                done_ids.add(room_id)
                log.info("Skip %s: %s bedrooms (need %d)", room_id, cb.group(1), BEDROOMS_EXACT)
                continue
 
            ok = False
            for attempt in range(1, MAX_RETRIES + 2):
                try:
                    row = scrape_listing(driver, wait, room_id, url, city, card_text)
                    if row["Bedrooms_found"] not in (None, BEDROOMS_EXACT):
                        done_ids.add(room_id)
                        log.info("Skip %s: page shows %s bedrooms (need %d)",
                                 room_id, row["Bedrooms_found"], BEDROOMS_EXACT)
                        ok = True
                        break
                    global CURRENCY_WARNED
                    if row["Currency"] not in (None, "€", "EUR") and not CURRENCY_WARNED:
                        CURRENCY_WARNED = True
                        log.error("Prices are in '%s', not EUR! Check the currency before using this data.",
                                  row["Currency"])
                    save_row(row)                     # checkpoint immediately
                    done_ids.add(room_id)
                    collected += 1
                    ok = True
                    log.info("[%s %d/%d] %s (%s, %s) | %s | star %s (%s) | Fav %s | SH %s",
                             city, collected, target, row["Price"], row["Price_type"],
                             row["Price_source"], row["Name"][:40],
                             row["Rating"], row["Reviews"], row["is_fav"], row["Superhost"])
                    break
                except RuntimeError as e:
                    if "BLOCKED" in str(e):
                        log.error("Blocked by Airbnb. Stop now and try later.")
                        raise
                except Exception as e:
                    log.warning("Retry %d for %s failed: %s", attempt, url, str(e)[:120])
                    time.sleep(2 * attempt)
            if not ok:
                log.error("Skipping listing %s after retries", room_id)
            time.sleep(random.uniform(1.5, 3.0))
 
        # go back to the search page and click Next
        if collected < target:
            try:
                driver.get(search_page)
                time.sleep(3)
                nxt = driver.find_element(By.CSS_SELECTOR, "a[aria-label='Next']")
                driver.execute_script("arguments[0].click();", nxt)
                time.sleep(4)
                dismiss_popups(driver)
            except Exception:
                log.info("No more result pages for %s", city)
                break
 
    return collected
 
 
# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", nargs="*", help="override city list, e.g. --cities Amsterdam Paris")
    ap.add_argument("--target", type=int, default=TARGET_PER_CITY)
    ap.add_argument("--data-dir", help="folder of the original CSVs (only used to learn city names)")
    ap.add_argument("--csv", help="single original CSV with a 'city' column")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()
 
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
 
    cities = args.cities or load_cities(args.data_dir, args.csv)
    log.info("Cities: %s | target per city: %d | stay %s -> %s", cities, args.target, CHECKIN, CHECKOUT)
 
    if os.path.exists(CHECKPOINT_FILE):
        old_cols = list(pd.read_csv(CHECKPOINT_FILE, nrows=0).columns)
        if old_cols != COLUMNS:
            backup = CHECKPOINT_FILE.replace(".csv", f"_old_{int(time.time())}.csv")
            os.replace(CHECKPOINT_FILE, backup)
            log.info("Old checkpoint had different columns -> moved to %s", backup)
    ckpt = load_checkpoint()
    bad = ckpt["Price_value"].isna() if len(ckpt) else []
    if len(ckpt) and bad.any():           # retry listings that were saved without a price
        log.info("Dropping %d checkpoint rows with no price (will be re-scraped)", int(bad.sum()))
        ckpt = ckpt[~bad]
        ckpt.to_csv(CHECKPOINT_FILE, index=False)
    done_ids = set(ckpt["room_id"].astype(str))
 
    driver = make_driver(args.headless)
    try:
        try:   # ask Airbnb for euro prices
            driver.get("https://www.airbnb.com/")
            driver.add_cookie({"name": "currency", "value": CURRENCY, "domain": ".airbnb.com", "path": "/"})
        except Exception as e:
            log.warning("Could not set currency cookie: %s", str(e)[:100])
        for city in cities:
            already = int((ckpt["city"] == city).sum()) if len(ckpt) else 0
            try:
                scrape_city(driver, city, args.target, done_ids, already)
            except RuntimeError:
                break
            ckpt = load_checkpoint()
    finally:
        driver.quit()
 
    # 9-10) merge everything and save the final CSV
    final = load_checkpoint().drop_duplicates(subset="room_id")
    final.to_csv(FINAL_FILE, index=False)
    log.info("Saved %d rows -> %s", len(final), FINAL_FILE)
    if len(final):
        log.info("Per city:\n%s", final["city"].value_counts().to_string())
 
 
if __name__ == "__main__":
    main()
 