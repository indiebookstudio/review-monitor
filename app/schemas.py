from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr

class BookCreate(BaseModel):
    asin: str = Field(..., min_length=5, max_length=20)
    marketplace: str = Field(default="amazon.com")
    title: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True

class BookUpdate(BaseModel):
    title: Optional[str] = None
    marketplace: Optional[str] = None
    asin: Optional[str] = None
    enabled: Optional[bool] = None

class BookResponse(BaseModel):
    id: int
    asin: str
    marketplace: str
    title: str
    product_url: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SettingsUpdate(BaseModel):
    check_frequency: str = Field(default="24h")
    alert_email: Optional[str] = Field(default="")
    notifications_enabled: bool = Field(default=True)
    dashboard_url: Optional[str] = Field(default="")

class PasswordChange(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str
