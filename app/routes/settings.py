import logging
import re
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pathlib import Path

from app.database import get_db
from app.auth import require_auth, authenticate_admin, hash_password, set_admin_password_hash
from app.models import AppSetting, AuditLog
from app.config import settings as app_settings
from app.notifications.email import send_test_email
from app.reviews.monitor import run_all_checks, reset_all_reviews

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/settings", dependencies=[Depends(require_auth)])

def get_setting_value(db: Session, key: str, default: str = "") -> str:
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    if s and s.value is not None:
        return s.value
    return default

def set_setting_value(db: Session, key: str, value: str):
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not s:
        s = AppSetting(key=key, value=value)
        db.add(s)
    else:
        s.value = value
    db.commit()

@router.get("/", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    msg: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db)
):
    alert_email = get_setting_value(db, "alert_email", app_settings.ALERT_EMAIL)
    notifications_enabled = get_setting_value(db, "notifications_enabled", str(app_settings.NOTIFICATIONS_ENABLED)).lower() in ("true", "1", "yes")
    check_frequency = get_setting_value(db, "check_frequency", f"{app_settings.CHECK_FREQUENCY_HOURS}h")
    dashboard_url = get_setting_value(db, "dashboard_url", app_settings.DASHBOARD_URL)
    next_check_at = get_setting_value(db, "next_check_at", "")
    
    smtp_host = get_setting_value(db, "smtp_host", app_settings.SMTP_HOST)
    smtp_port = get_setting_value(db, "smtp_port", str(app_settings.SMTP_PORT))
    smtp_user = get_setting_value(db, "smtp_user", app_settings.SMTP_USER)
    
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "alert_email": alert_email,
            "notifications_enabled": notifications_enabled,
            "check_frequency": check_frequency,
            "dashboard_url": dashboard_url,
            "next_check_at": next_check_at,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_user": smtp_user,
            "msg": msg,
            "error": error,
            "active_tab": "settings"
        }
    )

@router.post("/update")
async def update_settings(
    request: Request,
    alert_email: Optional[str] = Form(default=""),
    notifications_enabled: bool = Form(default=False),
    check_frequency: str = Form(default="24h"),
    dashboard_url: Optional[str] = Form(default=""),
    smtp_host: Optional[str] = Form(default=""),
    smtp_port: Optional[str] = Form(default="587"),
    smtp_user: Optional[str] = Form(default=""),
    smtp_password: Optional[str] = Form(default=""),
    db: Session = Depends(get_db)
):
    try:
        clean_email = alert_email.strip() if alert_email else ""
        if clean_email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean_email):
            return RedirectResponse(
                url="/settings?error=Formato indirizzo email non valido.",
                status_code=status.HTTP_303_SEE_OTHER
            )
            
        clean_url = dashboard_url.strip() if dashboard_url else ""
        if clean_url and not clean_url.startswith("http"):
            clean_url = f"https://{clean_url}"
            
        set_setting_value(db, "alert_email", clean_email)
        set_setting_value(db, "notifications_enabled", "true" if notifications_enabled else "false")
        set_setting_value(db, "check_frequency", check_frequency)
        set_setting_value(db, "dashboard_url", clean_url)
        
        if smtp_host:
            set_setting_value(db, "smtp_host", smtp_host.strip())
        if smtp_port:
            set_setting_value(db, "smtp_port", smtp_port.strip())
        if smtp_user:
            set_setting_value(db, "smtp_user", smtp_user.strip())
        if smtp_password and len(smtp_password.strip()) > 0:
            set_setting_value(db, "smtp_password", smtp_password.strip())
        
        audit = AuditLog(
            action="SETTINGS_UPDATED",
            details=f"Aggiornate impostazioni: Email={clean_email}, Notifiche={notifications_enabled}, Frequenza={check_frequency}"
        )
        db.add(audit)
        db.commit()
        
        return RedirectResponse(
            url="/settings?msg=Impostazioni salvate con successo!",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return RedirectResponse(
            url=f"/settings?error=Errore salvataggio impostazioni: {str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )

@router.post("/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    if not authenticate_admin(current_password, db):
        return RedirectResponse(
            url="/settings?error=La password attuale non è corretta.",
            status_code=status.HTTP_303_SEE_OTHER
        )
        
    if new_password != confirm_password:
        return RedirectResponse(
            url="/settings?error=La nuova password e la conferma non coincidono.",
            status_code=status.HTTP_303_SEE_OTHER
        )
        
    if len(new_password) < 6:
        return RedirectResponse(
            url="/settings?error=La nuova password deve contenere almeno 6 caratteri.",
            status_code=status.HTTP_303_SEE_OTHER
        )
        
    new_hash = hash_password(new_password)
    set_admin_password_hash(db, new_hash)
    
    audit = AuditLog(action="PASSWORD_CHANGED", details="Password amministratore modificata con successo.")
    db.add(audit)
    db.commit()
    
    return RedirectResponse(
        url="/settings?msg=Password modificata con successo!",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/test-email")
async def trigger_test_email(request: Request, db: Session = Depends(get_db)):
    email_dest = get_setting_value(db, "alert_email", app_settings.ALERT_EMAIL)
    if not email_dest:
        return RedirectResponse(
            url="/settings?error=Nessun indirizzo email destinatario configurato. Inserisci la tua email nel campo 'Email Destinataria Notifiche'.",
            status_code=status.HTTP_303_SEE_OTHER
        )
        
    success, err_msg = send_test_email(email_dest, db)
    if success:
        return RedirectResponse(
            url=f"/settings?msg=Email di test inviata con successo a {email_dest}!",
            status_code=status.HTTP_303_SEE_OTHER
        )
    else:
        clean_err = err_msg or "Verifica che 'Nome utente SMTP' e 'Password per le App' siano configurati."
        return RedirectResponse(
            url=f"/settings?error={clean_err}",
            status_code=status.HTTP_303_SEE_OTHER
        )

@router.post("/run-check")
async def trigger_run_check(request: Request, db: Session = Depends(get_db)):
    try:
        report = run_all_checks(db, force=True, force_alert=False)
        count = report.get("books_checked", 0)
        new_revs = report.get("total_new_reviews", 0)
        emails = report.get("total_emails_sent", 0)
        email_str = f" ({emails} notifiche email inviate)" if emails > 0 else ""
        
        referer = request.headers.get("referer", "/settings")
        return RedirectResponse(
            url=f"{referer}?msg=Controllo completato! Verificati {count} libri. Nuove recensioni trovate: {new_revs}.{email_str}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.error(f"Manual check run failed: {e}")
        referer = request.headers.get("referer", "/settings")
        return RedirectResponse(
            url=f"{referer}?error=Errore durante l'esecuzione del controllo: {str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )

@router.post("/reset-all-reviews")
async def trigger_reset_all_reviews(request: Request, db: Session = Depends(get_db)):
    try:
        deleted = reset_all_reviews(db)
        return RedirectResponse(
            url=f"/settings?msg=Azzeramento completato! Cancellate {deleted} recensioni da tutti i libri. Ora puoi eseguire 'Controlla Ora' per riscaricarle da zero e ricevere la notifica email di test.",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/settings?error=Errore durante l'azzeramento delle recensioni: {str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )
