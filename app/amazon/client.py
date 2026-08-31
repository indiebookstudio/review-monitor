import logging
import random
import time
import concurrent.futures
from typing import Tuple, Optional, Dict, Any, List
import requests
from bs4 import BeautifulSoup

from app.amazon.marketplace import get_reviews_url, get_product_url, MARKETPLACES, normalize_marketplace
from app.amazon.parser import (
    parse_amazon_reviews,
    extract_cover_image,
    extract_product_price,
    extract_kindle_details,
    is_blocked_or_unavailable,
    STATUS_OK,
    STATUS_NO_REVIEWS,
    STATUS_PAGE_UNAVAILABLE,
    STATUS_PARSER_ERROR
)
from app.config import settings

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
]

def get_headers(marketplace: str = "amazon.it") -> dict:
    ua = random.choice(USER_AGENTS)
    lang = "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
    if "amazon.com" in marketplace or "amazon.ca" in marketplace or "amazon.com.au" in marketplace:
        lang = "en-US,en;q=0.9"
    elif "amazon.co.uk" in marketplace or "amazon.ie" in marketplace:
        lang = "en-GB,en;q=0.9,en-US;q=0.8"
    elif "amazon.de" in marketplace:
        lang = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    elif "amazon.fr" in marketplace or "amazon.com.be" in marketplace:
        lang = "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
    elif "amazon.es" in marketplace:
        lang = "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7"
    elif "amazon.nl" in marketplace:
        lang = "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7"
    elif "amazon.pl" in marketplace:
        lang = "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7"
    elif "amazon.se" in marketplace:
        lang = "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7"
    elif "amazon.co.jp" in marketplace:
        lang = "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"

    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

