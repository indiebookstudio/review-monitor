import datetime
import pytest
from app.models import Book, Review, CheckRun
from app.reviews.statistics import (
    get_dashboard_kpis,
    get_book_statistics,
    get_all_books_summary,
    get_top_performers,
    get_attention_books
)

def test_statistics_calculations(db_session):
    # Book 1: High rating
    b1 = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Leo the Crane",
        product_url="https://amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    # Book 2: Low rating (needs attention)
    b2 = Book(
        asin="B012345678",
        marketplace="amazon.it",
        title="Low Rating Book",
        product_url="https://amazon.it/dp/B012345678",
        enabled=True
    )
    db_session.add_all([b1, b2])
    db_session.commit()

    now = datetime.datetime.now(datetime.timezone.utc)
    # Add reviews for b1 (5 stars and 4 stars)
    r1 = Review(
        book_id=b1.id,
        asin=b1.asin,
        marketplace=b1.marketplace,
        review_id="R1",
        rating=5.0,
        title="Love it",
        first_seen_at=now - datetime.timedelta(days=2)
    )
    r2 = Review(
        book_id=b1.id,
        asin=b1.asin,
        marketplace=b1.marketplace,
        review_id="R2",
        rating=4.0,
        title="Good",
        first_seen_at=now - datetime.timedelta(days=10)
    )
    # Add reviews for b2 (2 stars and 3 stars)
    r3 = Review(
        book_id=b2.id,
        asin=b2.asin,
        marketplace=b2.marketplace,
        review_id="R3",
        rating=2.0,
        title="Disappointed",
        first_seen_at=now - datetime.timedelta(days=5)
    )
    r4 = Review(
        book_id=b2.id,
        asin=b2.asin,
        marketplace=b2.marketplace,
        review_id="R4",
        rating=3.0,
        title="Average",
        first_seen_at=now - datetime.timedelta(days=40)
    )
    db_session.add_all([r1, r2, r3, r4])
    db_session.commit()

    # Test KPIs
    kpis = get_dashboard_kpis(db_session)
    assert kpis["total_books"] == 2
    assert kpis["total_reviews"] == 4
    # (5 + 4 + 2 + 3) / 4 = 3.5
    assert kpis["avg_rating"] == 3.5
    # 3 reviews in last 30d (r1, r2, r3)
    assert kpis["new_reviews_30d"] == 3

    # Test Single Book Stats for b1
    b1_stats = get_book_statistics(db_session, b1.id)
    assert b1_stats["total_reviews"] == 2
    assert b1_stats["avg_rating"] == 4.5
    assert b1_stats["reviews_7d"] == 1
    assert b1_stats["reviews_30d"] == 2
    assert b1_stats["star_counts"][5] == 1
    assert b1_stats["star_counts"][4] == 1
    assert b1_stats["star_counts"][1] == 0

    # Test Top Performers & Attention
    summary = get_all_books_summary(db_session)
    top = get_top_performers(summary)
    assert len(top) == 2
    assert top[0]["book"].id == b1.id # b1 has higher 30d reviews & rating

    attention = get_attention_books(summary)
    assert len(attention) >= 1
    assert any(item["book"].id == b2.id for item in attention) # b2 rating < 4.0 and has <=3 star review
