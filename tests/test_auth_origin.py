import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

from app.account import hash_password, now_iso
from app.db.models import Base, User
from app.web import routes
from app.web.main import app


@pytest.fixture
def auth_client_and_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[routes.get_db] = override_get_db
    client = TestClient(
        app,
        base_url="https://public.example.test:9443",
        client=("203.0.113.10", 12345),
    )
    try:
        yield client, SessionLocal
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def make_request(host: str, client_host: str, scheme: str = "http") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": scheme,
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"host", host.encode("ascii"))],
            "client": (client_host, 12345),
            "server": (host.split(":", 1)[0], 80),
        }
    )


def test_verification_url_prefers_configured_canonical_origin(monkeypatch):
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "https://public.example.test:9443")
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    request = make_request("attacker.example", "203.0.113.10")

    assert routes._verification_url(request, "secret-token") == (
        "https://public.example.test:9443/auth/verify-email?token=secret-token"
    )


def test_verification_url_uses_explicit_app_base_url_as_fallback(monkeypatch):
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "")
    monkeypatch.setenv("APP_BASE_URL", "https://configured.example.test")
    request = make_request("attacker.example", "203.0.113.10")

    assert routes._verification_url(request, "secret-token") == (
        "https://configured.example.test/auth/verify-email?token=secret-token"
    )


@pytest.mark.parametrize("host", ["attacker.example", "localhost:8000"])
def test_remote_registration_without_trusted_origin_is_rejected(auth_client_and_session, monkeypatch, host):
    client, SessionLocal = auth_client_and_session
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "")
    monkeypatch.delenv("APP_BASE_URL", raising=False)

    response = client.post(
        "/api/auth/register",
        headers={"host": host},
        json={"username": "trader", "email": "trader@example.test", "password": "secret-pass"},
    )

    assert response.status_code == 503
    assert "доверенный адрес" in response.json()["error"].lower()
    with SessionLocal() as db:
        assert db.scalars(select(User)).all() == []


def test_remote_resend_without_trusted_origin_keeps_existing_token(auth_client_and_session, monkeypatch):
    client, SessionLocal = auth_client_and_session
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "")
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    with SessionLocal() as db:
        db.add(
            User(
                username="trader",
                email="trader@example.test",
                display_name="Trader",
                password_hash=hash_password("secret-pass"),
                email_verification_token="existing-token",
                email_verification_sent_at="2026-10-09T00:00:00+00:00",
                created_at="2026-10-09T00:00:00+00:00",
            )
        )
        db.commit()

    response = client.post(
        "/api/auth/resend-verification",
        headers={"host": "attacker.example"},
        json={"username": "trader", "password": "secret-pass"},
    )

    assert response.status_code == 503
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.username == "trader")).one()
        assert user.email_verification_token == "existing-token"


def test_remote_smtp_failure_does_not_return_verification_token(auth_client_and_session, monkeypatch):
    client, _SessionLocal = auth_client_and_session
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "https://public.example.test")
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setattr(routes, "send_verification_email", lambda *_args: False)

    response = client.post(
        "/api/auth/register",
        headers={"host": "public.example.test"},
        json={"username": "trader", "email": "trader@example.test", "password": "secret-pass"},
    )

    assert response.status_code == 200
    assert response.json()["email_sent"] is False
    assert response.json()["dev_verification_url"] is None


def test_loopback_development_can_receive_dev_link_and_cookie_policy(monkeypatch):
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "")
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setattr(routes, "send_verification_email", lambda *_args: False)
    request = make_request("localhost:8000", "127.0.0.1")
    response = Response()
    user = User(email="trader@example.test", email_verification_token="secret-token")

    routes._set_session_cookie(response, "session-token", request)
    verification = routes._verification_payload(request, user)

    assert routes._verification_url(request, "secret-token") == (
        "http://localhost:8000/auth/verify-email?token=secret-token"
    )
    assert verification["dev_verification_url"].endswith("token=secret-token")
    assert "; Secure" not in response.headers["set-cookie"]


def test_trusted_https_origin_sets_secure_cookie(monkeypatch):
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "https://public.example.test")
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    request = make_request("attacker.example", "203.0.113.10")
    response = Response()

    routes._set_session_cookie(response, "session-token", request)

    assert "; Secure" in response.headers["set-cookie"]


def test_https_request_sets_secure_cookie_without_configured_origin(monkeypatch):
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "")
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    request = make_request("public.example.test", "203.0.113.10", scheme="https")
    response = Response()

    routes._set_session_cookie(response, "session-token", request)

    assert "; Secure" in response.headers["set-cookie"]


def test_login_issues_secure_cookie_and_authenticates(auth_client_and_session, monkeypatch):
    client, SessionLocal = auth_client_and_session
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "https://public.example.test:9443")
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    with SessionLocal() as db:
        db.add(
            User(
                username="trader",
                email="trader@example.test",
                display_name="Trader",
                password_hash=hash_password("secret-pass"),
                email_verified_at=now_iso(),
                created_at=now_iso(),
            )
        )
        db.commit()

    login = client.post("/api/auth/login", json={"username": "trader", "password": "secret-pass"})

    assert login.status_code == 200
    assert "; Secure" in login.headers["set-cookie"]
    assert client.get("/api/auth/me").json()["authenticated"] is True


def test_email_verification_issues_secure_cookie(auth_client_and_session, monkeypatch):
    client, SessionLocal = auth_client_and_session
    monkeypatch.setattr(routes, "PUBLIC_CANONICAL_ORIGIN", "https://public.example.test:9443")
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    with SessionLocal() as db:
        db.add(
            User(
                username="trader",
                email="trader@example.test",
                display_name="Trader",
                password_hash=hash_password("secret-pass"),
                email_verification_token="verification-token-12345",
                email_verification_sent_at=now_iso(),
                created_at=now_iso(),
            )
        )
        db.commit()

    response = client.get(
        "/auth/verify-email?token=verification-token-12345",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "; Secure" in response.headers["set-cookie"]
