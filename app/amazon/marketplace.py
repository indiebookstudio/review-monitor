from typing import Dict, Optional
import urllib.parse

MARKETPLACES: Dict[str, Dict[str, str]] = {
    "amazon.it": {
        "code": "IT",
        "name": "Italia",
        "domain": "amazon.it",
        "base_url": "https://www.amazon.it",
        "flag": "🇮🇹",
        "country": "it",
        "currency": "EUR",
        "symbol": "€"
    },
    "amazon.com": {
        "code": "US",
        "name": "United States",
        "domain": "amazon.com",
        "base_url": "https://www.amazon.com",
        "flag": "🇺🇸",
        "country": "us",
        "currency": "USD",
        "symbol": "$"
    },
    "amazon.co.uk": {
        "code": "UK",
        "name": "United Kingdom",
        "domain": "amazon.co.uk",
        "base_url": "https://www.amazon.co.uk",
        "flag": "🇬🇧",
        "country": "gb",
        "currency": "GBP",
        "symbol": "£"
    },
    "amazon.de": {
        "code": "DE",
        "name": "Deutschland",
        "domain": "amazon.de",
        "base_url": "https://www.amazon.de",
        "flag": "🇩🇪",
        "country": "de",
        "currency": "EUR",
        "symbol": "€"
    },
    "amazon.fr": {
        "code": "FR",
        "name": "France",
        "domain": "amazon.fr",
        "base_url": "https://www.amazon.fr",
        "flag": "🇫🇷",
        "country": "fr",
        "currency": "EUR",
        "symbol": "€"
    },
    "amazon.es": {
        "code": "ES",
        "name": "España",
        "domain": "amazon.es",
        "base_url": "https://www.amazon.es",
        "flag": "🇪🇸",
        "country": "es",
        "currency": "EUR",
        "symbol": "€"
    },
    "amazon.nl": {
        "code": "NL",
        "name": "Nederland",
        "domain": "amazon.nl",
        "base_url": "https://www.amazon.nl",
        "flag": "🇳🇱",
        "country": "nl",
        "currency": "EUR",
        "symbol": "€"
    },
    "amazon.pl": {
        "code": "PL",
        "name": "Polska",
        "domain": "amazon.pl",
        "base_url": "https://www.amazon.pl",
        "flag": "🇵🇱",
        "country": "pl",
        "currency": "PLN",
        "symbol": "zł"
    },
    "amazon.se": {
        "code": "SE",
        "name": "Sverige",
        "domain": "amazon.se",
        "base_url": "https://www.amazon.se",
        "flag": "🇸🇪",
        "country": "se",
        "currency": "SEK",
        "symbol": "kr"
    },
    "amazon.com.be": {
        "code": "BE",
        "name": "Belgique / België",
        "domain": "amazon.com.be",
        "base_url": "https://www.amazon.com.be",
        "flag": "🇧🇪",
        "country": "be",
        "currency": "EUR",
        "symbol": "€"
    },
    "amazon.ie": {
        "code": "IE",
        "name": "Ireland",
        "domain": "amazon.ie",
        "base_url": "https://www.amazon.ie",
        "flag": "🇮🇪",
        "country": "ie",
        "currency": "EUR",
        "symbol": "€"
    },
    "amazon.co.jp": {
        "code": "JP",
        "name": "Japan (日本)",
        "domain": "amazon.co.jp",
        "base_url": "https://www.amazon.co.jp",
        "flag": "🇯🇵",
        "country": "jp",
        "currency": "JPY",
        "symbol": "¥"
    },
    "amazon.ca": {
        "code": "CA",
        "name": "Canada",
        "domain": "amazon.ca",
        "base_url": "https://www.amazon.ca",
        "flag": "🇨🇦",
        "country": "ca",
        "currency": "CAD",
        "symbol": "CA$"
    },
    "amazon.com.au": {
        "code": "AU",
        "name": "Australia",
        "domain": "amazon.com.au",
        "base_url": "https://www.amazon.com.au",
        "flag": "🇦🇺",
        "country": "au",
        "currency": "AUD",
        "symbol": "AU$"
    }
}

def normalize_marketplace(marketplace: str) -> str:
    m = marketplace.lower().strip()
    if m.startswith("https://") or m.startswith("http://"):
        parsed = urllib.parse.urlparse(m)
        m = parsed.netloc.replace("www.", "")
    elif m.startswith("www."):
        m = m.replace("www.", "")
    
    if m in MARKETPLACES:
        return m
        
    # Check by country code (e.g. 'it', 'us', 'uk', 'de', etc.)
    for domain, data in MARKETPLACES.items():
        if data.get("code", "").lower() == m:
            return domain
            
    # Fallback search by domain match
    for key in MARKETPLACES:
        if key in m:
            return key
            
    return "amazon.it"

def get_product_url(asin: str, marketplace: str = "amazon.it") -> str:
    norm_m = normalize_marketplace(marketplace)
    base = MARKETPLACES.get(norm_m, {}).get("base_url", "https://www.amazon.it")
    return f"{base}/dp/{asin.strip().upper()}"

def get_reviews_url(asin: str, marketplace: str = "amazon.it", sort_by_recent: bool = True) -> str:
    norm_m = normalize_marketplace(marketplace)
    base = MARKETPLACES.get(norm_m, {}).get("base_url", "https://www.amazon.it")
    sort_param = "&sortBy=recent" if sort_by_recent else ""
    return f"{base}/product-reviews/{asin.strip().upper()}?reviewerType=all_reviews{sort_param}"

def get_review_url(asin: str, review_id: str, marketplace: str = "amazon.it") -> str:
    norm_m = normalize_marketplace(marketplace)
    base = MARKETPLACES.get(norm_m, {}).get("base_url", "https://www.amazon.it")
    if review_id and review_id.startswith("R"):
        return f"{base}/gp/customer-reviews/{review_id}"
    return get_product_url(asin, marketplace)
