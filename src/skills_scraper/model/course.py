import re
import time
from pathlib import Path as PathlibPath
from skills_scraper.model.base_entity import BaseEntity
from skills_scraper.model.labs import Labs
from skills_scraper.model.lab import Lab
from selenium.common import NoSuchElementException
import json
import html
import requests
from bs4 import BeautifulSoup
from skills_scraper.config import BASE_URL, QL_IFRAME
from skills_scraper.services.browser import get_page, open_page
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from skills_scraper.utils.utils import util_replace_quote_marks, util_replace_special_chars, util_strip_html_tags

# TODO: Convert these constants to Enums
# Constants for the extraction of the course data
COURSE_LD_JSON = "script[type='application/ld+json']"
COURSE_META_DESCRIPTION = "meta[name='description']"
COURSE_CONTENTS_MENU = "ql-contents-menu"
QL_YOUTUBE_VIDEO = "ql-youtube-video"
LAB_REVIEW_LAB_ID = "#lab_review_lab_id"
LAB_CONTENT_OUTLINE = "ul.lab-content__outline"
QL_QUIZ = "ql-quiz"
XPATH_START_BUTTON = "//a[@class='start-button button button--positive']"
XPATH_QUIZ = "//ql-quiz"
QUIZ_VERSION = "quizVersion"
QUIZ_ITEMS = "quizItems"
LINK_URL_A_TAG = "ql-card.document-link a"


