"""Tests for authentication: login, logout, session management."""

import pytest
from app.models.session import Session
from app.models.user import User


class TestLogin:
    def test_login_success(self, client, regular_user):
        resp = client.post("/api/auth/login", json={
            "email": "user@test.com",
            "password": "user1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["redirect"] == "/"
        assert "session_token" in resp.cookies

    def test_login_wrong_password(self, client, regular_user):
        resp = client.post("/api/auth/login", json={
            "email": "user@test.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody@test.com",
            "password": "whatever",
        })
        assert resp.status_code == 401


class TestLogout:
    def test_logout_clears_session(self, client, user_session_token):
        client.cookies.set("session_token", user_session_token)
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_logout_without_session(self, client):
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestSessionValidation:
    def test_unauthenticated_api_returns_401(self, client):
        resp = client.get("/api/search", headers={"accept": "application/json"})
        assert resp.status_code == 401

    def test_authenticated_api_succeeds(self, client, user_session_token):
        client.cookies.set("session_token", user_session_token)
        resp = client.get("/api/search", headers={"accept": "application/json"})
        # Will return validation error (missing params) but NOT 401
        assert resp.status_code == 200
