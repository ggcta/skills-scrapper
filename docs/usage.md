# Usage

All commands run as:

```bash
uv run app/main.py <command> [options]
```

There are two ways to drive the app — a **command line** and an **interactive
menu**. They share the same underlying logic, so anything you can do in one you
can do in the other.

## First run

Most pages require you to be signed in, and no data ships with the app. So:

```bash
# 1. Sign in (a browser opens; log in, then press Enter)
uv run app/main.py login          # add -B for the partner portal

# 2. Build the catalog of paths (only needed if you want to browse/list paths)
uv run app/main.py list --reload --paths
```

You can skip step 2 if you already know the ID (or URL) of what you want and
just `fetch` it directly.

## Portals

Every data command works against one portal at a time. Default is **public**.

| Flag | Portal |
|---|---|
| `-A` / `-a` / `--public` | Public — `www.skills.google` (default) |
| `-B` / `-b` / `--partner` | Partner — `partner.skills.google` |
| `--portal <name>` / `-P` | Explicit name (advanced) |

Or paste a **full URL** in place of an ID and the portal is detected from the
host automatically.

## Commands

### `fetch` (alias `f`) — scrape content

```bash
uv run app/main.py fetch -p <id...>   # path(s)  → cascades to courses → labs
uv run app/main.py fetch -c <id...>   # course(s) → cascades to their labs
uv run app/main.py fetch -l <id...>   # lab(s)
```

Options:

| Option | Effect |
|---|---|
| `--force` / `-f` | Re-scrape even if already stored (applies down the tree). |
| `--toc` / `-t` | Table of contents / structure only. |
| `--no-transcript` | Keep everything except video transcripts. |
| `--no-md` | Update the database only; don't write Markdown. |
| `--headless` | Run Chrome without a visible window. |
| portal flags | `-A` / `-B` / `--portal` as above. |

Examples:

```bash
uv run app/main.py fetch -p 16                 # public path + everything under it
uv run app/main.py fetch -c 53 1145 --toc      # two courses, outline only
uv run app/main.py fetch -B -p 4343            # a partner path
uv run app/main.py fetch -c https://partner.skills.google/course_templates/35
```

#### Bulk fetch everything — `fetch --all`

A power-user option (hidden from `--help`, but fully supported) refreshes the
catalog from the site, then scrapes every item it finds. `--all` takes an
optional kind — `paths` (the default), `courses`, `labs`, or `all`:

```bash
uv run app/main.py fetch --all              # every public path (cascades to its courses + labs)
uv run app/main.py fetch --all -B           # every partner path
uv run app/main.py fetch --all courses      # every standalone course
uv run app/main.py fetch --all all --headless   # paths + courses + labs, no window
skills-scraper fetch --all                             # same, via the Go binary
```

Because paths cascade to their courses and labs, plain `fetch --all` already
pulls almost the entire portal; `--all all` additionally sweeps any standalone
courses/labs not reachable from a path. Combine with `-f`/`--force` to re-scrape
items you already have. This can take a long time and drive a lot of traffic —
prefer `--headless` and expect it to run for a while.

### `list` (alias `l`) — see what you have

```bash
uv run app/main.py list --paths       # default
uv run app/main.py list --courses
uv run app/main.py list --labs
```

- `--reload` / `-r` — refresh the list from the website first (opens a browser).
- `--id` / `-i` or `--name` / `-n` — sort order.
- `--headless` — reload without a visible browser window.
- portal flags — e.g. `list -B --courses`.

Each row shows its **fetch status**: a green `✓ <date>` when the item has been
scraped (the date is when it was last fetched), or a dim `— not fetched` when
it's only a catalog entry you haven't downloaded yet. `search` shows the same
marker. In the GUI, the Browse and Search tabs render this as a status badge and
add a **Status** sort (fetched-first, newest first) plus an "N fetched" count.

### `search` (alias `s`) — query the local database

```bash
uv run app/main.py search "kubernetes"
uv run app/main.py search "networking" --course      # limit to courses
uv run app/main.py search "gke" --field title        # limit to one field
```

Add a portal flag to search the partner database instead.

### `md` — (re)generate Markdown from stored data

No browser needed; works offline from what you've already fetched.

```bash
uv run app/main.py md -c 53,1145        # comma-separated IDs
uv run app/main.py md -p 16 --toc
uv run app/main.py md -l 104653
```

### `interactive` (alias `i`) — guided menu

```bash
uv run app/main.py interactive
```

```
AVAILABLE OPTIONS  (working portal: public)
  1. f: FETCH content (path / course / lab)
  2. l: LIST paths / courses / labs
  3. s: SEARCH the database
  4. m: GENERATE markdown
  5. w: OPEN a reusable browser (fetches reuse it)
  6. p: SWITCH portal (public / partner)
  0. q: QUIT
```

The working portal is shown in the header and persists for the session; switch
it with option **6**. Fetch prompts also let a pasted URL override the portal
per item.

### `login` — sign in to a portal

```bash
uv run app/main.py login          # public
uv run app/main.py login -B       # partner
```

Opens a browser at the portal's home page. Log in, then press **Enter** to close
it. Your session is saved to the reusable Chrome profile, so later fetches are
already authenticated. Run it again whenever pages start returning empty.

