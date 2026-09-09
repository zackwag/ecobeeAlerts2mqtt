import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from main import (
    _EQUIPMENT_TYPE_TO_ALERT_NUMBER,
    _REMINDER_NAMES,
    _load_token,
    _require_env,
    _save_token,
)


# --- _require_env ---


class TestRequireEnv:
    def test_returns_value(self, monkeypatch):
        monkeypatch.setenv("TEST_KEY", "val")
        assert _require_env("TEST_KEY") == "val"

    def test_exits_on_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        with pytest.raises(SystemExit):
            _require_env("MISSING_KEY")

    def test_exits_on_empty(self, monkeypatch):
        monkeypatch.setenv("EMPTY_KEY", "")
        with pytest.raises(SystemExit):
            _require_env("EMPTY_KEY")


# --- _load_token / _save_token ---


class TestTokenPersistence:
    def test_load_existing(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({"refresh_token": "rt-saved"}))
        assert _load_token(str(token_file)) == "rt-saved"

    def test_load_missing_file(self, tmp_path):
        assert _load_token(str(tmp_path / "missing.json")) is None

    def test_load_missing_key(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({"other": "data"}))
        assert _load_token(str(token_file)) is None

    def test_save_creates_file(self, tmp_path):
        token_file = tmp_path / "subdir" / "token.json"
        _save_token(str(token_file), "new-rt")
        assert token_file.exists()
        data = json.loads(token_file.read_text())
        assert data["refresh_token"] == "new-rt"

    def test_save_overwrites(self, tmp_path):
        token_file = tmp_path / "token.json"
        _save_token(str(token_file), "first")
        _save_token(str(token_file), "second")
        data = json.loads(token_file.read_text())
        assert data["refresh_token"] == "second"


# --- Lookup tables ---


class TestLookupTables:
    def test_reminder_names_keys_are_ints(self):
        for key in _REMINDER_NAMES:
            assert isinstance(key, int)

    def test_equipment_type_maps_to_valid_alert_numbers(self):
        for eq_type, alert_num in _EQUIPMENT_TYPE_TO_ALERT_NUMBER.items():
            assert alert_num in _REMINDER_NAMES, f"{eq_type} -> {alert_num} not in _REMINDER_NAMES"

    def test_known_mappings(self):
        assert _REMINDER_NAMES[3130] == "Furnace Filter"
        assert _REMINDER_NAMES[3136] == "AC Maintenance"
        assert _EQUIPMENT_TYPE_TO_ALERT_NUMBER["furnaceFilter"] == 3130
        assert _EQUIPMENT_TYPE_TO_ALERT_NUMBER["ac"] == 3136


# --- main loop alert processing ---


