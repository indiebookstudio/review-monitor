import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

class Book(Base):
    __tablename__ = "books"
    
    id = Column(Integer, primary_key=True, index=True)
    asin = Column(String(20), nullable=False, index=True)
    marketplace = Column(String(50), nullable=False, default="amazon.it")
    title = Column(String(255), nullable=False)
    product_url = Column(Text, nullable=False)
    cover_image_url = Column(String(500), nullable=True)
    price = Column(String(50), nullable=True)
    has_kindle = Column(Boolean, default=False, nullable=False)
    kindle_price = Column(String(50), nullable=True)
    kindle_asin = Column(String(20), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    reviews = relationship("Review", back_populates="book", cascade="all, delete-orphan")
    check_runs = relationship("CheckRun", back_populates="book", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint("asin", "marketplace", name="uix_book_asin_marketplace"),
    )

class Review(Base):
    __tablename__ = "reviews"
    
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=True)
    asin = Column(String(20), nullable=False, index=True)
    marketplace = Column(String(50), nullable=False)
    review_id = Column(String(100), nullable=False)
    rating = Column(Float, nullable=False)
    title = Column(String(255), nullable=True)
    body = Column(Text, nullable=True)
    author = Column(String(255), nullable=True)
    review_date = Column(String(100), nullable=True)
    review_url = Column(Text, nullable=True)
    images = Column(Text, nullable=True)
    video_url = Column(Text, nullable=True)
    first_seen_at = Column(DateTime, default=utc_now, nullable=False)
    
    book = relationship("Book", back_populates="reviews")
    
    __table_args__ = (
        UniqueConstraint("review_id", "marketplace", name="uix_review_id_marketplace"),
    )

class CheckRun(Base):
    __tablename__ = "check_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=True)
    asin = Column(String(20), nullable=False, index=True)
    marketplace = Column(String(50), nullable=False)
    checked_at = Column(DateTime, default=utc_now, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    reviews_found = Column(Integer, default=0, nullable=False)
    new_reviews = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    status_code = Column(String(50), default="OK", nullable=False)
    
    book = relationship("Book", back_populates="check_runs")

class AppSetting(Base):
    __tablename__ = "settings"
    
    key = Column(String(100), primary_key=True, index=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
