import pytest
from fastapi.testclient import TestClient
from main import app
from app.core.database import engine, Base

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)

def test_health_check():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "OK"
        assert "PatentLens AI" in data["service"]

def test_user_registration_and_login():
    import uuid
    with TestClient(app) as client:
        email = f"test.inventor.{uuid.uuid4().hex[:6]}@patentlens.ai"
        password = "SecurePassword123!"

        # 1. Register (Returns require_otp: True)
        reg_payload = {
            "name": "Test Inventor",
            "email": email,
            "password": password,
            "confirm_password": password
        }
        res_reg = client.post("/api/auth/register", json=reg_payload)
        assert res_reg.status_code == 201
        data_reg = res_reg.json()
        assert data_reg["require_otp"] is True
        demo_otp = data_reg["demo_otp"]

        # 2. Verify OTP for First-Time User
        res_verify = client.post("/api/auth/verify-otp", json={"email": email, "otp": demo_otp})
        assert res_verify.status_code == 200
        data_verify = res_verify.json()
        assert "access_token" in data_verify
        assert data_verify["user"]["is_verified"] is True

        # 3. Direct Login (Subsequent login bypasses OTP)
        login_payload = {
            "email": email,
            "password": password
        }
        res_login = client.post("/api/auth/login", json=login_payload)
        assert res_login.status_code == 200
        data_login = res_login.json()
        assert "access_token" in data_login
        assert data_login["require_otp"] is False
        token = data_login["access_token"]

        # 4. Get Current User Profile
        headers = {"Authorization": f"Bearer {token}"}
        res_me = client.get("/api/auth/me", headers=headers)
        assert res_me.status_code == 200
        assert res_me.json()["email"] == email

def test_invalid_login():
    with TestClient(app) as client:
        login_payload = {
            "email": "nonexistent@patentlens.ai",
            "password": "wrongpassword"
        }
        res = client.post("/api/auth/login", json=login_payload)
        assert res.status_code == 401

def test_google_oauth_existing_and_new_user():
    import uuid
    with TestClient(app) as client:
        email = f"google.user.{uuid.uuid4().hex[:6]}@gmail.com"

        # 1. Google sign-in for new first-time user requires OTP verification
        res1 = client.post("/api/auth/google", json={"email": email, "name": "Google User"})
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["require_otp"] is True
        demo_otp = data1["demo_otp"]

        # 2. Verify 6-digit OTP code
        res_verify = client.post("/api/auth/verify-otp", json={"email": email, "otp": demo_otp})
        assert res_verify.status_code == 200
        data_verify = res_verify.json()
        assert "access_token" in data_verify
        assert data_verify["user"]["is_verified"] is True

        # 3. Subsequent Google sign-in for returning verified user logs in seamlessly
        res2 = client.post("/api/auth/google", json={"email": email, "name": "Google User"})
        assert res2.status_code == 200
        data2 = res2.json()
        assert "access_token" in data2
        assert data2["require_otp"] is False
        assert data2["user"]["email"] == email

