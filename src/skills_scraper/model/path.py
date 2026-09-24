import json
import re
from skills_scraper.services.browser import get_page
from skills_scraper.utils.utils import util_replace_special_chars
from skills_scraper.config import BASE_URL, BASE_URL_COURSES, COURSE_CONTENTS_MENU, LD_JSON
from skills_scraper.model.base_entity import BaseEntity

# Path entity
class Path(BaseEntity):
    """
    Class representing a Path entity.
    """

    def __init__(self,
                 id: str,
                 name: str = None,
                 description: str = None,
                 datePublished: str = None,
                 courses: dict = None,
                 driver=None):
        super().__init__(id,
                         name,
                         description)
        self.datePublished = datePublished
        self.courses = courses or {}
        self.driver = driver

    # Fetch the Path data from the website
    def fetch_data(self):
        """
        Fetch Path data from the website and save it to a JSON file.
        """

        try:
            # Navigate to the path URL in the signed-in browser
            path_html = get_page(self.driver, self.url, f"path {self.id}")
            if path_html is None:
                return {}

            # Locate the <script> tag containing the JSON data
            script_element = path_html.select_one(LD_JSON)
            json_content = script_element.string

            # Parse JSON content
            path_data = json.loads(json_content)

        except Exception as error:
            print(f"fetch_data(): Unable to find LD+JSON element - {error}")
            return {}

        # Core Path details
        self.name = path_data['name'].strip()
        self.description = self.clean_text(path_data['description'])
        self.datePublished = path_data.get('datePublished', '').strip()

        # Courses (and standalone labs) of the Path
        self.courses = self.consolidate_activities(path_data, path_html)

    def consolidate_activities(self, path_data: dict, path_html) -> dict:
        """
        Build the path's activity list from two sources.

        The ld+json ``hasPart`` labels every entry ``Course`` and points a
        standalone lab at an unrelated course_templates id, so its URLs cannot
        be trusted. The page's ``ql-contents-menu`` is authoritative for order
        and kind: a top-level ``/focuses/<id>`` href is a lab, anything else is
        a course. The ld+json only supplies the course id when the menu href is
        a session deep-link, and a cleaner name.
        """
        ld_by_name: dict[str, dict] = {}
        for part in path_data.get('hasPart', []):
            name = part["name"].strip()
            ld_by_name[name.lower()] = {"id": part['url'].split('/')[-1], "name": name}

        menu = self.menu_activities(path_html)
        activities: dict[str, dict] = {}

        if not menu:
            # No contents menu (unusual): labs cannot be told apart, courses still resolve.
            for part in path_data.get('hasPart', []):
                course_id = part['url'].split('/')[-1]
                activities[course_id] = {
                    "id": course_id,
                    "type": "Course",
                    "name": part["name"].strip(),
                    "url": part["url"].strip(),
                }
            return activities

        for activity in menu:
            title = (activity.get("title") or "").strip()
            href = activity.get("href") or ""
            ld_hit = ld_by_name.get(title.lower())
            name = ld_hit["name"] if ld_hit else title

            focus_match = re.match(r'^/focuses/(\d+)', href)
            if focus_match:
                lab_id = focus_match.group(1)
                activities[lab_id] = {
                    "id": lab_id,
                    "type": "lab",
                    "name": name,
                    "url": f"{BASE_URL}{href}",
                }
                continue

            template_match = re.search(r'/course_templates/(\d+)', href)
            if template_match:
                course_id = template_match.group(1)
            elif ld_hit:
                course_id = ld_hit["id"]
            else:
                print(f"(consolidate_activities) Skipping unresolvable activity: {title}")
                continue
            activities[course_id] = {
                "id": course_id,
                "type": "Course",
                "name": name,
                "url": f"{BASE_URL_COURSES}/{course_id}",
            }
        return activities

    @staticmethod
    def menu_activities(path_html) -> list:
        """
        The path's ql-contents-menu activities, in page order.
        """
        if path_html is None:
            return []
        menu = path_html.select_one(COURSE_CONTENTS_MENU)
        if not menu or not menu.get("modules"):
            return []
        try:
            modules = json.loads(menu["modules"])
        except (ValueError, TypeError):
            return []
        return [activity
                for module in modules
                for step in module.get("steps", [])
                for activity in step.get("activities", [])]

    # Print out the courses list of a certain Path
    def courses_list(self):
        """
        Print out the courses list of a certain Path.
        """

        # Show the Path Title
        heading = f"{self.id} - {self.name.upper()}"
        print(f"\n\033[45m[{heading:^85}]\033[0m\n")

        # Print out each course in the Path
        for course in self.courses.values():
            course_id = course['id']
            course_name = course['name']
            print(f"+|-• \033[35m[{course_id:>5} - {course_name:<72}]\033[0m")

    def generate_markdown(self, toc_only: bool = False, **kwargs) -> str:
        """
        Generate the Markdown representation of the Path.
        :param toc_only: If True, only generate table of contents (structure).
        """

        # Convert the Path object to a dictionary
        markdown = []
        markdown.append(self.generate_front_matter())

        # Add the main heading
        markdown.append(f"# [{self.name}]({self.url})")
        
        # Add the description
        if not toc_only:
            if hasattr(self, 'description') and self.description:
                markdown.append(f"{self.description}")
        
        # Add the courses list
        if hasattr(self, 'courses') and self.courses:
            markdown.append("## Courses & Progress")
            # Add each course in the Path
            course_list = []
            for course_id, course in self.courses.items():
                folder = "labs" if course.get('type', '').lower() == 'lab' else "courses"
                course_md_name = f"{util_replace_special_chars(course['name'])}.md"
                course_list.append(f"- [ ] [{course['name']} ({course_id})](../{folder}/{course_md_name})")
            markdown.append("\n".join(course_list))

        return "\n\n".join(markdown) + "\n"

