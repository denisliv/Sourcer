"""Tests for admin user management endpoints."""

import pytest


class TestAdminCreateUser:
    def test_create_user_as_admin(self, client, admin_session_token):
        client.cookies.set("session_token", admin_session_token)
        resp = client.post("/api/admin/users", json={
            "email": "newuser@test.com",
            "password": "pass1234",
            "full_name": "New User",
            "is_admin": False,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "newuser@test.com"
        assert data["full_name"] == "New User"
        assert data["is_admin"] is False
        assert data["must_change_password"] is True

    def test_create_user_as_non_admin_forbidden(self, client, user_session_token):
        client.cookies.set("session_token", user_session_token)
        resp = client.post("/api/admin/users", json={
            "email": "another@test.com",
            "password": "pass1234",
        })
        assert resp.status_code == 403

    def test_create_user_unauthenticated(self, client):
        resp = client.post(
            "/api/admin/users",
            json={"email": "x@test.com", "password": "pass1234"},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_create_duplicate_user(self, client, admin_session_token, regular_user):
        client.cookies.set("session_token", admin_session_token)
        resp = client.post("/api/admin/users", json={
            "email": "user@test.com",
            "password": "pass1234",
        })
        assert resp.status_code == 409


class TestAdminListUsers:
    def test_list_users_as_admin(self, client, admin_session_token, admin_user, regular_user):
        client.cookies.set("session_token", admin_session_token)
        resp = client.get("/api/admin/users")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        emails = [u["email"] for u in data]
        assert "admin@test.com" in emails
        assert "user@test.com" in emails

    def test_list_users_as_non_admin_forbidden(self, client, user_session_token):
        client.cookies.set("session_token", user_session_token)
        resp = client.get("/api/admin/users")
        assert resp.status_code == 403


class TestAdminDeleteUser:
    def test_delete_user_as_admin(self, client, admin_session_token, regular_user):
        client.cookies.set("session_token", admin_session_token)
        resp = client.delete(f"/api/admin/users/{regular_user.id}")
        assert resp.status_code == 204

    def test_cannot_delete_self(self, client, admin_session_token, admin_user):
        client.cookies.set("session_token", admin_session_token)
        resp = client.delete(f"/api/admin/users/{admin_user.id}")
        assert resp.status_code == 400

    def test_delete_nonexistent_user(self, client, admin_session_token):
        client.cookies.set("session_token", admin_session_token)
        resp = client.delete("/api/admin/users/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
