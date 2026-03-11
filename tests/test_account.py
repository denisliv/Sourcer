"""Tests for account endpoints: status, password change, credentials, logs."""

from unittest.mock import AsyncMock, patch

import pytest


class TestAccountStatus:
    def test_unauthenticated(self, client):
        resp = client.get("/api/account/status", headers={"Accept": "application/json"})
        assert resp.status_code == 401

    def test_status_no_credentials(self, client, user_session_token):
        resp = client.get(
            "/api/account/status",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hh_status"] == "not_configured"
        assert data["li_status"] == "not_configured"
        assert data["user"]["email"] == "user@test.com"

    def test_status_returns_user_info(self, client, admin_session_token):
        resp = client.get(
            "/api/account/status",
            cookies={"session_token": admin_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["is_admin"] is True
        assert data["user"]["email"] == "admin@test.com"

    async def test_status_with_hh_credential(
        self, async_client, db_session, regular_user, user_session_token,
    ):
        from datetime import datetime, timedelta, timezone
        from app.core.security import encrypt_credentials
        from app.models.credential import Credential

        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        cred_data = {
            "access_token": "test_token",
            "refresh_token": "test_refresh",
            "expires_at": expires,
            "user_agent": "test-agent",
        }
        cred = Credential(
            user_id=regular_user.id,
            provider="hh",
            status="active",
            encrypted_data=encrypt_credentials(cred_data),
        )
        db_session.add(cred)
        await db_session.commit()

        resp = await async_client.get(
            "/api/account/status",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hh_status"] == "active"

    async def test_status_with_linkedin_credential(
        self, async_client, db_session, regular_user, user_session_token,
    ):
        from app.core.security import encrypt_credentials
        from app.models.credential import Credential

        cred_data = {"username": "john@example.com", "password": "secret"}
        cred = Credential(
            user_id=regular_user.id,
            provider="linkedin",
            status="active",
            encrypted_data=encrypt_credentials(cred_data),
        )
        db_session.add(cred)
        await db_session.commit()

        resp = await async_client.get(
            "/api/account/status",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["li_status"] == "active"
        assert data["li_username"] == "john@example.com"


class TestChangePassword:
    def test_unauthenticated(self, client):
        resp = client.post(
            "/api/account/password",
            json={"current_password": "x", "new_password": "y"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_wrong_current_password(self, client, user_session_token):
        resp = client.post(
            "/api/account/password",
            json={"current_password": "wrongpass", "new_password": "newpass123"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    def test_new_password_too_short(self, client, user_session_token):
        resp = client.post(
            "/api/account/password",
            json={"current_password": "user1234", "new_password": "abc"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400

    def test_change_password_success(self, client, user_session_token):
        resp = client.post(
            "/api/account/password",
            json={"current_password": "user1234", "new_password": "newpassword123"},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Login with old password should fail
        resp2 = client.post("/api/auth/login", json={
            "email": "user@test.com",
            "password": "user1234",
        })
        assert resp2.status_code == 401

        # Login with new password should succeed
        resp3 = client.post("/api/auth/login", json={
            "email": "user@test.com",
            "password": "newpassword123",
        })
        assert resp3.status_code == 200


class TestHHOAuth:
    def test_authorize_unauthenticated(self, client):
        resp = client.get(
            "/api/account/hh/authorize",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_authorize_redirects(self, client, user_session_token):
        resp = client.get(
            "/api/account/hh/authorize",
            cookies={"session_token": user_session_token},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert "hh.ru/oauth/authorize" in resp.headers.get("location", "")

    def test_callback_missing_code(self, client):
        resp = client.get("/api/account/hh/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert "hh_error" in resp.headers.get("location", "")

    def test_callback_with_error(self, client):
        resp = client.get(
            "/api/account/hh/callback?error=access_denied&error_description=User+denied",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "hh_error" in resp.headers.get("location", "")

    def test_callback_invalid_state(self, client):
        resp = client.get(
            "/api/account/hh/callback?code=test_code&state=invalid_state",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "hh_error" in resp.headers.get("location", "")

    def test_authorize_url_in_production(self, client, user_session_token):
        with patch("app.api.account.settings") as mock_settings:
            mock_settings.is_production = True
            mock_settings.hh_app_client_id = "test"
            mock_settings.hh_redirect_uri = "http://test"
            mock_settings.secret_key = "test-secret"
            resp = client.get(
                "/api/account/hh/authorize-url",
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 404

    def test_dev_code_empty(self, client, user_session_token):
        resp = client.post(
            "/api/account/hh/dev-code",
            json={"code": "  "},
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 400


class TestDeleteHHCredentials:
    def test_unauthenticated(self, client):
        resp = client.delete(
            "/api/account/credentials/hh",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_delete_when_none(self, client, user_session_token):
        resp = client.delete(
            "/api/account/credentials/hh",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_delete_existing(
        self, async_client, db_session, regular_user, user_session_token,
    ):
        from app.core.security import encrypt_credentials
        from app.models.credential import Credential

        cred = Credential(
            user_id=regular_user.id,
            provider="hh",
            status="active",
            encrypted_data=encrypt_credentials({"access_token": "x"}),
        )
        db_session.add(cred)
        await db_session.commit()

        resp = await async_client.delete(
            "/api/account/credentials/hh",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestLinkedInCredentials:
    def test_save_unauthenticated(self, client):
        resp = client.post(
            "/api/account/credentials/linkedin",
            json={"username": "test", "password": "test"},
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_save_credentials(self, client, user_session_token):
        with patch(
            "app.services.linkedin_oauth.create_linkedin_cookies",
            new_callable=AsyncMock,
            side_effect=Exception("Browser not available"),
        ):
            resp = client.post(
                "/api/account/credentials/linkedin",
                json={"username": "user@example.com", "password": "pass123"},
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data.get("cookies_failed") is True

    def test_save_credentials_with_cookies(self, client, user_session_token):
        with patch(
            "app.services.linkedin_oauth.create_linkedin_cookies",
            new_callable=AsyncMock,
            return_value={"cookies": "mock_data"},
        ):
            resp = client.post(
                "/api/account/credentials/linkedin",
                json={"username": "user@example.com", "password": "pass123"},
                cookies={"session_token": user_session_token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert "cookies_failed" not in data

    def test_delete_unauthenticated(self, client):
        resp = client.delete(
            "/api/account/credentials/linkedin",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_delete_when_none(self, client, user_session_token):
        resp = client.delete(
            "/api/account/credentials/linkedin",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_delete_existing_linkedin(
        self, async_client, db_session, regular_user, user_session_token,
    ):
        from app.core.security import encrypt_credentials
        from app.models.credential import Credential

        cred = Credential(
            user_id=regular_user.id,
            provider="linkedin",
            status="active",
            encrypted_data=encrypt_credentials({"username": "x", "password": "y"}),
        )
        db_session.add(cred)
        await db_session.commit()

        resp = await async_client.delete(
            "/api/account/credentials/linkedin",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestAuditLogs:
    def test_unauthenticated(self, client):
        resp = client.get(
            "/api/account/logs",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_empty_logs(self, client, user_session_token):
        resp = client.get(
            "/api/account/logs",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 0
        assert isinstance(data["logs"], list)

    def test_logs_pagination(self, client, user_session_token):
        resp = client.get(
            "/api/account/logs?page=1&per_page=5",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 5

    def test_logs_filter_by_action(self, client, user_session_token):
        resp = client.get(
            "/api/account/logs?action=login",
            cookies={"session_token": user_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        for log in data["logs"]:
            assert log["action"] == "login"

    async def test_admin_sees_all_logs(
        self, async_client, db_session, admin_user, regular_user, admin_session_token,
    ):
        from app.models.audit_log import AuditLog

        db_session.add(AuditLog(user_id=regular_user.id, action="login"))
        db_session.add(AuditLog(user_id=admin_user.id, action="login"))
        await db_session.commit()

        resp = await async_client.get(
            "/api/account/logs",
            cookies={"session_token": admin_session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
