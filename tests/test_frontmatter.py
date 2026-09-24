# The front matter must be valid YAML whatever the title, and an OKF superset.
import yaml

from skills_scraper.model.course import Course
from skills_scraper.model.lab import Lab
from skills_scraper.model.path import Path


def parse(front_matter: str) -> dict:
    body = front_matter.strip().strip("-").strip()
    return yaml.safe_load(body)


def test_quotes_in_title_stay_valid_yaml():
    course = Course(id="892", name="Google's \"AI\" course: it's here", description="Use it. Then more.",
                    datePublished="2023-11-21", topics=["Vertex AI", "Dialogflow CX"])
    data = parse(course.generate_front_matter())
    assert data["title"] == "Google's \"AI\" course: it's here"
    assert data["description"] == "Use it."
    assert data["tags"] == ["Vertex AI", "Dialogflow CX"]


def test_okf_keys_and_legacy_aliases():
    course = Course(id="892", name="C", description="d", datePublished="2023-11-21", topics=["T"])
    data = parse(course.generate_front_matter())
    for key in ("type", "title", "description", "resource", "tags", "sources", "generated"):
        assert key in data, key
    assert data["type"] == "Course"
    assert data["resource"] == data["url"] == "https://www.skills.google/course_templates/892"
    assert data["sources"][0]["last_modified"] == data["date_published"]
    assert data["generated"]["by"].startswith("skills-scraper/")
    assert data["topics"] == data["tags"]
    assert data["id"] == "892"


def test_every_entity_type_has_a_type_key():
    for entity in (Path(id="1", name="P"), Course(id="2", name="C"), Lab(id="3", name="L")):
        data = parse(entity.generate_front_matter())
        assert data["type"] == entity.type
        assert "date_published" not in data or data["date_published"]
