# Settings for the scraper, in three layers: built-in defaults, then config.yaml, then
# environment variables. config.yaml is data, so nothing personal ever lives in code.
import os
from pathlib import Path

import yaml

# Layer 1: defaults, relative to the current working directory.
DEFAULTS = {
    "paths": {
        "data": "data",                     # JSON files, one per path/course/lab
        "vault": "csbmdvault",              # Markdown output, open it in Obsidian
        "profile": ".webdriver_profiles",   # Chrome profile that keeps the sign-in
    },
    "browser": {
        "name": "chrome",                   # chrome | edge
        "headless": False,                  # a visible window is needed to sign in
    },
}

# Layer 3: environment variables that override single keys.
ENV_KEYS = {
    ("paths", "data"): "CSB_DATA",
    ("paths", "vault"): "CSB_VAULT",
    ("paths", "profile"): "CSB_PROFILE_DIR",
    ("browser", "name"): "CSB_BROWSER",
    ("browser", "headless"): "CSB_HEADLESS",
}


def find_config_file() -> Path | None:
    """
    Locate config.yaml: $CSB_CONFIG, then ./config.yaml, then ./config/config.yaml.
    """
    candidates = [os.environ.get("CSB_CONFIG"), "config.yaml", "config/config.yaml"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def load_settings() -> dict:
    """
    Merge the three layers. Relative paths in config.yaml resolve against the
    folder holding that file, so `vault: ../skills-vault` means the same thing
    no matter where the command is run from.
    """
    settings = {section: dict(values) for section, values in DEFAULTS.items()}
    base_dir = Path.cwd()

    config_file = find_config_file()
    if config_file:
        base_dir = config_file.parent
        with open(config_file, encoding="utf-8") as yamlfile:
            user = yaml.safe_load(yamlfile) or {}
        for section, values in user.items():
            if section in settings and isinstance(values, dict):
                settings[section].update(values)

    for (section, key), env_name in ENV_KEYS.items():
        if env_name in os.environ:
            settings[section][key] = os.environ[env_name]

    for key, value in settings["paths"].items():
        settings["paths"][key] = (base_dir / str(value)).resolve()

    headless = settings["browser"]["headless"]
    if isinstance(headless, str):
        settings["browser"]["headless"] = headless.strip().lower() in ("1", "true", "yes", "on")

    return settings


SETTINGS = load_settings()

# Names the rest of the package imports.
DATA_FOLDER_NAME: Path = SETTINGS["paths"]["data"]
OUTPUT_FOLDER_NAME: Path = SETTINGS["paths"]["vault"]
WEBDRIVER_PROFILE_FOLDER_NAME: Path = SETTINGS["paths"]["profile"]
WEBDRIVER_BROWSER: str = str(SETTINGS["browser"]["name"])
WEBDRIVER_OPTIONS_HEADLESS: bool = bool(SETTINGS["browser"]["headless"])

# Base URL for the Google Skills website
BASE_URL: str = "https://www.skills.google"
BASE_URL_PATHS: str = f"{BASE_URL}/paths"
API_URL_PATHS: str = f"{BASE_URL}/catalog/list?format%5B%5D=learning_plans"
API_URL_COURSES: str = f"{BASE_URL}/catalog/list?format%5B%5D=courses"
API_URL_LABS: str = f"{BASE_URL}/catalog/list?format%5B%5D=labs"
BASE_URL_LAB: str = f"{BASE_URL}/catalog_lab"
BASE_URL_COURSES: str = f"{BASE_URL}/course_templates"
BASE_URL_PARTNERS: str = "https://partner.skills.google/"

# Constants for the extraction of the course data
COURSE_CONTENTS_MENU = "ql-contents-menu"
LAB_CONTENT_OUTLINE = "ul.lab-content__outline"
LAB_REVIEW_LAB_ID = "#lab_review_lab_id"
LAB_TITLE = "ql-title-medium"
LD_JSON = "script[type='application/ld+json']"
LINK_URL_A_TAG = "ql-card.document-link a"
META_DESCRIPTION = "meta[name='description']"
PATH_CARDS = "ql-activity-card"
QL_IFRAME = "ql-iframe"
QL_QUIZ = "ql-quiz"
QL_YOUTUBE_VIDEO = "ql-youtube-video"
QUIZ_ITEMS = "quizItems"
QUIZ_VERSION = "quizVersion"
XPATH_QUIZ = "//ql-quiz"
XPATH_START_BUTTON = "//a[@class='start-button button button--positive']"
