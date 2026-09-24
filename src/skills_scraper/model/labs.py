from skills_scraper.model.collection import Collection
from skills_scraper.config import BASE_URL_LAB, API_URL_LABS


class Labs(Collection):
    """
    Class representing a collection of labs.
    """

    API_URL = API_URL_LABS

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL_LAB,
                 collection: dict = None,
                 driver=None):
        super().__init__(name, url, collection, driver)

    def fetch_labs(self, force: bool = False) -> bool:
        """
        Gather all labs from the catalog API. Returns a Boolean to check status.
        """
        return self.fetch_catalog(force=force)
