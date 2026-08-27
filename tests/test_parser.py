import pytest
from app.amazon.parser import (
    parse_amazon_reviews,
    extract_rating,
    STATUS_OK,
    STATUS_NO_REVIEWS,
    STATUS_PAGE_UNAVAILABLE,
    STATUS_PARSER_ERROR
)

def test_extract_rating():
    assert extract_rating("5.0 out of 5 stars") == 5.0
    assert extract_rating("4.5 su 5 stelle") == 4.5
    assert extract_rating("3,8 von 5 Sternen") == 3.8
    assert extract_rating("1.0 out of 5") == 1.0
    assert extract_rating(None) is None

def test_parse_valid_reviews_fixture(sample_html_reviews):
    res = parse_amazon_reviews(sample_html_reviews, asin="B0H6ZDZ2N8", marketplace="amazon.com")
    assert res["status"] == STATUS_OK
    assert res["error"] is None
    assert len(res["reviews"]) == 2
    
    rev1 = res["reviews"][0]
    assert rev1["review_id"] == "R3K8O9W1X2Y3Z4"
    assert rev1["rating"] == 5.0
    assert "delightful bedtime story" in rev1["title"]
    assert rev1["author"] == "Sarah Jenkins"
    assert "August 15, 2026" in rev1["review_date"]
    assert "6-year-old" in rev1["body"]
    
    rev2 = res["reviews"][1]
    assert rev2["review_id"] == "R1A2B3C4D5E6F7"
    assert rev2["rating"] == 4.0
    assert "Great book" in rev2["title"]
    assert rev2["author"] == "Mark R."

def test_parse_no_reviews_fixture(sample_html_no_reviews):
    res = parse_amazon_reviews(sample_html_no_reviews, asin="B0XYZ12345", marketplace="amazon.com")
    assert res["status"] == STATUS_NO_REVIEWS
    assert len(res["reviews"]) == 0
    assert res["error"] is None

def test_parse_blocked_fixture(sample_html_blocked):
    res = parse_amazon_reviews(sample_html_blocked, asin="B0H6ZDZ2N8", marketplace="amazon.com")
    assert res["status"] == STATUS_PAGE_UNAVAILABLE
    assert len(res["reviews"]) == 0
    assert res["error"] is not None

def test_parse_empty_or_broken_html():
    res_empty = parse_amazon_reviews("", asin="B0H6ZDZ2N8")
    assert res_empty["status"] == STATUS_PAGE_UNAVAILABLE
    
    res_broken = parse_amazon_reviews("<html><body><div>Random strange text</div></body></html>", asin="B0H6ZDZ2N8")
    assert res_broken["status"] == STATUS_PARSER_ERROR
