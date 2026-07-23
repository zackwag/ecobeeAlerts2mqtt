"""ecobeeAlerts2mqtt: polls ecobee thermostat alerts and publishes them to
Home Assistant via MQTT discovery, one binary_sensor per reminder.

Env vars (all required unless noted):
  ECOBEE_API_KEY            API key from your ecobee developer app
  ECOBEE_REFRESH_TOKEN      optional; if unset and no token file exists yet,
                            the service blocks on first run and walks you
                            through ecobee's PIN authorization in the logs
  MQTT_DISCOVERY_PREFIX     optional, default "homeassistant"
  MQTT_HOST
  MQTT_PASSWORD             optional
  MQTT_PORT                 optional, default 1883
  MQTT_TOPIC_PREFIX         optional, default "ecobeeAlerts2mqtt"
  MQTT_USERNAME             optional
  POLL_INTERVAL_SECONDS     optional, default 300
  TOKEN_FILE_PATH           optional, default "/data/ecobee_token.json"
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

from ecobee_api import EcobeeApiError, EcobeeAuthPending, EcobeeClient
from mqtt_publisher import MqttPublisher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger("ecobeeAlerts2mqtt")

# ecobee's alertNumber is a fixed numeric code (see ecobee API docs, Alert
# Object) that's stable across recurrences of the same reminder, unlike
# acknowledgeRef or the free-text alert body. This maps the maintenance-
# reminder range to the same short names ecobee's own app uses.
_REMINDER_NAMES = {
    3130: "Furnace Filter",
    3131: "Humidifier Filter",
    3132: "Ventilator",
    3133: "Dehumidifier Filter",
    3134: "Economizer",
    3135: "UV Lamp",
    3136: "AC Maintenance",
    3137: "Air Filter",
    3138: "Air Cleaner",
    3140: "HVAC Maintenance",
}

# Maps ecobee's configured-equipment-reminder type (from
# thermostat.notificationSettings.equipment[].type) to the same alertNumber
# it fires under once due, so the entity created ahead of time (defaulting to
# off) and the one the actual alert updates are the same entity.
_EQUIPMENT_TYPE_TO_ALERT_NUMBER = {
    "hvac": 3140,
    "furnaceFilter": 3130,
    "humidifierFilter": 3131,
    "dehumidifierFilter": 3133,
    "ventilator": 3132,
    "ac": 3136,
    "airFilter": 3137,
    "airCleaner": 3138,
    "uvLamp": 3135,
}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        _LOGGER.error("Missing required environment variable: %s", name)
        sys.exit(1)
    return value


def _load_token(token_file_path: str) -> str | None:
    if os.path.exists(token_file_path):
        with open(token_file_path, encoding="utf-8") as f:
            return json.load(f).get("refresh_token")
    return None


def _save_token(token_file_path: str, refresh_token: str) -> None:
    os.makedirs(os.path.dirname(token_file_path), exist_ok=True)
    with open(token_file_path, "w", encoding="utf-8") as f:
        json.dump({"refresh_token": refresh_token}, f)


def _bootstrap_auth(client: EcobeeClient, token_file_path: str) -> None:
    """Blocking PIN authorization walkthrough for first run. No silent fallback:
    if authorization doesn't complete in time, the process exits non-zero."""
    registration = client.request_pin()
    _LOGGER.info("=" * 60)
    _LOGGER.info("ecobee authorization required")
    _LOGGER.info("Go to ecobee.com -> My Apps -> Add Application")
    _LOGGER.info("Enter this PIN: %s", registration.ecobee_pin)
    _LOGGER.info("Waiting for you to authorize (checking every %ss)...", registration.interval_seconds)
    _LOGGER.info("=" * 60)

    deadline = time.time() + registration.expires_in_seconds
    while time.time() < deadline:
        time.sleep(registration.interval_seconds)
        try:
            client.complete_pin_auth(registration.auth_code)
        except EcobeeAuthPending:
            continue
        except EcobeeApiError:
            _LOGGER.exception("Authorization failed")
            sys.exit(1)
        else:
            _save_token(token_file_path, client.refresh_token)
            _LOGGER.info("Authorized. Refresh token saved to %s", token_file_path)
            return

    _LOGGER.error("PIN expired before authorization completed. Restart to try again.")
    sys.exit(1)


