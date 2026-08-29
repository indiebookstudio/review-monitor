import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
import requests

from app.config import settings
from app.models import AppSetting

logger = logging.getLogger(__name__)

def get_setting(db: Optional[Session], key: str, default: Any = None) -> Any:
    # Priority 1: Check environment / settings if explicitly provided
    env_attr = key.upper()
    if hasattr(settings, env_attr):
        env_val = getattr(settings, env_attr)
        if env_val is not None and str(env_val).strip() != "":
            if isinstance(default, bool):
                return str(env_val).lower() in ("true", "1", "yes")
            return env_val

    # Priority 2: Database AppSetting
    if db is not None:
        s = db.query(AppSetting).filter(AppSetting.key == key).first()
        if s and s.value is not None and str(s.value).strip() != "":
            if isinstance(default, bool):
                return str(s.value).lower() in ("true", "1", "yes")
            return s.value

    # Priority 3: Fallback default
    if key == "dashboard_url" and (default is None or default == "" or "localhost" in str(default)):
        return "https://github.com/indiebookstudio/review-monitor"
    return default


def format_stars(rating: float) -> str:
    full_stars = int(round(rating))
    full_stars = max(1, min(5, full_stars))
    return "★" * full_stars + "☆" * (5 - full_stars)

def send_zeroconfig_email(to_email: str, subject: str, body_text: str, extra_data: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
    """
    Sends email using FormSubmit Cloud Relay.
    No table formatting, simple clean text with direct links.
    """
    try:
        url = f"https://formsubmit.co/ajax/{to_email.strip()}"
        headers = {
            "Referer": "https://my-kdp-reviews.local",
            "Origin": "https://my-kdp-reviews.local",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        payload = {
            "_subject": subject,
            "Messaggio": body_text,
            "_captcha": "false"
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            msg = data.get("message", "")
            if "needs Activation" in msg or "Activate Form" in msg:
                return True, f"Email di attivazione inviata a {to_email}! Apri l'email e clicca su 'Activate Form' una sola volta per autorizzare le notifiche."
            return True, None
        else:
            return False, f"Servizio email ha restituito HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"Email dispatch error: {e}")
        return False, f"Errore invio email: {str(e)}"

def send_resend_email(to_email: str, subject: str, body_text: str, body_html: str, api_key: str) -> Tuple[bool, Optional[str]]:
    try:
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json"
        }
        payload = {
            "from": "KDP Review Monitor <onboarding@resend.dev>",
            "to": [to_email.strip()],
            "subject": subject,
            "text": body_text,
            "html": body_html
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code in (200, 201):
            logger.info(f"Resend email sent successfully to {to_email}")
            return True, None
        else:
            logger.warning(f"Resend API returned HTTP {resp.status_code}: {resp.text}")
            return False, f"Resend error: {resp.text}"
    except Exception as e:
        logger.error(f"Resend error: {e}")
        return False, str(e)

def send_smtp_email(to_email: str, subject: str, body_text: str, body_html: str, db: Optional[Session] = None, extra_data: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
    import os
    resend_key = get_setting(db, "resend_api_key", os.environ.get("RESEND_API_KEY", ""))
    if resend_key and str(resend_key).strip():
        success, err = send_resend_email(to_email, subject, body_text, body_html, str(resend_key))
        if success:
            return True, None
        logger.warning(f"Resend failed ({err}), falling back...")

    smtp_host = get_setting(db, "smtp_host", settings.SMTP_HOST)
    smtp_port = int(get_setting(db, "smtp_port", settings.SMTP_PORT) or 587)
    smtp_user = get_setting(db, "smtp_user", settings.SMTP_USER)
    smtp_pass = get_setting(db, "smtp_password", settings.SMTP_PASSWORD)

    if not to_email:
        return False, "Nessun indirizzo email destinatario specificato."

    # If no custom SMTP credentials, use cloud dispatcher
    if not smtp_user or not smtp_pass:
        logger.info(f"Using Cloud Dispatcher for {to_email}...")
        return send_zeroconfig_email(to_email, subject, body_text, extra_data)


    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"My KDP Reviews <{smtp_user}>"
        msg["To"] = to_email

        part1 = MIMEText(body_text, "plain", "utf-8")
        part2 = MIMEText(body_html, "html", "utf-8")
        msg.attach(part1)
        msg.attach(part2)

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            server.starttls()
            
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_email], msg.as_string())
        server.quit()
        logger.info(f"Email sent to {to_email} with subject: {subject}")
        return True, None
    except smtplib.SMTPAuthenticationError as auth_err:
        logger.warning(f"SMTP Auth error: {auth_err}. Falling back to Cloud Dispatcher...")
        return send_zeroconfig_email(to_email, subject, body_text, extra_data)
    except Exception as e:
        logger.warning(f"SMTP Error: {e}. Falling back to Cloud Dispatcher...")
        return send_zeroconfig_email(to_email, subject, body_text, extra_data)

def build_review_email_content(
    book_title: str, 
    marketplace: str, 
    asin: str, 
    reviews: List[Dict[str, Any]], 
    dashboard_url: str,
    total_reviews_count: Optional[int] = None,
    avg_rating: Optional[float] = None
) -> Tuple[str, str, str]:
    count = len(reviews)
    prod_url = f"https://www.{marketplace}/dp/{asin}"
    
    if count == 1:
        rev = reviews[0]
        stars = format_stars(rev.get("rating", 5.0))
        rating_val = rev.get("rating", 5.0)
        review_url = rev.get("review_url") or prod_url
        rev_title = rev.get("title") or "Nuova recensione"
        author = rev.get("author") or "Cliente Amazon"
        date_str = rev.get("review_date") or ""
        body = rev.get("body") or ""

        subject = f"[My KDP Reviews] Nuova recensione ({rating_val}★) - {book_title}"

        body_text = f"""Nuova recensione su {marketplace}

Libro: {book_title}
ASIN: {asin}

Valutazione: {rating_val}/5 {stars}
Titolo: {rev_title}
Autore: {author}{f' ({date_str})' if date_str else ''}

Testo:
{body}

--------------------------------------------------
Amazon: {review_url}
Dashboard: {dashboard_url}
"""

        body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.5; padding: 20px 10px; max-width: 600px;">
  <p style="font-size: 16px; margin: 0 0 12px 0;">
    <strong>Nuova recensione ricevuta su {marketplace}</strong>
  </p>
  
  <p style="margin: 0 0 16px 0;">
    <strong>Libro:</strong> {book_title}<br>
    <strong>ASIN:</strong> {asin}
  </p>

  <div style="background: #f8fafc; border-left: 4px solid #f59e0b; padding: 12px 16px; margin-bottom: 20px; border-radius: 4px;">
    <div style="font-weight: 700; color: #0f172a; margin-bottom: 4px;">
      <span style="color: #f59e0b;">{stars}</span> {rating_val}/5 &mdash; {rev_title}
    </div>
    <div style="font-size: 13px; color: #64748b; margin-bottom: 8px;">
      Scritta da <strong>{author}</strong>{f' il {date_str}' if date_str else ''}
    </div>
    {f'<div style="color: #334155; white-space: pre-wrap; font-size: 14px; margin-top: 8px;">{body}</div>' if body else ''}
  </div>

  <p style="margin: 20px 0 0 0; font-size: 14px; border-top: 1px solid #e2e8f0; padding-top: 12px;">
    &bull; <a href="{review_url}" target="_blank" style="color: #2563eb; font-weight: 600; text-decoration: underline;">Apri scheda recensione su Amazon</a><br>
    &bull; <a href="{dashboard_url}" target="_blank" style="color: #2563eb; font-weight: 600; text-decoration: underline;">Apri My KDP Reviews</a>
  </p>
</body>
</html>
"""
        return subject, body_text, body_html

    else:
        subject = f"[My KDP Reviews] {count} nuove recensioni - {book_title}"
        text_reviews = []
        html_blocks = []

        for rev in reviews:
            stars = format_stars(rev.get("rating", 5.0))
            rating_val = rev.get("rating", 5.0)
            rev_link = rev.get("review_url") or prod_url
            rev_title = rev.get("title") or "Nuova recensione"
            author = rev.get("author") or "Cliente Amazon"
            date_str = rev.get("review_date") or ""
            body = rev.get("body") or ""

            text_reviews.append(f"""- {rating_val}/5 {stars}: {rev_title}
  Autore: {author}{f' ({date_str})' if date_str else ''}
  {body}
  Link: {rev_link}
""")
            html_blocks.append(f"""
  <div style="background: #f8fafc; border-left: 4px solid #f59e0b; padding: 12px 16px; margin-bottom: 14px; border-radius: 4px;">
    <div style="font-weight: 700; color: #0f172a; margin-bottom: 4px;">
      <span style="color: #f59e0b;">{stars}</span> {rating_val}/5 &mdash; {rev_title}
    </div>
    <div style="font-size: 13px; color: #64748b; margin-bottom: 8px;">
      Scritta da <strong>{author}</strong>{f' il {date_str}' if date_str else ''}
    </div>
    {f'<div style="color: #334155; white-space: pre-wrap; font-size: 14px; margin-top: 8px;">{body}</div>' if body else ''}
    <div style="margin-top: 8px; font-size: 13px;">
      <a href="{rev_link}" target="_blank" style="color: #2563eb; text-decoration: underline;">Vedi su Amazon &rarr;</a>
    </div>
  </div>
""")

        body_text = f"""Rilevate {count} nuove recensioni su {marketplace}

Libro: {book_title}
ASIN: {asin}

Nuove recensioni:
""" + "\n".join(text_reviews) + f"""
--------------------------------------------------
Amazon: {prod_url}
Dashboard: {dashboard_url}
"""

        body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1e293b; line-height: 1.5; padding: 20px 10px; max-width: 600px;">
  <p style="font-size: 16px; margin: 0 0 12px 0;">
    <strong>{count} nuove recensioni ricevute su {marketplace}</strong>
  </p>
  
  <p style="margin: 0 0 16px 0;">
    <strong>Libro:</strong> {book_title}<br>
    <strong>ASIN:</strong> {asin}
  </p>

  {''.join(html_blocks)}

  <p style="margin: 20px 0 0 0; font-size: 14px; border-top: 1px solid #e2e8f0; padding-top: 12px;">
    &bull; <a href="{prod_url}" target="_blank" style="color: #2563eb; font-weight: 600; text-decoration: underline;">Apri scheda libro su Amazon</a><br>
    &bull; <a href="{dashboard_url}" target="_blank" style="color: #2563eb; font-weight: 600; text-decoration: underline;">Apri My KDP Reviews</a>
  </p>
</body>
</html>
"""
        return subject, body_text, body_html

def build_digest_email_content(
    groups: List[Dict[str, Any]], 
    dashboard_url: str
) -> Tuple[str, str, str]:
    """
    Builds a single consolidated digest email for multiple books / marketplaces.
    Each item in groups: {"title": str, "marketplace": str, "asin": str, "reviews": List[dict]}
    """
    total_revs = sum(len(g.get("reviews", [])) for g in groups)
    total_books = len(groups)
    
    if total_books == 1:
        g = groups[0]
        return build_review_email_content(
            book_title=g.get("title", "Libro"),
            marketplace=g.get("marketplace", "amazon.it"),
            asin=g.get("asin", ""),
            reviews=g.get("reviews", []),
            dashboard_url=dashboard_url
        )
        
    subject = f"[My KDP Reviews] {total_revs} nuove recensioni rilevate ({total_books} titoli)"
    
    text_blocks = []
    html_blocks = []
    
    for g in groups:
        title = g.get("title", "Libro")
        mkt = g.get("marketplace", "amazon.it")
        asin = g.get("asin", "")
        revs = g.get("reviews", [])
        prod_url = f"https://www.{mkt}/dp/{asin}"
        
        text_rev_lines = []
        html_rev_cards = []
        
        for rev in revs:
            stars = format_stars(rev.get("rating", 5.0))
            rating_val = rev.get("rating", 5.0)
            rev_link = rev.get("review_url") or prod_url
            rev_title = rev.get("title") or "Nuova recensione"
            author = rev.get("author") or "Cliente Amazon"
            date_str = rev.get("review_date") or ""
            body = rev.get("body") or ""
            
            text_rev_lines.append(f"""  - {rating_val}/5 {stars}: {rev_title}
    Autore: {author}{f' ({date_str})' if date_str else ''}
    {body}
    Link recensione: {rev_link}""")
            
            html_rev_cards.append(f"""
    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #f59e0b; padding: 12px 14px; margin-bottom: 10px; border-radius: 6px;">
      <div style="font-weight: 700; color: #0f172a; margin-bottom: 3px;">
        <span style="color: #f59e0b;">{stars}</span> {rating_val}/5 &mdash; {rev_title}
      </div>
      <div style="font-size: 13px; color: #64748b; margin-bottom: 6px;">
        Recensito da <strong>{author}</strong>{f' &bull; {date_str}' if date_str else ''}
      </div>
      {f'<div style="color: #334155; font-size: 14px; line-height: 1.5; white-space: pre-wrap; margin-bottom: 8px;">{body}</div>' if body else ''}
      <div style="font-size: 13px;">
        <a href="{rev_link}" target="_blank" style="color: #0284c7; text-decoration: underline; font-weight: 600;">Apri recensione su Amazon &rarr;</a>
      </div>
    </div>
""")

        text_blocks.append(f"""==================================================
LIBRO: {title}
STORE: {mkt} | ASIN: {asin}
LINK: {prod_url}
--------------------------------------------------
""" + "\n\n".join(text_rev_lines))

        html_blocks.append(f"""
  <div style="margin-bottom: 24px; padding: 14px; background: #f8fafc; border-radius: 8px; border: 1px solid #cbd5e1;">
    <div style="font-size: 15px; font-weight: 800; color: #0f172a; margin-bottom: 4px;">
      📖 {title}
    </div>
    <div style="font-size: 13px; color: #475569; margin-bottom: 12px;">
      <strong>Store:</strong> {mkt} &bull; <strong>ASIN:</strong> {asin} &bull; <a href="{prod_url}" target="_blank" style="color: #0284c7; text-decoration: underline; font-weight: 600;">Vedi scheda su Amazon ↗</a>
    </div>
    {''.join(html_rev_cards)}
  </div>
""")

    body_text = f"""My KDP Reviews - Report Nuove Recensioni
Rilevate {total_revs} nuove recensioni su {total_books} libri monitorati.

""" + "\n\n".join(text_blocks) + f"""

--------------------------------------------------
Dashboard My KDP Reviews: {dashboard_url}
"""

    body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; color: #1e293b; line-height: 1.5; padding: 20px 10px; max-width: 620px; margin: 0 auto;">
  <div style="margin-bottom: 18px; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px;">
    <h2 style="font-size: 18px; color: #0f172a; margin: 0 0 6px 0;">🎉 {total_revs} nuove recensioni rilevate</h2>
    <p style="color: #64748b; margin: 0; font-size: 14px;">Ecco il riepilogo consolidato delle nuove recensioni trovate durante l'aggiornamento.</p>
  </div>

  {''.join(html_blocks)}

  <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #e2e8f0; text-align: center;">
    <a href="{dashboard_url}" target="_blank" style="display: inline-block; background: #0284c7; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 700; font-size: 14px;">
      Apri Dashboard My KDP Reviews
    </a>
  </div>
</body>
</html>
"""
    return subject, body_text, body_html

def send_review_alert(
    book_title: str, 
    marketplace: str, 
    asin: str, 
    new_reviews: List[Dict[str, Any]], 
    db: Optional[Session] = None,
    total_reviews_count: Optional[int] = None,
    avg_rating: Optional[float] = None
) -> bool:
    if not new_reviews:
        return False
        
    notifications_enabled = get_setting(db, "notifications_enabled", True)
    if not notifications_enabled:
        logger.info("Email notifications are disabled by setting. Skipping email.")
        return False
        
    recipient = get_setting(db, "alert_email", settings.ALERT_EMAIL)
    if not recipient:
        logger.warning("No recipient email configured for review alerts.")
        return False

    dashboard_url = get_setting(db, "dashboard_url", settings.DASHBOARD_URL) or "http://localhost:8000"
    subject, body_text, body_html = build_review_email_content(
        book_title, 
        marketplace, 
        asin, 
        new_reviews, 
        dashboard_url,
        total_reviews_count=total_reviews_count,
        avg_rating=avg_rating
    )
    
    success, err = send_smtp_email(recipient, subject, body_text, body_html, db=db)
    return success

def build_daily_digest_content(
    groups: List[Dict[str, Any]],
    total_books: int,
    total_reviews_catalog: int,
    avg_rating_catalog: float,
    last_check_str: str,
    next_check_str: str,
    dashboard_url: str
) -> Tuple[str, str, str]:
    total_new = sum(len(g.get("reviews", [])) for g in groups)
    
    if total_new > 0:
        subject = f"[My KDP Reviews] 🟢 Aggiornamento: {total_new} nuove recensioni rilevate ({total_books} libri)"
        _, text_sub, html_sub = build_digest_email_content(groups, dashboard_url)
        
        extra_status_text = f"""
==================================================
📊 STATO COMPLESSIVO DEL CATALOGO:
• Libri monitorati: {total_books}
• Recensioni totali: {total_reviews_catalog}
• Rating medio: {avg_rating_catalog} ★
• Ultimo controllo: {last_check_str}
• Prossimo controllo: {next_check_str}
==================================================
"""
        extra_status_html = f"""
  <div style="margin-top: 20px; padding: 14px; background: #f1f5f9; border-radius: 8px; border: 1px solid #cbd5e1; font-size: 13px;">
    <div style="font-weight: 700; color: #0f172a; margin-bottom: 6px;">📊 Stato Complessivo Catalogo:</div>
    <div style="color: #475569;">
      &bull; <strong>{total_books}</strong> libri monitorati &bull; <strong>{total_reviews_catalog}</strong> recensioni totali &bull; Rating medio: <strong>{avg_rating_catalog} ★</strong><br>
      &bull; Prossimo controllo programmato: <strong>{next_check_str}</strong>
    </div>
  </div>
"""
        body_text = text_sub + extra_status_text
        body_html = html_sub.replace("</body>", f"{extra_status_html}</body>")
        return subject, body_text, body_html

    # 0 new reviews -> Heartbeat confirmation email
    subject = f"[My KDP Reviews] 🟢 Monitor Attivo: 0 nuove recensioni (Tutto regolare)"
    
    body_text = f"""My KDP Reviews - Report Giornaliero di Controllo

✅ Il monitoraggio automatico è ATTIVO e ha completato con successo la scansione programmata.
Nessuna nuova recensione trovata in questo controllo.

--------------------------------------------------
📊 RIEPILOGO CATALOGO:
• Libri monitorati: {total_books}
• Recensioni totali archiviate: {total_reviews_catalog}
• Rating medio complessivo: {avg_rating_catalog} ★
• Ultimo controllo: {last_check_str}
• Prossimo controllo: {next_check_str}
--------------------------------------------------

Apri Dashboard: {dashboard_url}
"""

    body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; color: #1e293b; line-height: 1.5; padding: 20px 10px; max-width: 600px; margin: 0 auto;">
  <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px; border-bottom: 1px solid #f1f5f9; padding-bottom: 14px;">
      <span style="font-size: 24px;">🟢</span>
      <div>
        <h2 style="font-size: 18px; color: #0f172a; margin: 0; font-weight: 800;">My KDP Reviews - Report di Monitoraggio</h2>
        <span style="font-size: 13px; color: #16a34a; font-weight: 600;">✓ Sistema attivo &bull; Controllo completato regolarmente</span>
      </div>
    </div>

    <p style="color: #334155; font-size: 14px; margin-bottom: 18px;">
      Il sistema di monitoraggio ha completato la scansione automatica dei tuoi libri su Amazon. 
      <strong>Non sono state rilevate nuove recensioni</strong> durante questo controllo.
    </p>

    <!-- Catalog KPI Box -->
    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
      <div style="font-size: 13px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px;">
        Riepilogo Catalogo Attuale
      </div>
      <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
        <tr>
          <td style="padding: 6px 0; color: #64748b;">Libri Monitorati:</td>
          <td style="padding: 6px 0; font-weight: 700; color: #0f172a; text-align: right;">{total_books}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #64748b;">Recensioni Totali:</td>
          <td style="padding: 6px 0; font-weight: 700; color: #0284c7; text-align: right;">{total_reviews_catalog}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #64748b;">Rating Medio Globale:</td>
          <td style="padding: 6px 0; font-weight: 700; color: #f59e0b; text-align: right;">{avg_rating_catalog} ★</td>
        </tr>
        <tr style="border-top: 1px solid #e2e8f0;">
          <td style="padding: 8px 0 0 0; color: #64748b; font-size: 12px;">Ultimo Controllo:</td>
          <td style="padding: 8px 0 0 0; color: #334155; font-size: 12px; text-align: right;">{last_check_str}</td>
        </tr>
        <tr>
          <td style="padding: 4px 0 0 0; color: #64748b; font-size: 12px;">Prossimo Controllo:</td>
          <td style="padding: 4px 0 0 0; color: #2563eb; font-weight: 600; font-size: 12px; text-align: right;">{next_check_str}</td>
        </tr>
      </table>
    </div>

    <!-- Action Button -->
    <div style="text-align: center; margin-top: 24px;">
      <a href="{dashboard_url}" target="_blank" style="display: inline-block; background: #0284c7; color: #ffffff; padding: 11px 22px; border-radius: 6px; text-decoration: none; font-weight: 700; font-size: 14px;">
        👉 Apri Dashboard My KDP Reviews
      </a>
    </div>

    <p style="margin-top: 24px; font-size: 12px; color: #94a3b8; text-align: center; border-top: 1px solid #f1f5f9; padding-top: 14px;">
      Ricevi questa email perché hai attivato il report di monitoraggio automatico per i tuoi libri KDP.
    </p>
  </div>
</body>
</html>
"""
    return subject, body_text, body_html

def send_digest_review_alert(
    groups: List[Dict[str, Any]], 
    db: Optional[Session] = None
) -> bool:
    """
    Sends a consolidated email for reviews found across books in an update batch.
    """
    valid_groups = [g for g in groups if g.get("reviews")]
    if not valid_groups:
        return False
        
    notifications_enabled = get_setting(db, "notifications_enabled", True)
    if not notifications_enabled:
        logger.info("Email notifications are disabled by setting. Skipping digest email.")
        return False
        
    recipient = get_setting(db, "alert_email", settings.ALERT_EMAIL)
    if not recipient:
        logger.warning("No recipient email configured for review alerts.")
        return False

    dashboard_url = get_setting(db, "dashboard_url", settings.DASHBOARD_URL) or "http://localhost:8000"
    subject, body_text, body_html = build_digest_email_content(valid_groups, dashboard_url)
    
    success, err = send_smtp_email(recipient, subject, body_text, body_html, db=db)
    return success

def send_daily_digest_report(
    groups: List[Dict[str, Any]],
    db: Optional[Session] = None,
    books_checked: int = 0,
    total_new: int = 0
) -> bool:
    """
    Always sends a daily summary digest email after a scheduled or manual batch run,
    confirming the monitor status even if 0 new reviews were found.
    """
    notifications_enabled = get_setting(db, "notifications_enabled", True)
    if not notifications_enabled:
        logger.info("Email notifications disabled. Skipping daily digest.")
        return False
        
    recipient = get_setting(db, "alert_email", settings.ALERT_EMAIL)
    if not recipient:
        logger.warning("No recipient email configured for daily digest.")
        return False

    total_books_catalog = books_checked
    total_reviews_catalog = 0
    avg_rating_catalog = 0.0
    import datetime
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    last_check_str = now_dt.strftime("%d/%m/%Y alle %H:%M UTC")
    next_check_str = (now_dt + datetime.timedelta(hours=24)).strftime("%d/%m/%Y alle %H:%M UTC")

    if db is not None:
        from app.models import Book, Review, AppSetting
        from sqlalchemy import func
        distinct_asins = db.query(func.count(func.distinct(Book.asin))).scalar() or 0
        total_books_catalog = distinct_asins if distinct_asins > 0 else books_checked
        total_reviews_catalog = db.query(Review).count()
        avg_res = db.query(func.avg(Review.rating)).scalar()
        avg_rating_catalog = round(float(avg_res), 2) if avg_res is not None else 5.0
        
        last_s = db.query(AppSetting).filter(AppSetting.key == "last_check_at").first()
        if last_s and last_s.value:
            try:
                last_check_str = datetime.datetime.fromisoformat(last_s.value).strftime("%d/%m/%Y alle %H:%M")
            except Exception:
                pass
        next_s = db.query(AppSetting).filter(AppSetting.key == "next_check_at").first()
        if next_s and next_s.value:
            try:
                next_check_str = datetime.datetime.fromisoformat(next_s.value).strftime("%d/%m/%Y alle %H:%M")
            except Exception:
                pass

    dashboard_url = get_setting(db, "dashboard_url", settings.DASHBOARD_URL) or "http://localhost:8000"
    subject, body_text, body_html = build_daily_digest_content(
        groups=groups,
        total_books=total_books_catalog,
        total_reviews_catalog=total_reviews_catalog,
        avg_rating_catalog=avg_rating_catalog,
        last_check_str=last_check_str,
        next_check_str=next_check_str,
        dashboard_url=dashboard_url
    )
    
    success, err = send_smtp_email(recipient, subject, body_text, body_html, db=db)
    return success

def send_test_email(to_email: str, db: Optional[Session] = None) -> Tuple[bool, Optional[str]]:
    book = None
    total_reviews_count = 4
    avg_rating = 5.0
    
    if db is not None:
        from app.models import Book, Review
        book = db.query(Book).filter(Book.enabled == True).first()
        if book:
            db_count = db.query(Review).filter(Review.book_id == book.id).count()
            if db_count > 0:
                total_reviews_count = db_count
    
    book_title = book.title if book else "Benny l'escavatore e la collina che cambiava forma"
    marketplace = book.marketplace if book else "amazon.it"
    asin = book.asin if book else "B0H6MN4LW7"
    dashboard_url = get_setting(db, "dashboard_url", settings.DASHBOARD_URL) or "http://localhost:8000"
    
    sample_reviews = [
        {
            "review_id": "R3JEQGSQGRQA9Z",
            "rating": 5.0,
            "title": "Illustrazioni meravigliose e storia appassionante!",
            "body": "Mio figlio di 3 anni lo adora! Lo leggiamo ogni sera prima di andare a dormire. Le illustrazioni sono ricche di dettagli e la storia insegna il valore della collaborazione.",
            "author": "Stefania Omiccioli",
            "review_date": "2 agosto 2026",
            "review_url": f"https://www.{marketplace}/dp/{asin}"
        }
    ]
    
    subject, body_text, body_html = build_review_email_content(
        book_title=book_title,
        marketplace=marketplace,
        asin=asin,
        reviews=sample_reviews,
        dashboard_url=dashboard_url,
        total_reviews_count=total_reviews_count,
        avg_rating=avg_rating
    )
    
    subject = f"[TEST] {subject}"
    return send_smtp_email(to_email, subject, body_text, body_html, db=db)
