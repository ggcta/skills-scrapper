
import html
import json
import re
from bs4 import BeautifulSoup
from selenium.common import NoSuchElementException
import requests
from skills_scraper.config.settings import BASE_URL_LAB, LAB_CONTENT_OUTLINE, LAB_REVIEW_LAB_ID, LAB_TITLE, LD_JSON, META_DESCRIPTION, COURSE_OUTLINE, META_DESCRIPTION, PATH_CARDS
from skills_scraper.model.collection import Collection
from skills_scraper.model.course import Course
from skills_scraper.model.lab import Lab
from skills_scraper.model.path import Path
from skills_scraper.utils.utils import util_replace_quote_marks, util_strip_html_tags

class DataManagement():
    def __init__(self):
        self.paths_collection, self.courses_collection, self.labs_collection = self.load_data()

    @staticmethod
    def load_data():
        col_paths = Collection(type='paths')
        col_paths.load_json()

        col_courses = Collection(type='courses')
        col_courses.load_json()

        col_labs = Collection(type='labs')
        col_labs.load_json()

        return col_paths, col_courses, col_labs

    def fetch_path_data(self, path_id):
        
        """
        Fetch path data based on the provided path_id.
        """
        # Path URL
        a_path = Path(id=path_id)

        try:
            # Navigate to the path URL
            response = requests.get(a_path.url, timeout=20)
            response.raise_for_status()

            path_html = BeautifulSoup(response.text, "html.parser")

            # Locate the <script> tag containing the JSON data
            script_element = path_html.select_one(LD_JSON)
            json_content = script_element.string

            # Parse JSON content
            path_data = json.loads(json_content)

        except Exception as error:
            print(f"fetch_data(): Unable to find LD+JSON element - {error}")
            return {}

        # Process Path and Courses data
        # Extract course details, collect id and name only
        courses_list: dict[str, dict] = {}

        # A Path JSON element should and must have 'hasPart' key
        for course in path_data['hasPart']:
            course_id = course['url'].split('/')[-1]
            courses_list[course_id] = {
                "id": course_id,
                "type": course["@type"],
                "name": course["name"].strip(),
                "url": course["url"]
            }

        # Core Path details
        a_path.name = path_data['name'].strip()
        a_path.description = path_data['description'].strip()
        a_path.datePublished = path_data['datePublished'].strip()

        # Courses list of the Path
        a_path.courses = courses_list

        a_path.save_json()
        a_path.save_markdown()

    def fetch_course_data(self, course_id):

        """
        Fetch course data from the website and save it to a JSON file.
        """

        # The course URL
        a_course = Course(id=course_id)

        # Browse the course url
        try:
            response = requests.get(a_course.url, timeout=20)
            response.raise_for_status()
        except requests.RequestException as get_course_url_error:
            print(f"(extract_transcript) Error: Unable to load the course page. {get_course_url_error}")
            return

        # Parse the HTML content
        course_html = BeautifulSoup(response.text, "html.parser")

        # Get the course properties from the ld+json element including the course objectives, description, etc.
        try:
            course_ld_json_element = course_html.select_one(LD_JSON)
            # Locate the <meta> element by its name attribute
            meta_element = course_html.select_one(META_DESCRIPTION)
            # meta_element = course_html.find("meta", {"name": "description"})

            if not course_ld_json_element or not meta_element:
                raise NoSuchElementException("(fetch_data) meta_element not found.")

            course_ld_json_text = course_ld_json_element.string

            # Extract the content attribute
            course_description = html.unescape(meta_element['content'])
            course_description = util_strip_html_tags(course_description)
            # Strip out extra \n caused by multiple <p> or <br/>
            # The code is not clean, I know, but it works. Damn the text.
            course_description = re.sub(r'\s{2,}', '\n\n', course_description)
            course_description = util_replace_quote_marks(course_description)

            course_objectives_json = json.loads(course_ld_json_text)

            # Set the course properties
            a_course.id = course_objectives_json.get('@id').split('/')[-1]
            a_course.url = course_objectives_json.get('@id')
            a_course.type = course_objectives_json.get('@type')
            a_course.name = course_objectives_json.get('name').strip()
            a_course.description = course_description
            a_course.datePublished = course_objectives_json.get('datePublished')
            a_course.topics = course_objectives_json.get('about')
            a_course.objectives = course_objectives_json.get('teaches')

        except NoSuchElementException as _:
            print(
                f"(fetch_data) Error: Failed to process the course: {a_course.id}{': ' + a_course.name if a_course.name else ''}.\n")
            return  # Exit the function early

        # Get the course outline
        try:
            course_outline_element = course_html.select_one(COURSE_OUTLINE)
            if not course_outline_element:
                raise NoSuchElementException("(fetch_data) ql-course-outline is not found.")

            # Set the course modules, this is important
            a_course.modules = json.loads(course_outline_element["modules"])
        except NoSuchElementException as _:
            print(
                f"(fetch_data) Error: Failed to detect outline for: {a_course.id}{': ' + a_course.name if a_course.name else ''}.")
            return

        # Save the course data to a JSON file and a Markdown file
        a_course.save_json()
        a_course.save_markdown()

    def fetch_lab_data(self, lab_id):
        """
        Fetch lab data based on the provided lab_id.
        """

        a_lab = Lab(id=lab_id)
        
        # Get the lab title, description, and permalink
        try:
            response = requests.get(a_lab.url)
            response.raise_for_status()

            lab_page_html = BeautifulSoup(response.text, "html.parser")

            lab_title_element = lab_page_html.select_one(LAB_TITLE)
            lab_id_element = lab_page_html.select_one(LAB_REVIEW_LAB_ID)
            lab_description_element = lab_page_html.select_one(META_DESCRIPTION)
            lab_content_outline_element = lab_page_html.select_one(LAB_CONTENT_OUTLINE)

            # Getting the lab id, then compile a permalink for the lab
            lab_title = lab_title_element.text.strip()
            lab_description = lab_description_element['content'].strip()
            lab_id = lab_id_element["value"].strip()
            lab_permalink = a_lab.url

            # Extract outline or steps from the lab
            lab_steps = {}
            if lab_content_outline_element:
                for a_tag in lab_content_outline_element.find_all('a'):
                    step = a_tag['href'].strip('#step')
                    text = a_tag.text
                    lab_steps[step] = text

        except NoSuchElementException as _error:
            print(f"(extract_transcript) {lab_title}:\n"
                    f"Unable to locate the id lab_review_lab_id\n")
            raise NoSuchElementException

        # Create a Lab instance
        lab = Lab(
            id=lab_id,
            name=lab_title,
            url=lab_permalink,
            description=lab_description,
            steps=lab_steps
        )

        # Save the lab data to a JSON file and a Markdown file
        lab.save_json()
        lab.save_markdown()

    def fetch_data(self):
        """
        Fetch all paths from Cloud Skills Boost website.
        """

        if self.paths_collection.fetch_paths():
            print("Paths List refreshed. Proceed with courses of each path.\n")
            self.paths_collection.save_json()
            self.paths_collection.write_md()
        else:
            print("Paths List not refreshed. Proceed with courses of each path.\n")

        # Get all courses from all the paths
        for path_id in self.paths_collection.collection.keys():
            path_data = Path(id=path_id)

            path_data.fetch_data()
            path_data.save_json()
            path_data.save_markdown()
    
            # Add the course to the courses collection
            for course in path_data.courses.values():
                self.courses_collection.add_item(course['id'], course['name'])
        self.courses_collection.save_json()
