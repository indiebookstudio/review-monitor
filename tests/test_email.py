import pytest
from app.notifications.email import format_stars, build_review_email_content, send_test_email

def test_format_stars():
    assert format_stars(5.0) == "★★★★★"
    assert format_stars(4.0) == "★★★★☆"
    assert format_stars(3.2) == "★★★☆☆"
    assert format_stars(1.0) == "★☆☆☆☆"

def test_build_single_review_email():
    reviews = [{
        "review_id": "R12345",
        "rating": 5.0,
        "title": "Stupendo!",
        "body": "Libro davvero ben fatto, consigliatissimo.",
        "author": "Marco B.",
        "review_date": "27 Agosto 2026",
        "review_url": "https://www.amazon.it/gp/customer-reviews/R12345"
    }]
    
    subject, body_text, body_html = build_review_email_content(
        book_title="Leo the Crane",
        marketplace="amazon.it",
        asin="B0H6ZDZ2N8",
        reviews=reviews,
        dashboard_url="https://kdp.mydomain.com"
    )
    
    assert "Nuova recensione" in subject
    assert "Leo the Crane" in subject
    assert "Leo the Crane" in body_text
    assert "My KDP Reviews" in body_html
    assert "Amazon" in body_html
    assert "Stupendo!" in body_html

def test_build_multiple_reviews_email():
    reviews = [
        {
            "review_id": "R1",
            "rating": 5.0,
            "title": "Top",
            "body": "Ottimo libro",
            "author": "User 1",
            "review_date": "2026-08-27",
            "review_url": "https://amazon.com/r1"
        },
        {
            "review_id": "R2",
            "rating": 4.0,
            "title": "Bello",
            "body": "Piaciuto ai miei figli",
            "author": "User 2",
            "review_date": "2026-08-26",
            "review_url": "https://amazon.com/r2"
        }
    ]
    
    subject, body_text, body_html = build_review_email_content(
        book_title="Leo the Crane",
        marketplace="amazon.com",
        asin="B0H6ZDZ2N8",
        reviews=reviews,
        dashboard_url="https://kdp.mydomain.com"
    )
    
    assert "2 nuove recensioni" in subject
    assert "User 1" in body_text
    assert "User 2" in body_text
    assert "My KDP Reviews" in body_html
