from fastapi.testclient import TestClient

from app.web.main import app


def test_xapct_without_port_redirects_to_canonical_port() -> None:
    client = TestClient(app)

    response = client.get("/?view=lots", headers={"host": "xapct.ru"}, follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "https://xapct.ru:9038/?view=lots"


def test_xapct_with_canonical_port_is_not_redirected() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"host": "xapct.ru:9038"}, follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_test_host_is_not_redirected() -> None:
    client = TestClient(app)

    response = client.get("/health", follow_redirects=False)

    assert response.status_code == 200


def test_canonical_redirect_preserves_path_and_query() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/account/pins?league=Runes%20of%20Aldur",
        headers={"host": "xapct.ru:443"},
        follow_redirects=False,
    )

    assert response.status_code == 308
    assert response.headers["location"] == "https://xapct.ru:9038/api/account/pins?league=Runes%20of%20Aldur"
