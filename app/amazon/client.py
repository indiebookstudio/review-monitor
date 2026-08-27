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
    is_blocked_or_unavailable
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

    def fetch_reviews_page(self, asin: str, marketplace: str = "amazon.it") -> Tuple[Optional[str], int, Optional[str]]:
        """
        Fetches the product page for an ASIN.
        """
        prod_url = get_product_url(asin, marketplace)
        headers = get_headers(marketplace)
        
        logger.info(f"Fetching page for ASIN {asin} on {marketplace}...")
        
        # 1. HTTP Request fast attempt
        try:
            from bs4 import BeautifulSoup
            session = requests.Session()
            response = session.get(prod_url, headers=headers, timeout=12)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                if not is_blocked_or_unavailable(response.text, soup):
                    return response.text, 200, None
            elif response.status_code == 404:
                return None, 404, "Page not found (HTTP 404)"
        except Exception as http_e:
            logger.info(f"Fast HTTP fetch failed for {marketplace}: {http_e}")

        # 2. Try Playwright if enabled
        if self.use_playwright:
            content, code, err = self._fetch_playwright(prod_url)
            if content and code == 200:
                return content, 200, None

        return None, 500, "Impossibile recuperare la pagina Amazon"

    def _fetch_playwright(self, url: str) -> Tuple[Optional[str], int, Optional[str]]:
        """Playwright execution in a dedicated thread to safely isolate from any asyncio event loops."""
        def _exec_sync():
            try:
                from playwright.sync_api import sync_playwright
                logger.info(f"Fetching {url} via Playwright Stealth in worker thread...")
                with sync_playwright() as p:
                    try:
                        browser = p.chromium.launch(
                            headless=True,
                            channel="chrome",
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--no-sandbox",
                                "--disable-setuid-sandbox"
                            ]
                        )
                    except Exception:
                        browser = p.chromium.launch(
                            headless=True,
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--no-sandbox",
                                "--disable-setuid-sandbox"
                            ]
                        )
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        locale="it-IT",
                        timezone_id="Europe/Rome",
                        viewport={"width": 1280, "height": 800}
                    )
                    page = context.new_page()
                    alt_url = url.replace("/gp/product/", "/dp/") if "/gp/product/" in url else url.replace("/dp/", "/gp/product/")
                    content = None
                    for target_url in [url, alt_url]:
                        try:
                            page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(1.0)
                            page_title = page.title()
                            if "Amazon" in page_title and len(page_title) < 15:
                                time.sleep(1.5)
                                page.reload(wait_until="domcontentloaded")
                            html_text = page.content()
                            if html_text and len(html_text) > 15000:
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
