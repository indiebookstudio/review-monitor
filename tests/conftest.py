import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.auth import hash_password, set_admin_password_hash
from app.models import Book, AppSetting

# StaticPool ensures the in-memory SQLite DB is shared across threads and connections in tests
engine_test = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine_test)
    db = TestingSessionLocal()
    
    # Seed default admin password
    set_admin_password_hash(db, hash_password("secret123"))
    
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine_test)

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture
def auth_client(client):
    # Log in to get session cookie
    response = client.post(
        "/login",
        data={"password": "secret123", "next": "/"},
        follow_redirects=False
    )
    assert response.status_code == 303
    return client

@pytest.fixture
def sample_html_reviews():
    path = Path(__file__).parent / "fixtures" / "amazon_product_reviews.html"
    return path.read_text(encoding="utf-8")

@pytest.fixture
def sample_html_no_reviews():
    path = Path(__file__).parent / "fixtures" / "amazon_no_reviews.html"
    return path.read_text(encoding="utf-8")

@pytest.fixture
def sample_html_blocked():
    path = Path(__file__).parent / "fixtures" / "amazon_blocked.html"
    return path.read_text(encoding="utf-8")
