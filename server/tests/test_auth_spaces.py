from __future__ import annotations

from tests.conftest import ApiClient, create_space, signup


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_error_format_is_korean_envelope(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "unauthorized"
    assert "로그인" in body["error"]["message_ko"]


def test_csrf_header_required(client):
    r = client.post(
        "/api/auth/login", json={"email": "x@example.com", "password": "x"}, headers={"x-yeoun-request": "0"}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


def test_signup_login_logout(client):
    user = signup(client)
    assert user["email"] == "a@example.com"
    assert user["prefs"]["rest_reminder"] is True
    assert client.get("/api/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401
    r = client.post("/api/auth/login", json={"email": "A@example.com", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    r = client.post("/api/auth/login", json={"email": "A@example.com", "password": "password123"})
    assert r.status_code == 200


def test_password_is_hashed_with_argon2(client, db):
    from app.models import User

    signup(client)
    u = db.query(User).one()
    assert u.password_hash.startswith("$argon2")
    assert "password123" not in u.password_hash


def test_duplicate_email(client):
    signup(client)
    client.post("/api/auth/logout")
    r = client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "password123", "display_name": "x"}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_staging_requires_invite_code(app, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "env", "staging")
    monkeypatch.setattr(s, "invite_codes", "hello-friends, second")
    with ApiClient(app) as c:
        body = {"email": "b@example.com", "password": "password123", "display_name": "b"}
        assert c.post("/api/auth/signup", json=body).json()["error"]["code"] == "invite_required"
        bad = c.post("/api/auth/signup", json={**body, "invite_code": "nope"})
        assert bad.json()["error"]["code"] == "invalid_invite"
        ok = c.post("/api/auth/signup", json={**body, "invite_code": "second"})
        assert ok.status_code == 201


def test_space_crud_and_privacy(app):
    a = ApiClient(app)
    b = ApiClient(app)
    signup(a, "a@example.com")
    signup(b, "b@example.com")
    space = create_space(a, "엄마", "엄마")
    assert space["role"] == "owner"
    assert space["counts"]["clips"] == 0

    # 다른 사용자는 존재 여부도 알 수 없다
    assert b.get(f"/api/spaces/{space['id']}").status_code == 404
    assert b.patch(f"/api/spaces/{space['id']}", json={"name": "x"}).status_code == 404
    assert b.post(f"/api/spaces/{space['id']}/delete", json={"confirm_name": "엄마"}).status_code == 404
    assert b.get("/api/spaces").json() == []

    r = a.patch(f"/api/spaces/{space['id']}", json={"memorial_day": "2024-03-02", "birthday": "1955-06-01"})
    assert r.json()["memorial_day"] == "2024-03-02"
    assert len(a.get("/api/spaces").json()) == 1

    assert a.post(f"/api/spaces/{space['id']}/delete", json={"confirm_name": "아빠"}).status_code == 400
    assert a.post(f"/api/spaces/{space['id']}/delete", json={"confirm_name": "엄마"}).status_code == 204
    assert a.get("/api/spaces").json() == []


def test_space_key_is_wrapped(client, db):
    from app.models import Space
    from app.security import crypto

    signup(client)
    sp = create_space(client)
    space = db.get(Space, sp["id"])
    assert space.wrapped_key.startswith(b"YE1")
    dek = crypto.unwrap_key(space.wrapped_key, space.id)
    assert len(dek) == 32
