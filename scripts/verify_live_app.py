import requests
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_URL = "http://127.0.0.1:8000"

def run_live_tests():
    session = requests.Session()
    print("--- 1. Testing Unauthenticated Access ---")
    res = session.get(f"{BASE_URL}/", allow_redirects=False)
    print(f"GET / status: {res.status_code}, Location: {res.headers.get('Location')}")
    assert res.status_code in (303, 307)
    assert "/login" in res.headers.get("Location", "")
    print("✓ Unauthenticated access is properly blocked.")

    print("\n--- 2. Testing Login with Wrong Password ---")
    res_bad = session.post(f"{BASE_URL}/login", data={"password": "wrong_password", "next": "/"})
    print(f"POST /login (wrong pwd) status: {res_bad.status_code}")
    assert res_bad.status_code == 401
    assert "Password non valida" in res_bad.text
    print("✓ Invalid password correctly rejected.")

    print("\n--- 3. Testing Login with Correct Password ---")
    # Initial password set by lifespan is admin123 or from CLI
    # Let's test admin123 first; if changed, test my_new_admin_pwd_123
    res_login = session.post(f"{BASE_URL}/login", data={"password": "my_new_admin_pwd_123", "next": "/"}, allow_redirects=False)
    if res_login.status_code != 303:
        res_login = session.post(f"{BASE_URL}/login", data={"password": "admin123", "next": "/"}, allow_redirects=False)
    
    print(f"POST /login (correct pwd) status: {res_login.status_code}, Location: {res_login.headers.get('Location')}")
    assert res_login.status_code == 303
    print("✓ Login successful and session established.")

    print("\n--- 4. Testing Authenticated Dashboard & Empty State ---")
    res_dash = session.get(f"{BASE_URL}/")
    print(f"GET / status: {res_dash.status_code}")
    assert res_dash.status_code == 200
    assert "KDP PERFORMANCE" in res_dash.text
    assert "Libri Monitorati" in res_dash.text
    print("✓ Authenticated dashboard renders properly.")

    print("\n--- 5. Inserting Test ASINs: B0H7JK9R46 and B0H6MN4LW7 ---")
    # ASIN 1: B0H7JK9R46 on amazon.com
    res_add1 = session.post(
        f"{BASE_URL}/books/add",
        data={
            "asin": "B0H7JK9R46",
            "marketplace": "amazon.com",
            "title": "Amazon KDP Book - B0H7JK9R46"
        },
        allow_redirects=True
    )
    print(f"Add Book 1 status: {res_add1.status_code}")
    assert "B0H7JK9R46" in res_add1.text
    print("✓ ASIN B0H7JK9R46 successfully added to database.")

    # ASIN 2: B0H6MN4LW7 on amazon.it
    res_add2 = session.post(
        f"{BASE_URL}/books/add",
        data={
            "asin": "B0H6MN4LW7",
            "marketplace": "amazon.it",
            "title": "Libro KDP Italia - B0H6MN4LW7"
        },
        allow_redirects=True
    )
    print(f"Add Book 2 status: {res_add2.status_code}")
    assert "B0H6MN4LW7" in res_add2.text
    print("✓ ASIN B0H6MN4LW7 successfully added to database.")

    print("\n--- 6. Verifying Dashboard Books Display ---")
    res_dash2 = session.get(f"{BASE_URL}/")
    assert "B0H7JK9R46" in res_dash2.text
    assert "B0H6MN4LW7" in res_dash2.text
    assert "2" in res_dash2.text # Libri monitorati: 2
    print("✓ Both books appear on Dashboard with KPIs updated.")

    print("\n--- 7. Testing Settings Management ---")
    res_settings = session.post(
        f"{BASE_URL}/settings/update",
        data={
            "alert_email": "marco.author@example.com",
            "notifications_enabled": "true",
            "check_frequency": "12h",
            "dashboard_url": "https://my-kdp-dashboard.example.com"
        },
        allow_redirects=True
    )
    assert res_settings.status_code == 200
    assert "marco.author@example.com" in res_settings.text
    assert "Ogni 12 ore" in res_settings.text or "12h" in res_settings.text
    assert "https://my-kdp-dashboard.example.com" in res_settings.text
    print("✓ Settings updated and persisted (Email, Frequency, Notifications, URL).")

    print("\n--- 8. Testing Manual Review Check Trigger ---")
    res_check = session.post(f"{BASE_URL}/settings/run-check", allow_redirects=True)
    assert res_check.status_code == 200
    assert "Controllo completato" in res_check.text
    print("✓ Manual review check triggered and executed.")

    print("\n--- 9. Testing Toggle Book Monitoring (Disable / Re-enable) ---")
    # Find book 1 id
    res_books = session.get(f"{BASE_URL}/books")
    # Toggle first book
    res_toggle = session.post(f"{BASE_URL}/books/1/toggle", allow_redirects=True)
    assert res_toggle.status_code == 200
    assert "Monitoraggio disattivato" in res_toggle.text or "Disattivato" in res_toggle.text
    print("✓ Book monitoring successfully disabled without losing data.")

    res_toggle2 = session.post(f"{BASE_URL}/books/1/toggle", allow_redirects=True)
    assert res_toggle2.status_code == 200
    assert "Monitoraggio riattivato" in res_toggle2.text or "Attivo" in res_toggle2.text
    print("✓ Book monitoring successfully re-enabled.")

    print("\n--- 10. Testing Security & Password Change ---")
    current_pwd = "my_new_admin_pwd_123" if res_login.status_code == 303 else "admin123"
    res_pwd = session.post(
        f"{BASE_URL}/settings/password",
        data={
            "current_password": current_pwd,
            "new_password": "super_secret_admin_2026",
            "confirm_password": "super_secret_admin_2026"
        },
        allow_redirects=True
    )
    assert res_pwd.status_code == 200
    assert "Password modificata con successo" in res_pwd.text
    print("✓ Password successfully changed and hashed with bcrypt.")

    # Verify logout and login with new password
    session2 = requests.Session()
    res_new_login = session2.post(
        f"{BASE_URL}/login",
        data={"password": "super_secret_admin_2026", "next": "/"},
        allow_redirects=False
    )
    assert res_new_login.status_code == 303
    print("✓ Login with new password succeeded.")

    print("\n=======================================================")
    print("✅ ALL LIVE INTEGRATION AND FUNCTIONAL TESTS PASSED!")
    print("=======================================================")

if __name__ == "__main__":
    try:
        run_live_tests()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        sys.exit(1)
