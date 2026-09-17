# AGENTS.md

## Project overview

ecobeeAlerts2mqtt polls the ecobee API for thermostat alerts/reminders (filter change, maintenance, etc.) and publishes them to Home Assistant as MQTT Discovery binary sensors. Python 3, runs as a Docker container.

## Setup

```bash
pip install -r requirements.txt
pip install pytest   # test-only dependency, not in requirements.txt
```

## Build / Run

```bash
docker build -t ecobeealerts2mqtt .
python main.py   # requires ECOBEE_API_KEY, MQTT_HOST, etc. — see README for full env var table
```

## Test

```bash
pytest
```

`test_ecobee_api.py`, `test_main.py`, `test_mqtt_publisher.py` cover the three modules with mocked HTTP/MQTT calls. Not currently run in CI — only `conventional-commits.yml` and `release.yml` exist under `.github/workflows/`.

## Repository structure

- `ecobee_api.py` — ecobee API client (PIN auth, token refresh, alerts fetch)
- `mqtt_publisher.py` — MQTT Discovery publishing
- `main.py` — polling loop that ties the two together
- `test_*.py` — pytest suite, one file per module
- `Dockerfile` — container build definition

## Commit and PR conventions

- Commit messages and PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`, `perf:`, `style:`, `revert:`), optionally with a scope, e.g. `fix(api): handle null response`.
- This repo squash-merges pull requests only; the PR title becomes the final commit message on `main`.
- A "Conventional Commits" CI check enforces this on both PR titles and direct-push commit messages.
- Branch protection on `main`: no force-pushes, no branch deletion, required status checks must pass.
