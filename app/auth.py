import logging
import bcrypt
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AppSetting, AuditLog

logger = logging.getLogger(__name__)

def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password or not plain_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def get_admin_password_hash(db: Session) -> str:
    # 1. Check in database settings table
    setting = db.query(AppSetting).filter(AppSetting.key == "admin_password_hash").first()
    if setting and setting.value:
        return setting.value
    
    # 2. Check environment variable ADMIN_PASSWORD_HASH
    if settings.ADMIN_PASSWORD_HASH:
        set_admin_password_hash(db, settings.ADMIN_PASSWORD_HASH)
        return settings.ADMIN_PASSWORD_HASH
    
    # 3. Fallback to ADMIN_PASSWORD in environment (hash it and save)
    default_plain = settings.ADMIN_PASSWORD or "admin123"
    hashed = hash_password(default_plain)
    set_admin_password_hash(db, hashed)
    return hashed

def set_admin_password_hash(db: Session, hashed: str):
    setting = db.query(AppSetting).filter(AppSetting.key == "admin_password_hash").first()
    if not setting:
        setting = AppSetting(key="admin_password_hash", value=hashed)
        db.add(setting)
    else:
        setting.value = hashed
    db.commit()

def authenticate_admin(password: str, db: Session) -> bool:
    hashed = get_admin_password_hash(db)
    return verify_password(password, hashed)

def is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated") is True

async def require_auth(request: Request):
    """FastAPI dependency to protect HTML endpoints. Redirects to /login if unauthenticated."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"}
        )
    return True

async def require_auth_api(request: Request):
    """FastAPI dependency for JSON API endpoints."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non autenticato. Effettua il login."
        )
    return True
