"""Public landing page: the product story shown before sign-in."""

import socket

import pytest
from fastapi.testclient import TestClient

from autoassess.web.app import create_app
from autoassess.web.landing import NAME, REPO_URL, TAGLINE


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    monkeypatch.setenv("AUTOASSESS_DEMO_DRY_RUN", "1")

    def blocked(*args, **kwargs):
        pytest.fail("Landing tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    with TestClient(create_app(tmp_path / "app", seed_samples=False)) as c:
        yield c


def test_landing_is_public_and_leads_to_the_demo(client):
    response = client.get("/", follow_redirects=True)
    assert response.status_code == 200 and response.url.path == "/sign-in"
    page = response.text
    for text in (
        "Try the demo",
        REPO_URL,
        NAME,
        TAGLINE,
        "How it works",
        "Bodhan IndicOCR",
        'lang="ta"',
        "example-redink.webp",
    ):
        assert text in page
    # The landing page sells the product; evaluation detail lives in the README.
    for text in ("HONEST SCOPE", "MEASURED, NOT CLAIMED", "QWK"):
        assert text not in page
    assert page.count('value="demo@redink.local"') == 2
    assert client.get("/static/landing.css").status_code == 200
    assert client.get("/static/example-redink.webp").headers["content-type"] == "image/webp"
    signed_in = client.post("/sign-in", data={"email": "demo@redink.local"})
    assert "Hello, Demo Teacher." in signed_in.text and "Try the demo" not in signed_in.text


def test_failed_sign_in_keeps_the_landing_page(client):
    response = client.post("/sign-in", data={"email": "nobody@example.org"})
    assert response.status_code == 400 and "recognise that email" in response.text and "How it works" in response.text


def test_grading_lab_uses_the_red_ink_brand(client):
    client.post("/sign-in", data={"email": "demo@redink.local"})
    assert "#ad343b" in client.get("/lab/theme.css").text
    config = client.get("/lab/config").json()
    assert "redink-bar" in config["css"]
    assert f"Back to {NAME}" in str(config["components"])
