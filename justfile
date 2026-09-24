# Google Skills Scraper: task runner. `just` lists the recipes.

default:
    @just --list

# Install Python 3.12, the deps and the two commands into .venv
sync:
    uv sync

# Run the CLI, e.g. `just run list -p` or `just run fetch -c 892 --toc`
run *ARGS:
    uv run skills-scraper {{ARGS}}

# The interactive menu
tui:
    uv run skills-scraper-tui

# Offline tests on the recorded pages
test:
    uv run pytest

# Lint
lint:
    uv run ruff check src tests

# Rebuild data/index.json from the JSON files
reindex:
    uv run skills-scraper reindex
