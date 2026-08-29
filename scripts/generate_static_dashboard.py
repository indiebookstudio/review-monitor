#!/usr/bin/env python3
"""
Generates the clean, table-based, sortable KDP dashboard for GitHub Pages
with marketplace switcher bar and sortable columns.
Outputs to docs/index.html.
"""
import os
import sys
import json
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import SessionLocal
from app.models import Book, Review
from app.reviews.statistics import get_dashboard_kpis, format_compact_date
from app.amazon.marketplace import MARKETPLACES

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
            ratings = [r.rating for r in b_revs if r.rating is not None]
            avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else (5.0 if rev_count > 0 else 0.0)
            
            # Reviews in last 30d
            new_30d = sum(1 for r in b_revs if r.first_seen_at and r.first_seen_at.replace(tzinfo=datetime.timezone.utc) >= d30)
            
            # Last review date
            last_date = "-"
            if b_revs:
                # get newest review
                sorted_revs = sorted(b_revs, key=lambda x: x.first_seen_at or datetime.datetime.min, reverse=True)
                if sorted_revs and sorted_revs[0].review_date:
                    last_date = sorted_revs[0].review_date

            m_meta = MARKETPLACES.get(b.marketplace, {})
            country = m_meta.get("country", "it")
            mkt_code = m_meta.get("code", b.marketplace.replace("amazon.", "").upper())

            serialized_revs = [
                {
                    "id": r.review_id,
                    "rating": r.rating or 5.0,
                    "stars": format_stars(r.rating or 5.0),
                    "title": r.title or "Recensione",
                    "author": r.author or "Cliente Amazon",
                    "date": r.review_date or "",
                    "body": r.body or "",
                    "url": r.review_url or f"https://www.{b.marketplace}/dp/{b.asin}"
                }
                for r in b_revs
            ]

            table_rows.append({
                "id": b.id,
                "asin": b.asin,
                "title": b.title or f"Libro {b.asin}",
                "cover": b.cover_image_url or "",
                "marketplace": b.marketplace,
                "mkt_code": mkt_code,
                "country": country,
                "price": b.price or "",
                "has_kindle": b.has_kindle,
                "kindle_price": b.kindle_price or "",
                "reviews_count": rev_count,
                "avg_rating": avg_rating,
                "new_30d": new_30d,
                "last_date": last_date,
                "product_url": f"https://www.{b.marketplace}/dp/{b.asin}",
                "reviews": serialized_revs
            })

        table_rows_json = json.dumps(table_rows)
        mkt_counts_json = json.dumps(mkt_counts)

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
      --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.07);
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
    }}

    .kpi-value {{
      font-size: 1.6rem;
      font-weight: 800;
      color: var(--text-main);
      margin-top: 2px;
    }}

    /* Marketplace Selector Bar (Tabs with Flags) */
    .mkt-bar {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 8px 12px;
      margin-bottom: 18px;
      box-shadow: var(--shadow-sm);
      display: flex;
      align-items: center;
      gap: 6px;
      overflow-x: auto;
      white-space: nowrap;
      scrollbar-width: thin;
    }}

    .mkt-tab {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 8px;
      border: 1px solid transparent;
      background: #f1f5f9;
      color: #334155;
      font-size: 0.82rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s ease;
      text-decoration: none;
      flex-shrink: 0;
    }}

    .mkt-tab:hover {{
      background: #e2e8f0;
      color: var(--text-main);
    }}

    .mkt-tab.active {{
      background: #0284c7;
      color: #ffffff;
      border-color: #0284c7;
    }}

    .mkt-flag {{
      width: 18px;
      height: 13px;
      object-fit: cover;
      border-radius: 2px;
    }}

    .mkt-badge {{
      background: rgba(0, 0, 0, 0.08);
      padding: 1px 6px;
      border-radius: 999px;
      font-size: 0.72rem;
    }}

    .mkt-tab.active .mkt-badge {{
      background: rgba(255, 255, 255, 0.25);
      color: #ffffff;
    }}

    /* Main Table Container */
    .table-card {{
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      box-shadow: var(--shadow-sm);
      overflow: hidden;
    }}

    .table-toolbar {{
      padding: 14px 20px;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      background: #ffffff;
    }}

    .table-title {{
      font-size: 1rem;
      font-weight: 800;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .search-box {{
      position: relative;
      min-width: 280px;
    }}

    .search-box input {{
      width: 100%;
      padding: 7px 12px 7px 32px;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      font-size: 0.84rem;
      outline: none;
      transition: border-color 0.15s;
    }}

    .search-box input:focus {{
      border-color: var(--primary);
    }}

    .search-icon {{
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 0.85rem;
    }}

    .table-wrapper {{
      width: 100%;
      overflow-x: auto;
    }}

    table.kdp-table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.85rem;
    }}

    table.kdp-table th {{
      background: #f8fafc;
      color: #475569;
      font-weight: 700;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 11px 14px;
      border-bottom: 1px solid var(--border-color);
      user-select: none;
      cursor: pointer;
      white-space: nowrap;
      transition: background 0.15s;
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
    }}

    .sort-indicator {{
      display: inline-block;
      margin-left: 4px;
      font-size: 0.75rem;
      color: #94a3b8;
    }}

    th.sorted-asc .sort-indicator::after {{ content: ' ▲'; color: #0284c7; }}
    th.sorted-desc .sort-indicator::after {{ content: ' ▼'; color: #0284c7; }}
    th:not(.sorted-asc):not(.sorted-desc) .sort-indicator::after {{ content: ' ⇅'; opacity: 0.4; }}

    table.kdp-table td {{
      padding: 12px 14px;
      border-bottom: 1px solid #f1f5f9;
      vertical-align: middle;
    }}

    table.kdp-table tr:hover td {{
      background: #f8fafc;
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

    /* Modal for Reviews */
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
      flex-col: column;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);
      border: 1px solid var(--border-color);
      overflow: hidden;
      display: flex;
      flex-direction: column;
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
      <div style="font-size: 0.8rem; color: var(--text-muted);">
        Ultimo controllo: <strong style="color: #0f172a;">{now_str}</strong> &bull; Schedulazione: <span style="color: #0284c7; font-weight: 700;">Ogni notte alle 03:00 UTC</span>
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

        <div class="search-box">
          <span class="search-icon">🔍</span>
          <input type="text" id="tableSearch" placeholder="Cerca per titolo, ASIN o autore..." oninput="handleSearch()">
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
              <th onclick="sortTable(8, 'string')" style="width: 110px; text-align: center;">Ultima Rec. <span class="sort-indicator"></span></th>
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

  <!-- Reviews Modal -->
  <div class="modal-overlay" id="reviewsModal" onclick="closeReviewsModal(event)">
    <div class="modal-box" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3 class="modal-title" id="modalBookTitle">Recensioni Libro</h3>
        <button class="modal-close" onclick="closeReviewsModal()">&times;</button>
      </div>
      <div class="modal-body" id="modalReviewsList">
        <!-- Rendered by JS -->
      </div>
    </div>
  </div>

  <!-- Client-Side Engine (Filtering, Multi-Column Sorting, Modal) -->
  <script>
    const RAW_ROWS = {table_rows_json};
    let currentMkt = 'all';
    let searchQuery = '';
    let currentSortCol = 5; // Default sort by reviews count
    let currentSortAsc = false; // Descending

    function renderTable() {{
      const tbody = document.getElementById("tableBody");
      
      // Filter
      let filtered = RAW_ROWS.filter(r => {{
        const matchMkt = (currentMkt === 'all' || r.marketplace === currentMkt);
        const q = searchQuery.toLowerCase().trim();
        const matchSearch = !q || r.title.toLowerCase().includes(q) || r.asin.toLowerCase().includes(q);
        return matchMkt && matchSearch;
      }});

      // Sort
      filtered.sort((a, b) => {{
        let valA, valB;
        if (currentSortCol === 1) {{ valA = a.title; valB = b.title; }}
        else if (currentSortCol === 2) {{ valA = a.asin; valB = b.asin; }}
        else if (currentSortCol === 3) {{ valA = a.marketplace; valB = b.marketplace; }}
        else if (currentSortCol === 4) {{ 
          valA = parseFloat((a.price || '0').replace(/[^0-9.,]/g, '').replace(',', '.')) || 0;
          valB = parseFloat((b.price || '0').replace(/[^0-9.,]/g, '').replace(',', '.')) || 0;
        }}
        else if (currentSortCol === 5) {{ valA = a.reviews_count; valB = b.reviews_count; }}
        else if (currentSortCol === 6) {{ valA = a.avg_rating; valB = b.avg_rating; }}
        else if (currentSortCol === 7) {{ valA = a.new_30d; valB = b.new_30d; }}
        else if (currentSortCol === 8) {{ valA = a.last_date; valB = b.last_date; }}
        else {{ valA = a.id; valB = b.id; }}

        if (typeof valA === 'string') {{
          return currentSortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }} else {{
          return currentSortAsc ? valA - valB : valB - valA;
        }}
      }});

      document.getElementById("rowCountBadge").innerText = filtered.length + " libri";

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

      tbody.innerHTML = filtered.map((r, idx) => `
        <tr>
          <td style="text-align: center; font-weight: 700; color: #94a3b8;">${{idx + 1}}</td>
          
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

          <td style="text-align: center; font-size: 0.78rem; color: #64748b;">${{r.last_date}}</td>

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
            <div class="review-meta">Scritta da <strong>${{r.author}}</strong> ${{r.date ? 'il ' + r.date : ''}}</div>
            <div class="review-text">${{r.body}}</div>
          </div>
        `).join('');
      }}

      document.getElementById("reviewsModal").classList.add("open");
    }}

    function closeReviewsModal(e) {{
      document.getElementById("reviewsModal").classList.remove("open");
    }}

    // Initial table render
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
