# Google Skills Scraper

---

MAINTAINER IS NEEDED! Drop me an Issue or PR if you're interested in helping out.

---

<!--TODO: The interactive version is outdated, need to update this photo.-->

![Welcome Screen](docs/assets/welcome-screen.png)

---

Turn [Google Skills](https://www.skills.google) courses, learning paths, and labs into clean, well-structured **Markdown files** you can drop straight into Obsidian (or any Markdown-based personal knowledge base).

---

Update:

> **v2.2.0 — renamed to Google Skills Scraper.** Formerly "Cloud Skills Boost / CSB Studio"; the site itself is now [Google Skills](https://www.skills.google). The CLI binary is `skills-scraper.bin` (legacy `csb.bin`/`csb` still resolve) and the desktop app is **Google Skills Scraper**. Existing `data/` and `csbmdvault/` folders are unchanged — no migration needed.

> New here and not a developer? Jump to the **[Getting Started guide](docs/getting-started.md)** — it walks you through everything step by step.

## A Quick Example: PKB with Obsidian

- Check out the sample folder for real files:
  - [Google-Cloud-Applied-AI-Summit-Learning-Path](./docs/samples/output/paths/Google-Cloud-Applied-AI-Summit-Learning-Path.md).
  - [Conversational-AI-on-Vertex-AI-and-Dialogflow-CX.md](./docs/samples/output/courses/Conversational-AI-on-Vertex-AI-and-Dialogflow-CX.md)

File view, graph view, and the script in action:

![Obsidian File View](docs/assets/obsidian-files.png)

![Obsidian Graph View](docs/assets/obsidian-graph.png)

![The script in action](docs/assets/script-in-action.png)

## What it does

- Scrapes **paths → courses → labs** and writes one Markdown file per item,
  with front-matter (id, title, url, topics, scraped date), a table of
  contents, video transcripts, quizzes, and links to downloaded documents.
- Fetching a **path cascades down the whole tree**: it pulls every course in
  the path and every lab in those courses, inheriting your options as it goes.
- Supports **both portals**:
  - **Public** — `https://www.skills.google` (default)
  - **Partner** — `https://partner.skills.google`

  The same content can have *different IDs* on each portal, so each portal keeps
  its own scoped storage and can never overwrite the other.
- Stores everything locally in a **TinyDB** database plus per-item JSON backups,
  so you can `list`, `search`, and re-generate Markdown offline.
- Ships a **command-line interface** and a friendly **interactive menu** — they
  share the exact same logic under the hood.

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — the package/venv manager used to run
  the app (`uv run …` handles the virtual environment and dependencies for you).
- **Google Chrome** — the scraper drives a real Chrome browser via Selenium.
- A **Google Skills account** — most course/lab pages require you to
  be signed in.
- *For PDF export only:* **pandoc** + **typst** on your PATH, and the theme's
  fonts installed. Run `skills-scraper pdf --doctor` (or **Settings → Check PDF
  setup** in the app) for a per-OS checklist of anything missing.

See **[docs/installation.md](docs/installation.md)** for setup details.

## Quick start

```bash
# 1. Install dependencies (creates the virtualenv automatically)
uv sync

# 2. Sign in once — a browser opens; log in, then press Enter to close it.
#    Your session is saved to a reusable browser profile.
uv run app/main.py login            # public portal
uv run app/main.py login -B         # partner portal

# 3. Build the catalog of paths (first run only)
uv run app/main.py list --reload --paths

# 4. Fetch a path and everything under it → Markdown
uv run app/main.py fetch -p 16

# 5. Open the generated Markdown in Obsidian (see "Where files go" below)
```

Prefer menus over flags? Just run the interactive mode:

```bash
uv run app/main.py interactive
```

## Command reference

Every command runs as `uv run app/main.py <command> [options]`.

| Command | Aliases | What it does |
|---|---|---|
| `list` | `l` | List stored paths / courses / labs. Add `--reload/-r` to refresh from the website first. |
| `fetch` | `f` | Scrape content into Markdown + JSON. |
| `interactive` | `i` | Launch the guided menu. |
| `md` | | Re-generate Markdown from already-stored data (no browser needed). |
| `search` | `s` | Search the local database. |
| `browser` | `b`, `w` | Open a browser for manual login/debugging. |

### Choosing a portal

Every data command accepts a portal selector (default = **public**):

| Flag | Portal |
|---|---|
| `-A` / `-a` / `--public` | Public — `www.skills.google` (default) |
| `-B` / `-b` / `--partner` | Partner — `partner.skills.google` |
| `--portal <name>` / `-P` | Explicit name (advanced) |

You can also just paste a **full URL** instead of an ID — the portal is inferred
from the host automatically:

```bash
uv run app/main.py fetch -c https://partner.skills.google/course_templates/35
```

### `fetch` — the main workhorse

```bash
# A whole path (→ its courses → their labs)
uv run app/main.py fetch -p 16

# One or more courses
uv run app/main.py fetch -c 53 1145

# A standalone lab
uv run app/main.py fetch -l 104653

# A partner path
uv run app/main.py fetch -B -p 4343
```

Useful `fetch` options:

| Option | Effect |
|---|---|
| `--force` / `-f` | Re-scrape even if the item is already stored (cascades to children). |
| `--toc` / `-t` | Table of contents / structure only — skip transcripts and details. |
| `--no-transcript` | Keep everything but video transcripts. |
| `--no-md` | Update the database only; don't write Markdown. |
| `--headless` | Run Chrome without a visible window. |

### Other examples

```bash
# List partner courses, refreshing from the website first
uv run app/main.py list -B --courses --reload

# Search the public database for "kubernetes"
uv run app/main.py search kubernetes

# Re-generate Markdown for courses 53 and 1145 (offline)
uv run app/main.py md -c 53,1145
```

## Where your files go

```
data/                         # local database + JSON backups (per portal)
  public/ | partner/
    database.json
    courses/ | paths/ | labs/

csbmdvault/                   # your Markdown vault → open this in Obsidian
  public/ | partner/
    courses/ | paths/ | labs/   # one .md file per item
  materials/                    # downloaded documents, shared across portals
    courses/<id>/…
```

Point Obsidian at the `csbmdvault/` folder to browse everything as a graph.

## Configuration (optional)

Don't like the default locations? Copy **`config.example.yaml`** to
**`config.yaml`** (or `config/config.yaml`) and set only the keys you care
about — for example, point the vault straight at your Obsidian folder:

```yaml
paths:
  vault: /Users/me/Obsidian/Google Skills
portal: partner        # make partner the default portal
```

Both the Python app and the Go binary read the same file. Precedence is
**environment variable → `config.yaml` → built-in default**, and CLI flags still
win over everything. Every key is optional; relative paths resolve against the
project root, absolute paths are used as-is. See `config.example.yaml` for the
full list (`paths.data` / `vault` / `logs` / `profile`, and `portal`) with the
matching `CSB_*` environment variables.

## Go rewrite (in progress)

A single-binary [Go reimplementation](go/README.md) lives under `go/`. It reads
and writes the same `data/` and `csbmdvault/` layout and shares the login
profile, so it runs interchangeably with this Python version. It already has full
command parity (`md`, `list`/`--reload`, `search`, `fetch -l/-c/-p`, `login`,
`interactive`), with output verified byte-for-byte against the Python build. See
[docs/rewrite-plan.md](docs/rewrite-plan.md) for the roadmap (Go CLI → Tauri GUI).

![A Simple GUI](docs/assets/gui-260710.png)

## Further reading

1. [Getting Started (non-technical walkthrough)](docs/getting-started.md)
2. [Installation](docs/installation.md)
3. [Usage](docs/usage.md)
4. [What the data files look like](docs/data.md)
5. [What the Markdown files look like](docs/output.md)
6. [Generating prompts to reformat transcripts](docs/promt-llm.md)
7. [Plan: re-implementing as a single binary (Go / Rust / Tauri)](docs/rewrite-plan.md)
8. [Contributing](CONTRIBUTING.md)

## A note on responsible use

This tool automates a signed-in browser to save content **you already have
access to** for personal offline study. Respect Google Skills's
Terms of Service, keep your fetches reasonable, and don't redistribute scraped
content.

## LICENSE

- [MIT License](./LICENSE)
