from skills_scraper.model.collection import Collection
from skills_scraper.config.settings import BASE_URL_LAB


class Labs(Collection):
    """
    Class representing a collection of labs.
    """

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL_LAB,
                 collection: dict = None):
        super().__init__(name, url, collection)

    def fetch_labs(self, force: bool = False) -> bool:
        """
        Gather all labs from the CloudSkillsBoost Labs page using the API.
        Returns a Boolean to check status.
        """
        if not force and self.collection:
            print("(Labs.fetch_labs) Collection not empty. Skipping fetch.")
            return True

        from skills_scraper.config.settings import API_URL_LABS
        import requests
        import json

        print(f"Fetching labs from API: {API_URL_LABS}")
        
        all_labs = {}
        page = 1
        has_more = True
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        try:
            while has_more:
                url = f"{API_URL_LABS}&page={page}"
                print(f"Fetching page {page}...", end='\r')
                
                response = requests.get(url, headers=headers, timeout=10)
                
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
                        # Extract ID from path (e.g. /catalog_lab/123?...)
                        clean_path = path_url.split('?')[0]
                        lab_id = clean_path.split('/')[-1]
                        
                        if lab_id:
                            all_labs[lab_id] = title.strip()
                
                page += 1
                if page > 100: 
                    print("\nReached safety limit of 100 pages.")
                    break

            print(f"\nTotal labs found: {len(all_labs)}")

            if all_labs:
                self.collection = all_labs
                self.save_json()
                return True
            else:
                print("(Labs.fetch_labs) No labs found.")
                return False

        except requests.RequestException as req_err:
            print(f"(Labs.fetch_labs) Network error: {req_err}")
            return False
        except Exception as error:
            print(f"(Labs.fetch_labs) Error occurred: {error}")
            return False
