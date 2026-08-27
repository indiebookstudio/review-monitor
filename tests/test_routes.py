import pytest
from app.models import Book, Review, AppSetting

def test_add_book_success(auth_client, db_session):
    res = auth_client.post(
        "/books/add",
        data={
            "asin": "B0H6ZDZ2N8",
            "marketplace": "amazon.com",
            "title": "Leo the Crane and the Mountain Gems",
            "price": "€12,90",
            "cover_image_url": "https://m.media-amazon.com/images/I/sample.jpg"
        },
        follow_redirects=False
    )
    assert res.status_code == 303
    
    # Verify in DB
    book = db_session.query(Book).filter(Book.asin == "B0H6ZDZ2N8").first()
    assert book is not None
    assert "Leo the" in book.title
    assert book.marketplace == "amazon.com"
    assert "https://www.amazon.com/dp/B0H6ZDZ2N8" == book.product_url
    assert book.enabled is True

def test_add_duplicate_asin_rejected(auth_client, db_session):
    # Insert existing book in DB
    book = Book(
        asin="B0DUP12345",
        marketplace="amazon.it",
        title="Existing Book",
        product_url="https://www.amazon.it/dp/B0DUP12345",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    # Try to add the same ASIN again
    res = auth_client.post(
        "/books/add",
        data={
            "asin": "B0DUP12345",
            "marketplace": "amazon.it",
            "title": "Duplicate Try"
        },
        follow_redirects=False
    )
    assert res.status_code == 303
    assert "error=" in res.headers["Location"]
    assert "presente" in res.headers["Location"]

def test_add_book_invalid_asin(auth_client, db_session):
    res = auth_client.post(
        "/books/add",
        data={
            "asin": "INVALID_SHORT",
            "marketplace": "amazon.com",
            "title": "Invalid ASIN Book"
        },
        follow_redirects=True
    )
    assert "10 caratteri" in res.text or "non valido" in res.text

def test_preview_asin_endpoint(auth_client):
    res = auth_client.post(
        "/books/preview-asin",
        json={"asin": "B0H6ZDZ2N8"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "data" in data
    assert data["data"]["asin"] == "B0H6ZDZ2N8"
    assert "marketplaces" in data["data"]
    assert len(data["data"]["marketplaces"]) == 14

def test_edit_book(auth_client, db_session):
    book = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Original Title",
        product_url="https://www.amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    res = auth_client.post(
        f"/books/{book.id}/edit",
        data={
            "asin": "B0H6ZDZ2N8",
            "marketplace": "amazon.it",
            "title": "Updated Title in Italian"
        },
        follow_redirects=False
    )
    assert res.status_code == 303
    
    db_session.refresh(book)
    assert book.title == "Updated Title in Italian"
    assert book.marketplace == "amazon.it"
    assert "amazon.it/dp/B0H6ZDZ2N8" in book.product_url

def test_toggle_book(auth_client, db_session):
    book = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Test Book",
        product_url="https://www.amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    # Toggle to disable
    res = auth_client.post(f"/books/{book.id}/toggle", follow_redirects=False)
    assert res.status_code == 303
    db_session.refresh(book)
    assert book.enabled is False

    # Toggle back to enable
    res = auth_client.post(f"/books/{book.id}/toggle", follow_redirects=False)
    assert res.status_code == 303
    db_session.refresh(book)
    assert book.enabled is True

def test_delete_book(auth_client, db_session):
    book = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Delete Me",
        product_url="https://www.amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    # Add a review for this book
    rev = Review(
        book_id=book.id,
        asin=book.asin,
        marketplace=book.marketplace,
        review_id="R_DEL_1",
        rating=5.0
    )
    db_session.add(rev)
    db_session.commit()

    # Delete
    res = auth_client.post(f"/books/{book.id}/delete", follow_redirects=False)
    assert res.status_code == 303

    assert db_session.query(Book).filter(Book.id == book.id).first() is None
    assert db_session.query(Review).filter(Review.review_id == "R_DEL_1").first() is None

def test_reset_book_reviews_route(auth_client, db_session):
    book = Book(
        asin="B0RESET123",
        marketplace="amazon.it",
        title="Book to reset",
        product_url="https://www.amazon.it/dp/B0RESET123",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    rev = Review(
        book_id=book.id,
        asin=book.asin,
        marketplace=book.marketplace,
        review_id="R_RESET_1",
        rating=5.0
    )
    db_session.add(rev)
    db_session.commit()

    assert db_session.query(Review).filter(Review.book_id == book.id).count() == 1

    res = auth_client.post(f"/books/{book.id}/reset-reviews", follow_redirects=False)
    assert res.status_code == 303

    assert db_session.query(Review).filter(Review.book_id == book.id).count() == 0

def test_reset_all_reviews_route(auth_client, db_session):
    book = Book(
        asin="B0RESETALL",
        marketplace="amazon.it",
        title="Book all reset",
        product_url="https://www.amazon.it/dp/B0RESETALL",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    rev = Review(
        book_id=book.id,
        asin=book.asin,
        marketplace=book.marketplace,
        review_id="R_RESET_ALL",
        rating=4.0
    )
    db_session.add(rev)
    db_session.commit()

    res = auth_client.post("/settings/reset-all-reviews", follow_redirects=False)
    assert res.status_code == 303
    assert db_session.query(Review).count() == 0

def test_settings_update_persistence(auth_client, db_session):
    res = auth_client.post(
        "/settings/update",
        data={
            "alert_email": "author@mydomain.com",
            "notifications_enabled": "true",
            "check_frequency": "6h",
            "dashboard_url": "https://kdp.author.com"
        },
        follow_redirects=False
    )
    assert res.status_code == 303

    # Check persistence in settings table
    email_setting = db_session.query(AppSetting).filter(AppSetting.key == "alert_email").first()
    assert email_setting.value == "author@mydomain.com"

    freq_setting = db_session.query(AppSetting).filter(AppSetting.key == "check_frequency").first()
    assert freq_setting.value == "6h"

    dash_url_setting = db_session.query(AppSetting).filter(AppSetting.key == "dashboard_url").first()
    assert dash_url_setting.value == "https://kdp.author.com"
