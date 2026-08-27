import pytest
from app.auth import hash_password, verify_password, authenticate_admin, set_admin_password_hash

def test_password_hashing():
    pwd = "my_secure_password"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrong_password", hashed) is False

def test_unauthenticated_access_redirect(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers.get("Location", "")

def test_login_failed_wrong_password(client):
    response = client.post(
        "/login",
        data={"password": "incorrect_password", "next": "/"},
        follow_redirects=True
    )
    assert response.status_code == 401
    assert "Password non valida" in response.text

def test_login_success(client):
    response = client.post(
        "/login",
        data={"password": "secret123", "next": "/"},
        follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["Location"] == "/"

def test_authenticated_dashboard_access(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "My KDP Reviews" in response.text
    assert "Libri Monitorati" in response.text

def test_logout(auth_client):
    # Logout
    res_logout = auth_client.get("/logout", follow_redirects=False)
    assert res_logout.status_code == 303
    
    # Try accessing protected route again
    res_dash = auth_client.get("/", follow_redirects=False)
    assert res_dash.status_code == 303
    assert "/login" in res_dash.headers["Location"]

def test_change_password_route(auth_client, db_session):
    # Change password
    res = auth_client.post(
        "/settings/password",
        data={
            "current_password": "secret123",
            "new_password": "new_secret_456",
            "confirm_password": "new_secret_456"
        },
        follow_redirects=False
    )
    assert res.status_code == 303
    assert authenticate_admin("new_secret_456", db_session) is True
    assert authenticate_admin("secret123", db_session) is False
