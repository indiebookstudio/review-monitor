// KDP Performance Dashboard - Interactive Scripts

document.addEventListener("DOMContentLoaded", () => {
  // Mobile Navigation Toggle
  const mobileToggle = document.getElementById("mobileMenuToggle");
  const navLinks = document.getElementById("navLinks");
  if (mobileToggle && navLinks) {
    mobileToggle.addEventListener("click", () => {
      navLinks.classList.toggle("active");
    });
  }

  // Modal Open/Close Helpers
  window.openModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.classList.add("active");
    }
  };

  window.closeModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.classList.remove("active");
    }
  };

  // Close modal when clicking on overlay background
  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) {
        overlay.classList.remove("active");
      }
    });
  });

  // Edit Book Modal Populate
  window.openEditBookModal = function(bookId, asin, marketplace, title, price, cover) {
    const form = document.getElementById("editBookForm");
    if (form) {
      form.action = `/books/${bookId}/edit`;
      const asinEl = document.getElementById("edit_asin");
      const mktEl = document.getElementById("edit_marketplace");
      const titleEl = document.getElementById("edit_title");
      const priceEl = document.getElementById("edit_price");
      const coverEl = document.getElementById("edit_cover");
      
      if (asinEl) asinEl.value = asin || "";
      if (mktEl) mktEl.value = marketplace || "amazon.it";
      if (titleEl) titleEl.value = title || "";
      if (priceEl) priceEl.value = price || "";
      if (coverEl) coverEl.value = cover || "";
      openModal("editBookModal");
    }
  };

  // Delete Single Book Modal Populate
  window.openDeleteBookModal = function(bookId, title, asin) {
    const form = document.getElementById("deleteBookForm");
    const label = document.getElementById("deleteBookTitle");
    if (form && label) {
      form.action = `/books/${bookId}/delete`;
      label.textContent = `Sei sicuro di voler eliminare questo record del libro "${title}" (${asin})?`;
      openModal("deleteBookModal");
    }
  };

  // Delete Book From ALL Marketplaces Modal Populate
  window.openDeleteAllStoresModal = function(asin, title) {
    const form = document.getElementById("deleteAllStoresForm");
    const label = document.getElementById("deleteAllStoresTitle");
    if (form && label) {
      form.action = `/books/asin/${asin}/delete`;
      label.textContent = `Sei sicuro di voler eliminare definitivamente il libro "${title}" (ASIN: ${asin}) da TUTTI i 14 marketplace Amazon e cancellare tutto il suo storico di recensioni?`;
      openModal("deleteAllStoresModal");
    }
  };

  // Reset Book Reviews Modal Populate
  window.openResetBookModal = function(bookId, title, asin, isAsinWide) {
    const form = document.getElementById("resetBookForm");
    const label = document.getElementById("resetBookTitle");
    if (form && label) {
      if (isAsinWide) {
        form.action = `/books/asin/${asin}/reset-reviews`;
        label.textContent = `Sei sicuro di voler azzerare TUTTE le recensioni registrate per l'ASIN "${asin}" (${title}) su tutti i marketplace? Potrai poi riscaricarle da zero.`;
      } else {
        form.action = `/books/${bookId}/reset-reviews`;
        label.textContent = `Sei sicuro di voler azzerare le recensioni per "${title}" (ID: ${bookId})? Potrai poi riscaricarle premendo 'Forza Aggiornamento'.`;
      }
      openModal("resetBookModal");
    }
  };

  // Open Book Reviews Viewer Modal
  window.openBookReviewsModal = async function(bookId, title) {
    const modalTitle = document.getElementById("bookReviewsModalTitle");
    const modalBody = document.getElementById("bookReviewsModalBody");
    
    if (modalTitle) modalTitle.textContent = `💬 Recensioni: ${title}`;
    if (modalBody) {
      modalBody.innerHTML = `
        <div style="text-align: center; padding: 40px 20px; color: var(--text-subtle);">
          <div style="font-size: 2rem; margin-bottom: 8px;">⏳</div>
          <div>Caricamento recensioni in corso...</div>
        </div>
      `;
    }
    
    openModal("bookReviewsModal");
    
    try {
      const res = await fetch(`/books/${bookId}/reviews-json`);
      const data = await res.json();
      if (!data.success) {
        throw new Error(data.error || "Impossibile recuperare le recensioni");
      }
      
      if (data.reviews.length === 0) {
        modalBody.innerHTML = `
          <div style="text-align: center; padding: 40px 20px;">
            <div style="font-size: 2.5rem; margin-bottom: 10px;">📭</div>
            <h4 style="font-weight: 700; color: #0f172a; margin-bottom: 6px;">Nessuna recensione registrata</h4>
            <p style="color: var(--text-subtle); font-size: 0.9rem; margin-bottom: 16px;">
              Non sono ancora state rilevate recensioni per questa edizione su Amazon.
            </p>
            <a href="${data.book.product_url}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">
              Verifica su Amazon ↗
            </a>
          </div>
        `;
        return;
      }
      
      let html = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border-color);">
          <div style="font-size: 0.92rem; font-weight: 700; color: #0f172a;">
            Trovate ${data.count} recensioni su ${data.book.marketplace}
          </div>
          <a href="${data.book.product_url}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm" style="font-size: 0.8rem;">
            Vedi su Amazon ↗
          </a>
        </div>
      `;
      
      data.reviews.forEach(r => {
        const starsCount = Math.round(r.rating || 5);
        const starsStr = "★".repeat(starsCount) + "☆".repeat(5 - starsCount);
        const isCritical = r.rating <= 3.0;

        let mediaHtml = "";
        if (r.images && r.images.length > 0) {
          mediaHtml += `<div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px;">`;
          r.images.forEach(imgUrl => {
            mediaHtml += `
              <a href="${imgUrl}" target="_blank" rel="noopener" title="Ingrandisci immagine" style="display: inline-block; border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden; width: 90px; height: 90px; background: #f8fafc; cursor: zoom-in;">
                <img src="${imgUrl}" alt="Foto cliente" style="width: 100%; height: 100%; object-fit: cover; display: block;" loading="lazy" />
              </a>
            `;
          });
          mediaHtml += `</div>`;
        }

        if (r.video_url) {
          mediaHtml += `
            <div style="margin-top: 10px; border-radius: 6px; overflow: hidden; max-width: 320px; border: 1px solid var(--border-color);">
              <video src="${r.video_url}" controls style="width: 100%; display: block;" preload="metadata"></video>
            </div>
          `;
        }
        
        html += `
          <div class="review-card-item ${isCritical ? 'negative-review' : 'positive-review'}" style="margin-bottom: 14px; padding: 16px; border-radius: 8px; border: 1px solid var(--border-color); background: #ffffff;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
              <div>
                <span class="stars-rating" style="font-size: 1.05rem; color: #eab308;">${starsStr}</span>
                <span style="font-weight: 800; font-size: 0.95rem; margin-left: 6px; color: #1e293b;">${r.rating}/5</span>
                ${isCritical ? '<span class="badge badge-danger" style="margin-left: 6px; font-size: 0.75rem;">Critica</span>' : ''}
              </div>
              <a href="${r.review_url}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 0.75rem; font-weight: 600;">
                Amazon ↗
              </a>
            </div>
            
            <div style="font-weight: 800; font-size: 0.95rem; color: #0f172a; margin-bottom: 4px;">
              ${r.title}
            </div>
            
            <div style="font-size: 0.8rem; color: var(--text-subtle); margin-bottom: 10px;">
              Recensione di <strong>${r.author}</strong> ${r.review_date ? '&bull; ' + r.review_date : ''}
            </div>
            
            ${r.body ? `<div style="font-size: 0.88rem; color: #334155; line-height: 1.6; white-space: pre-wrap; word-break: break-word;">${r.body}</div>` : ''}
            
            ${mediaHtml}
          </div>
        `;
      });
      
      modalBody.innerHTML = html;
    } catch (err) {
      modalBody.innerHTML = `
        <div style="text-align: center; padding: 30px; color: var(--danger);">
          ⚠️ Errore nel caricamento delle recensioni: ${err.message}
        </div>
      `;
    }
  };

  // ==========================================
  // Live Streaming Check Logs Modal (SSE)
  // ==========================================
  let currentEventSource = null;

  window.startLiveCheck = function(endpoint, title) {
    const modalTitle = document.getElementById("liveCheckTitle");
    const logContainer = document.getElementById("liveCheckLogs");
    const progressBar = document.getElementById("liveCheckProgress");
    const closeBtn = document.getElementById("liveCheckCloseBtn");

    if (modalTitle) modalTitle.textContent = title || "Controllo Aggiornamenti in Corso";
    if (logContainer) logContainer.innerHTML = `<div class="log-line start">⚡ Avvio connessione ai server Amazon...</div>`;
    if (progressBar) progressBar.style.display = "block";
    if (closeBtn) {
      closeBtn.disabled = true;
      closeBtn.textContent = "Controllo in corso...";
    }

    openModal("liveCheckModal");

    if (currentEventSource) {
      currentEventSource.close();
    }

    currentEventSource = new EventSource(endpoint);

    currentEventSource.onmessage = function(event) {
      try {
        const msg = JSON.parse(event.data);
        const line = document.createElement("div");
        line.className = `log-line ${msg.type || ''}`;
        line.textContent = msg.text;
        
        if (logContainer) {
          logContainer.appendChild(line);
          logContainer.scrollTop = logContainer.scrollHeight;
        }

        if (msg.type === "done") {
          if (progressBar) progressBar.style.display = "none";
          if (closeBtn) {
            closeBtn.disabled = false;
            closeBtn.textContent = "✓ Chiudi e Ricarica";
            closeBtn.onclick = function() {
              window.location.reload();
            };
          }
          currentEventSource.close();
        }
      } catch (err) {
        console.error("SSE parse error", err);
      }
    };

    currentEventSource.onerror = function() {
      if (progressBar) progressBar.style.display = "none";
      if (closeBtn) {
        closeBtn.disabled = false;
        closeBtn.textContent = "Chiudi";
        closeBtn.onclick = function() {
          closeModal("liveCheckModal");
          window.location.reload();
        };
      }
      if (currentEventSource) currentEventSource.close();
    };
  };

  // Auto-dismiss alert banners after 7 seconds
  const alerts = document.querySelectorAll(".alert-banner");
  if (alerts.length > 0) {
    setTimeout(() => {
      alerts.forEach(a => {
        a.style.transition = "opacity 0.5s ease";
        a.style.opacity = "0";
        setTimeout(() => a.remove(), 500);
      });
    }, 7000);
  }

  // ==========================================
  // Interactive Table Column Sorting
  // ==========================================
  const tables = document.querySelectorAll("table.sortable-table");
  tables.forEach(table => {
    const headers = table.querySelectorAll("th.sortable-th");
    const tbody = table.querySelector("tbody");
    if (!tbody || headers.length === 0) return;

    headers.forEach((th) => {
      const colIndex = th.cellIndex;
      const sortType = th.getAttribute("data-sort-type") || "string";
      th.innerHTML = `${th.innerHTML} <span class="sort-icon">↕</span>`;

      th.addEventListener("click", () => {
        const isAsc = !th.classList.contains("sort-asc");
        
        headers.forEach(h => {
          h.classList.remove("sort-asc", "sort-desc");
          const icon = h.querySelector(".sort-icon");
          if (icon) icon.textContent = "↕";
        });

        th.classList.toggle("sort-asc", isAsc);
        th.classList.toggle("sort-desc", !isAsc);
        const icon = th.querySelector(".sort-icon");
        if (icon) icon.textContent = isAsc ? "▲" : "▼";

        const rows = Array.from(tbody.querySelectorAll("tr"));
        rows.sort((rowA, rowB) => {
          const cellA = rowA.children[colIndex];
          const cellB = rowB.children[colIndex];
          if (!cellA || !cellB) return 0;

          // For title column, extract from .book-title-link if available
          let valA = "";
          let valB = "";
          const linkA = cellA.querySelector(".book-title-link");
          const linkB = cellB.querySelector(".book-title-link");
          if (linkA && linkB) {
            valA = linkA.textContent.trim();
            valB = linkB.textContent.trim();
          } else {
            valA = cellA.getAttribute("data-sort-val") || cellA.textContent.trim();
            valB = cellB.getAttribute("data-sort-val") || cellB.textContent.trim();
          }

          if (sortType === "number") {
            const numA = parseFloat(valA.toString().replace(/[^0-9.-]+/g, "")) || 0;
            const numB = parseFloat(valB.toString().replace(/[^0-9.-]+/g, "")) || 0;
            return isAsc ? numA - numB : numB - numA;
          } else if (sortType === "date") {
            const parseDate = (dStr) => {
              if (!dStr || dStr === "-" || dStr === "N/A" || dStr === "—" || dStr === "None") return null;
              const parts = dStr.split("/");
              if (parts.length === 3) {
                const yr = parseInt(parts[2], 10);
                const fullYr = yr < 50 ? 2000 + yr : (yr < 100 ? 1900 + yr : yr);
                return new Date(fullYr, parseInt(parts[1], 10) - 1, parseInt(parts[0], 10)).getTime();
              }
              const parsed = new Date(dStr).getTime();
              return isNaN(parsed) ? null : parsed;
            };
            const timeA = parseDate(valA);
            const timeB = parseDate(valB);

            // Entries with no review date ALWAYS go to the bottom
            if (timeA === null && timeB === null) return 0;
            if (timeA === null) return 1;
            if (timeB === null) return -1;

            return isAsc ? timeA - timeB : timeB - timeA;
          } else {
            return isAsc 
              ? valA.localeCompare(valB, "it", { sensitivity: "base", numeric: true }) 
              : valB.localeCompare(valA, "it", { sensitivity: "base", numeric: true });
          }
        });

        rows.forEach(r => tbody.appendChild(r));

        // Re-index fixed progressive numbers (#)
        tbody.querySelectorAll("tr").forEach((row, idx) => {
          const numCell = row.querySelector(".static-row-num, .row-num-cell");
          if (numCell) numCell.textContent = idx + 1;
        });
      });
    });
  });

  // ==========================================
  // Real-Time ASIN Scanner & Modal Flow
  // ==========================================
  const asinInput = document.getElementById("asin");
  const scanBtn = document.getElementById("scanAsinBtn");
  const scannerStatus = document.getElementById("scannerStatusBox");
  const scanResultCard = document.getElementById("scanResultCard");
  const addSubmitBtn = document.getElementById("addBookSubmitBtn");

  const previewCoverImg = document.getElementById("previewCoverImg");
  const previewCoverFallback = document.getElementById("previewCoverFallback");
  const previewTitle = document.getElementById("previewTitle");
  const previewPrice = document.getElementById("previewPrice");
  const previewKindle = document.getElementById("previewKindle");
  const previewMarketplacesList = document.getElementById("previewMarketplacesList");

  const hiddenTitle = document.getElementById("hidden_title");
  const hiddenCover = document.getElementById("hidden_cover_image_url");
  const hiddenPrice = document.getElementById("hidden_price");
  const hiddenHasKindle = document.getElementById("hidden_has_kindle");
  const hiddenKindlePrice = document.getElementById("hidden_kindle_price");
  const hiddenMarketplaces = document.getElementById("hidden_selected_marketplaces");

  let isScanning = false;

  async function performAsinScan() {
    if (!asinInput) return;
    const rawVal = asinInput.value.trim();
    if (!rawVal) {
      alert("Inserisci un codice ASIN o link del libro.");
      asinInput.focus();
      return;
    }

    if (isScanning) return;
    isScanning = true;

    if (scannerStatus) scannerStatus.classList.add("active");
    if (scanResultCard) scanResultCard.classList.remove("active");
    if (scanBtn) {
      scanBtn.disabled = true;
      scanBtn.textContent = "🔍 Scansione in corso...";
    }
    if (addSubmitBtn) {
      addSubmitBtn.disabled = true;
    }

    try {
      const response = await fetch("/books/preview-asin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asin: rawVal })
      });

      const res = await response.json();
      if (!res.success) {
        throw new Error(res.error || "Impossibile completare la scansione.");
      }

      const data = res.data;

      if (previewTitle) previewTitle.textContent = data.title || `Libro ASIN: ${data.asin}`;
      if (hiddenTitle) hiddenTitle.value = data.title || "";

      if (data.cover_image_url) {
        if (previewCoverImg) {
          previewCoverImg.src = data.cover_image_url;
          previewCoverImg.style.display = "block";
        }
        if (previewCoverFallback) previewCoverFallback.style.display = "none";
        if (hiddenCover) hiddenCover.value = data.cover_image_url;
      } else {
        if (previewCoverImg) previewCoverImg.style.display = "none";
        if (previewCoverFallback) previewCoverFallback.style.display = "flex";
        if (hiddenCover) hiddenCover.value = "";
      }

      if (hiddenPrice) hiddenPrice.value = data.price || "";
      if (hiddenHasKindle) hiddenHasKindle.value = data.has_kindle ? "true" : "false";
      if (hiddenKindlePrice) hiddenKindlePrice.value = data.kindle_price || "";

      if (previewMarketplacesList && data.marketplaces) {
        previewMarketplacesList.innerHTML = "";
        const foundStores = [];
        data.marketplaces.forEach(m => {
          const chip = document.createElement("div");
          chip.className = `mkt-chip ${m.found ? 'found' : 'not-found'}`;
          const priceLabel = m.price 
            ? `<span style="color: #059669; font-weight: 700; margin-left: 3px;">${m.price}</span>` 
            : `<span style="color: #94a3b8; margin-left: 3px;">—</span>`;
          chip.innerHTML = `${m.flag} <strong>${m.code || m.marketplace}</strong>: ${priceLabel}`;
          previewMarketplacesList.appendChild(chip);
          if (m.found) {
            foundStores.push(m.marketplace);
          }
        });
        if (hiddenMarketplaces) {
          hiddenMarketplaces.value = foundStores.join(",") || "all";
        }
      }

      if (scannerStatus) scannerStatus.classList.remove("active");
      if (scanResultCard) scanResultCard.classList.add("active");

      if (data.already_exists) {
        if (addSubmitBtn) {
          addSubmitBtn.disabled = true;
          addSubmitBtn.textContent = "⚠️ Libro Già a Catalogo";
          addSubmitBtn.className = "btn btn-secondary";
        }
        if (previewTitle) {
          previewTitle.innerHTML = `<span style="color: var(--danger); font-size: 0.85rem; font-weight: 800; display: block; margin-bottom: 3px;">⚠️ Questo ASIN è già presente nel catalogo:</span> ${data.title || data.existing_title || data.asin}`;
        }
      } else {
        if (addSubmitBtn) {
          addSubmitBtn.disabled = false;
          addSubmitBtn.textContent = `✓ Aggiungi Libro (${data.found_count || 14} Store Rilevati)`;
          addSubmitBtn.className = "btn btn-primary";
        }
      }

    } catch (err) {
      console.warn("Scan warning:", err.message);
      if (scannerStatus) scannerStatus.classList.remove("active");
      if (addSubmitBtn) {
        addSubmitBtn.disabled = false;
        addSubmitBtn.textContent = "+ Aggiungi Libro";
      }
    } finally {
      isScanning = false;
      if (scanBtn) {
        scanBtn.disabled = false;
        scanBtn.textContent = "🔍 Cerca / Ricarica Info";
      }
    }
  }

  if (scanBtn) {
    scanBtn.addEventListener("click", (e) => {
      e.preventDefault();
      performAsinScan();
    });
  }

  if (asinInput) {
    asinInput.addEventListener("paste", () => {
      setTimeout(performAsinScan, 200);
    });
  }
});
