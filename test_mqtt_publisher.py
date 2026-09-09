import json
from unittest.mock import MagicMock, patch

import pytest

from mqtt_publisher import MqttPublisher, _slugify


# --- _slugify ---


class TestSlugify:
    def test_simple(self):
        assert _slugify("hello") == "hello"

    def test_spaces_to_underscores(self):
        assert _slugify("Furnace Filter") == "furnace_filter"

    def test_special_characters(self):
        assert _slugify("a!b@c#d") == "a_b_c_d"

    def test_leading_trailing_stripped(self):
        assert _slugify("!!test!!") == "test"

    def test_numbers(self):
        assert _slugify("3130") == "3130"

    def test_mixed(self):
        assert _slugify("UV Lamp (2024)") == "uv_lamp__2024"


# --- MqttPublisher ---


@pytest.fixture()
def publisher():
    with patch("mqtt_publisher.mqtt.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        pub = MqttPublisher(
            host="mqtt.local",
            port=1883,
            username="user",
            password="pass",
            discovery_prefix="homeassistant",
            topic_prefix="ecobeeAlerts2mqtt",
        )
        yield pub


@pytest.fixture()
def publisher_no_auth():
    with patch("mqtt_publisher.mqtt.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        pub = MqttPublisher(
            host="mqtt.local",
            port=1883,
            username=None,
            password=None,
            discovery_prefix="homeassistant",
            topic_prefix="ecobeeAlerts2mqtt",
        )
        mock_client.username_pw_set.assert_not_called()
        yield pub


class TestMqttPublisherInit:
    def test_connects(self):
        with patch("mqtt_publisher.mqtt.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            MqttPublisher(
                host="broker",
                port=1884,
                username="u",
                password="p",
                discovery_prefix="ha",
                topic_prefix="tp",
            )
            mock_client.username_pw_set.assert_called_once_with("u", "p")
            mock_client.connect.assert_called_once_with("broker", 1884, keepalive=60)
            mock_client.loop_start.assert_called_once()


class TestPublishDiscovery:
    def test_returns_object_id(self, publisher):
        oid = publisher.publish_discovery("therm123", "My Thermostat", "3130", "Furnace Filter")
        assert oid == "ecobee_alert_therm123_3130"

    def test_publishes_correct_topic(self, publisher):
        publisher.publish_discovery("t1", "Thermostat", "3130", "Furnace Filter")
        call = publisher.client.publish.call_args
        assert call[0][0] == "homeassistant/binary_sensor/ecobee_alert_t1_3130/config"

    def test_payload_structure(self, publisher):
        publisher.publish_discovery("t1", "Living Room", "3136", "AC Maintenance")
        payload = json.loads(publisher.client.publish.call_args[0][1])
        assert payload["name"] == "AC Maintenance"
        assert payload["unique_id"] == "ecobee_alert_t1_3136"
        assert payload["device_class"] == "problem"
        assert payload["payload_on"] == "ON"
        assert payload["payload_off"] == "OFF"
        assert payload["device"]["identifiers"] == ["ecobee_t1"]
        assert payload["device"]["name"] == "Living Room"
        assert payload["device"]["manufacturer"] == "ecobee"

    def test_retain_and_qos(self, publisher):
        publisher.publish_discovery("t1", "T", "3130", "Filter")
        call = publisher.client.publish.call_args
        assert call[1]["qos"] == 1 or call[0][2] == 1
        assert call[1]["retain"] is True or call[0][3] is True

    def test_slugifies_reminder_key(self, publisher):
        oid = publisher.publish_discovery("t1", "T", "some text alert!", "Alert")
        assert oid == "ecobee_alert_t1_some_text_alert"


class TestPublishState:
    def test_on(self, publisher):
        publisher.publish_state("ecobee_alert_t1_3130", is_on=True, attributes={"date": "2025-01-01"})
        calls = publisher.client.publish.call_args_list
        state_call = calls[0]
        attrs_call = calls[1]
        assert state_call[0][0] == "ecobeeAlerts2mqtt/ecobee_alert_t1_3130/state"
        assert state_call[0][1] == "ON"
        assert attrs_call[0][0] == "ecobeeAlerts2mqtt/ecobee_alert_t1_3130/attributes"
        assert json.loads(attrs_call[0][1])["date"] == "2025-01-01"

    def test_off(self, publisher):
        publisher.publish_state("ecobee_alert_t1_3130", is_on=False, attributes={})
        state_call = publisher.client.publish.call_args_list[0]
        assert state_call[0][1] == "OFF"


class TestRemoveDiscovery:
    def test_publishes_empty_payload(self, publisher):
        publisher.remove_discovery("ecobee_alert_t1_3130")
        call = publisher.client.publish.call_args
        assert call[0][0] == "homeassistant/binary_sensor/ecobee_alert_t1_3130/config"
        assert call[0][1] == ""


class TestClose:
    def test_stops_and_disconnects(self, publisher):
        publisher.close()
        publisher.client.loop_stop.assert_called_once()
        publisher.client.disconnect.assert_called_once()
