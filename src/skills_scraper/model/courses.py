from skills_scraper.model.collection import Collection
from skills_scraper.config import BASE_URL_COURSES, API_URL_COURSES


class Courses(Collection):
    """
    Class representing a collection of courses.
    """

    API_URL = API_URL_COURSES

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL_COURSES,
                 collection: dict = None,
                 driver=None):
        super().__init__(name, url, collection, driver)

    def fetch_courses(self, force: bool = False) -> bool:
        """
        Gather all courses from the catalog API. Returns a Boolean to check status.
        """
        return self.fetch_catalog(force=force)
