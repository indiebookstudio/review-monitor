import re
import json
import logging
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup

from app.amazon.marketplace import get_review_url, get_product_url

logger = logging.getLogger(__name__)

STATUS_OK = "OK"
STATUS_NO_REVIEWS = "NO_REVIEWS"
STATUS_PAGE_UNAVAILABLE = "PAGE_UNAVAILABLE"
STATUS_PARSER_ERROR = "PARSER_ERROR"

def extract_rating(text: str) -> Optional[float]:
    if not text:
        return None
    # Matches patterns like "5.0 out of 5 stars", "4,5 su 5 stelle", "5 von 5 Sternen", "5,0 sur 5 étoiles"
    match = re.search(r'([0-9]+[.,]?[0-9]*)\s*(?:out of|su|von|sur|de|van|z|po)\s*5', text, re.IGNORECASE)
    if match:
        val_str = match.group(1).replace(",", ".")
        try:
            return float(val_str)
        except ValueError:
            pass
    # Simple fallback: "5.0 stars"
    match_simple = re.search(r'([1-5](?:[.,][0-9])?)', text)
    if match_simple:
        try:
            return float(match_simple.group(1).replace(",", "."))
        except ValueError:
            pass
    return None

def is_blocked_or_unavailable(html: str, soup: BeautifulSoup) -> bool:
    if not html or len(html.strip()) == 0:
        return True
        
    html_lower = html.lower()
    
    # Captcha / Robot checks
    if "enter the characters you see below" in html_lower or \
       "robot check" in html_lower or \
       "api-services-support@amazon.com" in html_lower or \
       "type the characters you see in this image" in html_lower:
        return True
    
    # Sign-in redirects / Auth walls
    if "ap/signin" in html_lower or \
       "openid.return_to" in html_lower or \
       "accedi o crea un account" in html_lower:
        title_tag = soup.find("title")
        if title_tag:
            t_text = title_tag.get_text(strip=True).lower()
            if any(s in t_text for s in ["accedi", "sign in", "sign-in", "anmelden", "identifiez-vous", "iniciar sesión", "inicia sesión"]):
                return True

    # Amazon Dog / 404 / Unavailable
    if "looking for something?" in html_lower or \
       "dogs of amazon" in html_lower or \
       "sorry! we couldn't find that page" in html_lower:
        return True
        
    return False

def is_no_reviews_page(html: str, soup: BeautifulSoup) -> bool:
    html_lower = html.lower()
    
    no_review_phrases = [
        "no customer reviews",
        "nessuna recensione",
        "0 customer reviews",
        "0 recensioni cliente",
        "there are no customer reviews",
        "no reviews yet",
        "keine kundenrezensionen",
        "aucun commentaire client",
        "no hay opiniones de clientes",
        "geen klantbeoordelingen",
        "brak recenzji",
        "inga kundrecensioner"
    ]
    
    for phrase in no_review_phrases:
        if phrase in html_lower:
            return True
            
    # Check for empty review elements
    no_review_elem = soup.find("div", {"data-hook": "empty-search-review-results"}) or \
                     soup.find("div", {"id": "no-reviews-filter-search-msg"})
    if no_review_elem:
        return True
        
    return False

def extract_cover_image(soup: BeautifulSoup) -> Optional[str]:
    """Extracts high quality book cover image URL from Amazon product page."""
    # 1. Check landingImage data-a-dynamic-image (JSON with high-res URLs)
    landing_img = soup.find("img", {"id": "landingImage"}) or \
                  soup.find("img", {"id": "imgBlkFront"}) or \
                  soup.find("img", {"id": "ebooksImgBlkFront"}) or \
                  soup.find("img", {"id": "main-image"})
    
    if landing_img:
        dynamic_data = landing_img.get("data-a-dynamic-image")
        if dynamic_data:
            try:
                img_dict = json.loads(dynamic_data)
                if img_dict and isinstance(img_dict, dict):
                    # Sort by resolution (largest width * height)
                    best_url = max(img_dict.items(), key=lambda item: item[1][0] * item[1][1])[0]
                    if best_url and best_url.startswith("http"):
                        return best_url
            except Exception:
                pass
        
        hires = landing_img.get("data-old-hires")
        if hires and hires.startswith("http"):
            return hires
            
        src = landing_img.get("src")
        if src and src.startswith("http") and not src.endswith(".gif"):
            return src

    # 2. Check OpenGraph meta image
    og_img = soup.find("meta", {"property": "og:image"})
    if og_img and og_img.get("content"):
        content = og_img.get("content").strip()
        if content.startswith("http") and not "no-img" in content:
            return content

    # 3. Check any dynamic book image container
    front_img = soup.find("img", {"class": lambda c: c and "frontImage" in c}) or \
                soup.find("img", {"class": lambda c: c and "a-dynamic-image" in c})
    if front_img:
        src = front_img.get("src")
        if src and src.startswith("http") and not src.endswith(".gif"):
            return src

    return None

