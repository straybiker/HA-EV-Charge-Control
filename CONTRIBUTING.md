# Contributing

Thank you for your help. Report bugs and ideas as [issues](https://github.com/straybiker/HA-EV-Charge-Control/issues). For a pull request, read this file first.

## Read first

- [docs/behaviour.md](docs/behaviour.md): the specification of the charging behaviour.
- [docs/engine.md](docs/engine.md): the decision engine.
- [docs/integration.md](docs/integration.md): the Home Assistant side.

## Development setup

Python 3.14 is necessary.

**Linux, macOS or CI:** the full suite.

```bash
pip install -r requirements-dev.txt
pytest -q
```

**Windows:** the Home Assistant test harness needs Linux (it imports `fcntl`). Run the engine, property and repository tests natively; `tests/ha` is skipped there.

```powershell
pip install -r requirements-dev-windows.txt
pytest -q
```

Run the full suite in Docker. All arguments go to pytest:

```powershell
.\scripts\test-ha.ps1
.\scripts\test-ha.ps1 tests/ha -x
```

**Lint and format** with the version that CI uses (pinned in the requirements files):

```bash
ruff check .
ruff format --check .
```

**hassfest** after a change to the manifest, strings, translations or icons:

```bash
docker run --rm -v "$PWD:/github/workspace" ghcr.io/home-assistant/hassfest
```

## Rules

- **The engine stays pure.** `engine/` imports nothing from `homeassistant` and takes values, not entity IDs.
- **Behaviour is specified first.** A change to what the controller does with current, phases, grid, solar, EMS, SOC or timers changes `docs/behaviour.md`, the engine and its tests together, and adds a row to the decision record. Open an issue to discuss it first.
- **Home Assistant code is async.** No blocking I/O in the event loop.
- **Translations.** `strings.json` and `translations/en.json` are identical; `translations/nl.json` has the same keys. `tests/test_translations.py` checks this.
- **Comments say why.** No changelog comments: git is the changelog.
- **No private data.** The repository is public: no secrets, `.env` files or entity IDs of real devices.
- **Docs are part of the change.** Before each commit, check `README.md`, `docs/*.md` and `CONTRIBUTING.md` against the change.

## Test report

[docs/test-report.md](docs/test-report.md) and [docs/test-report.html](docs/test-report.html) show the latest full run. Rebuild them after a change to behaviour or tests, and commit them with the change.

```powershell
python scripts/report/collect.py        # runs the suite and hassfest in Docker
python scripts/report/collect.py --ci   # or: uses the finished CI run of the pushed HEAD (needs gh)
python scripts/report/build.py
```

The YAML package column needs a checkout of [EV Load Balancer](https://github.com/straybiker/HA-load-balancer) next to this repository, as `../EV_Loadbalancer`. Without it, that column is empty.

## Releases

1. Set the same version in `custom_components/ev_charge_control/manifest.json` and `pyproject.toml` (SemVer). `tests/test_manifest.py` checks that they match.
2. Rebuild and commit the test report.
3. Publish a GitHub release with the tag `v<version>`, for example `v0.3.0`. HACS offers releases as versions; the Release workflow fails when the tag does not match the manifest.

For a test version, use a SemVer pre-release version such as `0.3.0-beta.1` and mark the GitHub release as a pre-release. HACS offers it only to users who turn on **Show beta versions** for the repository.

## Pull requests

- Branch from `main`.
- CI runs pytest, ruff, hassfest and the HACS validation. All must pass.
- Keep a pull request to one subject.
