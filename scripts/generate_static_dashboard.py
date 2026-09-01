#!/usr/bin/env python3
"""
Generates the clean, table-based, sortable KDP dashboard for GitHub Pages
with marketplace switcher bar, sortable columns, + Aggiungi Libro and 🔄 Forza Controllo.
Outputs to docs/index.html.
"""
import os
import sys
import re
import json
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import SessionLocal
from app.models import Book, Review
from app.reviews.statistics import get_dashboard_kpis
from app.amazon.marketplace import MARKETPLACES
from app.amazon.parser import extract_origin_country

MONTHS_MAP = {
    # Italian
    'gennaio': '01', 'febbraio': '02', 'marzo': '03', 'aprile': '04', 'maggio': '05', 'giugno': '06',
    'luglio': '07', 'agosto': '08', 'settembre': '09', 'ottobre': '10', 'novembre': '11', 'dicembre': '12',
    # English
    'january': '01', 'february': '02', 'march': '03', 'april': '04', 'may': '05', 'june': '06',
    'july': '07', 'august': '08', 'september': '09', 'october': '10', 'november': '11', 'december': '12',
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'jun': '06', 'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    # French
    'janvier': '01', 'février': '02', 'fevrier': '02', 'mars': '03', 'avril': '04', 'mai': '05', 'juin': '06',
    'juillet': '07', 'août': '08', 'aout': '08', 'septembre': '09', 'octobre': '10', 'novembre': '11', 'décembre': '12', 'decembre': '12',
    # German
    'januar': '01', 'februar': '02', 'märz': '03', 'maerz': '03', 'april': '04', 'mai': '05', 'juni': '06', 'juli': '07', 'august': '08', 'september': '09', 'oktober': '10', 'november': '11', 'dezember': '12',
    # Spanish
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04', 'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08', 'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
    # Polish
    'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04', 'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08', 'września': '09', 'wrzesnia': '09', 'października': '10', 'pazdziernika': '10', 'listopada': '11', 'grudnia': '12',
    # Dutch
    'januari': '01', 'februari': '02', 'maart': '03', 'mei': '05', 'augustus': '08',
    # Swedish & Portuguese
    'augusti': '08', 'janeiro': '01', 'fevereiro': '02', 'março': '03', 'marco': '03', 'junho': '06', 'julho': '07',
}

def parse_clean_review_date(date_str: str) -> tuple:
    if not date_str or str(date_str).strip() in ('N/A', '-', 'None', ''):
        return ('-', 0)
    cleaned = str(date_str).lower().strip()
    
    # Japanese format: 2026年7月12日
    m_jp = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', cleaned)
    if m_jp:
        y, m, d = m_jp.groups()
        return (f'{int(d):02d}/{int(m):02d}/{y}', int(f'{y}{int(m):02d}{int(d):02d}'))
        
    # European style: DD Month YYYY (e.g. 12 luglio 2026, 12 de julio de 2026, 12 juillet 2026, op 10 augustus 2026)
    m_eu = re.search(r'(\d{1,2})\.?(?:\s+de|\s+d\'|\s+du|\s+dnia|\s+den|\s+le|\s+il|\s+on|\s+am|\s+op)?\s+([a-zà-ÿ]+)\.?(?:\s+de|\s+del)?\s+(\d{4})', cleaned)
    if m_eu:
        day, m_name, year = m_eu.groups()
        m_num = MONTHS_MAP.get(m_name.strip('.'))
        if m_num:
            return (f'{int(day):02d}/{m_num}/{year}', int(f'{year}{m_num}{int(day):02d}'))
            
    # English style: Month DD, YYYY (e.g. August 2, 2026)
    m_en = re.search(r'([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})', cleaned)
    if m_en:
        m_name, day, year = m_en.groups()
        m_num = MONTHS_MAP.get(m_name.strip('.'))
        if m_num:
            return (f'{int(day):02d}/{m_num}/{year}', int(f'{year}{m_num}{int(day):02d}'))

    # ISO fallback YYYY-MM-DD
    m_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', cleaned)
    if m_iso:
        y, m, d = m_iso.groups()
        return (f'{d}/{m}/{y}', int(f'{y}{m}{d}'))
        
    return ('-', 0)

def format_stars(rating: float) -> str:
    full = int(round(rating or 5.0))
    full = max(1, min(5, full))
    return "★" * full + "☆" * (5 - full)