### `pdf` — generate a styled PDF

Implemented in the Go core (and the GUI's **Generate PDF** button). Python parity
is on the backlog.

```bash
skills-scraper pdf -c 159 -B                 # one course (partner)
skills-scraper pdf -p 91                       # a path + all its courses & labs
skills-scraper pdf -c 159 --theme humanist
skills-scraper pdf --list-themes               # available themes
skills-scraper pdf --doctor                    # is this machine set up to render?
```

Renders a stored item's Markdown to a PDF next to its vault `.md`, via Typst
(using Pandoc: `pandoc --pdf-engine=typst`). A path **cascades** to its courses
and labs — one command, the whole set. If an item isn't fully fetched you get a
warning (the PDF may be missing sections); `--force` silences it.

Themes live in `theme/<name>/` (a `theme.yaml` manifest + a Typst
`template.typ`). The default is **humanist** — Inter headings, Lora body, a
terracotta accent, a title band, contents, and running headers. Pick one with
`--theme <name>`.

#### What rendering needs on your machine

Neither the CLI nor the app bundles the render pipeline, so a fresh machine needs
two tools on your PATH plus the theme's fonts. Run `skills-scraper pdf --doctor`
(or, in the GUI, **Settings → Check PDF setup**) for a checklist of what's
missing with the exact command for your OS; it's also run automatically before
each render.

| | macOS | Windows | Linux |
| --- | --- | --- | --- |
| pandoc | `brew install pandoc` | `winget install --id JohnMacFarlane.Pandoc` | `sudo apt install pandoc` |
| typst | `brew install typst` | `winget install --id Typst.Typst` | `cargo install --locked typst-cli` |
| fonts → | `~/Library/Fonts` | `%LOCALAPPDATA%\Microsoft\Windows\Fonts` | `~/.local/share/fonts` |

A theme declares the font families it needs in its `theme.yaml` `fonts:` list —
humanist uses **Inter**, **Lora**, **Fira Code**, and **Noto Sans**, all free
under the SIL Open Font License and downloadable from
[Google Fonts](https://fonts.google.com). Fonts matter more than they look:
Typst only *warns* about a family it can't find and still exits successfully, so
a missing font gives you a PDF that renders fine but silently uses substitutes.
Missing tools stop a render; missing fonts only warn.

In the GUI, open the **Browse** tab, click an item to select it, pick a theme,
and click **Generate PDF** (you're warned first if it isn't fully fetched). If
the toolchain is incomplete you get the setup checklist instead of an error; if
only fonts are missing you can still choose **Generate anyway**.

### `db` (alias `mgmt`) — manage stored items

Implemented in the Go core (and the GUI's Browse-tab right-click menu). Review,
delete, or rename items in the database — handy for bogus or mis-keyed entries
(e.g. an id that isn't a real path, saved as a data-less stub).

```bash
skills-scraper db list -A -p              # review paths; flags "⚠ stub (no data)"
skills-scraper db show -A -p 264          # inspect one item and its files
skills-scraper db rm -A -p 60,264 --yes   # delete: ledger row + JSON + vault .md/.pdf
skills-scraper db rm -A -c 159 --materials  # also remove materials/courses/159/
skills-scraper db set -A -c 159 --name "New title"   # rename
```

`db rm` prompts for confirmation unless `--yes`/`-y` is given, and leaves the
shared `materials/<type>/<id>/` alone unless `--materials` is passed. `db set`
renames the ledger row and per-item JSON, dropping the now-stale `.md`/`.pdf`
(regenerate with `md`/`pdf`). In the GUI, right-click a Browse row → **Rename…**
or **Delete**. Python parity is on the backlog.

### `browser` (aliases `b`, `w`) — reusable browser

```bash
uv run app/main.py browser          # public
uv run app/main.py browser -B       # partner
```

Opens a Chrome window (with the shared profile) you can sign in to and browse in,
and keeps it open until you press **Enter** (or it receives Ctrl+C / SIGTERM).
While it is open, `fetch` and `list -r` **attach to this same window** instead of
launching their own browser — so the site never re-challenges for sign-in between
tasks, and you don't need `--signin` on each fetch. Closing it (Enter) shuts the
browser down and stops the reuse.

`browser-status` prints `none` / `alive` / `stale` — whether a reusable browser
is currently advertised and reachable (used by the GUI).

## Where output goes

| Path | Contents |
|---|---|
| `csbmdvault/<portal>/{courses,paths,labs}/*.md` | Your Markdown notes. Open the vault in Obsidian. |
| `csbmdvault/materials/courses/<id>/…` | Downloaded documents (shared across portals). |
| `data/<portal>/database.json` | The TinyDB database. |
| `data/<portal>/{courses,paths,labs}/*.json` | Per-item JSON backups. |

These locations are configurable. For the CLI / Python tools, set them in
`config.yaml` (see `config.example.yaml`) or via the `CSB_DATA`, `CSB_VAULT`,
`CSB_LOG_DIR`, `CSB_PROFILE_DIR`, and `CSB_THEME_DIR` env vars. In the desktop
app, use the **⚙ Settings** dialog (topbar) — it writes the same choices and
overrides `config.yaml`.
