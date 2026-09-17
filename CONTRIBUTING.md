# Contributing to ecobeeAlerts2mqtt

Thanks for considering a contribution to this ecobee alerts/reminders → Home Assistant MQTT bridge.

## Getting started

```bash
git clone https://github.com/zackwag/ecobeeAlerts2mqtt.git
cd ecobeeAlerts2mqtt
pip install -r requirements.txt
pip install pytest
```

## Development

```bash
pytest              # run the test suite
python main.py       # run the bridge directly (see README for required env vars)
```

There's no CI test workflow yet — `pytest` currently only runs locally.

## Commit messages and pull requests

This repo uses [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, etc.). Pull requests are squash-merged, and the **PR title** becomes the commit on `main` — so PR titles must follow this format. This is enforced automatically by the "Conventional Commits" check.

Direct pushes to `main` are allowed but must also use a Conventional Commits-formatted commit message (validated by the same check).

## Opening a pull request

1. Fork the repo and create a branch off `main`.
2. Make your changes.
3. Open a pull request with a Conventional Commits-formatted title.
4. Wait for CI to pass — required checks must be green before merge.

## Reporting issues

Use [GitHub Issues](../../issues) for bugs and feature requests.