def main() -> None:
    api_key = _require_env("ECOBEE_API_KEY")
    mqtt_host = _require_env("MQTT_HOST")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_username = os.environ.get("MQTT_USERNAME")
    mqtt_password = os.environ.get("MQTT_PASSWORD")
    mqtt_discovery_prefix = os.environ.get("MQTT_DISCOVERY_PREFIX", "homeassistant")
    mqtt_topic_prefix = os.environ.get("MQTT_TOPIC_PREFIX", "ecobeeAlerts2mqtt")
    poll_interval_seconds = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
    token_file_path = os.environ.get("TOKEN_FILE_PATH", "/data/ecobee_token.json")

    refresh_token = os.environ.get("ECOBEE_REFRESH_TOKEN") or _load_token(token_file_path)
    client = EcobeeClient(api_key, refresh_token)

    if not refresh_token:
        _bootstrap_auth(client, token_file_path)

    mqtt_pub = MqttPublisher(
        host=mqtt_host,
        port=mqtt_port,
        username=mqtt_username,
        password=mqtt_password,
        discovery_prefix=mqtt_discovery_prefix,
        topic_prefix=mqtt_topic_prefix,
    )

    known_object_ids: set[str] = set()

    _LOGGER.info("Polling ecobee every %ss", poll_interval_seconds)
    while True:
        try:
            thermostats = client.get_thermostats_with_alerts()
        except EcobeeApiError:
            _LOGGER.exception("Poll failed, will retry next interval")
            time.sleep(poll_interval_seconds)
            continue

        # Persist a rotated refresh token immediately; ecobee invalidates the
        # previous one on every use.
        if client.refresh_token != refresh_token:
            refresh_token = client.refresh_token
            _save_token(token_file_path, refresh_token)

        current_object_ids: set[str] = set()

        for thermostat in thermostats:
            thermostat_id = thermostat["identifier"]
            thermostat_name = thermostat.get("name", thermostat_id)

            # Figure out which reminders are actually firing right now, keyed
            # the same way as the equipment loop below, so each object_id is
            # published exactly once per cycle -- either "on" from an actual
            # alert or "off" as a baseline, never both (publishing "off" then
            # "on" for the same firing reminder every cycle would flip the
            # entity and re-trigger state-change automations on every poll).
            firing_alerts_by_key: dict[str, dict] = {}
            for alert in thermostat.get("alerts", []):
                ack_ref = alert.get("acknowledgeRef")
                if not ack_ref:
                    continue
                alert_number = alert.get("alertNumber")
                reminder_key = str(alert_number) if alert_number is not None else alert.get("text", "")
                firing_alerts_by_key[reminder_key] = alert

            # Pre-create an entity (defaulting to off) for every enabled
            # configured reminder that isn't currently firing, so there's
            # something stable to build a notification against before it's
            # ever due.
            equipment_settings = thermostat.get("notificationSettings", {}).get("equipment", [])
            for equipment in equipment_settings:
                if not equipment.get("enabled"):
                    continue
                alert_number = _EQUIPMENT_TYPE_TO_ALERT_NUMBER.get(equipment.get("type"))
                if alert_number is None:
                    continue
                reminder_key = str(alert_number)
                if reminder_key in firing_alerts_by_key:
                    continue
                name = _REMINDER_NAMES.get(alert_number, equipment.get("type"))
                object_id = mqtt_pub.publish_discovery(thermostat_id, thermostat_name, reminder_key, name)
                mqtt_pub.publish_state(
                    object_id,
                    is_on=False,
                    attributes={
                        "alert_number": alert_number,
                        "remind_me_date": equipment.get("remindMeDate"),
                        "filter_last_changed": equipment.get("filterLastChanged"),
                    },
                )
                current_object_ids.add(object_id)

            for reminder_key, alert in firing_alerts_by_key.items():
                ack_ref = alert.get("acknowledgeRef")
                alert_number = alert.get("alertNumber")
                name = _REMINDER_NAMES.get(alert_number, alert.get("text", "Ecobee Alert"))
                object_id = mqtt_pub.publish_discovery(thermostat_id, thermostat_name, reminder_key, name)
                mqtt_pub.publish_state(
                    object_id,
                    is_on=True,
                    attributes={
                        "date": alert.get("date"),
                        "time": alert.get("time"),
                        "text": alert.get("text"),
                        "alert_type": alert.get("alertType"),
                        "alert_number": alert_number,
                        "severity": alert.get("severity"),
                        "acknowledge_ref": ack_ref,
                    },
                )
                current_object_ids.add(object_id)

        # Anything we published last cycle but didn't see this cycle has
        # cleared (acknowledged on the thermostat, or ecobee cleared it).
        for stale_object_id in known_object_ids - current_object_ids:
            mqtt_pub.publish_state(stale_object_id, is_on=False, attributes={})

        known_object_ids = current_object_ids
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    main()
