import pytest
from unittest.mock import patch, MagicMock
from app.models import Book, Review, CheckRun
from app.reviews.monitor import run_book_check, run_all_checks
from app.amazon.client import AmazonClient

class MockAmazonClient(AmazonClient):
    def __init__(self, html_content: str, status_code: int = 200, error: str = None):
        self.html_content = html_content
        self.status_code = status_code
        self.error = error

    def fetch_reviews_page(self, asin: str, marketplace: str = "amazon.com"):
        return self.html_content, self.status_code, self.error

def test_monitor_bootstrap_no_alert(db_session, sample_html_reviews):
    # Add a book
    book = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Leo the Crane and the Mountain Gems",
        product_url="https://www.amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    mock_client = MockAmazonClient(sample_html_reviews)

    with patch("app.reviews.monitor.send_review_alert") as mock_alert:
        res = run_book_check(book, db_session, client=mock_client)
        
        assert res["success"] is True
        assert res["is_bootstrap"] is True
        assert res["reviews_found"] == 2
        assert res["new_reviews"] == 0 # Bootstrap doesn't count as new for alert
        
        # Ensure NO email alert was called during bootstrap
        mock_alert.assert_not_called()

    # Check reviews were stored in DB
    reviews_in_db = db_session.query(Review).filter(Review.book_id == book.id).all()
    assert len(reviews_in_db) == 2

    # Check check_runs recorded
    runs = db_session.query(CheckRun).filter(CheckRun.book_id == book.id).all()
    assert len(runs) == 1
    assert runs[0].success is True

def test_monitor_second_run_no_new_reviews(db_session, sample_html_reviews):
    book = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Leo the Crane and the Mountain Gems",
        product_url="https://www.amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    mock_client = MockAmazonClient(sample_html_reviews)
    
    # 1. Run bootstrap
    run_book_check(book, db_session, client=mock_client)

    # 2. Run again with same content
    with patch("app.reviews.monitor.send_review_alert") as mock_alert:
        res2 = run_book_check(book, db_session, client=mock_client)
        assert res2["success"] is True
        assert res2["is_bootstrap"] is False
        assert res2["reviews_found"] == 2
        assert res2["new_reviews"] == 0
        mock_alert.assert_not_called()

def test_monitor_new_review_detected_triggers_email(db_session, sample_html_reviews):
    book = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Leo the Crane and the Mountain Gems",
        product_url="https://www.amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    # 1. Bootstrap with 2 reviews
    mock_client1 = MockAmazonClient(sample_html_reviews)
    run_book_check(book, db_session, client=mock_client1)

    # 2. Simulate new HTML containing a 3rd new review inside the review list
    third_review_snippet = """
      <div id="customer_review-R99NEWREVIEW99" data-hook="review" class="a-section review">
        <span class="a-profile-name">Emily Davis</span>
        <i data-hook="review-star-rating"><span class="a-icon-alt">5.0 out of 5 stars</span></i>
        <a data-hook="review-title"><span>Fantastic story!</span></a>
        <span data-hook="review-date">August 27, 2026</span>
        <span data-hook="review-body">Just received this book today, amazing!</span>
      </div>
    """
    html_with_third_review = sample_html_reviews.replace("</div>\n  </div>\n</body>", f"{third_review_snippet}</div>\n  </div>\n</body>")

    mock_client2 = MockAmazonClient(html_with_third_review)
    with patch("app.reviews.monitor.send_review_alert") as mock_alert:
        res2 = run_book_check(book, db_session, client=mock_client2)
        assert res2["success"] is True
        assert res2["reviews_found"] == 3
        assert res2["new_reviews"] == 1
        
        # Email alert MUST be called
        assert mock_alert.called
        args, _ = mock_alert.call_args
        assert args[0] == "Leo the Crane and the Mountain Gems"
        assert args[2] == "B0H6ZDZ2N8"
        assert len(args[3]) == 1 # 1 new review object

def test_monitor_amazon_error_handling(db_session, sample_html_blocked):
    book = Book(
        asin="B0H6ZDZ2N8",
        marketplace="amazon.com",
        title="Leo the Crane and the Mountain Gems",
        product_url="https://www.amazon.com/dp/B0H6ZDZ2N8",
        enabled=True
    )
    db_session.add(book)
    db_session.commit()

    mock_client = MockAmazonClient(sample_html_blocked, status_code=503, error="Service Unavailable")
    res = run_book_check(book, db_session, client=mock_client)
    
    assert res["success"] is False
    assert res["status"] == "PAGE_UNAVAILABLE"
    
    # Check that error is recorded in check_runs
    check_run = db_session.query(CheckRun).filter(CheckRun.book_id == book.id).first()
    assert check_run is not None
    assert check_run.success is False
