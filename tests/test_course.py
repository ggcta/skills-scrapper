# Parsers and renderer of Course, offline, on the recorded pages.
from skills_scraper.model.course import Course


def test_metadata_from_ld_json(course_72_html):
    course = Course(id="72")
    assert course.extract_course_metadata(course_72_html, force=True) is True
    assert course.id == "72"
    assert course.name
    assert course.datePublished
    assert isinstance(course.topics, list) and course.topics
    assert isinstance(course.objectives, list)


def test_metadata_skips_when_date_published_unchanged(course_72_html):
    course = Course(id="72")
    assert course.extract_course_metadata(course_72_html, force=True)
    again = Course(id="72", datePublished=course.datePublished)
    assert again.extract_course_metadata(course_72_html) is False


def test_outline_from_contents_menu(course_72_html):
    course = Course(id="72")
    assert course.extract_course_outline(course_72_html) is True
    assert course.modules
    module = course.modules[0]
    assert {"title", "steps"} <= set(module)
    activity = module["steps"][0]["activities"][0]
    assert {"id", "type", "title", "href"} <= set(activity)


def test_markdown_renders_every_activity_kind(course_72_modules):
    course = Course(id="72", name="PDE", description="desc")
    course.modules = course_72_modules
    kinds = {a["type"] for m in course.modules for s in m["steps"] for a in s["activities"]}
    assert "badge" in kinds, "the fixture carries a kind the tool has no handler for"

    markdown = course.generate_markdown(toc_only=True)

    assert markdown.startswith("---\n")
    assert "# [PDE](https://www.skills.google/course_templates/72)" in markdown
    for module in course.modules:
        assert f"## {module['title'].strip()}" in markdown
    assert "### Badge - " in markdown
    assert "(No transcript available)" not in markdown, "toc_only must drop transcripts"


def test_markdown_lists_use_dashes(course_72_modules):
    course = Course(id="72", name="PDE", description="desc", objectives=["Learn a thing"])
    course.modules = course_72_modules
    markdown = course.generate_markdown()
    assert "- Learn a thing" in markdown
    assert "\n* " not in markdown
