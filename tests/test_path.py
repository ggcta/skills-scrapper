# Path.consolidate_activities: the contents menu decides, ld+json only helps.
from bs4 import BeautifulSoup

from skills_scraper.model.path import Path

MENU = """<html>
<ql-contents-menu modules='[{"steps":[{"activities":[
 {"title":"A Tour of Google Cloud Hands-on Labs","href":"/focuses/2794?parent=catalog&path=16"},
 {"title":"Big Data Course","href":"/paths/16/course_templates/72"},
 {"title":"Resumed Course","href":"/paths/16/course_sessions/999/video/1"}]}]}]'></ql-contents-menu>
</html>"""

LD_JSON = {
    "name": "Data Engineer",
    "description": "d",
    "hasPart": [
        {"name": "A Tour of Google Cloud Hands-on Labs", "url": "https://www.skills.google/course_templates/1281"},
        {"name": "Resumed Course", "url": "https://www.skills.google/course_templates/55"},
    ],
}


def test_menu_tells_labs_from_courses():
    activities = Path(id="16").consolidate_activities(LD_JSON, BeautifulSoup(MENU, "html.parser"))
    assert list(activities) == ["2794", "72", "55"], "menu order, lab id from /focuses, not 1281"
    assert activities["2794"]["type"] == "lab"
    assert activities["2794"]["url"].startswith("https://www.skills.google/focuses/2794")
    assert activities["72"]["type"] == "Course"
    assert activities["55"]["url"] == "https://www.skills.google/course_templates/55"


def test_without_menu_falls_back_to_ld_json():
    activities = Path(id="16").consolidate_activities(LD_JSON, BeautifulSoup("<html></html>", "html.parser"))
    assert list(activities) == ["1281", "55"]


def test_path_markdown_links_labs_to_labs_folder():
    path = Path(id="16", name="Data Engineer", description="d")
    path.courses = Path(id="16").consolidate_activities(LD_JSON, BeautifulSoup(MENU, "html.parser"))
    markdown = path.generate_markdown()
    assert "(../labs/A-Tour-of-Google-Cloud-Hands-on-Labs.md)" in markdown
    assert "(../courses/Big-Data-Course.md)" in markdown