def extract_product_price(soup: BeautifulSoup) -> Optional[str]:
    """Extracts paperback/current product price from page across all global marketplaces."""
    # 1. Check Paperback swatch explicitly if present
    for swatch in soup.find_all(["li", "div"], class_=lambda c: c and "swatch" in c.lower()):
        text = swatch.get_text(" ", strip=True)
        if any(w in text.lower() for w in ["paperback", "copertina flessibile", "taschenbuch", "broché", "tapa blanda", "pasta blanda"]):
            slot = swatch.find(class_=lambda c: c and "slot-price" in c) or swatch.find("span", class_="a-price")
            if slot:
                off = slot.find("span", class_="a-offscreen")
                t = off.get_text(strip=True) if off else slot.get_text(strip=True)
                if t and not any(z in t for z in ["0.00", "0,00"]):
                    return t.replace("\xa0", " ").strip()

    selectors = [
        ("span", {"id": "price_inside_buybox"}),
        ("span", {"id": "price"}),
        ("div", {"id": "corePrice_feature_div"}),
        ("div", {"id": "corePriceDisplay_desktop_feature_div"}),
        ("div", {"id": "booksHeaderSection"}),
        ("span", {"class": "a-price"}),
        ("span", {"class": "slot-price"}),
        ("div", {"id": "apex_desktop"}),
    ]
    
    # 2. Search inside specific price elements
    for tag, attrs in selectors:
        elem = soup.find(tag, attrs)
        if elem:
            offscreen = elem.find("span", {"class": "a-offscreen"})
            if offscreen and offscreen.get_text(strip=True):
                p_text = offscreen.get_text(strip=True).replace("\xa0", " ")
                if re.search(r'\d', p_text) and not any(w in p_text.lower() for w in ["0,00", "0.00", "spedizione", "shipping"]):
                    return p_text
            p_text = elem.get_text(strip=True).replace("\xa0", " ")
            m = re.search(r'([€$£¥złkrCA$AU$A$C$]|EUR|USD|GBP|CAD|AUD|JPY|PLN|SEK)\s*[\d.,]+|[\d.,]+\s*([€$£¥złkr]|EUR|USD|GBP|CAD|AUD|JPY|PLN|SEK)', p_text)
            if m and not any(w in m.group(0) for w in ["0,00", "0.00"]):
                return m.group(0).strip()
                
    # 3. Search anywhere for a-offscreen with price
    all_offscreen = soup.find_all("span", {"class": "a-offscreen"})
    for s in all_offscreen:
        txt = s.get_text(strip=True).replace("\xa0", " ")
        if re.search(r'([€$£¥złkrCA$AU$A$C$]|EUR|USD|GBP|CAD|AUD|JPY|PLN|SEK)\s*[\d.,]+|[\d.,]+\s*([€$£¥złkr]|EUR|USD|GBP|CAD|AUD|JPY|PLN|SEK)', txt):
            if not any(w in txt.lower() for w in ["0,00", "0.00", "spedizione", "shipping", "livraison", "delivery", "versand"]):
                return txt

    return None

