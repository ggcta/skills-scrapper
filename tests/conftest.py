import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

FIXTURES = Path(__file__).parent / "fixtures" / "google_skills"


@pytest.fixture
def course_72_html():
    """The recorded course template page for course 72."""
    return BeautifulSoup((FIXTURES / "course-72.html").read_text(encoding="utf-8"), "html.parser")


@pytest.fixture
def course_72_modules():
    """The recorded outline (ql-contents-menu modules) of course 72."""
    return json.loads((FIXTURES / "course-72-modules.json").read_text(encoding="utf-8"))
