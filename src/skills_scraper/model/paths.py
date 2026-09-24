from skills_scraper.model.collection import Collection
from skills_scraper.config.settings import BASE_URL_PATHS, API_URL_PATHS
import requests
import json

class Paths(Collection):
    """
    Class representing a collection of paths.
    """

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL_PATHS,
                 collection: dict = None):
        super().__init__(name, url, collection)

    def fetch_paths(self, base_url: str = BASE_URL_PATHS, force: bool = False) -> bool:
        """
        Gather all paths from the CloudSkillsBoost Paths page using the API.\n
        Returns a Boolean to check status.

        :param base_url: CloudSkillsBoost Paths page URL (unused in API method, kept for signature).
        :param force: If True, fetch even if collection is not empty.
        """
        if not force and self.collection:
            print("(Collection.fetch_paths) Collection not empty. Skipping fetch.")
            return True

        print(f"Fetching paths from API: {API_URL_PATHS}")
        
        all_paths = {}
        page = 1
        has_more = True
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        try:
            while has_more:
                url = f"{API_URL_PATHS}&page={page}"
                print(f"Fetching page {page}...", end='\r')
                
                response = requests.get(url, headers=headers, timeout=10)
                # The API might allow 404 or just return empty list/error for out of range?
                # Based on debug, it returns list.
                
                if response.status_code != 200:
                    print(f"\nFailed to fetch page {page}. Status: {response.status_code}")
                    break
                
                try:
                    data = response.json()
                except json.JSONDecodeError:
                    print(f"\nFailed to decode JSON on page {page}")
                    break
                
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                     items = data.get("searchResults", [])
                
                if not items:
                    # No more items
                    has_more = False
                    break
                
                # Process items
                for item in items:
                    title = item.get("title")
                    path_url = item.get("path")
                    if title and path_url:
                        # Extract ID from path (e.g. /paths/16?...)
                        # Split by '?' first to remove query params, then '/'
                        clean_path = path_url.split('?')[0]
                        path_id = clean_path.split('/')[-1]
                        
                        if path_id:
                            all_paths[path_id] = title.strip()
                
                page += 1
                # Safety break to avoid infinite loops if API changes behavior
                if page > 50: 
                    print("\nReached safety limit of 50 pages.")
                    break

            print(f"\nTotal paths found: {len(all_paths)}")

            # Check if the collection is not empty
            if all_paths:
                self.collection = all_paths
                self.save_json()
                return True
            else:
                print("(Collection.fetch_paths) No paths found.")
                return False

        except requests.RequestException as req_err:
            print(f"(Collection.get_paths) Network error: {req_err}")
            return False
        except Exception as error:
            print(f"(Collection.get_paths) Error occurred: {error}")
            return False