def extract_kindle_details(soup: BeautifulSoup) -> Dict[str, Any]:
    """
    Detects if Kindle version exists on this product and extracts Kindle purchase price (not Kindle Unlimited 0,00).
    """
    has_kindle = False
    kindle_price = None
    kindle_asin = None
    kindle_swatch = None
    
    # Swatches / format tabs (e.g. #tmmSwatches, #formats, .swatchElement)
    swatch_blocks = soup.find_all("li", {"class": lambda c: c and "swatchElement" in c}) or \
                    soup.find_all("div", {"class": lambda c: c and "swatchElement" in c}) or \
                    soup.find_all("div", {"id": lambda i: i and "swatch" in i.lower()})

    for swatch in swatch_blocks:
        stext = swatch.get_text(" ", strip=True).lower()
        if "kindle" in stext or "ebook" in stext or "formato kindle" in stext or "kindle edition" in stext or "kindle-editie" in stext or "kindle ausgabe" in stext:
            has_kindle = True
            kindle_swatch = swatch
            
            # Extract Kindle purchase price from swatch (ignore 0,00 or Kindle Unlimited)
            # Find all potential price tags in swatch
            price_spans = swatch.find_all(["span", "div", "p"])
            for ps in price_spans:
                ptxt = ps.get_text(strip=True)
                if "0,00" in ptxt or "0.00" in ptxt or "unlimited" in ptxt.lower() or "gratis" in ptxt.lower():
                    continue
                m = re.search(r'([€$£¥złkrCA$AU$]\s*[1-9][\d.,]*|[1-9][\d.,]*\s*[€$£¥złkr])', ptxt)
                if m:
                    kindle_price = m.group(1).strip()
                    break
                    
            # Kindle link/asin
            klink = swatch.find("a")
            if klink and klink.get("href"):
                href = klink.get("href")
                m_asin = re.search(r'/dp/([A-Z0-9]{10})', href)
                if m_asin:
                    kindle_asin = m_asin.group(1)
            break

    # If price was not found or is None, search in full page buybox/ebook areas
    if has_kindle and not kindle_price:
        # Check specific Amazon Kindle purchase elements
        kindle_price_selectors = [
            soup.find("span", {"id": "kindle-price"}),
            soup.find("span", {"id": "ebooks-price"}),
            soup.find("span", {"id": "digital-list-price"}),
            soup.find("span", {"id": "price"})
        ]
        for sel in kindle_price_selectors:
            if sel:
                txt = sel.get_text(strip=True)
                if "0,00" not in txt and "0.00" not in txt:
                    m = re.search(r'([€$£¥złkrCA$AU$]\s*[1-9][\d.,]*|[1-9][\d.,]*\s*[€$£¥złkr])', txt)
                    if m:
                        kindle_price = m.group(1).strip()
                        break

    # If still not found, search purchase phrase in text: "per acquistare", "to buy", "o € X per acquistare"
    if has_kindle and not kindle_price:
        soup_text = soup.get_text(" ")
        buy_patterns = [
            r'([€$£¥złkrCA$AU$]\s*[1-9][\d.,]*|[1-9][\d.,]*\s*[€$£¥złkr])\s*(?:per acquistare|da acquistare|to buy|Kaufen|pour acheter|para comprar|om te kopen|do kupienia)',
            r'(?:per acquistare|da acquistare|to buy|Kaufen|pour acheter|para comprar|om te kopen|do kupienia)\s*[:\s]*([€$£¥złkrCA$AU$]\s*[1-9][\d.,]*|[1-9][\d.,]*\s*[€$£¥złkr])',
            r'Prezzo di acquisto\s*[:\s]*([€$£¥złkrCA$AU$]\s*[1-9][\d.,]*|[1-9][\d.,]*\s*[€$£¥złkr])',
            r'Purchase price\s*[:\s]*([€$£¥złkrCA$AU$]\s*[1-9][\d.,]*|[1-9][\d.,]*\s*[€$£¥złkr])'
        ]
        for pat in buy_patterns:
            m = re.search(pat, soup_text, re.IGNORECASE)
            if m:
                kindle_price = m.group(1).strip()
                break

    # If not found in swatches, check full page text for Kindle edition references
    if not has_kindle:
        kindle_tab = soup.find("a", href=re.compile(r'/dp/[A-Z0-9]{10}.*format.*kindle', re.IGNORECASE)) or \
                     soup.find("div", {"id": "mediaTab_heading_eBook"}) or \
                     soup.find("span", string=re.compile(r'Formato Kindle|Kindle Edition|Kindle Ausgabe', re.IGNORECASE))
        if kindle_tab:
            has_kindle = True
            k_price_elem = soup.find("span", {"id": "kindle-price"})
            if k_price_elem:
                txt = k_price_elem.get_text(strip=True)
                if "0,00" not in txt and "0.00" not in txt:
                    m = re.search(r'([€$£¥złkrCA$AU$]\s*[1-9][\d.,]*|[1-9][\d.,]*\s*[€$£¥złkr])', txt)
                    if m:
                        kindle_price = m.group(1).strip()

    return {
        "has_kindle": has_kindle,
        "kindle_price": kindle_price or ("Disponibile" if has_kindle else None),
        "kindle_asin": kindle_asin
    }