def generate_static_html(output_path: Path) -> str:
    db = SessionLocal()
    try:
        books = db.query(Book).filter(Book.enabled == True).all()
        reviews = db.query(Review).all()
        kpis = get_dashboard_kpis(db)
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y alle %H:%M UTC")

        # Marketplace stats
        mkt_counts = {}
        for mkt_key, meta in MARKETPLACES.items():
            mkt_counts[mkt_key] = {
                "name": meta.get("name", mkt_key),
                "code": meta.get("code", mkt_key),
                "country": meta.get("country", "it"),
                "flag": meta.get("flag", "🌐"),
                "count": 0
            }

        # Index reviews by book_id
        reviews_by_book = {}
        for r in reviews:
            reviews_by_book.setdefault(r.book_id, []).append(r)
            if r.marketplace in mkt_counts:
                mkt_counts[r.marketplace]["count"] += 1

        # Build table rows data
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        d30 = now_dt - datetime.timedelta(days=30)

        table_rows = []
        for b in books:
            b_revs = reviews_by_book.get(b.id, [])
            rev_count = len(b_revs)
            
            # Avg rating
            if rev_count > 0:
                ratings = [r.rating for r in b_revs if r.rating]
                avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 5.0
            else:
                avg_rating = 0.0

            # New reviews last 30 days
            new_30d = sum(1 for r in b_revs if r.first_seen_at and r.first_seen_at.replace(tzinfo=datetime.timezone.utc if r.first_seen_at.tzinfo is None else None) >= d30)

            # Last review date
            last_date_str = "-"
            last_date_sort = 0
            if rev_count > 0:
                for r in b_revs:
                    f_date, s_date = parse_clean_review_date(r.review_date)
                    if s_date > last_date_sort:
                        last_date_sort = s_date
                        last_date_str = f_date
                if last_date_str == "-":
                    last_created = max(r.first_seen_at for r in b_revs if r.first_seen_at) if b_revs else None
                    if last_created:
                        last_date_str = last_created.strftime("%d/%m/%Y")
                        last_date_sort = int(last_created.strftime("%Y%m%d"))

            # Clean price numeric for sorting
            p_val = 0.0
            if b.price:
                m_p = re.search(r'[\d.,]+', b.price.replace(',', '.'))
                if m_p:
                    try:
                        p_val = float(m_p.group(0))
                    except:
                        p_val = 0.0

            # Reviews data for modal
            modal_reviews = []
            for r in b_revs:
                f_date, _ = parse_clean_review_date(r.review_date)
                c_name, c_flag = extract_origin_country(r.review_date, r.marketplace)
                modal_reviews.append({
                    "id": r.review_id,
                    "rating": r.rating,
                    "stars": format_stars(r.rating),
                    "title": r.title or f"Valutazione {r.rating} stelle",
                    "body": r.body or "(Nessun commento testuale rilasciato)",
                    "author": r.author or "Cliente Amazon",
                    "date": f_date if f_date != '-' else (r.review_date or '-'),
                    "url": r.review_url or b.product_url,
                    "flag": c_flag or "🌐",
                    "country_name": c_name or r.marketplace
                })

            m_meta = MARKETPLACES.get(b.marketplace, {})

            table_rows.append({
                "id": b.id,
                "asin": b.asin,
                "title": b.title or f"Libro {b.asin}",
                "cover": b.cover_image_url or "",
                "marketplace": b.marketplace,
                "mkt_code": m_meta.get("code", b.marketplace),
                "country": m_meta.get("country", "it"),
                "product_url": b.product_url or f"https://www.{b.marketplace}/dp/{b.asin}",
                "price": b.price or "-",
                "price_sort": p_val,
                "has_kindle": b.has_kindle,
                "kindle_price": b.kindle_price or "-",
                "reviews_count": rev_count,
                "avg_rating": avg_rating,
                "new_30d": new_30d,
                "last_date": last_date_str,
                "last_date_sort": last_date_sort,
                "reviews": modal_reviews
            })

        table_rows_json = json.dumps(table_rows)

        html_content = f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KDP Review Monitor &mdash; Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  
  <style>
    :root {{
      --bg-page: #f8fafc;
      --card-bg: #ffffff;
      --border-color: #e2e8f0;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --primary: #0284c7;
      --primary-hover: #0369a1;
      --emerald: #10b981;
      --amber: #f59e0b;
      --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg-page);
      color: var(--text-main);
      line-height: 1.5;
      padding-bottom: 60px;
    }}

    /* Top Navbar */
    .navbar {{
      background: #ffffff;
      border-bottom: 1px solid var(--border-color);
      padding: 12px 24px;
      position: sticky;
      top: 0;
      z-index: 50;
      box-shadow: var(--shadow-sm);
    }}

    .navbar-inner {{
      max-width: 1400px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}

    .brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 800;
      font-size: 1.15rem;
      color: var(--text-main);
    }}

    .brand-icon {{
      width: 34px;
      height: 34px;
      background: linear-gradient(135deg, #0284c7, #0369a1);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 1.1rem;
    }}

    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      background: #ecfdf5;
      color: #047857;
      border: 1px solid #a7f3d0;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 700;
    }}

    .btn-nav {{
      border: none;
      padding: 8px 14px;
      border-radius: 8px;
      font-weight: 700;
      font-size: 0.84rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
      transition: all 0.15s;
    }}

    .btn-nav-primary {{
      background: #0284c7;
      color: #ffffff;
    }}
    .btn-nav-primary:hover {{
      background: #0369a1;
      transform: translateY(-1px);
    }}

    .btn-nav-secondary {{
      background: #f1f5f9;
      color: #1e293b;
      border: 1px solid #cbd5e1;
    }}
    .btn-nav-secondary:hover {{
      background: #e2e8f0;
      border-color: #94a3b8;
    }}

    .container {{
      max-width: 1400px;
      margin: 20px auto;
      padding: 0 20px;
    }}

    /* KPI Row */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }}

    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 16px 20px;
      box-shadow: var(--shadow-sm);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .kpi-label {{
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 4px;
    }}

    .kpi-value {{
      font-size: 1.6rem;
      font-weight: 800;
      color: var(--text-main);
      line-height: 1.1;
    }}

    /* Marketplace Switcher Bar */
    .mkt-bar {{
      display: flex;
      align-items: center;
      gap: 6px;
      overflow-x: auto;
      padding: 6px 0 16px 0;
      scrollbar-width: thin;
    }}

    .mkt-tab {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #ffffff;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 6px 12px;
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--text-muted);
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s;
    }}

    .mkt-tab:hover {{
      background: #f1f5f9;
      color: var(--text-main);
      border-color: #cbd5e1;
    }}

    .mkt-tab.active {{
      background: #0284c7;
      color: #ffffff;
      border-color: #0284c7;
      box-shadow: 0 2px 4px rgba(2, 132, 199, 0.25);
    }}

    .mkt-tab.active .mkt-badge {{
      background: rgba(255, 255, 255, 0.25);
      color: #ffffff;
    }}

    .mkt-flag {{
      width: 18px;
      height: 13px;
      border-radius: 2px;
      object-fit: cover;
      display: inline-block;
    }}

    .mkt-badge {{
      background: #f1f5f9;
      color: #475569;
      padding: 1px 6px;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 800;
    }}

    /* Main Table Card */
    .table-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      box-shadow: var(--shadow-sm);
      overflow: hidden;
    }}

    .table-toolbar {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      background: #ffffff;
    }}

    .table-title {{
      font-weight: 800;
      font-size: 1.05rem;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .search-box {{
      position: relative;
      min-width: 260px;
    }}

    .search-box input {{
      width: 100%;
      padding: 8px 12px 8px 34px;
      border-radius: 8px;
      border: 1px solid var(--border-color);
      font-size: 0.85rem;
      outline: none;
      font-family: inherit;
    }}

    .search-box input:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
    }}

    .search-icon {{
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: #94a3b8;
      font-size: 0.85rem;
    }}

    /* Table */
    .table-wrapper {{
      overflow-x: auto;
    }}

    table.kdp-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
      text-align: left;
    }}

    table.kdp-table th {{
      background: #f8fafc;
      color: #475569;
      font-weight: 700;
      padding: 10px 14px;
      border-bottom: 1px solid var(--border-color);
      white-space: nowrap;
      user-select: none;
      cursor: pointer;
      position: relative;
    }}

    table.kdp-table th:hover {{
      background: #f1f5f9;
      color: #0f172a;
    }}

    table.kdp-table th.no-sort {{
      cursor: default;
    }}

    table.kdp-table th.no-sort:hover {{
      background: #f8fafc;
      color: #475569;
    }}

    table.kdp-table th .sort-indicator {{
      display: inline-block;
      margin-left: 4px;
      font-size: 0.75rem;
      color: #94a3b8;
    }}

    table.kdp-table th.sorted-asc .sort-indicator::after {{
      content: '▲';
      color: var(--primary);
    }}

    table.kdp-table th.sorted-desc .sort-indicator::after {{
      content: '▼';
      color: var(--primary);
    }}

    table.kdp-table td {{
      padding: 10px 14px;
      border-bottom: 1px solid #f1f5f9;
      vertical-align: middle;
    }}

    table.kdp-table tbody tr:hover {{
      background: #f8fafc;
    }}

    .row-num {{
      font-weight: 700;
      color: #94a3b8;
      font-size: 0.75rem;
      text-align: center;
    }}

    .book-cell {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 280px;
    }}

    .book-cover {{
      width: 36px;
      height: 48px;
      object-fit: cover;
      border-radius: 4px;
      border: 1px solid var(--border-color);
      background: #e2e8f0;
      flex-shrink: 0;
    }}

    .book-title {{
      font-weight: 700;
      color: #0f172a;
      line-height: 1.3;
      text-decoration: none;
    }}

    .book-title:hover {{
      color: var(--primary);
    }}

    .asin-tag {{
      font-family: 'JetBrains Mono', monospace;
      font-weight: 700;
      font-size: 0.8rem;
      color: #334155;
    }}

    .price-badge {{
      font-weight: 700;
      color: #0f172a;
      white-space: nowrap;
    }}

    .reviews-btn {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      border-radius: 999px;
      background: #f1f5f9;
      color: #334155;
      font-weight: 800;
      font-size: 0.82rem;
      border: 1px solid #e2e8f0;
      cursor: pointer;
      transition: all 0.15s;
    }}

    .reviews-btn.has-revs {{
      background: #f0fdf4;
      color: #15803d;
      border-color: #bbf7d0;
    }}

    .reviews-btn:hover {{
      transform: scale(1.04);
      border-color: #0284c7;
    }}

    .rating-badge {{
      font-weight: 800;
      color: #d97706;
      white-space: nowrap;
    }}

    .date-badge {{
      font-size: 0.82rem;
      font-weight: 600;
      color: #334155;
      white-space: nowrap;
    }}

    .btn-amazon {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      border-radius: 6px;
      background: #f8fafc;
      border: 1px solid var(--border-color);
      color: #0284c7;
      font-weight: 700;
      font-size: 0.78rem;
      text-decoration: none;
      white-space: nowrap;
      transition: all 0.15s;
    }}

    .btn-amazon:hover {{
      background: #0284c7;
      color: #ffffff;
      border-color: #0284c7;
    }}

    /* Modal for Reviews & Tools */
    .modal-overlay {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.6);
      backdrop-filter: blur(4px);
      z-index: 100;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}

    .modal-overlay.open {{
      display: flex;
    }}

    .modal-box {{
      background: #ffffff;
      border-radius: 16px;
      width: 100%;
      max-width: 680px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);
      border: 1px solid var(--border-color);
      overflow: hidden;
    }}

    .modal-header {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #f8fafc;
    }}

    .modal-title {{
      font-size: 1rem;
      font-weight: 800;
      color: var(--text-main);
    }}

    .modal-close {{
      background: none;
      border: none;
      font-size: 1.4rem;
      color: #64748b;
      cursor: pointer;
      line-height: 1;
    }}

    .modal-body {{
      padding: 20px;
      overflow-y: auto;
      flex: 1;
    }}

    .review-card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 4px solid #f59e0b;
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 12px;
    }}

    .review-stars {{
      color: #f59e0b;
      font-weight: 700;
      font-size: 0.95rem;
    }}

    .review-title {{
      font-weight: 800;
      color: #0f172a;
      margin: 4px 0 2px 0;
      font-size: 0.9rem;
    }}

    .review-meta {{
      font-size: 0.78rem;
      color: #64748b;
      margin-bottom: 8px;
    }}

    .review-text {{
      font-size: 0.85rem;
      color: #334155;
      white-space: pre-wrap;
      line-height: 1.45;
    }}

    /* Live Terminal Box */
    .terminal-box {{
      background: #0f172a;
      color: #38bdf8;
      border-radius: 10px;
      padding: 14px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.82rem;
      line-height: 1.5;
      max-height: 220px;
      overflow-y: auto;
      margin-top: 10px;
      border: 1px solid #334155;
    }}

    .terminal-line {{
      margin-bottom: 4px;
    }}
    .terminal-line.success {{ color: #4ade80; }}
    .terminal-line.info {{ color: #38bdf8; }}
    .terminal-line.warn {{ color: #facc15; }}
  </style>
</head>
<body>

  <!-- Top Navbar -->
  <nav class="navbar">
    <div class="navbar-inner">
      <div class="brand">
        <div class="brand-icon">📚</div>
        <span>KDP Review Monitor</span>
        <span class="status-pill">● Live</span>
      </div>
      <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
        <div style="font-size: 0.8rem; color: var(--text-muted); margin-right: 4px;">
          Ultimo controllo: <strong style="color: #0f172a;">{now_str}</strong>
        </div>
        <button class="btn-nav btn-nav-secondary" onclick="openForceCheckModal()">
          <span>🔄 Forza Controllo</span>
        </button>
        <button class="btn-nav btn-nav-primary" onclick="openAddBookModal()">
          <span>+ Aggiungi Libro</span>
        </button>
      </div>
    </div>
  </nav>

  <div class="container">

    <!-- KPI Row -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div>
          <div class="kpi-label">Libri Monitorati</div>
          <div class="kpi-value">{kpis['total_books']}</div>
        </div>
        <div style="font-size: 1.5rem;">📖</div>
      </div>

      <div class="kpi-card">
        <div>
          <div class="kpi-label">Recensioni Totali</div>
          <div class="kpi-value" style="color: var(--primary);">{kpis['total_reviews']}</div>
        </div>
        <div style="font-size: 1.5rem;">💬</div>
      </div>

      <div class="kpi-card">
        <div>
          <div class="kpi-label">Rating Medio</div>
          <div class="kpi-value" style="color: #d97706;">{kpis['avg_rating']} ★</div>
        </div>
        <div style="font-size: 1.5rem;">⭐</div>
      </div>

      <div class="kpi-card">
        <div>
          <div class="kpi-label">Nuove (30 gg)</div>
          <div class="kpi-value" style="color: #10b981;">+{kpis['new_reviews_30d']}</div>
        </div>
        <div style="font-size: 1.5rem;">📈</div>
      </div>
    </div>

    <!-- Marketplace Selector Bar (Tabs with flags) -->
    <div class="mkt-bar" id="mktBar">
      <button class="mkt-tab active" onclick="selectMarketplace('all', this)">
        <span>🌐 Tutti i Marketplace</span>
        <span class="mkt-badge">{kpis['total_reviews']}</span>
      </button>
      { "".join([f'''
      <button class="mkt-tab" onclick="selectMarketplace('{mkt_key}', this)" title="{meta['name']}">
        <img src="https://flagcdn.com/24x18/{meta['country']}.png" class="mkt-flag" alt="{meta['code']}">
        <span>{meta['code']}</span>
        <span class="mkt-badge">{meta['count']}</span>
      </button>
      ''' for mkt_key, meta in mkt_counts.items()]) }
    </div>

    <!-- Main Table Card -->
    <div class="table-card">
      <div class="table-toolbar">
        <div class="table-title">
          <span id="currentMktTitle">Tutti i Marketplace</span>
          <span id="rowCountBadge" style="font-size: 0.78rem; background: #f1f5f9; padding: 2px 8px; border-radius: 999px; color: #475569; font-weight: 700;">
            {len(table_rows)} libri
          </span>
        </div>

        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-left: auto;">
          <button class="btn-nav btn-nav-secondary" onclick="openForceCheckModal()" style="padding: 6px 12px; font-size: 0.8rem;">
            <span>🔄 Forza Controllo</span>
          </button>
          <button class="btn-nav btn-nav-primary" onclick="openAddBookModal()" style="padding: 6px 12px; font-size: 0.8rem;">
            <span>+ Aggiungi ASIN</span>
          </button>
          <div class="search-box">
            <span class="search-icon">🔍</span>
            <input type="text" id="tableSearch" placeholder="Cerca per titolo, ASIN o autore..." oninput="handleSearch()">
          </div>
        </div>
      </div>

      <div class="table-wrapper">
        <table class="kdp-table" id="booksTable">
          <thead>
            <tr>
              <th class="no-sort" style="width: 40px; text-align: center;">#</th>
              <th onclick="sortTable(1, 'string')">Copertina &amp; Titolo <span class="sort-indicator"></span></th>
              <th onclick="sortTable(2, 'string')" style="width: 100px;">ASIN <span class="sort-indicator"></span></th>
              <th onclick="sortTable(3, 'string')" style="width: 80px; text-align: center;">Store <span class="sort-indicator"></span></th>
              <th onclick="sortTable(4, 'currency')" style="width: 90px; text-align: right;">Prezzo <span class="sort-indicator"></span></th>
              <th onclick="sortTable(5, 'number')" style="width: 85px; text-align: center;">Recensioni <span class="sort-indicator"></span></th>
              <th onclick="sortTable(6, 'number')" style="width: 85px; text-align: center;">Rating <span class="sort-indicator"></span></th>
              <th onclick="sortTable(7, 'number')" style="width: 75px; text-align: center;">+30gg <span class="sort-indicator"></span></th>
              <th onclick="sortTable(8, 'date')" style="width: 115px; text-align: center;">Ultima Rec. <span class="sort-indicator"></span></th>
              <th class="no-sort" style="width: 90px; text-align: center;">Amazon</th>
            </tr>
          </thead>
          <tbody id="tableBody">
            <!-- Rendered by JS -->
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Modal for Book Reviews -->
  <div class="modal-overlay" id="reviewsModal" onclick="closeReviewsModal(event)">
    <div class="modal-box" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div class="modal-title" id="modalBookTitle">💬 Recensioni</div>
        <button class="modal-close" onclick="closeReviewsModal()">&times;</button>
      </div>
      <div class="modal-body" id="modalReviewsList">
        <!-- Rendered by JS -->
      </div>
    </div>
  </div>

  <!-- Modal Forza Controllo Online -->
  <div class="modal-overlay" id="forceCheckModal" onclick="closeForceCheckModal(event)">
    <div class="modal-box" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div class="modal-title" style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.2rem;">🔄</span>
          <span>Forza Controllo Recensioni Subito</span>
        </div>
        <button class="modal-close" onclick="closeForceCheckModal()">&times;</button>
      </div>
      <div class="modal-body">
        <p style="font-size: 0.9rem; color: #334155; margin-bottom: 16px; line-height: 1.5;">
          Puoi avviare la scansione immediata di tutti i <strong>308 marketplace</strong> del catalogo con rilevamento automatico delle nuove recensioni e invio della notifica email.
        </p>

        <!-- Method 1: GitHub Actions 1-Click -->
        <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 16px; margin-bottom: 16px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="font-weight: 800; font-size: 0.95rem; color: #1e40af;">
              Metodo 1: Avvia su GitHub Actions (Cloud 1-Click)
            </div>
            <span style="background: #dbeafe; color: #1d4ed8; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 999px;">CONSIGLIATO</span>
          </div>
          <p style="font-size: 0.82rem; color: #1e3a8a; margin-bottom: 12px; line-height: 1.45;">
            Clicca sotto per aprire GitHub Actions: premi <strong>"Run workflow"</strong> sul branch <code>master</code>. Il bot eseguirà tutti i controlli in ~2 minuti e invierà le notifiche email.
          </p>
          <a href="https://github.com/indiebookstudio/review-monitor/actions/workflows/monitor.yml" target="_blank" style="display: inline-flex; align-items: center; gap: 8px; background: #0284c7; color: white; text-decoration: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; font-size: 0.88rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: background 0.15s;">
            <span>🚀 Apri GitHub Actions per Avviare il Controllo ↗</span>
          </a>
        </div>

        <!-- Method 2: Live Local Server SSE -->
        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px; padding: 16px; margin-bottom: 16px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="font-weight: 800; font-size: 0.95rem; color: #166534;">
              Metodo 2: Interfaccia Locale con Log Live (localhost:8000)
            </div>
            <span style="background: #dcfce7; color: #15803d; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 999px;">STREAMING LIVE</span>
          </div>
          <p style="font-size: 0.82rem; color: #14532d; margin-bottom: 12px; line-height: 1.45;">
            Se hai avviato il server locale sul tuo computer, puoi vedere i log in streaming in tempo reale riga per riga su <a href="http://localhost:8000" target="_blank" style="color: #15803d; font-weight: 700; text-decoration: underline;">localhost:8000</a>:
          </p>
          <a href="http://localhost:8000" target="_blank" style="display: inline-flex; align-items: center; gap: 8px; background: #16a34a; color: white; text-decoration: none; padding: 9px 16px; border-radius: 8px; font-weight: 700; font-size: 0.84rem;">
            <span>🖥️ Apri Console Streaming su localhost:8000 ↗</span>
          </a>
        </div>

        <!-- Method 3: CLI Terminal -->
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="font-weight: 800; font-size: 0.95rem; color: #334155;">
              Metodo 3: Da Riga di Comando Locale (CLI)
            </div>
            <span style="background: #e2e8f0; color: #475569; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 999px;">TERMINALE</span>
          </div>
          <p style="font-size: 0.82rem; color: #64748b; margin-bottom: 10px; line-height: 1.4;">
            Esegui direttamente nel terminale per eseguire la scansione completa e forzata con output dettagliato:
          </p>
          <div style="display: flex; gap: 8px; align-items: center;">
            <code id="cliRunCmd" style="flex: 1; background: #0f172a; color: #38bdf8; padding: 8px 12px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem;">python scripts/run_monitor.py --force</code>
            <button type="button" onclick="copyForceCommand()" style="background: #ffffff; border: 1px solid #cbd5e1; padding: 8px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; cursor: pointer; white-space: nowrap;">
              📋 Copia
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Modal Aggiungi Libro Online -->
  <div class="modal-overlay" id="addBookModal" onclick="closeAddBookModal(event)">
    <div class="modal-box" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div class="modal-title" style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.2rem;">📚</span>
          <span>Aggiungi Nuovo Libro al Monitor</span>
        </div>
        <button class="modal-close" onclick="closeAddBookModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div style="margin-bottom: 18px;">
          <label style="display: block; font-weight: 700; font-size: 0.88rem; margin-bottom: 6px; color: #0f172a;">
            Codice ASIN Amazon (o incolla il link completo del libro):
          </label>
          <input 
            type="text" 
            id="onlineAsinInput" 
            placeholder="es. B0H717X9ZL (oppure link https://www.amazon.it/dp/...)" 
            style="width: 100%; padding: 10px 14px; border: 1.5px solid #cbd5e1; border-radius: 8px; font-size: 1rem; font-weight: 700; font-family: inherit; outline: none;"
            oninput="updateAddBookActions()"
          >
          <div style="font-size: 0.8rem; color: #64748b; margin-top: 6px; line-height: 1.4;">
            💡 <strong>Zero configurazioni:</strong> Inserendo solo l'ASIN, il bot scarica automaticamente titolo, copertina HD, prezzi cartaceo/Kindle e registra il libro su tutti i <strong>14 marketplace Amazon</strong>!
          </div>
        </div>

        <!-- Action Box: 1-Click GitHub Actions -->
        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px; padding: 16px; margin-bottom: 16px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="font-weight: 800; font-size: 0.95rem; color: #166534;">
              Metodo 1: Avvia da GitHub Actions (Online)
            </div>
            <span style="background: #dcfce7; color: #15803d; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 999px;">AUTOMATICO</span>
          </div>
          <p style="font-size: 0.82rem; color: #14532d; margin-bottom: 12px; line-height: 1.4;">
            Clicca il pulsante sotto per aprire la procedura su GitHub Actions: clicca <strong>"Run workflow"</strong>, inserisci l'ASIN e conferma. Il bot scaricherà il libro e aggiornerà la dashboard in 60 secondi.
          </p>
          <a id="ghActionBtn" href="https://github.com/indiebookstudio/review-monitor/actions/workflows/add_book.yml" target="_blank" style="display: inline-flex; align-items: center; gap: 8px; background: #16a34a; color: white; text-decoration: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; font-size: 0.88rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: background 0.15s;">
            <span>🚀 Apri GitHub Actions per Aggiungere ↗</span>
          </a>
        </div>

        <!-- Action Box: Terminal / CLI Command -->
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="font-weight: 800; font-size: 0.95rem; color: #334155;">
              Metodo 2: Da Terminale Locale (CLI)
            </div>
            <span style="background: #e2e8f0; color: #475569; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 999px;">TERMINALE</span>
          </div>
          <p style="font-size: 0.82rem; color: #64748b; margin-bottom: 10px; line-height: 1.4;">
            Se preferisci eseguire da riga di comando sul tuo computer:
          </p>
          <div style="display: flex; gap: 8px; align-items: center;">
            <code id="cliCmdCode" style="flex: 1; background: #0f172a; color: #38bdf8; padding: 8px 12px; border-radius: 6px; font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; word-break: break-all;">python scripts/add_book.py B0XXXXXXXX</code>
            <button type="button" onclick="copyCliCommand()" style="background: #ffffff; border: 1px solid #cbd5e1; padding: 8px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; cursor: pointer; white-space: nowrap;">
              📋 Copia
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const RAW_ROWS = {table_rows_json};

    let currentMkt = 'all';
    let searchQuery = '';
    let currentSortCol = 5; // Default sort by reviews count
    let currentSortAsc = false; // Descending by default

    function renderTable() {{
      const tbody = document.getElementById("tableBody");
      
      // Filter by marketplace
      let filtered = RAW_ROWS;
      if (currentMkt !== 'all') {{
        filtered = filtered.filter(r => r.marketplace === currentMkt);
      }}

      // Filter by search
      if (searchQuery.trim() !== '') {{
        const q = searchQuery.toLowerCase().trim();
        filtered = filtered.filter(r => 
          r.title.toLowerCase().includes(q) ||
          r.asin.toLowerCase().includes(q) ||
          (r.reviews && r.reviews.some(rev => (rev.author && rev.author.toLowerCase().includes(q)) || (rev.body && rev.body.toLowerCase().includes(q))))
        );
      }}

      // Sort
      filtered.sort((a, b) => {{
        let vA, vB;
        if (currentSortCol === 1) {{
          vA = a.title.toLowerCase(); vB = b.title.toLowerCase();
          return currentSortAsc ? vA.localeCompare(vB) : vB.localeCompare(vA);
        }} else if (currentSortCol === 2) {{
          vA = a.asin; vB = b.asin;
          return currentSortAsc ? vA.localeCompare(vB) : vB.localeCompare(vA);
        }} else if (currentSortCol === 3) {{
          vA = a.mkt_code; vB = b.mkt_code;
          return currentSortAsc ? vA.localeCompare(vB) : vB.localeCompare(vA);
        }} else if (currentSortCol === 4) {{
          vA = a.price_sort; vB = b.price_sort;
        }} else if (currentSortCol === 5) {{
          vA = a.reviews_count; vB = b.reviews_count;
        }} else if (currentSortCol === 6) {{
          vA = a.avg_rating; vB = b.avg_rating;
        }} else if (currentSortCol === 7) {{
          vA = a.new_30d; vB = b.new_30d;
        }} else if (currentSortCol === 8) {{
          vA = a.last_date_sort; vB = b.last_date_sort;
        }} else {{
          vA = a.reviews_count; vB = b.reviews_count;
        }}

        if (typeof vA === 'number' && typeof vB === 'number') {{
          return currentSortAsc ? vA - vB : vB - vA;
        }}
        return 0;
      }});

      document.getElementById('rowCountBadge').innerText = `${{filtered.length}} libri`;

      if (filtered.length === 0) {{
        tbody.innerHTML = `
          <tr>
            <td colspan="10" style="text-align: center; padding: 40px 20px; color: #64748b;">
              Nessun libro trovato per i filtri selezionati.
            </td>
          </tr>
        `;
        return;
      }}

      tbody.innerHTML = filtered.map((r, index) => `
        <tr>
          <td class="row-num">${{index + 1}}</td>

          <td>
            <div class="book-cell">
              <img src="${{r.cover || 'https://via.placeholder.com/36x48?text=KDP'}}" alt="Cover" class="book-cover" onerror="this.src='https://via.placeholder.com/36x48?text=KDP'">
              <div>
                <a href="${{r.product_url}}" target="_blank" class="book-title" title="${{r.title}}">${{r.title}}</a>
                <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 2px;">Store: ${{r.marketplace}}</div>
              </div>
            </div>
          </td>

          <td><span class="asin-tag">${{r.asin}}</span></td>

          <td style="text-align: center;">
            <span style="display: inline-flex; align-items: center; gap: 4px; font-weight: 700; font-size: 0.78rem;">
              <img src="https://flagcdn.com/24x18/${{r.country}}.png" class="mkt-flag" alt="${{r.mkt_code}}">
              ${{r.mkt_code}}
            </span>
          </td>

          <td style="text-align: right;"><span class="price-badge">${{r.price || '-'}}</span></td>

          <td style="text-align: center;">
            <button class="reviews-btn ${{r.reviews_count > 0 ? 'has-revs' : ''}}" onclick="openReviewsModal(${{r.id}})" title="Leggi recensioni">
              💬 ${{r.reviews_count}}
            </button>
          </td>

          <td style="text-align: center;">
            <span class="rating-badge">${{r.reviews_count > 0 ? r.avg_rating + ' ★' : '-'}}</span>
          </td>

          <td style="text-align: center;">
            ${{r.new_30d > 0 ? `<span style="color: #16a34a; font-weight: 800; background: #dcfce7; padding: 2px 6px; border-radius: 999px; font-size: 0.78rem;">+${{r.new_30d}}</span>` : '<span style="color: #94a3b8;">0</span>'}}
          </td>

          <td style="text-align: center;">
            <span class="date-badge">${{r.last_date}}</span>
          </td>

          <td style="text-align: center;">
            <a href="${{r.product_url}}" target="_blank" class="btn-amazon">
              <span>Apri ↗</span>
            </a>
          </td>
        </tr>
      `).join('');
    }}

    function selectMarketplace(mkt, el) {{
      currentMkt = mkt;
      document.querySelectorAll('.mkt-tab').forEach(t => t.classList.remove('active'));
      if (el) el.classList.add('active');
      document.getElementById('currentMktTitle').innerText = mkt === 'all' ? 'Tutti i Marketplace' : mkt;
      renderTable();
    }}

    function handleSearch() {{
      searchQuery = document.getElementById("tableSearch").value;
      renderTable();
    }}

    function sortTable(colIdx, type) {{
      if (currentSortCol === colIdx) {{
        currentSortAsc = !currentSortAsc;
      }} else {{
        currentSortCol = colIdx;
        currentSortAsc = (type === 'string');
      }}

      // Update UI classes
      const ths = document.querySelectorAll('table.kdp-table th');
      ths.forEach((th, idx) => {{
        th.classList.remove('sorted-asc', 'sorted-desc');
        if (idx === colIdx) {{
          th.classList.add(currentSortAsc ? 'sorted-asc' : 'sorted-desc');
        }}
      }});

      renderTable();
    }}

    function openReviewsModal(bookId) {{
      const book = RAW_ROWS.find(b => b.id === bookId);
      if (!book) return;

      document.getElementById("modalBookTitle").innerText = `💬 Recensioni (${{book.reviews.length}}) - ${{book.title}}`;
      const listEl = document.getElementById("modalReviewsList");

      if (book.reviews.length === 0) {{
        listEl.innerHTML = `
          <div style="text-align: center; padding: 40px 20px; color: #64748b;">
            Nessuna recensione testuale archiviata per questo store.
          </div>
        `;
      }} else {{
        listEl.innerHTML = book.reviews.map(r => `
          <div class="review-card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <span class="review-stars">${{r.stars}} ${{r.rating}}/5</span>
              <a href="${{r.url}}" target="_blank" style="font-size: 0.78rem; color: #0284c7; font-weight: 700; text-decoration: underline;">Vedi su Amazon ↗</a>
            </div>
            <div class="review-title">${{r.title}}</div>
            <div class="review-meta">Scritta da <strong>${{r.author}}</strong> ${{r.flag ? r.flag + ' <span style=\"color: #64748b; font-size: 0.76rem;\">(' + r.country_name + ')</span>' : ''}} &bull; Data: <strong>${{r.date}}</strong></div>
            <div class="review-text">${{r.body}}</div>
          </div>
        `).join('');
      }}

      document.getElementById("reviewsModal").classList.add("open");
    }}

    function closeReviewsModal(e) {{
      document.getElementById("reviewsModal").classList.remove("open");
    }}

    function openAddBookModal() {{
      document.getElementById("addBookModal").classList.add("open");
      document.getElementById("onlineAsinInput").focus();
    }}

    function closeAddBookModal(e) {{
      document.getElementById("addBookModal").classList.remove("open");
    }}

    function openForceCheckModal() {{
      document.getElementById("forceCheckModal").classList.add("open");
    }}

    function closeForceCheckModal(e) {{
      document.getElementById("forceCheckModal").classList.remove("open");
    }}

    function updateAddBookActions() {{
      let val = document.getElementById("onlineAsinInput").value.trim();
      const m = val.match(/(?:dp|product|gp\\/product)\\/([A-Z0-9]{{10}})/i);
      let asin = m ? m[1].toUpperCase() : val.replace(/[^A-Z0-9]/gi, '').toUpperCase();
      if (!asin) asin = 'B0XXXXXXXX';
      
      document.getElementById("cliCmdCode").innerText = `python scripts/add_book.py ${{asin}}`;
    }}

    function copyCliCommand() {{
      const code = document.getElementById("cliCmdCode").innerText;
      navigator.clipboard.writeText(code).then(() => {{
        alert("Comando copiato negli appunti: " + code);
      }}).catch(() => {{
        prompt("Copia il comando:", code);
      }});
    }}

    function copyForceCommand() {{
      const code = document.getElementById("cliRunCmd").innerText;
      navigator.clipboard.writeText(code).then(() => {{
        alert("Comando copiato negli appunti: " + code);
      }}).catch(() => {{
        prompt("Copia il comando:", code);
      }});
    }}

    // Initial table render: sorted by date descending if wanted or by reviews
    sortTable(5, 'number'); // Default sort by reviews count descending
  </script>

</body>
</html>
"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        return str(output_path)

    finally:
        db.close()

if __name__ == "__main__":
    out_file = BASE_DIR / "docs" / "index.html"
    print(f"Generating clean table dashboard to {out_file}...")
    res = generate_static_html(out_file)
    print(f"Dashboard generated: {res}")