class AmazonClient:
    def __init__(self, use_playwright: Optional[bool] = None):
        self.use_playwright = use_playwright if use_playwright is not None else True

    def _fetch_url_resilient(self, url: str, marketplace: str = "amazon.it", max_http_retries: int = 2) -> Tuple[Optional[str], int, Optional[str]]:
        """
        Fetches any Amazon URL with multi-layered fallback:
        1. Fast HTTP GET with rotated User-Agents, cookies, and retry backoff.
        2. Stealth Playwright Browser with anti-detection evasions if HTTP is blocked.
        """
        # 1. Fast HTTP attempts with retries
        for attempt in range(1, max_http_retries + 1):
            headers = get_headers(marketplace)
            try:
                session = requests.Session()
                session.headers.update(headers)
                resp = session.get(url, timeout=12)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    if not is_blocked_or_unavailable(resp.text, soup):
                        return resp.text, 200, None
                    logger.warning(f"HTTP attempt {attempt} for {url} encountered CAPTCHA or blocking.")
                elif resp.status_code == 404:
                    return None, 404, "Page not found (HTTP 404)"
                elif resp.status_code == 503:
                    logger.warning(f"HTTP 503 Service Unavailable for {url} (attempt {attempt}).")
            except Exception as http_e:
                logger.info(f"HTTP fetch error on attempt {attempt} for {url}: {http_e}")
            
            if attempt < max_http_retries:
                time.sleep(random.uniform(0.8, 1.5))

        # 2. Stealth Playwright Browser Fallback
        if self.use_playwright:
            logger.info(f"Falling back to Playwright Stealth for {url}...")
            content, code, err = self._fetch_playwright(url)
            if content and code == 200:
                return content, 200, None

        return None, 500, "Impossibile recuperare la pagina Amazon dopo tentativi multipli"

    def fetch_reviews_page(self, asin: str, marketplace: str = "amazon.it") -> Tuple[Optional[str], int, Optional[str]]:
        """
        Fetches the primary page for an ASIN (tries reviews page, then product page).
        """
        rev_url = get_reviews_url(asin, marketplace, sort_by_recent=True)
        content, code, err = self._fetch_url_resilient(rev_url, marketplace)
        if content and code == 200:
            return content, 200, None
            
        prod_url = get_product_url(asin, marketplace)
        return self._fetch_url_resilient(prod_url, marketplace)

    def fetch_all_reviews_for_book(self, asin: str, marketplace: str = "amazon.it", max_pages: int = 5) -> Dict[str, Any]:
        """
        Fetches ALL reviews for a book using a bulletproof multi-layer strategy:
        1. Fetches the main product page (/dp/<asin>) for 100% reliable metadata and initial reviews.
        2. If more reviews exist, paginates through /product-reviews/<asin> to collect all reviews.
        3. Never fails silently; resilient against temporary blocks or redirects.
        """
        clean_asin = asin.strip().upper()
        norm_m = normalize_marketplace(marketplace)
        base = MARKETPLACES.get(norm_m, {}).get("base_url", "https://www.amazon.it")
        
        all_reviews_dict: Dict[str, Dict[str, Any]] = {}
        combined_result: Dict[str, Any] = {
            "status": STATUS_OK,
            "error": None,
            "product_title": None,
            "cover_image_url": None,
            "price": None,
            "has_kindle": False,
            "kindle_price": None,
            "kindle_asin": None,
            "reviews": [],
            "total_reviews": 0,
            "average_rating": None
        }

        # Step 1: Main product page (/dp/<asin>)
        prod_url = f"{base}/dp/{clean_asin}"
        html_prod, code_prod, err_prod = self._fetch_url_resilient(prod_url, norm_m)
        
        # Fallback to /gp/product/ or /product-reviews/ if /dp/ returned 500/unavailable
        if not html_prod or code_prod != 200:
            logger.info(f"/dp/ page not available for {clean_asin} on {norm_m}. Trying alternative reviews page...")
            alt_url = f"{base}/product-reviews/{clean_asin}?reviewerType=all_reviews&sortBy=recent&pageNumber=1"
            html_prod, code_prod, err_prod = self._fetch_url_resilient(alt_url, norm_m)

        if not html_prod or code_prod != 200:
            error_msg = err_prod or f"HTTP status {code_prod}"
            combined_result["status"] = STATUS_PAGE_UNAVAILABLE
            combined_result["error"] = error_msg
            return combined_result

        # Parse main page
        parsed_prod = parse_amazon_reviews(html_prod, clean_asin, norm_m)
        combined_result["product_title"] = parsed_prod.get("product_title")
        combined_result["cover_image_url"] = parsed_prod.get("cover_image_url")
        combined_result["price"] = parsed_prod.get("price")
        combined_result["has_kindle"] = parsed_prod.get("has_kindle", False)
        combined_result["kindle_price"] = parsed_prod.get("kindle_price")
        combined_result["kindle_asin"] = parsed_prod.get("kindle_asin")
        combined_result["average_rating"] = parsed_prod.get("average_rating")
        combined_result["total_reviews"] = parsed_prod.get("total_reviews", 0)

        for r in parsed_prod.get("reviews", []):
            if r.get("review_id"):
                all_reviews_dict[r["review_id"]] = r

        # Step 2: Paginate through /product-reviews/ if more reviews exist
        total_reported = parsed_prod.get("total_reviews", 0)
        current_count = len(all_reviews_dict)
        
        if (total_reported > current_count or current_count >= 8) and max_pages > 1:
            for page_num in range(1, max_pages + 1):
                page_url = f"{base}/product-reviews/{clean_asin}?reviewerType=all_reviews&sortBy=recent&pageNumber={page_num}"
                html_page, code_page, _ = self._fetch_url_resilient(page_url, norm_m, max_http_retries=1)
                if not html_page or code_page != 200:
                    break
                
                parsed_page = parse_amazon_reviews(html_page, clean_asin, norm_m)
                page_revs = parsed_page.get("reviews", [])
                if not page_revs:
                    break
                
                new_found = 0
                for r in page_revs:
                    r_id = r.get("review_id")
                    if r_id and r_id not in all_reviews_dict:
                        all_reviews_dict[r_id] = r
                        new_found += 1
                        
                # Update total reviews count and rating if more accurate
                if parsed_page.get("total_reviews", 0) > combined_result["total_reviews"]:
                    combined_result["total_reviews"] = parsed_page["total_reviews"]
                if parsed_page.get("average_rating") and not combined_result["average_rating"]:
                    combined_result["average_rating"] = parsed_page["average_rating"]
                
                # Stop if no new reviews on this page or we collected all
                if new_found == 0 or len(all_reviews_dict) >= combined_result["total_reviews"]:
                    break
                    
                time.sleep(random.uniform(0.5, 1.0))

        combined_result["reviews"] = list(all_reviews_dict.values())
        combined_result["total_reviews"] = max(len(all_reviews_dict), combined_result["total_reviews"])
        
        if len(all_reviews_dict) > 0:
            combined_result["status"] = STATUS_OK
        elif combined_result["product_title"] or parsed_prod.get("status") == STATUS_NO_REVIEWS:
            combined_result["status"] = STATUS_NO_REVIEWS
        else:
            combined_result["status"] = parsed_prod.get("status", STATUS_OK)
        
        return combined_result

    def _fetch_playwright(self, url: str) -> Tuple[Optional[str], int, Optional[str]]:
        """Playwright execution in a dedicated thread with stealth anti-bot evasion."""
        def _exec_sync():
            try:
                from playwright.sync_api import sync_playwright
                logger.info(f"Fetching {url} via Playwright Stealth in worker thread...")
                with sync_playwright() as p:
                    launch_args = [
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-infobars",
                        "--window-size=1920,1080",
                    ]
                    try:
                        browser = p.chromium.launch(headless=True, channel="chrome", args=launch_args)
                    except Exception:
                        browser = p.chromium.launch(headless=True, args=launch_args)
                    
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        locale="it-IT",
                        timezone_id="Europe/Rome",
                        viewport={"width": 1920, "height": 1080},
                        extra_http_headers={
                            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
                            "DNT": "1"
                        }
                    )
                    
                    # Inject stealth scripts before page scripts load
                    context.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                        window.chrome = { runtime: {} };
                    """)
                    
                    page = context.new_page()
                    alt_url = url.replace("/gp/product/", "/dp/") if "/gp/product/" in url else url.replace("/dp/", "/gp/product/")
                    content = None
                    
                    for target_url in [url, alt_url]:
                        try:
                            page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(1.2)
                            
                            # Trigger lazy loading by scrolling down
                            try:
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                                time.sleep(0.5)
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                time.sleep(0.5)
                            except Exception:
                                pass
                                
                            page_title = page.title()
                            if "Amazon" in page_title and len(page_title) < 15:
                                time.sleep(1.5)
                                page.reload(wait_until="domcontentloaded")
                                
                            html_text = page.content()
                            if html_text and len(html_text) > 10000:
                                content = html_text
                                break
                        except Exception as e:
                            time.sleep(1.0)
                            
                    browser.close()
                    if content:
                        return content, 200, None
                    return None, 500, "Impossibile recuperare la pagina Amazon"
            except ImportError:
                return None, 500, "Playwright fallback not installed"
            except Exception as e:
                logger.error(f"Playwright execution error for {url}: {e}")
                return None, 500, f"Playwright error: {str(e)}"

        try:
            return _exec_sync()
        except Exception as te:
            logger.error(f"Execution error for Playwright on {url}: {te}")
            return None, 500, f"Playwright execution error: {str(te)}"

    def check_single_marketplace_fast(self, asin: str, marketplace: str) -> Dict[str, Any]:
        """
        Lightweight check to verify if product exists on a specific marketplace and parse its details.
        """
        prod_url = get_product_url(asin, marketplace)
        headers = get_headers(marketplace)
        meta = MARKETPLACES.get(marketplace, {})
        flag = meta.get("flag", "🌐")
        name = meta.get("name", marketplace)
        code = meta.get("code", "")

        try:
            resp = requests.get(prod_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                html = resp.text
                if not is_blocked_or_unavailable(html, BeautifulSoup(html, "html.parser")):
                    soup = BeautifulSoup(html, "html.parser")
                    title_elem = soup.find("span", {"id": "productTitle"}) or soup.find("h1")
                    title = title_elem.get_text(strip=True) if title_elem else None
                    
                    if not title:
                        title_tag = soup.find("title")
                        if title_tag:
                            raw = title_tag.get_text(strip=True).split(" : ")[0].split(" | ")[0]
                            if not raw.startswith("Amazon") and len(raw) > 3:
                                title = raw

                    cover = extract_cover_image(soup)
                    price = extract_product_price(soup)
                    kindle = extract_kindle_details(soup)

                    return {
                        "marketplace": marketplace,
                        "name": name,
                        "code": code,
                        "flag": flag,
                        "found": True,
                        "product_url": prod_url,
                        "title": title,
                        "cover_image_url": cover,
                        "price": price,
                        "has_kindle": kindle["has_kindle"],
                        "kindle_price": kindle["kindle_price"]
                    }
            elif resp.status_code == 404:
                return {
                    "marketplace": marketplace,
                    "name": name,
                    "code": code,
                    "flag": flag,
                    "found": False,
                    "product_url": prod_url,
                    "title": None,
                    "cover_image_url": None,
                    "price": None,
                    "has_kindle": False,
                    "kindle_price": None
                }
        except Exception as e:
            logger.info(f"Fast check error for {marketplace}: {e}")

        # If HTTP didn't confirm, treat as not found or fallback
        return {
            "marketplace": marketplace,
            "name": name,
            "code": code,
            "flag": flag,
            "found": False,
            "product_url": prod_url,
            "title": None,
            "cover_image_url": None,
            "price": None,
            "has_kindle": False,
            "kindle_price": None
        }

    def check_asin_across_all_marketplaces(self, asin: str) -> Dict[str, Any]:
        """
        Scans all 14 Amazon KDP marketplaces in parallel to detect book existence,
        download cover image, prices, and title.
        """
        clean_asin = asin.strip().upper()
        results: List[Dict[str, Any]] = []

        # Run parallel checks across all 14 stores
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_mkt = {
                executor.submit(self.check_single_marketplace_fast, clean_asin, mkt): mkt
                for mkt in MARKETPLACES.keys()
            }
            for future in concurrent.futures.as_completed(future_to_mkt):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as ex:
                    mkt = future_to_mkt[future]
                    meta = MARKETPLACES.get(mkt, {})
                    results.append({
                        "marketplace": mkt,
                        "name": meta.get("name", mkt),
                        "code": meta.get("code", ""),
                        "flag": meta.get("flag", "🌐"),
                        "found": False,
                        "product_url": get_product_url(clean_asin, mkt),
                        "title": None,
                        "cover_image_url": None,
                        "price": None,
                        "has_kindle": False,
                        "kindle_price": None
                    })

        # Preserve standard order of marketplaces
        ordered_results = []
        for mkt_key in MARKETPLACES.keys():
            matching = next((r for r in results if r["marketplace"] == mkt_key), None)
            if matching:
                ordered_results.append(matching)

        # If Italian/primary marketplace wasn't found or got blocked via fast HTTP, try full fetch
        it_res = next((r for r in ordered_results if r["marketplace"] == "amazon.it"), None)
        best_title = None
        best_cover = None
        best_price = None
        has_any_kindle = False
        kindle_price_best = None

        for r in ordered_results:
            if r.get("found"):
                if r.get("title") and not best_title:
                    best_title = r["title"]
                if r.get("cover_image_url") and not best_cover:
                    best_cover = r["cover_image_url"]
                if r.get("price") and not best_price:
                    best_price = r["price"]
                if r.get("has_kindle"):
                    has_any_kindle = True
                    if r.get("kindle_price") and not kindle_price_best:
                        kindle_price_best = r["kindle_price"]

        # If no result found across all marketplaces via fast HTTP, try single deep fetch on amazon.it
        if not any(r["found"] for r in ordered_results):
            content, code, _ = self.fetch_reviews_page(clean_asin, "amazon.it")
            if content and code == 200:
                parsed = parse_amazon_reviews(content, clean_asin, "amazon.it")
                if parsed.get("product_title"):
                    best_title = parsed["product_title"]
                    best_cover = parsed.get("cover_image_url")
                    best_price = parsed.get("price")
                    has_any_kindle = parsed.get("has_kindle", False)
                    kindle_price_best = parsed.get("kindle_price")
                    
                    # Mark amazon.it as found
                    for r in ordered_results:
                        if r["marketplace"] == "amazon.it":
                            r["found"] = True
                            r["title"] = best_title
                            r["cover_image_url"] = best_cover
                            r["price"] = best_price
        # In Amazon KDP, a published book ASIN is global across all 14 stores.
        # If confirmed on at least one store, mark all 14 marketplaces as available
        # and distribute the best title, cover image, and metadata.
        if best_title:
            from app.reviews.statistics import format_marketplace_price
            for r in ordered_results:
                r["found"] = True
                if not r.get("title"):
                    r["title"] = best_title
                if not r.get("cover_image_url"):
                    r["cover_image_url"] = best_cover
                raw_p = r.get("price") or best_price
                if raw_p:
                    r["price"] = format_marketplace_price(raw_p, r["marketplace"])
                if has_any_kindle:
                    r["has_kindle"] = True
                raw_kp = r.get("kindle_price") or kindle_price_best
                if raw_kp:
                    r["kindle_price"] = format_marketplace_price(raw_kp, r["marketplace"])

        found_count = sum(1 for r in ordered_results if r["found"])

        return {
            "asin": clean_asin,
            "title": best_title or f"Libro KDP ({clean_asin})",
            "cover_image_url": best_cover,
            "price": best_price,
            "has_kindle": has_any_kindle,
            "kindle_price": kindle_price_best,
            "total_marketplaces": len(ordered_results),
            "found_count": found_count,
            "marketplaces": ordered_results
        }

    def fetch_product_title(self, asin: str, marketplace: str = "amazon.it") -> Optional[str]:
        """Fetches product title directly from Amazon given an ASIN."""
        content, code, _ = self.fetch_reviews_page(asin, marketplace)
        if content:
            soup = BeautifulSoup(content, "html.parser")
            tag = soup.find("span", {"id": "productTitle"}) or soup.find("h1")
            if tag:
                title = tag.get_text(strip=True)
                if title:
                    return title
            title_tag = soup.find("title")
            if title_tag:
                raw_t = title_tag.get_text(strip=True)
                raw_t = raw_t.split(" : ")[0].split(" : Amazon")[0].split(" | Amazon")[0]
                if len(raw_t) > 3 and not raw_t.startswith("Amazon"):
                    return raw_t
        return None
