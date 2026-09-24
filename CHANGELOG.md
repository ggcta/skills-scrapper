# Changelog

Python line of the scraper, on top of v2.0.0. Tags carry the `py/` prefix because the main line already used `v2.1.0` and up for the Go and Tauri work.

## py/v2.1.0 (unreleased)

- The site requires a sign-in for course pages: every page is read through one signed-in Chrome session (`services/browser.py`), `requests` only downloads documents.
- Catalog lists are read through the browser too (the endpoint answers 403 to bare requests); one `Collection.fetch_catalog` replaces three copies.
- `html_bundle` activities are handled; unknown kinds (`badge`, `credential`) are kept in the JSON instead of dropped.
- Path membership comes from `ql-contents-menu`, which tells labs from courses; `ld+json` only enriches.
- Front matter is valid YAML (quotes in titles) and an Open Knowledge Format v0.2 superset; `title` replaces `name`.
- No database: JSON files are the source of truth, `data/index.json` is a rebuildable ledger (`reindex`), every file is written atomically.
- Downloaded materials land in `<vault>/materials/courses/<id>/`, links are relative to the vault.
- `fetch -p ID --cascade`, `--headless`, `md --lab` no longer crashes.
- Chrome flags: `--headless=new`, no automation banner, profile reused by default; Chrome and Edge share one flag list.
- Offline tests on the recorded pages (`uv run pytest`).

## py/v2.0.1

- Packaged with uv: `pyproject.toml`, `uv.lock`, `src/skills_scraper/`, console scripts `skills-scraper` and `skills-scraper-tui`.
- `config.yaml` (data) replaces `settings.py` (code); `CSB_*` environment variables override single keys; no personal paths in the repo.
- Flask web UI, `data_management.py`, `tasks/` and the dead `ql-course-outline` fallback removed. Recorded pages moved to `tests/fixtures/`.

## v2.0.0 (2026-02-18)

Reference point: CLI, interactive mode, Flask web UI, TinyDB plus per-item JSON, requests plus Selenium.
