"""Minimal synchronous ecobee API client: PIN auth, token refresh, read alerts."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import requests

ECOBEE_AUTHORIZE_URL = "https://api.ecobee.com/authorize"
ECOBEE_TOKEN_URL = "https://api.ecobee.com/token"
ECOBEE_API_BASE = "https://api.ecobee.com/1"
SCOPE = "smartRead"


class EcobeeApiError(Exception):
    pass


class EcobeeAuthPending(Exception):
    pass


@dataclass
class PinRegistration:
    ecobee_pin: str
    auth_code: str
    interval_seconds: int
    expires_in_seconds: int


class EcobeeClient:
    def __init__(self, api_key: str, refresh_token: str | None = None):
        self.api_key = api_key
        self.refresh_token = refresh_token
        self.access_token: str | None = None
        self._access_token_expires_at = 0.0

    def request_pin(self) -> PinRegistration:
        resp = requests.get(
            ECOBEE_AUTHORIZE_URL,
            params={"response_type": "ecobeePin", "client_id": self.api_key, "scope": SCOPE},
            timeout=15,
        )
        body = resp.json()
        if resp.status_code != 200:
            raise EcobeeApiError(f"PIN request failed: {body}")
        return PinRegistration(
            ecobee_pin=body["ecobeePin"],
            auth_code=body["code"],
            interval_seconds=int(body.get("interval", 30)),
            expires_in_seconds=int(body.get("expires_in", 900)),
        )

    def complete_pin_auth(self, auth_code: str) -> None:
        resp = requests.post(
            ECOBEE_TOKEN_URL,
            params={"grant_type": "ecobeePin", "code": auth_code, "client_id": self.api_key},
            timeout=15,
        )
        body = resp.json()
        if resp.status_code == 401:
            raise EcobeeAuthPending("PIN not yet authorized in the ecobee portal")
        if resp.status_code != 200:
            raise EcobeeApiError(f"Token exchange failed: {body}")
        self._store_tokens(body)

    def _refresh(self) -> None:
        if not self.refresh_token:
            raise EcobeeApiError("No refresh token available; re-authentication required")
        resp = requests.post(
            ECOBEE_TOKEN_URL,
            params={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.api_key,
            },
            timeout=15,
        )
        body = resp.json()
        if resp.status_code != 200:
            raise EcobeeApiError(f"Token refresh failed: {body}")
        self._store_tokens(body)

    def _store_tokens(self, body: dict) -> None:
        self.access_token = body["access_token"]
        self.refresh_token = body["refresh_token"]
        self._access_token_expires_at = time.time() + int(body.get("expires_in", 3600)) - 60

    def _ensure_access_token(self) -> str:
        if not self.access_token or time.time() >= self._access_token_expires_at:
            self._refresh()
        return self.access_token

    def get_thermostats_with_alerts(self) -> list[dict]:
        token = self._ensure_access_token()
        selection = {
            "selection": {
                "selectionType": "registered",
                "selectionMatch": "",
                "includeAlerts": True,
            }
        }
        resp = requests.get(
            f"{ECOBEE_API_BASE}/thermostat",
            headers={"Authorization": f"Bearer {token}"},
            params={"json": json.dumps(selection)},
            timeout=15,
        )
        body = resp.json()
        if resp.status_code == 401:
            self._refresh()
            resp = requests.get(
                f"{ECOBEE_API_BASE}/thermostat",
                headers={"Authorization": f"Bearer {self.access_token}"},
                params={"json": json.dumps(selection)},
                timeout=15,
            )
            body = resp.json()
        if resp.status_code != 200:
            raise EcobeeApiError(f"Failed to fetch thermostats: {body}")
        return body.get("thermostatList", [])
