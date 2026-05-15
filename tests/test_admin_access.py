import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.account import hash_password, now_iso
from app.db import migrate as migrations
from app.db.models import AIUsageEvent, Base, User
from app.web import routes
from app.web.main import app


@pytest.fixture
def client_and_session():
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
    try:
        yield TestClient(app), SessionLocal
    finally:
        app.dependency_overrides.clear()


def add_user(SessionLocal, username: str, *, is_admin: bool = False, can_use_ai: bool = False) -> User:
    with SessionLocal() as db:
        user = User(
            username=username,
            email=f"{username}@example.local",
            display_name=username.title(),
            password_hash=hash_password("secret-pass"),
            email_verified_at=now_iso(),
            is_admin=1 if is_admin else 0,
            can_use_ai=1 if can_use_ai else 0,
            created_at=now_iso(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def login(client: TestClient, username: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": "secret-pass"})
    assert response.status_code == 200


def test_admin_can_list_users_and_grant_permissions(client_and_session):
    client, SessionLocal = client_and_session
    add_user(SessionLocal, "admin", is_admin=True)
    user = add_user(SessionLocal, "trader")

    login(client, "admin")
    users_response = client.get("/api/admin/users")
    assert users_response.status_code == 200
    assert {item["username"] for item in users_response.json()["users"]} == {"admin", "trader"}

    update_response = client.patch(
        f"/api/admin/users/{user.id}/permissions",
        json={"is_admin": True, "can_use_ai": True},
    )
    assert update_response.status_code == 200
    assert update_response.json()["user"]["is_admin"] is True
    assert update_response.json()["user"]["effective_can_use_ai"] is True

    with SessionLocal() as db:
        updated = db.scalars(select(User).where(User.username == "trader")).one()
        assert updated.is_admin == 1
        assert updated.can_use_ai == 1


def test_non_admin_cannot_list_users(client_and_session):
    client, SessionLocal = client_and_session
    add_user(SessionLocal, "trader")

    login(client, "trader")
    response = client.get("/api/admin/users")

    assert response.status_code == 403
    assert response.json()["error_key"] == "accountErrorAdminRequired"


def test_admin_cannot_remove_own_admin_access(client_and_session):
    client, SessionLocal = client_and_session
    admin = add_user(SessionLocal, "admin", is_admin=True)

    login(client, "admin")
    response = client.patch(f"/api/admin/users/{admin.id}/permissions", json={"is_admin": False})

    assert response.status_code == 400
    assert response.json()["error_key"] == "accountErrorAdminSelfDemote"


def test_migration_promotes_first_existing_user_when_no_admin(client_and_session, monkeypatch):
    _client, SessionLocal = client_and_session
    first = add_user(SessionLocal, "first")
    add_user(SessionLocal, "second")
    monkeypatch.setattr(migrations, "get_session_for_migration", lambda: SessionLocal())

    migrations._ensure_existing_admin()

    with SessionLocal() as db:
        promoted = db.get(User, first.id)
        other = db.scalars(select(User).where(User.username == "second")).one()
        assert promoted.is_admin == 1
        assert promoted.can_use_ai == 1
        assert other.is_admin == 0


def test_ai_market_context_requires_ai_permission(client_and_session, monkeypatch):
    client, SessionLocal = client_and_session
    user = add_user(SessionLocal, "trader")

    async def fake_context(**kwargs):
        return {"ok": True, "league": kwargs["league"]}

    monkeypatch.setattr(routes, "load_ai_market_context", fake_context)
    login(client, "trader")
    params = {"league": "Test", "category": "Currency", "target": "exalted"}

    denied = client.get("/api/ai/market-context", params=params)
    assert denied.status_code == 403
    assert denied.json()["error_key"] == "accountErrorAiAccessRequired"

    with SessionLocal() as db:
        updated = db.get(User, user.id)
        updated.can_use_ai = 1
        db.commit()

    allowed = client.get("/api/ai/market-context", params=params)
    assert allowed.status_code == 200
    assert allowed.json()["ok"] is True
    assert allowed.json()["league"] == "Test"
    assert allowed.json()["ai_quota"]["used_today"] == 1


def test_funpay_rub_context_requires_profile_opt_in(client_and_session, monkeypatch):
    client, SessionLocal = client_and_session
    add_user(SessionLocal, "trader")

    async def fake_funpay_context(db, **kwargs):
        return {"ok": True, "league": kwargs["league"], "target_currency": kwargs["target_currency"]}

    monkeypatch.setattr(routes, "load_funpay_rub_context", fake_funpay_context)
    login(client, "trader")

    denied = client.get("/api/account/funpay-rub", params={"league": "Test", "target": "divine"})
    assert denied.status_code == 403
    assert denied.json()["error_key"] == "accountErrorFiatRubDisabled"

    preferences = client.patch(
        "/api/account/preferences",
        json={"fiat_rub_enabled": True, "account_target_currency": "divine"},
    )
    assert preferences.status_code == 200
    assert preferences.json()["user"]["fiat_rub_enabled"] is True
    assert preferences.json()["user"]["account_target_currency"] == "divine"

    allowed = client.get("/api/account/funpay-rub", params={"league": "Test", "target": "divine"})
    assert allowed.status_code == 200
    assert allowed.json()["ok"] is True
    assert allowed.json()["league"] == "Test"


def test_admin_metrics_include_ai_quota_and_recent_usage(client_and_session, monkeypatch):
    client, SessionLocal = client_and_session
    admin = add_user(SessionLocal, "admin", is_admin=True)
    user = add_user(SessionLocal, "trader", can_use_ai=True)
    monkeypatch.setenv("AI_DAILY_QUOTA", "5")
    with SessionLocal() as db:
        db.add(
            AIUsageEvent(
                user_id=user.id,
                feature="market_context",
                created_at=now_iso(),
                success=1,
                status_code=200,
                duration_ms=12,
            )
        )
        db.commit()

    login(client, "admin")
    response = client.get("/api/admin/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["users"]["total"] == 2
    assert payload["users"]["admins"] == 1
    assert payload["users"]["ai_enabled"] == 2
    assert payload["ai_quota"]["daily_limit"] == 5
    assert payload["ai_quota"]["used_today"] == 1
    assert payload["ai_quota"]["remaining"] == 4
    assert payload["ai_usage"]["recent"][0]["username"] == "trader"


def test_ai_market_context_stops_at_local_daily_quota(client_and_session, monkeypatch):
    client, SessionLocal = client_and_session
    add_user(SessionLocal, "trader", can_use_ai=True)
    monkeypatch.setenv("AI_DAILY_QUOTA", "0")

    async def fake_context(**kwargs):
        return {"ok": True}

    monkeypatch.setattr(routes, "load_ai_market_context", fake_context)
    login(client, "trader")
    response = client.get(
        "/api/ai/market-context",
        params={"league": "Test", "category": "Currency", "target": "exalted"},
    )

    assert response.status_code == 200

    monkeypatch.setenv("AI_DAILY_QUOTA", "1")
    denied = client.get(
        "/api/ai/market-context",
        params={"league": "Test", "category": "Currency", "target": "exalted"},
    )
    assert denied.status_code == 429
    assert denied.json()["error_key"] == "accountErrorAiQuotaExceeded"


def test_ai_market_analysis_requires_permission_and_creates_job(client_and_session, monkeypatch):
    client, SessionLocal = client_and_session
    user = add_user(SessionLocal, "trader")
    routes.AI_MARKET_ANALYSIS_JOBS.clear()

    monkeypatch.setattr(routes, "_schedule_ai_market_analysis_job", lambda job_id, params: None)
    login(client, "trader")
    payload = {"league": "Test", "category": "Currency", "target": "exalted", "status": "any"}

    denied = client.post("/api/ai/market-analysis", json=payload)
    assert denied.status_code == 403
    assert denied.json()["error_key"] == "accountErrorAiAccessRequired"

    with SessionLocal() as db:
        updated = db.get(User, user.id)
        updated.can_use_ai = 1
        db.commit()

    created = client.post("/api/ai/market-analysis", json=payload)
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert routes.AI_MARKET_ANALYSIS_JOBS[job_id]["params"]["league"] == "Test"

    status = client.get(f"/api/ai/market-analysis/{job_id}")
    assert status.status_code == 200
    assert status.json()["job_id"] == job_id

    routes.AI_MARKET_ANALYSIS_JOBS.clear()


def test_ai_currency_analysis_requires_permission_and_creates_job(client_and_session, monkeypatch):
    client, SessionLocal = client_and_session
    user = add_user(SessionLocal, "trader")
    routes.AI_CURRENCY_ANALYSIS_JOBS.clear()

    monkeypatch.setattr(routes, "_schedule_ai_currency_analysis_job", lambda job_id, params: None)
    login(client, "trader")
    payload = {"league": "Test", "currency_id": "divine", "target": "exalted", "status": "any"}

    denied = client.post("/api/ai/currency-analysis", json=payload)
    assert denied.status_code == 403
    assert denied.json()["error_key"] == "accountErrorAiAccessRequired"

    with SessionLocal() as db:
        updated = db.get(User, user.id)
        updated.can_use_ai = 1
        db.commit()

    created = client.post("/api/ai/currency-analysis", json=payload)
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert routes.AI_CURRENCY_ANALYSIS_JOBS[job_id]["params"]["currency_id"] == "divine"

    status = client.get(f"/api/ai/currency-analysis/{job_id}")
    assert status.status_code == 200
    assert status.json()["job_id"] == job_id

    routes.AI_CURRENCY_ANALYSIS_JOBS.clear()
