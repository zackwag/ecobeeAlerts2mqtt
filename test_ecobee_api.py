import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from ecobee_api import (
    EcobeeApiError,
    EcobeeAuthPending,
    EcobeeClient,
    PinRegistration,
)


@pytest.fixture()
def client():
    return EcobeeClient(api_key="test-key", refresh_token="test-refresh")


@pytest.fixture()
def client_no_token():
    return EcobeeClient(api_key="test-key")


# --- PinRegistration ---


class TestRequestPin:
    @patch("ecobee_api.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "ecobeePin": "abc1",
                "code": "auth-code-123",
                "interval": 30,
                "expires_in": 900,
            }),
        )
        client = EcobeeClient("my-key")
        reg = client.request_pin()
        assert isinstance(reg, PinRegistration)
        assert reg.ecobee_pin == "abc1"
        assert reg.auth_code == "auth-code-123"
        assert reg.interval_seconds == 30
        assert reg.expires_in_seconds == 900

    @patch("ecobee_api.requests.get")
    def test_failure(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=500,
            json=MagicMock(return_value={"error": "server error"}),
        )
        client = EcobeeClient("my-key")
        with pytest.raises(EcobeeApiError, match="PIN request failed"):
            client.request_pin()


# --- complete_pin_auth ---


class TestCompletePinAuth:
    @patch("ecobee_api.requests.post")
    def test_success(self, mock_post, client_no_token):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "expires_in": 3600,
            }),
        )
        client_no_token.complete_pin_auth("auth-code")
        assert client_no_token.access_token == "at-1"
        assert client_no_token.refresh_token == "rt-1"

    @patch("ecobee_api.requests.post")
    def test_pending(self, mock_post, client_no_token):
        mock_post.return_value = MagicMock(
            status_code=401,
            json=MagicMock(return_value={}),
        )
        with pytest.raises(EcobeeAuthPending):
            client_no_token.complete_pin_auth("auth-code")

    @patch("ecobee_api.requests.post")
    def test_failure(self, mock_post, client_no_token):
        mock_post.return_value = MagicMock(
            status_code=500,
            json=MagicMock(return_value={"error": "bad"}),
        )
        with pytest.raises(EcobeeApiError, match="Token exchange failed"):
            client_no_token.complete_pin_auth("auth-code")


# --- _refresh ---


class TestRefresh:
    @patch("ecobee_api.requests.post")
    def test_success(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "access_token": "new-at",
                "refresh_token": "new-rt",
                "expires_in": 3600,
            }),
        )
        client._refresh()
        assert client.access_token == "new-at"
        assert client.refresh_token == "new-rt"

    @patch("ecobee_api.requests.post")
    def test_failure(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=400,
            json=MagicMock(return_value={"error": "invalid"}),
        )
        with pytest.raises(EcobeeApiError, match="Token refresh failed"):
            client._refresh()

    def test_no_refresh_token(self, client_no_token):
        with pytest.raises(EcobeeApiError, match="No refresh token"):
            client_no_token._refresh()


# --- _store_tokens ---


class TestStoreTokens:
    def test_stores_values(self, client):
        client._store_tokens({
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 7200,
        })
        assert client.access_token == "a"
        assert client.refresh_token == "r"
        assert client._access_token_expires_at > time.time()

    def test_default_expiry(self, client):
        before = time.time()
        client._store_tokens({"access_token": "a", "refresh_token": "r"})
        assert client._access_token_expires_at >= before + 3600 - 61


# --- _ensure_access_token ---


class TestEnsureAccessToken:
    @patch("ecobee_api.requests.post")
    def test_refreshes_when_expired(self, mock_post, client):
        client.access_token = "old"
        client._access_token_expires_at = 0
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "access_token": "new",
                "refresh_token": "rt",
                "expires_in": 3600,
            }),
        )
        token = client._ensure_access_token()
        assert token == "new"
        mock_post.assert_called_once()

    def test_returns_existing_when_valid(self, client):
        client.access_token = "valid"
        client._access_token_expires_at = time.time() + 9999
        token = client._ensure_access_token()
        assert token == "valid"

    @patch("ecobee_api.requests.post")
    def test_refreshes_when_no_token(self, mock_post, client):
        client.access_token = None
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "access_token": "fresh",
                "refresh_token": "rt",
                "expires_in": 3600,
            }),
        )
        assert client._ensure_access_token() == "fresh"


# --- get_thermostats_with_alerts ---


class TestGetThermostatsWithAlerts:
    @patch("ecobee_api.requests.get")
    def test_success(self, mock_get, client):
        client.access_token = "at"
        client._access_token_expires_at = time.time() + 9999
        thermostats = [{"identifier": "t1", "alerts": []}]
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"thermostatList": thermostats}),
        )
        result = client.get_thermostats_with_alerts()
        assert result == thermostats

    @patch("ecobee_api.requests.get")
    @patch("ecobee_api.requests.post")
    def test_retries_on_401(self, mock_post, mock_get, client):
        client.access_token = "old-at"
        client._access_token_expires_at = time.time() + 9999

        first_resp = MagicMock(status_code=401, json=MagicMock(return_value={}))
        second_resp = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"thermostatList": [{"identifier": "t1"}]}),
        )
        mock_get.side_effect = [first_resp, second_resp]
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "access_token": "new-at",
                "refresh_token": "new-rt",
                "expires_in": 3600,
            }),
        )
        result = client.get_thermostats_with_alerts()
        assert result == [{"identifier": "t1"}]
        assert mock_get.call_count == 2

    @patch("ecobee_api.requests.get")
    def test_raises_on_error(self, mock_get, client):
        client.access_token = "at"
        client._access_token_expires_at = time.time() + 9999
        mock_get.return_value = MagicMock(
            status_code=500,
            json=MagicMock(return_value={"error": "bad"}),
        )
        with pytest.raises(EcobeeApiError, match="Failed to fetch thermostats"):
            client.get_thermostats_with_alerts()

    @patch("ecobee_api.requests.get")
    def test_empty_thermostat_list(self, mock_get, client):
        client.access_token = "at"
        client._access_token_expires_at = time.time() + 9999
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={}),
        )
        assert client.get_thermostats_with_alerts() == []
