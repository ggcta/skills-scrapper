from skills_scraper.model.collection import Collection
from skills_scraper.config import BASE_URL_PATHS, API_URL_PATHS


class Paths(Collection):
    """
    Class representing a collection of paths.
    """

    API_URL = API_URL_PATHS
    MAX_PAGES = 50

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL_PATHS,
                 collection: dict = None,
                 driver=None):
        super().__init__(name, url, collection, driver)

    def fetch_paths(self, base_url: str = BASE_URL_PATHS, force: bool = False) -> bool:
        """
        Gather all paths from the catalog API. Returns a Boolean to check status.

        :param base_url: kept for signature compatibility, unused.
        :param force: If True, fetch even if collection is not empty.
        """
        return self.fetch_catalog(force=force)
