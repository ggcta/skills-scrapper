# Google Skills Scraper

A small command-line tool that turns [Google Skills](https://www.skills.google) learning paths, courses and labs into JSON files and an [Obsidian](https://obsidian.md)-ready Markdown vault. One entity, one file; no database, no server, no GUI. Two ways in: a CLI for scripting and an interactive terminal mode for browsing.

![Graph view of a vault built with this tool](docs/assets/obsidian-graph.png)

## Why

skills.google shows one page at a time. A vault of linked Markdown answers the questions the site cannot: which paths contain this course, how much two paths overlap, which transcript mentions Vertex AI, and what Google changed since last time (git diff).

## Quick start

```bash
git clone https://github.com/ggcta/skills-scrapper && cd skills-scrapper
uv sync                                   # Python 3.12, deps, the two commands
cp config.example.yaml config.yaml        # optional: where data and the vault go
uv run skills-scraper list -p -r          # fetch the list of paths (opens Chrome)
uv run skills-scraper fetch -p 280 --cascade   # a path and every course in it
uv run skills-scraper md -c 892 --toc     # regenerate one course's Markdown, offline
```

The first fetch opens Chrome on a persistent profile (`.webdriver_profiles`); sign in once when asked and the session is kept for the next runs. Everything except `fetch` and `list -r` works offline from the JSON in `data/`.

## Commands

| Command | Does |
|---|---|
| `list -p / -c / -l [-r]` | list paths, courses or labs; `-r` reloads the catalog from the site |
| `fetch -p ID... / -c ID... [--cascade] [--force] [--toc] [--no-transcript] [--no-md]` | scrape into `data/` and render Markdown |
| `md -c ID,ID / -p ID / -l ID [--toc] [--no-transcript]` | render Markdown from the JSON already fetched |
| `search QUERY [-c/-p/-l] [--field name|topics|...]` | search the downloaded data |
| `reindex` | rebuild `data/index.json` from the entity files |
| `browser` | open the signed-in browser and wait, for logging in |
| `skills-scraper-tui` | the interactive menu over the same core |

## Layout

```
data/                     one JSON per path/course/lab, plus index.json (a ledger, rebuildable)
csbmdvault/               the vault: paths/ courses/ labs/ materials/courses/<id>/ paths.md
src/skills_scraper/
  model/                  the core: Serialize -> BaseEntity -> Path, Course, Lab
                                     Serialize -> Collection -> Paths, Courses, Labs, Topics
  services/               browser.py (Selenium + sign-in), store.py (files + index)
  config.py               defaults < config.yaml < CSB_* environment
  cli.py  tui.py          the two entry points
tests/                    offline tests on recorded pages: uv run pytest
```

Front matter is a superset of Google's [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) v0.2 (`type`, `title`, `description`, `resource`, `tags`, `sources`, `generated`) plus the legacy keys existing vaults query on. See `docs/`.

## Development

```bash
uv run pytest             # offline
uv run ruff check src
```

Course content belongs to Google. Keep vaults with transcripts and materials private; share structure (`--toc --no-transcript`) if you share at all.

## History

Started late 2024 as a Cloud Skills Boost helper for personal self-enablement. `v2.0.0` (Feb 2026) had a Flask web UI and TinyDB; the main line later grew a Go core and a Tauri desktop app (`v2.2.0` to `v2.17.0`). This branch keeps the Python core, drops the web UI and the database, and updates the scraping to the site as it is today (sign-in required, `html_bundle` activities, path menus).
