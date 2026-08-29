#!/usr/bin/env python3
"""
Generates a standalone, ultra-fast, mobile-responsive HTML dashboard
for GitHub Pages from the SQLite database.
Outputs to docs/index.html.
"""
import os
import sys
import json
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import SessionLocal, engine, Base
from app.models import Book, Review, CheckRun, AppSetting
from app.reviews.statistics import get_dashboard_kpis
from sqlalchemy import func


def format_stars(rating: float) -> str:
    full = int(round(rating or 5.0))
    full = max(1, min(5, full))
    return "★" * full + "☆" * (5 - full)

def generate_static_html(output_path: Path) -> str:
    db = SessionLocal()
    try:
        books = db.query(Book).filter(Book.enabled == True).all()
        reviews = db.query(Review).order_by(Review.first_seen_at.desc(), Review.id.desc()).all()
        stats = get_dashboard_kpis(db)

        
        # Group books by ASIN
        asins_map = {}
        for b in books:
            if b.asin not in asins_map:
                asins_map[b.asin] = {
                    "asin": b.asin,
                    "title": b.title,
                    "cover_image_url": b.cover_image_url or "https://via.placeholder.com/180x260?text=No+Cover",
                    "price": b.price or "",
                    "has_kindle": b.has_kindle,
                    "kindle_price": b.kindle_price or "",
                    "marketplaces": [],
                    "reviews_count": 0,
                    "avg_rating": 0.0,
                    "ratings": []
                }
            if b.marketplace not in asins_map[b.asin]["marketplaces"]:
                asins_map[b.asin]["marketplaces"].append(b.marketplace)
            if not asins_map[b.asin]["title"] or asins_map[b.asin]["title"].startswith("Amazon KDP"):
                if b.title:
                    asins_map[b.asin]["title"] = b.title
            if not asins_map[b.asin]["cover_image_url"] or "placeholder" in asins_map[b.asin]["cover_image_url"]:
                if b.cover_image_url:
                    asins_map[b.asin]["cover_image_url"] = b.cover_image_url
            if not asins_map[b.asin]["price"] and b.price:
                asins_map[b.asin]["price"] = b.price
            if b.has_kindle:
                asins_map[b.asin]["has_kindle"] = True
                if b.kindle_price and not asins_map[b.asin]["kindle_price"]:
                    asins_map[b.asin]["kindle_price"] = b.kindle_price

        # Aggregate reviews per ASIN
        for r in reviews:
            if r.asin in asins_map:
                asins_map[r.asin]["reviews_count"] += 1
                if r.rating is not None:
                    asins_map[r.asin]["ratings"].append(r.rating)

        for asin_data in asins_map.values():
            if asin_data["ratings"]:
                asin_data["avg_rating"] = round(sum(asin_data["ratings"]) / len(asin_data["ratings"]), 1)
            else:
                asin_data["avg_rating"] = 5.0

        # Star distribution
        rating_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        for r in reviews:
            val = int(round(r.rating or 5.0))
            val = max(1, min(5, val))
            rating_counts[val] += 1
        
        tot_revs = len(reviews)
        star_pcts = {
            s: round((rating_counts[s] / tot_revs * 100), 1) if tot_revs > 0 else 0
            for s in range(1, 6)
        }

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y alle %H:%M UTC")

        # Serialized JSON for dynamic search / filter on client side
        books_json = json.dumps(list(asins_map.values()))
        reviews_json = json.dumps([
            {
                "id": r.id,
                "asin": r.asin,
                "book_title": asins_map.get(r.asin, {}).get("title", r.asin),
                "marketplace": r.marketplace,
                "rating": r.rating or 5.0,
                "stars": format_stars(r.rating or 5.0),
                "title": r.title or "Recensione",
                "body": r.body or "",
                "author": r.author or "Cliente Amazon",
                "review_date": r.review_date or "",
                "review_url": r.review_url or f"https://www.{r.marketplace}/dp/{r.asin}",
                "first_seen_at": r.first_seen_at.strftime("%d/%m/%Y") if r.first_seen_at else ""
            }
            for r in reviews
        ])

        html_content = f"""<!DOCTYPE html>
<html lang="it" class="h-full bg-slate-950 text-slate-100">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KDP Review Monitor &mdash; Live Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          colors: {{
            brand: {{ 50: '#f0fdf4', 500: '#22c55e', 600: '#16a34a' }},
            accent: {{ 500: '#f59e0b', 600: '#d97706' }}
          }}
        }}
      }}
    }}
  </script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    .star-amber {{ color: #f59e0b; }}
    .glass-card {{ background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(12px); border: 1px solid rgba(51, 65, 85, 0.6); }}
  </style>
</head>
<body class="min-h-full flex flex-col antialiased selection:bg-emerald-500 selection:text-white pb-16">

  <!-- Navigation Bar -->
  <header class="sticky top-0 z-40 bg-slate-900/90 backdrop-blur border-b border-slate-800">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 to-emerald-500 flex items-center justify-center text-slate-950 font-black text-xl shadow-lg shadow-emerald-500/10">
          📚
        </div>
        <div>
          <h1 class="text-lg font-bold text-white tracking-tight flex items-center gap-2">
            KDP Review Monitor
            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              🟢 Live
            </span>
          </h1>
          <p class="text-xs text-slate-400">Scansione notturna automatica &bull; Aggiornato {now_str}</p>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <a href="https://github.com/indiebookstudio/review-monitor/actions" target="_blank" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 transition">
          <i class="fa-brands fa-github"></i>
          <span>GitHub Actions</span>
        </a>
      </div>
    </div>
  </header>

  <!-- Main Content Container -->
  <main class="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full space-y-8">

    <!-- KPI Summary Grid -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      
      <div class="glass-card rounded-2xl p-5 relative overflow-hidden">
        <div class="flex justify-between items-start">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Libri Monitorati</span>
          <div class="w-8 h-8 rounded-lg bg-blue-500/10 text-blue-400 flex items-center justify-center text-sm">
            <i class="fa-solid fa-book"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <span class="text-3xl font-extrabold text-white">{len(asins_map)}</span>
          <span class="text-xs text-slate-400">({len(books)} store)</span>
        </div>
        <div class="mt-1 text-xs text-emerald-400 font-medium">100% attivi</div>
      </div>

      <div class="glass-card rounded-2xl p-5 relative overflow-hidden">
        <div class="flex justify-between items-start">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Recensioni Totali</span>
          <div class="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center text-sm">
            <i class="fa-solid fa-comments"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <span class="text-3xl font-extrabold text-emerald-400">{tot_revs}</span>
          <span class="text-xs text-slate-400">archiviate</span>
        </div>
        <div class="mt-1 text-xs text-slate-400">Su Amazon globale</div>
      </div>

      <div class="glass-card rounded-2xl p-5 relative overflow-hidden">
        <div class="flex justify-between items-start">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Rating Globale</span>
          <div class="w-8 h-8 rounded-lg bg-amber-500/10 text-amber-400 flex items-center justify-center text-sm">
            <i class="fa-solid fa-star"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <span class="text-3xl font-extrabold text-amber-400">{stats.get('avg_rating', 5.0)}</span>
          <span class="text-xs text-amber-400/80">/ 5.0 ★</span>
        </div>
        <div class="mt-1 text-xs text-amber-300/80 font-mono tracking-widest">{format_stars(stats.get('avg_rating', 5.0))}</div>
      </div>

      <div class="glass-card rounded-2xl p-5 relative overflow-hidden">
        <div class="flex justify-between items-start">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Prossimo Check</span>
          <div class="w-8 h-8 rounded-lg bg-purple-500/10 text-purple-400 flex items-center justify-center text-sm">
            <i class="fa-solid fa-moon"></i>
          </div>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <span class="text-xl font-bold text-purple-300">03:00 UTC</span>
        </div>
        <div class="mt-1 text-xs text-purple-400 font-medium">Ogni notte con notifica email</div>
      </div>

    </div>

    <!-- Rating Distribution & Quick Stats -->
    <div class="glass-card rounded-2xl p-6">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-4 flex items-center gap-2">
        <i class="fa-solid fa-chart-simple text-amber-400"></i> Distribuzione Valutazioni a Stelle
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
        { "".join([f'''
        <div class="bg-slate-900/60 rounded-xl p-4 border border-slate-800 flex flex-col justify-between">
          <div class="flex items-center justify-between">
            <span class="text-sm font-bold text-amber-400">{s} ★</span>
            <span class="text-xs text-slate-400">{rating_counts[s]} recensioni</span>
          </div>
          <div class="w-full bg-slate-800 rounded-full h-2 mt-3 overflow-hidden">
            <div class="bg-amber-400 h-2 rounded-full" style="width: {star_pcts[s]}%;"></div>
          </div>
          <div class="mt-2 text-right text-xs font-semibold text-slate-300">{star_pcts[s]}%</div>
        </div>
        ''' for s in range(5, 0, -1)]) }
      </div>
    </div>

    <!-- Interactive Filter & Search Bar -->
    <div class="glass-card rounded-2xl p-4 sm:p-5">
      <div class="flex flex-col md:flex-row gap-4 items-center justify-between">
        
        <!-- Search Input -->
        <div class="relative w-full md:w-96">
          <i class="fa-solid fa-magnifying-glass absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500 text-sm"></i>
          <input 
            type="text" 
            id="searchInput" 
            placeholder="Cerca libro, ASIN, autore o testo..." 
            class="w-full pl-10 pr-4 py-2 bg-slate-900/80 border border-slate-700 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition"
            oninput="filterData()"
          >
        </div>

        <!-- Filter Selects -->
        <div class="flex flex-wrap gap-2 w-full md:w-auto">
          <select id="tabFilter" onchange="switchView(this.value)" class="px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-xl text-xs font-semibold text-slate-200 focus:outline-none focus:border-emerald-500">
            <option value="reviews">💬 Tutte le Recensioni ({tot_revs})</option>
            <option value="books">📖 Catalogo Libri ({len(asins_map)})</option>
          </select>

          <select id="marketplaceFilter" onchange="filterData()" class="px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-emerald-500">
            <option value="">🌐 Tutti i Marketplace</option>
            <option value="amazon.it">🇮🇹 Amazon.it</option>
            <option value="amazon.com">🇺🇸 Amazon.com</option>
            <option value="amazon.co.uk">🇬🇧 Amazon.co.uk</option>
            <option value="amazon.de">🇩🇪 Amazon.de</option>
            <option value="amazon.fr">🇫🇷 Amazon.fr</option>
            <option value="amazon.es">🇪🇸 Amazon.es</option>
          </select>

          <select id="starsFilter" onchange="filterData()" class="px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-emerald-500">
            <option value="">⭐ Tutte le stelle</option>
            <option value="5">5 Stelle (★★★★★)</option>
            <option value="4">4 Stelle (★★★★☆)</option>
            <option value="3">3 Stelle o meno (≤ ★★★☆☆)</option>
          </select>
        </div>

      </div>
    </div>

    <!-- Section 1: Reviews Feed Container -->
    <div id="reviewsContainer" class="space-y-4">
      <div class="flex items-center justify-between px-1">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <span>Elenco Recensioni</span>
          <span id="reviewsCountBadge" class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-normal">
            {tot_revs} elementi
          </span>
        </h3>
      </div>
      
      <div id="reviewsList" class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Rendered dynamically by JS -->
      </div>
    </div>

    <!-- Section 2: Books Catalog Container -->
    <div id="booksContainer" class="hidden space-y-4">
      <div class="flex items-center justify-between px-1">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <span>Catalogo Libri Monitorati</span>
          <span id="booksCountBadge" class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-normal">
            {len(asins_map)} titoli
          </span>
        </h3>
      </div>

      <div id="booksList" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        <!-- Rendered dynamically by JS -->
      </div>
    </div>

  </main>

  <!-- Footer -->
  <footer class="mt-auto border-t border-slate-900 py-6 text-center text-xs text-slate-500">
    <p>KDP Review Monitor &bull; 100% GitHub Actions &amp; GitHub Pages &bull; Aggiornato automaticamente ogni notte</p>
  </footer>

  <!-- Client-Side Data & Script -->
  <script>
    const ALL_REVIEWS = {reviews_json};
    const ALL_BOOKS = {books_json};

    function renderReviews(items) {{
      const container = document.getElementById("reviewsList");
      document.getElementById("reviewsCountBadge").innerText = items.length + " elementi";
      
      if (items.length === 0) {{
        container.innerHTML = `
          <div class="col-span-full py-16 text-center glass-card rounded-2xl">
            <div class="text-4xl mb-2">🔍</div>
            <p class="text-slate-400 text-sm font-medium">Nessuna recensione corrispondente ai filtri impostati.</p>
          </div>
        `;
        return;
      }}

      container.innerHTML = items.map(r => `
        <div class="glass-card rounded-2xl p-5 flex flex-col justify-between hover:border-slate-600 transition">
          <div>
            <div class="flex items-start justify-between gap-3 mb-2">
              <div>
                <span class="text-amber-400 font-mono tracking-wider font-bold text-sm">${{r.stars}}</span>
                <span class="text-xs font-bold text-slate-300 ml-1.5">${{r.rating}}/5</span>
              </div>
              <span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                ${{r.marketplace}}
              </span>
            </div>

            <h4 class="font-bold text-slate-100 text-sm mb-1 line-clamp-1">${{r.title}}</h4>
            <div class="text-[11px] text-slate-400 mb-3">
              Recensito da <strong class="text-slate-300">${{r.author}}</strong> ${{r.review_date ? 'il ' + r.review_date : ''}}
            </div>

            <p class="text-xs text-slate-300/90 whitespace-pre-wrap leading-relaxed mb-4">${{r.body}}</p>
          </div>

          <div class="pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
            <span class="text-slate-400 font-medium truncate max-w-[200px]" title="${{r.book_title}}">
              📖 ${{r.book_title}}
            </span>
            <a href="${{r.review_url}}" target="_blank" class="text-emerald-400 hover:text-emerald-300 font-semibold inline-flex items-center gap-1 transition">
              <span>Vedi su Amazon</span>
              <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
            </a>
          </div>
        </div>
      `).join('');
    }}

    function renderBooks(items) {{
      const container = document.getElementById("booksList");
      document.getElementById("booksCountBadge").innerText = items.length + " titoli";

      if (items.length === 0) {{
        container.innerHTML = `
          <div class="col-span-full py-16 text-center glass-card rounded-2xl">
            <div class="text-4xl mb-2">📚</div>
            <p class="text-slate-400 text-sm font-medium">Nessun libro trovato.</p>
          </div>
        `;
        return;
      }}

      container.innerHTML = items.map(b => `
        <div class="glass-card rounded-2xl p-5 flex flex-col justify-between hover:border-slate-600 transition">
          <div class="flex gap-4 items-start">
            <img src="${{b.cover_image_url}}" alt="Cover" class="w-20 h-28 object-cover rounded-lg shadow-md bg-slate-900 border border-slate-800 flex-shrink-0" onerror="this.src='https://via.placeholder.com/80x110?text=KDP'">
            <div class="flex-1 min-w-0">
              <h4 class="font-bold text-white text-sm line-clamp-2 mb-1" title="${{b.title}}">${{b.title}}</h4>
              <div class="text-xs text-slate-400 font-mono mb-2">ASIN: ${{b.asin}}</div>
              
              <div class="flex items-center gap-1.5 text-xs">
                <span class="text-amber-400 font-bold">${{b.avg_rating}} ★</span>
                <span class="text-slate-400">(${{b.reviews_count}} recensioni)</span>
              </div>

              ${{b.price ? `<div class="mt-2 text-xs font-semibold text-emerald-400">Cartaceo: ${{b.price}}</div>` : ''}}
              ${{b.has_kindle ? `<div class="text-xs text-blue-400">Kindle: ${{b.kindle_price || 'Disponibile'}}</div>` : ''}}
            </div>
          </div>

          <div class="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between">
            <span class="text-[11px] text-slate-400">${{b.marketplaces.length}} store monitorati</span>
            <a href="https://www.amazon.it/dp/${{b.asin}}" target="_blank" class="px-3 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 font-semibold text-xs inline-flex items-center gap-1.5 transition">
              <span>Scheda Amazon</span>
              <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
            </a>
          </div>
        </div>
      `).join('');
    }}

    function filterData() {{
      const query = document.getElementById("searchInput").value.toLowerCase().trim();
      const mkt = document.getElementById("marketplaceFilter").value;
      const stars = document.getElementById("starsFilter").value;

      // Filter reviews
      const filteredRevs = ALL_REVIEWS.filter(r => {{
        const matchQuery = !query || r.title.toLowerCase().includes(query) || r.body.toLowerCase().includes(query) || r.author.toLowerCase().includes(query) || r.asin.toLowerCase().includes(query) || r.book_title.toLowerCase().includes(query);
        const matchMkt = !mkt || r.marketplace === mkt;
        let matchStars = true;
        if (stars === "5") matchStars = r.rating >= 4.7;
        else if (stars === "4") matchStars = r.rating >= 3.7 && r.rating < 4.7;
        else if (stars === "3") matchStars = r.rating < 3.7;
        return matchQuery && matchMkt && matchStars;
      }});

      renderReviews(filteredRevs);

      // Filter books
      const filteredBooks = ALL_BOOKS.filter(b => {{
        const matchQuery = !query || b.title.toLowerCase().includes(query) || b.asin.toLowerCase().includes(query);
        const matchMkt = !mkt || b.marketplaces.includes(mkt);
        return matchQuery && matchMkt;
      }});

      renderBooks(filteredBooks);
    }}

    function switchView(tab) {{
      if (tab === "books") {{
        document.getElementById("booksContainer").classList.remove("hidden");
        document.getElementById("reviewsContainer").classList.add("hidden");
      }} else {{
        document.getElementById("booksContainer").classList.add("hidden");
        document.getElementById("reviewsContainer").classList.remove("hidden");
      }}
    }}

    // Initial render
    renderReviews(ALL_REVIEWS);
    renderBooks(ALL_BOOKS);
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
    print(f"Generating static dashboard to {out_file}...")
    res = generate_static_html(out_file)
    print(f"Dashboard successfully generated at: {res}")
