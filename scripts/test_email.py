#!/usr/bin/env python3
"""
CLI script to test email notification dispatch.
Used for manual diagnostics or testing directly from GitHub Actions workflow.
"""
import sys
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import AppSetting
from app.notifications.email import send_test_email, get_setting

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("kdp-test-email")

def main():
    parser = argparse.ArgumentParser(description="Test KDP Review Monitor email sending.")
    parser.add_argument(
        "--email",
        type=str,
        default="",
        help="Target email address (overrides settings if provided)"
    )
    args = parser.parse_args()

    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Sync environment variables into DB settings if provided
        for env_attr, setting_key in [
            ("ALERT_EMAIL", "alert_email"),
            ("RESEND_API_KEY", "resend_api_key"),
            ("SMTP_HOST", "smtp_host"),
            ("SMTP_PORT", "smtp_port"),
            ("SMTP_USER", "smtp_user"),
            ("SMTP_PASSWORD", "smtp_password"),
            ("DASHBOARD_URL", "dashboard_url"),
        ]:
            val = getattr(settings, env_attr, None)
            if val is not None and str(val).strip() != "":
                s = db.query(AppSetting).filter(AppSetting.key == setting_key).first()
                if s:
                    s.value = str(val)
                else:
                    db.add(AppSetting(key=setting_key, value=str(val)))
        db.commit()

        target_email = args.email.strip() or get_setting(db, "alert_email", settings.ALERT_EMAIL) or "saluccimarco@gmail.com"
        resend_key = get_setting(db, "resend_api_key", None)
        smtp_user = get_setting(db, "smtp_user", settings.SMTP_USER)
        smtp_host = get_setting(db, "smtp_host", settings.SMTP_HOST)
        smtp_port = get_setting(db, "smtp_port", settings.SMTP_PORT)

        print("\n" + "=" * 60)
        print("          TEST INVIO EMAIL - KDP REVIEW MONITOR")
        print("=" * 60)
        print(f" Destinatario:       {target_email}")
        print(f" Resend API Key:     {'CONFIGURATA (***)' if resend_key else 'NON PRESENTE'}")
        print(f" SMTP Host / Port:   {smtp_host}:{smtp_port}")
        print(f" SMTP User:          {smtp_user if smtp_user else 'NON CONFIGURATO'}")
        print("=" * 60 + "\n")

        logger.info(f"Avvio test invio email a {target_email}...")
        success, err_msg = send_test_email(target_email, db=db)

        if success:
            print("\n" + "*" * 60)
            print(" ✅ RISULTATO: EMAIL DI TEST INVIATA CON SUCCESSO!")
            print("*" * 60)
            if err_msg:
                print(f"\nℹ️ NOTA: {err_msg}")
            else:
                print(f"\nControlla la tua casella di posta ({target_email}) e la cartella Spam.")
            print("=" * 60 + "\n")
            sys.exit(0)
        else:
            print("\n" + "!" * 60)
            print(" ❌ RISULTATO: INVIO EMAIL FALLITO")
            print("!" * 60)
            print(f"\nMotivo / Errore:\n{err_msg}\n")
            print("-" * 60)
            print("💡 SUGGERIMENTI PER RISOLVERE:")
            print(" 1. Se usi Gmail SMTP: assicurati di usare una 'Password per le app' di Google a 16 caratteri")
            print("    (generabile su https://myaccount.google.com/apppasswords), NON la tua password normale.")
            print(" 2. In alternativa, puoi usare Resend (https://resend.com): crea una API Key gratuita")
            print("    e impostala nei secret del repository come RESEND_API_KEY.")
            print(" 3. Se usi FormSubmit Cloud Relay: controlla la tua posta e cerca una mail da FormSubmit")
            print("    con oggetto 'Activate Form' e clicca sul link di conferma una sola volta.")
            print("-" * 60 + "\n")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Errore imprevisto durante l'invio del test: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
