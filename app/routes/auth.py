import logging
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.auth import authenticate_admin, is_authenticated
from app.models import AuditLog

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": next, "error": None}
    )

@router.post("/login")
async def login_action(
    request: Request,
    password: str = Form(...),
    next: str = Form(default="/"),
    db: Session = Depends(get_db)
):
    if authenticate_admin(password, db):
        request.session["authenticated"] = True
        logger.info("Admin user logged in successfully.")
        
        audit = AuditLog(action="LOGIN", details="Accesso effettuato con successo.")
        db.add(audit)
        db.commit()
        
        target = next if next and next.startswith("/") else "/"
        return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
    
    logger.warning("Failed login attempt (invalid password).")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": next, "error": "Password non valida. Riprova."},
        status_code=status.HTTP_401_UNAUTHORIZED
    )

@router.get("/logout")
@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    if is_authenticated(request):
        audit = AuditLog(action="LOGOUT", details="Disconnessione effettuata.")
        db.add(audit)
        db.commit()
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
