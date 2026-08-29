#!/usr/bin/env python3
"""
CLI script to run KDP review monitoring check.
Can be run on schedule via GitHub Actions, Cron, or manual execution.
"""
import sys
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import AppSetting
from app.reviews.monitor import run_all_checks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("kdp-monitor-cli")

def main():
    parser = argparse.ArgumentParser(description="Run KDP review monitor check.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force check execution regardless of the configured frequency schedule."
    )
    args = parser.parse_args()

    logger.info("Initializing database tables...")
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

        logger.info(f"Starting review check (force={args.force})...")
        report = run_all_checks(db, force=args.force)
        
        if report.get("executed"):
            logger.info(
                f"Check finished: {report.get('books_checked')} books checked, "
                f"{report.get('total_new_reviews')} new reviews found, "
                f"{report.get('total_emails_sent', 0)} email(s) sent."
            )
        else:
            logger.info(f"Check skipped: {report.get('reason')}")

        # Always update GitHub Pages static dashboard
        try:
            from scripts.generate_static_dashboard import generate_static_html
            out_file = BASE_DIR / "docs" / "index.html"
            generate_static_html(out_file)
            logger.info(f"Static GitHub Pages dashboard generated at {out_file}")
        except Exception as ge:
            logger.warning(f"Could not generate static dashboard: {ge}")
            
    except Exception as e:

        logger.error(f"Fatal error during monitor run: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
