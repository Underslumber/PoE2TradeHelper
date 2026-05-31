from fastapi.testclient import TestClient

from app.web.main import app


def test_xapct_without_port_redirects_to_canonical_port() -> None:
    client = TestClient(app)

    response = client.get("/?view=lots", headers={"host": "xapct.ru"}, follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "https://xapct.ru:9038/?view=lots"
    assert response.headers["alt-svc"] == "clear"


def test_xapct_with_canonical_port_is_not_redirected() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"host": "xapct.ru:9038"}, follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["alt-svc"] == "clear"


def test_local_test_host_is_not_redirected() -> None:
    client = TestClient(app)

    response = client.get("/health", follow_redirects=False)

    assert response.status_code == 200


def test_canonical_redirect_preserves_path_and_query() -> None:
    client = TestClient(app)

    response = client.get(
        "/?view=cabinet&tab=rub",
        headers={"host": "xapct.ru:443"},
        follow_redirects=False,
    )

    assert response.status_code == 308
    assert response.headers["location"] == "https://xapct.ru:9038/?view=cabinet&tab=rub"


def test_api_on_public_host_without_port_is_not_redirected() -> None:
    client = TestClient(app)

    response = client.get("/api/auth/me", headers={"host": "xapct.ru"}, follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "user": None}


def test_public_port_origin_can_call_no_port_api_with_credentials() -> None:
    client = TestClient(app)

    response = client.options(
        "/api/auth/me",
        headers={
            "host": "xapct.ru",
            "origin": "https://xapct.ru:9038",
            "access-control-request-method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://xapct.ru:9038"
    assert response.headers["access-control-allow-credentials"] == "true"
