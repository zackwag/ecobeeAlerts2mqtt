# ecobeeAlerts2mqtt

Polls ecobee for thermostat alerts/reminders (filter change, maintenance, etc.) and publishes them to Home Assistant via MQTT discovery — one `binary_sensor` per reminder, `on` while pending, `off` once cleared.

Acknowledgement happens on the thermostat itself (or the ecobee app); the next poll picks up that the alert cleared and flips the sensor off.

## Env vars

| Variable | Required | Default | Notes |
|---|---|---|---|
| `ECOBEE_API_KEY` | yes | | From your ecobee developer app (scope: Smart Read) |
| `ECOBEE_REFRESH_TOKEN` | no | | Skip first-run PIN auth if you already have one |
| `MQTT_DISCOVERY_PREFIX` | no | `homeassistant` | |
| `MQTT_HOST` | yes | | |
| `MQTT_PASSWORD` | no | | |
| `MQTT_PORT` | no | `1883` | |
| `MQTT_TOPIC_PREFIX` | no | `ecobeeAlerts2mqtt` | |
| `MQTT_USERNAME` | no | | |
| `POLL_INTERVAL_SECONDS` | no | `300` | |
| `TOKEN_FILE_PATH` | no | `/data/ecobee_token.json` | Mount `/data` as a volume so the refresh token survives restarts |

## First run

1. Register a developer app at ecobee.com → Developer → Create New:
   Authorization Method **ecobee PIN**, scope **Smart Read**. Copy the API key.
2. Run the container with `ECOBEE_API_KEY` and `MQTT_HOST` set, `/data` mounted.
3. `docker logs -f` it — it'll print a PIN and wait (blocking, checking on the interval ecobee gives it). Go to ecobee.com → My Apps → Add Application, enter the PIN.
4. Once authorized it saves the refresh token to `/data/ecobee_token.json` and starts polling. Restarts after that are silent — no re-auth needed unless you revoke access on ecobee's side (refresh token rotates on every use and gets re-saved automatically).

## Compose example

```yaml
services:
  ecobee-alerts-2-mqtt:
    image: zackwag/ecobeealerts2mqtt
    restart: unless-stopped
    environment:
      ECOBEE_API_KEY: "[[ECOBEE_API_KEY]]"
      MQTT_HOST: mqtt.internal
      MQTT_USERNAME: "[[MQTT_USERNAME]]"
      MQTT_PASSWORD: "[[MQTT_PASSWORD]]"
    volumes:
      - ./data:/data
```

## Releasing

Push a version tag to `main` (e.g. `git tag v1.2.0 && git push origin v1.2.0`). That triggers `.github/workflows/release.yml`, which:

1. Creates a GitHub Release for the tag with auto-generated notes.
2. Builds the Docker image and pushes `zackwag/ecobeealerts2mqtt:1.2.0` and `:latest` to Docker Hub.

One-time setup: add `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker Hub access token, not your password) as repo secrets under Settings → Secrets and variables → Actions.

## Notes

- **Stable entities**: ecobee issues a new `acknowledgeRef` each time it raises the same reminder again (e.g. the next filter change), so the `binary_sensor` object_id is derived from the alert's type + text instead, not the ref. That keeps one entity per distinct reminder that just flips `on`/`off` across recurrences, instead of spawning a new entity each time -- easier to build a persistent automation/notification against. `acknowledgeRef` is still published as an attribute for reference.
- **Restart gap**: if the service is down when a reminder clears, that reminder's entity keeps its last retained state (`on`) until the service is back up and confirms it's gone from ecobee's alerts. Not a correctness issue, just a delay bounded by your downtime.
- **Rate limits**: ecobee's API has hourly call limits per API key; the 5-minute default poll is comfortably under that for one API key.
