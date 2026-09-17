"""MQTT publishing helpers using Home Assistant's MQTT discovery convention."""

from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        discovery_prefix: str,
        topic_prefix: str,
    ):
        self.discovery_prefix = discovery_prefix
        self.topic_prefix = topic_prefix
        self.client = mqtt.Client(client_id="ecobeeAlerts2mqtt")
        if username:
            self.client.username_pw_set(username, password)
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

    def publish_discovery(
        self, thermostat_id: str, thermostat_name: str, reminder_key: str, name: str
    ) -> str:
        """Publish (or refresh) the discovery config for one reminder. Returns its object_id.

        reminder_key must stay stable across recurrences of the same reminder (e.g.
        alertNumber) rather than ecobee's acknowledgeRef, which rotates every time the
        same reminder fires again -- keying on it would spawn a new entity each time.
        """
        object_id = f"ecobee_alert_{thermostat_id}_{_slugify(reminder_key)}"
        state_topic = f"{self.topic_prefix}/{object_id}/state"
        config_topic = f"{self.discovery_prefix}/binary_sensor/{object_id}/config"
        payload = {
            "name": name,
            "has_entity_name": True,
            "object_id": object_id,
            "unique_id": object_id,
            "state_topic": state_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "problem",
            "json_attributes_topic": f"{self.topic_prefix}/{object_id}/attributes",
            "device": {
                "identifiers": [f"ecobee_{thermostat_id}"],
                "name": thermostat_name,
                "manufacturer": "ecobee",
            },
        }
        self.client.publish(config_topic, json.dumps(payload), qos=1, retain=True)
        return object_id

    def publish_state(self, object_id: str, is_on: bool, attributes: dict) -> None:
        state_topic = f"{self.topic_prefix}/{object_id}/state"
        attrs_topic = f"{self.topic_prefix}/{object_id}/attributes"
        self.client.publish(state_topic, "ON" if is_on else "OFF", qos=1, retain=True)
        self.client.publish(attrs_topic, json.dumps(attributes), qos=1, retain=True)

    def remove_discovery(self, object_id: str) -> None:
        """Publish an empty retained message to remove the entity from HA."""
        config_topic = f"{self.discovery_prefix}/binary_sensor/{object_id}/config"
        self.client.publish(config_topic, "", qos=1, retain=True)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def _slugify(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower()
