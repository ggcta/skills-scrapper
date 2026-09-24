# Description: Configuration file for the project
from pathlib import Path as PathlibPath

# Determine the project root directory
# This to ensure the app can work with relative paths
PROJECT_ROOT = PathlibPath(__file__).parent.parent.parent

# Output: Folder for Markdown files
# Data: Folder for JSON files.
# You can specific path or use the relateve paths here.
OUTPUT_FOLDER_NAME: str = PathlibPath (PROJECT_ROOT) / "csbmdvault"
DATA_FOLDER_NAME: str = PathlibPath (PROJECT_ROOT) / "data"

OUTPUT_FOLDER_NAME = "/Users/samdinh/repos/Google-Cloud-Skills-Boost/03-resources/gcp"

# Base URL for the Cloud Skills Boost website
BASE_URL: str = "https://www.skills.google"
BASE_URL_PATHS: str = f"{BASE_URL}/paths"
API_URL_PATHS: str = f"{BASE_URL}/catalog/list?format%5B%5D=learning_plans"
API_URL_COURSES: str = f"{BASE_URL}/catalog/list?format%5B%5D=courses"
API_URL_LABS: str = f"{BASE_URL}/catalog/list?format%5B%5D=labs"
BASE_URL_LAB: str = f"{BASE_URL}/catalog_lab"
BASE_URL_COURSES: str = f"{BASE_URL}/course_templates"
BASE_URL_PARTNERS: str = "https://partner.skills.google/"

# Webdriver configuration
WEBDRIVER_PROFILE_FOLDER_NAME: str = PROJECT_ROOT / '.webdriver_profiles'
WEBDRIVER_OPTIONS_HEADLESS: bool = True

# Constants for the extraction of the course data
COURSE_OUTLINE = "ql-course-outline"
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