class Course(BaseEntity):
    """
    Class representing a course entity.\n
    Inherits from BaseEntity.\n
    This class is responsible for extracting course data from the Cloud Skills Boost platform.
    """

    def __init__(self,
                 id: str,
                 name: str = None,
                 description: str = None,
                 datePublished: str = None,
                 objectives: list = None,
                 topics: list = None,
                 modules: list = None,
                 driver=None):
        super().__init__(id,
                         name,
                         description)
        self.datePublished = datePublished or ""
        self.objectives = objectives or []
        self.topics = topics or []
        self.modules = modules or []
        self.driver = driver
        self.external_course_data = {}

    def to_dict(self):
        """
        Convert the entity's data to a dictionary, excluding external_course_data.
        """
        the_dict = super().to_dict()
        if 'external_course_data' in the_dict:
            del the_dict['external_course_data']
        return the_dict

    def extract_transcript(self, force=False, no_md=False, toc_only=False, no_transcript=False) -> None:
        """
        Main method to extract the transcript of a course.
        """

        print("\nTranscript Extracting is starting...\n")

        # Load the course data from JSON
        self.load_json()

        # Fetch and parse the course page
        course_html = self.fetch_course_page()
        if not course_html:
            return

        # Extract course metadata
        if not self.extract_course_metadata(course_html, force=force):
            # Sync with DB in case it's missing there, even if local file is up to date
            self.save_json()
            return

        # Extract course outline
        if not self.extract_course_outline(course_html):
            return

        # Process course modules
        self.process_modules()

        # Save the course data
        self.save_json()
        if not no_md:
            self.save_markdown(toc_only=toc_only, no_transcript=no_transcript)

        print(f"(extract_transcript) \033[34m•-• COMPLETED: {self.id} - {self.name.upper()}\033[0m\n")

    def fetch_course_page(self) -> BeautifulSoup:
        """
        Fetch the course page and return the parsed HTML.
        """

        try:
            print(f"(fetch_course_page) Fetching: {self.url}")
            return get_page(self.driver, self.url, f"course {self.id}")
        except Exception as error:
            print(f"(extract_transcript) Error: Unable to load the course page. {error}")
            return None

    def extract_course_metadata(self, course_html, force=False) -> bool:
        """
        Extract course metadata such as description, objectives, and topics.
        """

        try:
            course_ld_json_element = course_html.select_one(COURSE_LD_JSON)
            meta_element = course_html.select_one(COURSE_META_DESCRIPTION)

            if not course_ld_json_element or not meta_element:
                raise NoSuchElementException("(extract_course_metadata) meta_element not found.")

            course_ld_json_text = course_ld_json_element.string
            course_description = self.clean_text(meta_element['content'])
            course_description = re.sub(r'\s{2,}', '\n\n', course_description)
            course_description = course_description.strip()

            course_objectives_json = json.loads(course_ld_json_text)
            datePublished = course_objectives_json.get('datePublished')

            # If the course has the same datePublished, return False and not continue.
            if not force and datePublished == self.datePublished:
                print(f"(extract_course_metadata) Course {self.id} already extracted. datePublished: {datePublished}\n")
                return False

            self.id = course_objectives_json.get('@id').split('/')[-1]
            self.name = course_objectives_json.get('name').strip()
            self.description = course_description
            self.datePublished = course_objectives_json.get('datePublished')
            self.topics = course_objectives_json.get('about')
            self.objectives = course_objectives_json.get('teaches')

            return True
        except Exception as error:
            print(f"(extract_course_metadata) Error: {error}")
            return False

    def extract_course_outline(self, course_html) -> bool:
        """
        Extract the course outline and modules.
        """

        try:
            course_contents_element = course_html.select_one(COURSE_CONTENTS_MENU)
            if course_contents_element:
                self.modules = json.loads(course_contents_element["modules"])
                return True

            raise NoSuchElementException("(extract_course_outline) ql-contents-menu is not found.")
        except Exception as error:
            print(f"(extract_course_outline) Error: {error}")
            return False

    def process_modules(self) -> None:
        """
        Process each module in the course.
        """

        for module in self.modules:
            module_title = module["title"].strip()
            print(f"(process_modules) \033[34m• MODULE: {module_title}\033[0m")

            if module.get("description"):
                module['description'] = self.clean_text(module.get("description", ""))

            for step in module['steps']:
                self.process_step(step)

    def process_step(self, step) -> None:
        """
        Process each step in a module.
        """

        # One handler per activity kind. The set of kinds belongs to the site, not to us:
        # a kind we have never seen (badge, credential, ...) is kept as-is and logged.
        handlers = {
            "video": self.process_video,
            "lab": self.process_lab,
            "quiz": self.process_quiz,
            "link": self.process_link,
            "html_bundle": self.process_link,
            "document": self.process_document,
        }

        for activity in step['activities']:
            # Fix HREF if it is a session URL
            if activity.get('href') and '/course_sessions/' in activity['href']:
                 activity['href'] = re.sub(r'/course_sessions/[^/]+', f'/course_templates/{self.id}', activity['href'])

            activity_type = activity['type']
            activity_full_url = f"{BASE_URL}{activity['href']}"

            handler = handlers.get(activity_type)
            if handler:
                handler(activity, activity_full_url)
            else:
                print(f"(process_step) •-> {activity_type}: {activity['id']:>6} - {activity['title']} (kept as-is, no handler)")

    def process_video(self, activity, url) -> None:
        """
        Process a video activity.
        """

        print(f"(process_video) •-> Vid: {activity['id']:>6} - {activity['title']}")
        try:
            video_html = get_page(self.driver, url, f"video {activity['id']}")
            if video_html is None:
                return

            video_element = video_html.select_one(QL_YOUTUBE_VIDEO)
            video_id = video_element.get("videoId") or video_element.get("videoid")
            if video_id:
                activity['videoId'] = video_id

            transcript_data = video_element.get("transcript", None)
            if transcript_data:
                transcript_json = json.loads(transcript_data)
                activity['transcript'] = " ".join(map(lambda item: item['text'], transcript_json))
            else:
                activity['transcript'] = '(No video transcript.)'

            print(f"(process_video) •-• [+]")
        except Exception as error:
            print(f"(process_video) Error: {error}")

    def process_lab(self, activity, url) -> None:
        """
        Process a lab activity.
        """

        print(f"(process_lab) •-> Lab: {activity['id']:>6} - {activity['title']}")
        
        # Force use of Template URL to ensure consistent HTML structure (and access to outline)
        # Session URL might be different or require enrollment context which changes structure.
        # Template URL (Catalog view) usually exposes the outline.
        # Format: /course_templates/<course_id>/labs/<lab_id>
        # We need to construct absolute URL.
        template_url = f"{BASE_URL}/course_templates/{self.id}/labs/{activity['id']}"
        # print(f"(process_lab) Using template URL: {template_url}")

        try:
            lab_page_html = get_page(self.driver, template_url, f"lab {activity['id']}")
            if lab_page_html is None:
                return

            lab_review_lab_id_element = lab_page_html.select_one(LAB_REVIEW_LAB_ID)
            lab_content_outline_element = lab_page_html.select_one(LAB_CONTENT_OUTLINE)

            if lab_review_lab_id_element:
                lab_id = lab_review_lab_id_element["value"].strip()
            else:
                # Fallback to activity ID if element not found
                # print(f"(process_lab) [Warning] lab_review_lab_id not found. Using activity ID {activity['id']}")
                lab_id = activity['id']

            # Create a Lab instance for the lab_id
            lab = Lab(
                id=lab_id
            )
            # Load the lab data from JSON even it's empty
            lab.load_json()

            # If the lab.name does exist, that means the lab has been extracted already.
            if lab.name:
                print(f"(process_lab) •-• [+] Existed: {lab.id} - {lab.name}")
                return False

            # If the lab.name doesn't exist, the lab is new, continue.
            lab_steps = {}
            if lab_content_outline_element:
                for a_tag in lab_content_outline_element.find_all('a'):
                    step = a_tag['href'].strip('#step')
                    text = a_tag.text
                    lab_steps[step] = text

            # Set the lab's attributes.
            lab.name = activity['title'].strip()
            lab.description = self.clean_text(activity.get('description', ''))
            lab.steps = lab_steps

            # Save the lab to files.
            lab.save_json()
            lab.save_markdown()

            # Add the lab to the Labs Collection
            labs_collection = Labs(name='Labs Collection')
            labs_collection.load_json()
            labs_collection.collection[lab_id] = lab.name
            labs_collection.save_json()

            print(f"(process_lab) •-• [+]")
        except Exception as error:
            print(f"(process_lab) Error: {error}")

    def fetch_external_course_content(self, url: str) -> dict:
        """
        Fetch external course content using __fetchCourse() JS function.
        Caches the result by base URL (without hash).
        """
        try:
            base_url = url.split('#')[0]
            if base_url in self.external_course_data:
                return self.external_course_data[base_url]

            print(f"(fetch_external) Fetching external course data: {base_url}...")
            if open_page(self.driver, url, "external course content"):
                time.sleep(3) # Wait for scripts to load

                # Execute __fetchCourse
                script = """
                return (async () => {
                    if (typeof __fetchCourse === 'function') {
                        return await __fetchCourse();
                    }
                    return null;
                })();
                """
                data = self.driver.execute_script(script)

                if data:
                    self.external_course_data[base_url] = data
                    print(f"(fetch_external) •-• [+] Cached {len(str(data))} bytes")
                    return data
                else:
                    print("(fetch_external) [!] __fetchCourse not found or returned null")

            return None
        except Exception as e:
            print(f"(fetch_external) Error: {e}")
            return None

    def _extract_lesson_content(self, course_data: dict, lesson_id: str) -> str:
        """
        Extract content for a specific lesson from the full course data.
        """
        try:
            # Check if data is wrapped in 'course' key (common in Rise 360 / Google Storage)
            if 'course' in course_data:
                lessons = course_data['course'].get('lessons', [])
            else:
                lessons = course_data.get('lessons', [])

            target_lesson = next((l for l in lessons if l.get('id') == lesson_id), None)

            if not target_lesson:
                return None

            content_parts = []
            
            # (REMOVED) Add lesson title if available - requested by user to be removed
            # if 'title' in target_lesson:
            #     content_parts.append(f"### {target_lesson['title']}")
            
            items = target_lesson.get('items', [])
            for item in items:
                parsed_item = self._parse_lesson_item(item)
                if parsed_item:
                    content_parts.append(parsed_item)

            return "\n\n".join(content_parts)
        except Exception as e:
            print(f"(_extract_lesson_content) Error: {e}")
            return None

    def _parse_lesson_item(self, item: dict) -> str:
        """
        Parse a single item from the lesson data into Markdown/HTML.
        """
        # Based on observed structure, items have 'heading', 'paragraph', 'list', etc.
        # This is a best-effort parser.

        # Check for nested items (some structures might be recursive or wrapped)
        if 'items' in item:
             sub_content = []
             for sub in item['items']:
                 parsed = self._parse_lesson_item(sub)
                 if parsed:
                     sub_content.append(parsed)
             return "\n\n".join(sub_content)

        if 'heading' in item:
            # Clean heading: remove HTML tags if any, add markdown headers
            heading_text = self._html_to_markdown(item['heading'])
            # If the cleaned text doesn't look like a header, force it to be one (h4)
            if not heading_text.startswith('#'):
                return f"#### {heading_text}"
            return heading_text

        if 'paragraph' in item:
            return self._html_to_markdown(item['paragraph'])

        if 'list' in item:
            return self._html_to_markdown(item['list'])

        if 'image' in item:
             src = item['image'].get('src')
             alt = item['image'].get('alt', 'Image')
             if src:
                 return f"![{alt}]({src})"

        return None

    def _html_to_markdown(self, html_content: str) -> str:
        """
        Convert HTML content to Markdown.
        """
        if not html_content:
            return ""

        # Remove div tags but keep content
        content = re.sub(r'<div[^>]*>', '', html_content)
        content = re.sub(r'</div>', '\n', content)

        # Paragraphs to double newlines
        content = re.sub(r'<p[^>]*>', '', content)
        content = re.sub(r'</p>', '\n\n', content)

        # Bold
        content = re.sub(r'<strong[^>]*>', '**', content)
        content = re.sub(r'</strong>', '**', content)
        content = re.sub(r'<b[^>]*>', '**', content)
        content = re.sub(r'</b>', '**', content)

        # Italic
        content = re.sub(r'<em[^>]*>', '*', content)
        content = re.sub(r'</em>', '*', content)
        content = re.sub(r'<i[^>]*>', '*', content)
        content = re.sub(r'</i>', '*', content)

        # Lists
        content = re.sub(r'<ul[^>]*>', '', content)
        content = re.sub(r'</ul>', '', content)
        content = re.sub(r'<ol[^>]*>', '', content)
        content = re.sub(r'</ol>', '', content)
        content = re.sub(r'<li[^>]*>', '- ', content)
        content = re.sub(r'</li>', '\n', content)

        # Headers
        content = re.sub(r'<h1[^>]*>', '# ', content)
        content = re.sub(r'</h1>', '\n\n', content)
        content = re.sub(r'<h2[^>]*>', '## ', content)
        content = re.sub(r'</h2>', '\n\n', content)
        content = re.sub(r'<h3[^>]*>', '### ', content)
        content = re.sub(r'</h3>', '\n\n', content)

        # Remove spans and other tags but keep content
        content = re.sub(r'<span[^>]*>', '', content)
        content = re.sub(r'</span>', '', content)

        # Decode HTML entities
        content = html.unescape(content)

        # Collapse multiple newlines
        content = re.sub(r'\n\s*\n', '\n', content)

        return content.strip()

    def process_quiz(self, activity, url) -> None:
        """
        Process a quiz activity.
        """

        print(f"(process_quiz) •-> Qui: {activity['id']:>6} - {activity['title']}")
        try:
            if not open_page(self.driver, url, f"quiz {activity['id']}"):
                return

            # Check for Start Quiz button
            try:
                start_button = self.driver.find_element(By.XPATH, XPATH_START_BUTTON)
                if start_button:
                    print(f"(process_quiz) Start Quiz button found. Clicking...")
                    start_button.click()
                    # Wait for quiz content to load
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, XPATH_QUIZ))
                    )
            except NoSuchElementException:
                pass # Button not found, proceed as usual
            except Exception as e:
                print(f"(process_quiz) Warning: Error clicking Start Quiz button: {e}")

            quiz_page_html = BeautifulSoup(self.driver.page_source, "html.parser")

            quiz_element = quiz_page_html.select_one(QL_QUIZ)
            if quiz_element:
                quiz_question_data = quiz_element[QUIZ_VERSION.lower()]
                quiz_question_json = json.loads(quiz_question_data)
                activity[QUIZ_ITEMS] = quiz_question_json.get(QUIZ_ITEMS)

            print(f"(process_quiz) •-• [+]")
        except Exception as error:
            print(f"(process_quiz) Error: {error}")

    def process_link(self, activity, url) -> None:
        """
        Process a link activity.
        """

        print(f"(process_link) •-> {activity['type'][:3].title()}: {activity['id']:>6} - {activity['title']}")
        try:
            link_page_html = get_page(self.driver, url, f"link {activity['id']}")
            if link_page_html is None:
                return

            link_url_a_tag = link_page_html.select_one(LINK_URL_A_TAG)
            if link_url_a_tag:
                activity['link'] = link_url_a_tag['href']
            else:
                iframe_tag = link_page_html.select_one(QL_IFRAME)
                activity['link'] = iframe_tag['src'] if iframe_tag else None

            # Special handling for Google Storage HTML5 courses
            if activity.get('link') and 'storage.googleapis.com' in activity['link'] and '#/lessons/' in activity['link']:
                target_url = activity['link']
                print(f"(process_link) Detected external course content: {target_url}")

                try:
                    # Extract lesson ID
                    lesson_id = target_url.split('#/lessons/')[-1]

                    # Fetch full course data (cached)
                    course_data = self.fetch_external_course_content(target_url)

                    if course_data:
                        # Extract specific lesson content
                        transcript = self._extract_lesson_content(course_data, lesson_id)
                        if transcript:
                            activity['transcript'] = transcript
                            print(f"(process_link) •-• [+] Extracted transcript ({len(transcript)} chars)")
                except Exception as e:
                    print(f"(process_link) Error extracting external content: {e}")

            print(f"(process_link) •-• [+]")
        except Exception as error:
            print(f"(process_link) Error: {error}")

    def process_document(self, activity, url) -> None:
        """
        Process a document activity.
        """
        print(f"(process_document) •-> Doc: {activity['id']:>6} - {activity['title']}")

        try:
            # Create documents directory if it doesn't exist
            # csbmdvault/courses/documents/<course_id>/
            doc_dir = getattr(self, '_output_path', PathlibPath("csbmdvault")) / "courses" / "documents" / self.id
            doc_dir.mkdir(parents=True, exist_ok=True)

            doc_page_html = get_page(self.driver, url, f"document {activity['id']}")
            if doc_page_html is None:
                return

            # Find download link
            # Selector: a[aria-label="Download document"] or a#link
            # Actual HTML shows <ql-button icon="download" href="..."> or <div class="download-document"><ql-button ...>
            download_link = doc_page_html.select_one('ql-button[icon="download"]')
            if not download_link:
                download_link = doc_page_html.select_one('div.download-document ql-button')
            if not download_link:
                # Fallback to user provided selectors just in case
                download_link = doc_page_html.select_one('a[aria-label="Download document"]')
            if not download_link:
                download_link = doc_page_html.select_one('a#link')

            if download_link:
                file_url = download_link['href']

                # Check if it's a relative URL
                if not file_url.startswith('http'):
                     # It's likely an absolute path from root or relative
                     if file_url.startswith('/'):
                         file_url = f"{BASE_URL.rstrip('/')}{file_url}"

                # Add remote URL to activity
                activity['document_url'] = file_url

                # Extract filename
                filename = None
                from urllib.parse import urlparse, parse_qs, unquote
                parsed_url = urlparse(file_url)
                query_params = parse_qs(parsed_url.query)

                # Try to get filename from query params (response-content-disposition)
                # content-disposition: inline; filename="filename.pdf"; filename*=UTF-8''filename.pdf
                rcd = query_params.get('response-content-disposition', [None])[0]
                if rcd:
                    # Simple regex to extract filename
                    import re
                    match = re.search(r'filename="?([^";]+)"?', rcd)
                    if match:
                        filename = match.group(1)

                # Determine filename from URL path if not found
                if not filename:
                     filename = PathlibPath(parsed_url.path).name

                # Decode filename just in case
                filename = unquote(filename)

                # Prepare save path
                save_path = doc_dir / filename
                activity['local_document_path'] = f"documents/{self.id}/{filename}"

                if save_path.exists():
                     print(f"(process_document) •-• [+] Existed: {filename}")
                else:
                    print(f"(process_document) Downloading {filename}...")
                    # Download the file
                    # Use requests, but copy cookies from driver if available
                    cookies = {}
                    if self.driver:
                        for cookie in self.driver.get_cookies():
                            cookies[cookie['name']] = cookie['value']

                    file_response = requests.get(file_url, cookies=cookies, stream=True)
                    file_response.raise_for_status()

                    # If we didn't get filename from URL, check headers now
                    if not filename or filename == 'download': # generic name
                        cd = file_response.headers.get('content-disposition')
                        if cd:
                             match = re.search(r'filename="?([^";]+)"?', cd)
                             if match:
                                 filename = match.group(1)
                                 save_path = doc_dir / filename
                                 activity['local_document_path'] = f"documents/{self.id}/{filename}"

                    with open(save_path, 'wb') as f:
                        for chunk in file_response.iter_content(chunk_size=8192):
                            f.write(chunk)

                    print(f"(process_document) •-• [+] Saved: {filename}")

            else:
                 print("(process_document) [!] Download link not found.")

        except Exception as error:
            print(f"(process_document) Error: {error}")

    def generate_prompt(self) -> None:
        """
        Generate the prompts for videos from their transcripts.\n
        The prompt data will be saved to a JSON file.
        """

        # Proceed only if the course's json file does exist.
        if not self._json_path.exists():
            print("Sorry, the course json not found. Please fetch the course first.")
            return

        # Load the course data from the JSON file
        self.load_json()

        # The data structure will be simplified from the original course's json.
        course = {
            "id": self.id,
            "title": f'{self.name}'
            }

        modules = {}
        for module in self.modules:
            module_title = module["title"].strip()
            steps = {}
            for step in module['steps']:
                step_id = step['id']
                activities = {}
                for activity in step['activities']:
                    activity_title = activity['title']
                    activity_id = activity['id']
                    if activity['type'] == 'video':
                        this_video = {}
                        this_video['title'] = activity_title

                        # Prompt for the video in a simple format
                        # topic: {course.title}, {module.title}; title: {activity.title}; transcript: {activity.transcript}
                        video_prompt = []
                        video_prompt.append(f"topic: {self.name}, {module_title}")
                        video_prompt.append(f"title: {activity['title'].strip()}")
                        video_prompt.append(f"transcript: {activity.get('transcript', '(No transcript available)')}")
                        this_video['prompt'] = '; '.join(video_prompt)

                        activities[activity_id] = this_video
                steps[step_id] = activities
            modules[module_title] = steps

        course['modules'] = modules

        # JSON file name for the prompt data, a bit different from the course's json file
        json_name = f'{self.id}-prompt.json'
        json_path = PathlibPath(self._json_path.parent / json_name)

        # Save the prompt data to a JSON file, overwrite if exists
        with open(json_path, 'w', encoding='utf-8', newline='\n') as jsonfile:
            json.dump(course, jsonfile, ensure_ascii=False, indent=2)

    def generate_markdown(self, toc_only: bool = False, no_transcript: bool = False, **kwargs) -> str:
        """
        Generate the Markdown data for the course.
        :param toc_only: If True, only generate table of contents (structure).
        :param no_transcript: If True, skip transcripts for videos.
        """

        markdown = []
        markdown.append(self.generate_front_matter())

        markdown.append(f"# [{self.name}]({self.url})")

        if not toc_only:
            if hasattr(self, 'description') and self.description:
                markdown.append("**Description:**")
                markdown.append(f"{util_replace_quote_marks(self.description)}")

            if hasattr(self, 'objectives') and self.objectives:
                markdown.append("**Objectives:**")
                markdown.append("\n".join([f"- {util_replace_quote_marks(objective)}" for objective in self.objectives]))

        if hasattr(self, 'modules') and self.modules:
            for module in self.modules:
                module_title = module["title"].strip()
                markdown.append(f"## {module_title}")

                if not toc_only:
                    if module.get("description"):
                        module['description'] = self.clean_text(module.get("description", ""))
                        markdown.append(f"{util_replace_quote_marks(module['description'])}")

                for step in module.get("steps", []):
                    for activity in step.get("activities", []):
                        activity_title = activity['title'].strip()
                        activity_type = activity['type']
                        activity_href = activity['href']

                        heading_kind = "HTML" if activity_type == 'html_bundle' else activity_type.title()
                        markdown.append(f"### {heading_kind} - [{activity_title}]({BASE_URL}{activity_href if activity_href else ''})")

                        if activity_type == 'video':
                            video_id = activity.get('videoId')
                            if video_id:
                                markdown.append(f"- [YouTube: {activity_title}](https://www.youtube.com/watch?v={video_id})")
                            elif activity_href:
                                markdown.append(f"- [Video Link]({BASE_URL}{activity_href})")
                            if not toc_only and not no_transcript:
                                markdown.append(f"{util_replace_quote_marks(activity.get('transcript', '(No transcript available)'))}")

                        elif activity_type == 'lab':
                            if activity.get('description'):
                                markdown.append(activity['description'])
                            lab_md_name = f"{util_replace_special_chars(activity_title)}.md"
                            tick = "x" if activity.get('isComplete') else " "
                            markdown.append(f"- [{tick}] [{activity_title}](../labs/{lab_md_name})")

                        elif activity_type == 'quiz':
                            if not toc_only and activity.get('quizItems'):
                                quizItems = activity.get('quizItems')
                                quiz_number = 1
                                for quizItem in quizItems:
                                    quiz_list = []
                                    quiz_stem = self.clean_text(quizItem.get('stem'))
                                    quiz_stem = quiz_stem.replace('\n\n', '')
                                    markdown.append(f"#### Quiz {quiz_number}.")

                                    quiz_list.append(f"> [!important]")
                                    quiz_list.append(f"> **{self.clean_text(quiz_stem)}**")
                                    quiz_list.append(">")

                                    if quizItem.get('options'):
                                        for option in quizItem.get('options', []):
                                            quiz_list.append(f"> - [ ] {self.clean_text(option.get('title'))}")
                                    markdown.append("\n".join(quiz_list))
                                    quiz_number += 1

                        elif activity_type in ('link', 'html_bundle'):
                            link_url = activity.get('link') or (f"{BASE_URL}{activity_href}" if activity_href else "")
                            markdown.append(f"- [{activity_title}]({link_url})")
                            if not toc_only and not no_transcript:
                                if activity.get('transcript'):
                                    markdown.append("\n" + activity['transcript'] + "\n")

                        elif activity_type == 'document':
                            # activity['local_document_path'] should have been set in process_document
                            local_path = activity.get('local_document_path')
                            if local_path:
                                filename = PathlibPath(local_path).name
                                markdown.append(f"- [{filename}]({local_path})")

        return "\n\n".join(markdown) + "\n"

# END OF COURSE CLASS
# END OF FILE
