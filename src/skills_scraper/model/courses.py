from skills_scraper.model.collection import Collection
from skills_scraper.config import BASE_URL_COURSES


class Courses(Collection):
    """
    Class representing a collection of courses.
    """

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL_COURSES,
                 collection: dict = None):
        super().__init__(name, url, collection)

    def fetch_courses(self, force: bool = False) -> bool:
        """
        Gather all courses from the CloudSkillsBoost Courses page using the API.
        Returns a Boolean to check status.
        """
        if not force and self.collection:
            print("(Courses.fetch_courses) Collection not empty. Skipping fetch.")
            return True

        from skills_scraper.config import API_URL_COURSES
        import requests
        import json

        print(f"Fetching courses from API: {API_URL_COURSES}")
        
        all_courses = {}
        page = 1
        has_more = True
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        try:
            while has_more:
                url = f"{API_URL_COURSES}&page={page}"
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
                        # Extract ID from path (e.g. /course_templates/72?...)
                        clean_path = path_url.split('?')[0]
                        course_id = clean_path.split('/')[-1]
                        
                        if course_id:
                            all_courses[course_id] = title.strip()
                
                page += 1
                if page > 100: 
                    print("\nReached safety limit of 100 pages.")
                    break

            print(f"\nTotal courses found: {len(all_courses)}")

            if all_courses:
                self.collection = all_courses
                self.save_json()
                return True
            else:
                print("(Courses.fetch_courses) No courses found.")
                return False

        except requests.RequestException as req_err:
            print(f"(Courses.fetch_courses) Network error: {req_err}")
            return False
        except Exception as error:
            print(f"(Courses.fetch_courses) Error occurred: {error}")
            return False