def parse_amazon_reviews(html: str, asin: str, marketplace: str = "amazon.it") -> Dict[str, Any]:
    if not html:
        return {
            "status": STATUS_PAGE_UNAVAILABLE,
            "error": "HTML content is empty",
            "reviews": [],
            "total_reviews": 0,
            "average_rating": None,
            "cover_image_url": None,
            "price": None,
            "has_kindle": False,
            "kindle_price": None
        }

    soup = BeautifulSoup(html, "html.parser")

    if is_blocked_or_unavailable(html, soup):
        return {
            "status": STATUS_PAGE_UNAVAILABLE,
            "error": "Amazon page is blocked, requires captcha, or is unavailable",
            "reviews": [],
            "total_reviews": 0,
            "average_rating": None,
            "cover_image_url": None,
            "price": None,
            "has_kindle": False,
            "kindle_price": None
        }

    # Extract metadata (cover, price, kindle)
    cover_image_url = extract_cover_image(soup)
    price = extract_product_price(soup)
    kindle_info = extract_kindle_details(soup)

    reviews: List[Dict[str, Any]] = []

    # Review containers (multiple fallback selectors)
    review_elements = soup.find_all("div", {"data-hook": "review"})
    if not review_elements:
        review_elements = soup.find_all("div", {"class": lambda c: c and "review" in c and "a-section" in c})
    if not review_elements:
        review_elements = soup.find_all("div", id=re.compile(r"^customer_review-R[A-Z0-9]+"))

    # Product title
    product_title_str = None
    title_tag = soup.find("span", {"id": "productTitle"}) or soup.find("h1")
    if title_tag:
        product_title_str = title_tag.get_text(strip=True)
    if not product_title_str:
        title_tag = soup.find("title")
        if title_tag:
            raw_t = title_tag.get_text(strip=True)
            raw_t = raw_t.split(" : ")[0].split(" : Amazon")[0].split(" | Amazon")[0]
            if len(raw_t) > 3 and not raw_t.startswith("Amazon"):
                product_title_str = raw_t

    if not review_elements:
        if is_no_reviews_page(html, soup):
            return {
                "status": STATUS_NO_REVIEWS,
                "error": None,
                "product_title": product_title_str,
                "cover_image_url": cover_image_url,
                "price": price,
                "has_kindle": kindle_info["has_kindle"],
                "kindle_price": kindle_info["kindle_price"],
                "reviews": [],
                "total_reviews": 0,
                "average_rating": None
            }
        
        # If we have product details or title, but 0 review containers and not explicit no_reviews
        if product_title_str or soup.find("a", {"data-hook": "product-link"}):
            return {
                "status": STATUS_NO_REVIEWS,
                "error": None,
                "product_title": product_title_str,
                "cover_image_url": cover_image_url,
                "price": price,
                "has_kindle": kindle_info["has_kindle"],
                "kindle_price": kindle_info["kindle_price"],
                "reviews": [],
                "total_reviews": 0,
                "average_rating": None
            }
        
        return {
            "status": STATUS_PARSER_ERROR,
            "error": "Could not identify review elements or product indicators in HTML",
            "product_title": None,
            "cover_image_url": None,
            "price": None,
            "has_kindle": False,
            "kindle_price": None,
            "reviews": [],
            "total_reviews": 0,
            "average_rating": None
        }

    for elem in review_elements:
        # Review ID
        review_id = elem.get("id", "")
        if not review_id:
            id_tag = elem.find(id=re.compile(r"^customer_review-R[A-Z0-9]+"))
            if id_tag:
                review_id = id_tag.get("id", "").replace("customer_review-", "")
        else:
            review_id = review_id.replace("customer_review-", "")

        # Strictly validate that this is a real Amazon Review ID (must start with R and be alphanumeric)
        if not review_id or "ADPlaceholder" in review_id or "ad-placeholder" in review_id.lower() or not re.match(r"^R[A-Z0-9]{4,35}$", review_id):
            continue
            
        # Rating
        rating_elem = elem.find("i", {"data-hook": "review-star-rating"}) or \
                      elem.find("i", {"data-hook": "cmps-review-star-rating"}) or \
                      elem.find("span", {"class": "a-icon-alt"}) or \
                      elem.find("i", {"class": lambda c: c and "a-star-" in c})
        
        rating = None
        if rating_elem:
            rating = extract_rating(rating_elem.get_text(strip=True))
        if rating is None:
            rating = 5.0

        # Title
        title_elem = elem.find("a", {"data-hook": "review-title"}) or \
                     elem.find("span", {"data-hook": "review-title"}) or \
                     elem.find("a", {"class": lambda c: c and "review-title" in c})
        title = ""
        if title_elem:
            sub_span = title_elem.find("span", recursive=False)
            if sub_span:
                title = sub_span.get_text(strip=True)
            else:
                title = title_elem.get_text(strip=True)
            title = re.sub(r'^[0-9]+[.,]?[0-9]*\s*(?:out of|su|von|sur|de|van|z|po)\s*5\s*(?:stars|stelle|sternen|étoiles|gwiazdek)?', '', title, flags=re.IGNORECASE).strip()

        # Body
        body_elem = elem.find("span", {"data-hook": "review-body"}) or \
                    elem.find("div", {"data-hook": "review-collapsed"}) or \
                    elem.find("span", {"class": lambda c: c and "review-text" in c})
        body = ""
        if body_elem:
            body = body_elem.get_text("\n", strip=True)

        # Author
        author_elem = elem.find("span", {"class": "a-profile-name"}) or \
                      elem.find("div", {"data-hook": "genome-widget"})
        author = "Cliente Amazon"
        if author_elem:
            author = author_elem.get_text(strip=True) or author

        # Date
        date_elem = elem.find("span", {"data-hook": "review-date"})
        review_date = ""
        if date_elem:
            review_date = date_elem.get_text(strip=True)

        # Review URL
        review_url_elem = elem.find("a", {"data-hook": "review-title"}) or elem.find("a", {"class": lambda c: c and "review-title" in c})
        review_url = None
        if review_url_elem and review_url_elem.get("href"):
            href = review_url_elem.get("href")
            if href.startswith("http"):
                review_url = href
            else:
                from app.amazon.marketplace import MARKETPLACES, normalize_marketplace
                norm_m = normalize_marketplace(marketplace)
                base = MARKETPLACES.get(norm_m, {}).get("base_url", "https://www.amazon.it")
                review_url = f"{base}{href}"
        
        if not review_url:
            review_url = get_review_url(asin, review_id, marketplace)

        if not title:
            title = f"Valutazione a {int(rating)} stelle"

        # Customer Images & Media in review
        review_images = []
        img_tags = elem.find_all("img", {"class": lambda c: c and "review-image" in c}) or \
                   elem.find_all("img", {"alt": lambda a: a and "customer image" in a.lower()}) or \
                   elem.find_all("img", {"data-hook": "review-image-tile"})
        for itag in img_tags:
            isrc = itag.get("data-old-hires") or itag.get("data-src") or itag.get("src")
            if isrc and isrc.startswith("http") and not isrc.endswith(".gif") and not "no-img" in isrc:
                hi_src = re.sub(r'\._[A-Z0-9_,]+_\.', '.', isrc)
                review_images.append(hi_src if hi_src.startswith("http") else isrc)

        review_video = None
        vid_tag = elem.find("video") or elem.find("div", {"class": lambda c: c and "video" in c})
        if vid_tag:
            src_attr = vid_tag.get("src")
            if not src_attr:
                source_sub = vid_tag.find("source")
                if source_sub:
                    src_attr = source_sub.get("src")
            if src_attr and src_attr.startswith("http"):
                review_video = src_attr

        if review_id:
            reviews.append({
                "review_id": review_id,
                "rating": rating,
                "title": title,
                "body": body,
                "author": author,
                "review_date": review_date,
                "review_url": review_url,
                "images": review_images,
                "video_url": review_video
            })

    # Page aggregate stats
    total_reviews = len(reviews)
    total_elem = soup.find("div", {"data-hook": "total-review-count"}) or \
                 soup.find("span", {"data-hook": "total-review-count"}) or \
                 soup.find("span", {"id": "acrCustomerReviewText"})
    if total_elem:
        total_text = total_elem.get_text(strip=True)
        m_tot = re.search(r'([0-9.,]+)', total_text)
        if m_tot:
            try:
                total_reviews = int(m_tot.group(1).replace(".", "").replace(",", ""))
            except ValueError:
                pass

    avg_rating = None
    avg_elem = soup.find("span", {"data-hook": "rating-out-of-text"}) or \
               soup.find("i", {"data-hook": "average-star-rating"}) or \
               soup.find("span", {"id": "acrPopover"})
    if avg_elem:
        avg_rating = extract_rating(avg_elem.get("title", "") or avg_elem.get_text(strip=True))

    return {
        "status": STATUS_OK,
        "error": None,
        "product_title": product_title_str,
        "cover_image_url": cover_image_url,
        "price": price,
        "has_kindle": kindle_info["has_kindle"],
        "kindle_price": kindle_info["kindle_price"],
        "kindle_asin": kindle_info.get("kindle_asin"),
        "reviews": reviews,
        "total_reviews": max(len(reviews), total_reviews),
        "average_rating": avg_rating
    }
