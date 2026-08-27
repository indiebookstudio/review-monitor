#!/usr/bin/env python3
"""
CLI script to set or reset the admin password directly.
Usage: python scripts/set_admin_password.py [NEW_PASSWORD]
"""
import sys
import getpass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import engine, Base, SessionLocal
from app.auth import hash_password, set_admin_password_hash
from app.models import AuditLog

def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    Base.metadata.create_all(bind=engine)
    
    if len(sys.argv) > 1:
        new_pwd = sys.argv[1].strip()
    else:
        new_pwd = getpass.getpass("Inserisci la nuova password amministratore: ").strip()
        confirm = getpass.getpass("Conferma la nuova password: ").strip()
        if new_pwd != confirm:
            print("Errore: Le password non coincidono.")
            sys.exit(1)
            
    if len(new_pwd) < 6:
        print("Errore: La password deve avere almeno 6 caratteri.")
        sys.exit(1)
        
    db = SessionLocal()
    try:
        hashed = hash_password(new_pwd)
        set_admin_password_hash(db, hashed)
        
        audit = AuditLog(action="PASSWORD_RESET_CLI", details="Password reimpostata via script CLI.")
        db.add(audit)
        db.commit()
        
        print("[OK] Password amministratore impostata e salvata con successo!")
    finally:
        db.close()

if __name__ == "__main__":
    main()