class TestAlertProcessing:
    @patch("main.time.sleep", side_effect=StopIteration)
    @patch("main.MqttPublisher")
    @patch("main.EcobeeClient")
    def test_firing_alert_published_as_on(self, MockClient, MockPub, mock_sleep, monkeypatch):
        monkeypatch.setenv("ECOBEE_API_KEY", "key")
        monkeypatch.setenv("MQTT_HOST", "mqtt")
        monkeypatch.setenv("ECOBEE_REFRESH_TOKEN", "rt")

        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.refresh_token = "rt"

        mock_pub = MagicMock()
        MockPub.return_value = mock_pub
        mock_pub.publish_discovery.return_value = "ecobee_alert_t1_3130"

        mock_client.get_thermostats_with_alerts.return_value = [{
            "identifier": "t1",
            "name": "Living Room",
            "alerts": [{
                "acknowledgeRef": "ack-1",
                "alertNumber": 3130,
                "text": "Change filter",
                "alertType": "reminder",
                "date": "2025-01-01",
                "time": "12:00",
                "severity": 2,
            }],
            "notificationSettings": {"equipment": []},
        }]

        from main import main
        with pytest.raises(StopIteration):
            main()

        mock_pub.publish_state.assert_called()
        state_calls = [c for c in mock_pub.publish_state.call_args_list if c[1].get("is_on") is True or (c[0] and len(c[0]) > 1 and c[0][1] is True)]
        assert len(state_calls) >= 1

    @patch("main.time.sleep", side_effect=StopIteration)
    @patch("main.MqttPublisher")
    @patch("main.EcobeeClient")
    def test_equipment_without_alert_published_as_off(self, MockClient, MockPub, mock_sleep, monkeypatch):
        monkeypatch.setenv("ECOBEE_API_KEY", "key")
        monkeypatch.setenv("MQTT_HOST", "mqtt")
        monkeypatch.setenv("ECOBEE_REFRESH_TOKEN", "rt")

        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.refresh_token = "rt"

        mock_pub = MagicMock()
        MockPub.return_value = mock_pub
        mock_pub.publish_discovery.return_value = "ecobee_alert_t1_3130"

        mock_client.get_thermostats_with_alerts.return_value = [{
            "identifier": "t1",
            "name": "Living Room",
            "alerts": [],
            "notificationSettings": {
                "equipment": [{"type": "furnaceFilter", "enabled": True, "remindMeDate": "2025-06-01", "filterLastChanged": "2025-01-01"}]
            },
        }]

        from main import main
        with pytest.raises(StopIteration):
            main()

        off_calls = [c for c in mock_pub.publish_state.call_args_list if c[1].get("is_on") is False or (c[0] and len(c[0]) > 1 and c[0][1] is False)]
        assert len(off_calls) >= 1

    @patch("main.time.sleep", side_effect=[None, StopIteration])
    @patch("main.MqttPublisher")
    @patch("main.EcobeeClient")
    def test_stale_alerts_cleared(self, MockClient, MockPub, mock_sleep, monkeypatch):
        monkeypatch.setenv("ECOBEE_API_KEY", "key")
        monkeypatch.setenv("MQTT_HOST", "mqtt")
        monkeypatch.setenv("ECOBEE_REFRESH_TOKEN", "rt")

        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.refresh_token = "rt"

        mock_pub = MagicMock()
        MockPub.return_value = mock_pub
        mock_pub.publish_discovery.return_value = "ecobee_alert_t1_3130"

        alert_thermostat = {
            "identifier": "t1",
            "name": "Living Room",
            "alerts": [{"acknowledgeRef": "ack-1", "alertNumber": 3130}],
            "notificationSettings": {"equipment": []},
        }
        no_alert_thermostat = {
            "identifier": "t1",
            "name": "Living Room",
            "alerts": [],
            "notificationSettings": {"equipment": []},
        }
        mock_client.get_thermostats_with_alerts.side_effect = [
            [alert_thermostat],
            [no_alert_thermostat],
        ]

        from main import main
        with pytest.raises(StopIteration):
            main()

        last_publish_state = mock_pub.publish_state.call_args_list[-1]
        assert last_publish_state[1].get("is_on") is False or (last_publish_state[0] and len(last_publish_state[0]) > 1 and last_publish_state[0][1] is False)

    @patch("main.time.sleep", side_effect=StopIteration)
    @patch("main.MqttPublisher")
    @patch("main.EcobeeClient")
    def test_disabled_equipment_skipped(self, MockClient, MockPub, mock_sleep, monkeypatch):
        monkeypatch.setenv("ECOBEE_API_KEY", "key")
        monkeypatch.setenv("MQTT_HOST", "mqtt")
        monkeypatch.setenv("ECOBEE_REFRESH_TOKEN", "rt")

        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.refresh_token = "rt"

        mock_pub = MagicMock()
        MockPub.return_value = mock_pub

        mock_client.get_thermostats_with_alerts.return_value = [{
            "identifier": "t1",
            "name": "T",
            "alerts": [],
            "notificationSettings": {
                "equipment": [{"type": "furnaceFilter", "enabled": False}]
            },
        }]

        from main import main
        with pytest.raises(StopIteration):
            main()

        mock_pub.publish_discovery.assert_not_called()

    @patch("main.time.sleep", side_effect=StopIteration)
    @patch("main.MqttPublisher")
    @patch("main.EcobeeClient")
    def test_token_rotation_saved(self, MockClient, MockPub, mock_sleep, monkeypatch, tmp_path):
        token_file = str(tmp_path / "token.json")
        monkeypatch.setenv("ECOBEE_API_KEY", "key")
        monkeypatch.setenv("MQTT_HOST", "mqtt")
        monkeypatch.setenv("ECOBEE_REFRESH_TOKEN", "old-rt")
        monkeypatch.setenv("TOKEN_FILE_PATH", token_file)

        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.refresh_token = "new-rt"
        mock_client.get_thermostats_with_alerts.return_value = []

        mock_pub = MagicMock()
        MockPub.return_value = mock_pub

        from main import main
        with pytest.raises(StopIteration):
            main()

        data = json.loads(open(token_file).read())
        assert data["refresh_token"] == "new-rt"
