from datetime import datetime
import json

from skills_scraper.config import BASE_URL, BASE_URL_PATHS, DATA_FOLDER_NAME, OUTPUT_FOLDER_NAME
from skills_scraper.model.serialize import Serialize
from skills_scraper.model.base_entity import yaml_scalar
from skills_scraper.services.browser import get_page
from skills_scraper.services.store import Index, write_text
from pathlib import Path as PathlibPath


# Base entity for collection: Courses, Paths, Labs.
class Collection(Serialize):
    """
    Base entity for collection: Courses, Paths, Lab.
    """

    # Catalog API endpoint (paged JSON); subclasses that can be fetched set it.
    API_URL: str = None
    # Safety limit for the pagination loop, in case the API stops returning [].
    MAX_PAGES: int = 100

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL,
                 collection: dict = None,
                 driver=None):
        self.name = name
        self.url = url
        self.date = str(datetime.today().date())
        self.collection = collection or {}
        self.driver = driver

    def fetch_catalog(self, force: bool = False) -> bool:
        """
        Gather every item of this collection from the paged catalog API,
        read through the signed-in browser (the JSON lands in a <pre> tag).
        Returns True on success.

        :param force: If True, fetch even if the collection is not empty.
        """
        label = self.type.lower()

        if not self.API_URL:
            print(f"({self.type}.fetch_catalog) No catalog API for {label}.")
            return False

        if not force and self.collection:
            print(f"({self.type}.fetch_catalog) Collection not empty. Skipping fetch.")
            return True

        print(f"Fetching {label} from API: {self.API_URL}")

        items_found = {}
        page = 1

        try:
            while True:
                print(f"Fetching page {page}...", end='\r')
                page_html = get_page(self.driver, f"{self.API_URL}&page={page}", f"{label} page {page}")
                if page_html is None:
                    break

                # The browser renders the JSON response inside <pre>.
                pre_element = page_html.select_one("pre")
                json_text = pre_element.get_text() if pre_element else page_html.get_text()

                try:
                    data = json.loads(json_text)
                except json.JSONDecodeError:
                    print(f"\nFailed to decode JSON on page {page}")
                    break

                items = data if isinstance(data, list) else data.get("searchResults", [])
                if not items:
                    break

                for item in items:
                    title = item.get("title")
                    item_path = item.get("path")
                    if title and item_path:
                        # /paths/16?locale=en -> 16 : drop the query, keep the last segment
                        item_id = item_path.split('?')[0].split('/')[-1]
                        if item_id:
                            items_found[item_id] = title.strip()

                page += 1
                if page > self.MAX_PAGES:
                    print(f"\nReached safety limit of {self.MAX_PAGES} pages.")
                    break

            print(f"\nTotal {label} found: {len(items_found)}")

            if items_found:
                self.collection = items_found
                self.save_json()
                return True

            print(f"({self.type}.fetch_catalog) No {label} found.")
            return False

        except Exception as error:
            print(f"({self.type}.fetch_catalog) Error occurred: {error}")
            return False

    @property
    def type(self):
        """
        Override the type property to return the class name.
        """
        return self.__class__.__name__

    # Properties to get the JSON and Markdown file names and paths
    @property
    def _json_name(self):
        return f"{self.type.lower()}.json"
    
    # Properties to get the JSON and Markdown file names and paths
    @property
    def _json_path(self):
        return PathlibPath(DATA_FOLDER_NAME) / self._json_name

    # Properties to get the JSON and Markdown file names and paths
    @property
    def _md_name(self):
        return f"{self.type.lower()}.md"
    
    # Properties to get the JSON and Markdown file names and paths
    @property
    def _md_path(self):
        return PathlibPath(OUTPUT_FOLDER_NAME) / self._md_name

    # Convert the entity's data to a dictionary without private attributes
    def to_dict(self):
        """
        Convert the entity's data to a dictionary, without the browser.
        """
        collection_dict = {k: v for k, v in self.__dict__.items() if not k.startswith('_') and k != 'driver'}
        collection_dict['type'] = self.type
        
        return collection_dict
    
    @property
    def _kind(self):
        """
        Table name in the index: paths, courses, labs (the class name, lowered).
        """
        return self.type.lower()

    # Load the collection from the index
    def load_json(self):
        """
        Load {id: name} for this kind from data/index.json.
        """
        self.collection = {item_id: entry.get('name', 'Unknown')
                           for item_id, entry in Index().all(self._kind).items()}

    # Save the collection to the index
    def save_json(self):
        """
        Upsert every {id: name} of this collection into data/index.json.
        Names may be plain strings or dicts carrying a 'name'.
        """
        import time
        self.scrapedTime = int(time.time() * 1000)

        index = Index()
        for item_id, item_val in self.collection.items():
            name = item_val.get('name', 'Unknown') if isinstance(item_val, dict) else item_val
            index.upsert(self._kind, {'id': item_id, 'name': name})
        index.save()

    def print_list(self, sort_by: str = 'name'):
        """
        Print out the collection prior to prompting user for a selection.
        :param sort_by: 'name' or 'id'
        """

        # Sort the collection by name and convert to a list
        if self.collection and all(isinstance(value, str) for value in self.collection.values()):
            # If all values are strings (id: name), sort based on param
            if sort_by == 'id':
                # Sort by keys (id)
                a_sorted_list = sorted(self.collection.items(), key=lambda item: item[0])
            else:
                # Defaults to name
                a_sorted_list = sorted(self.collection.items(), key=lambda item: item[1])
        elif self.collection and all(isinstance(value, dict) for value in self.collection.values()):
             # If values are dicts, we usually sort by ID (key) or Name (value['name'])
             # Current implementation assumed sorting by keys (item[0]) for dicts in one branch??
             # Let's check original code:
             # elif self.collection and all(isinstance(value, dict) for value in self.collection.values()):
             #    a_sorted_list = sorted(self.collection.items(), key=lambda item: item[0])
             
             if sort_by == 'id':
                 a_sorted_list = sorted(self.collection.items(), key=lambda item: item[0])
             else:
                 # Try to find 'name' in dict, otherwise fallback to key
                 # This assumes value is a dict with 'name' key
                 a_sorted_list = sorted(self.collection.items(), key=lambda item: item[1].get('name', item[0]))

        else:
            a_sorted_list = list(self.collection.items())
        if self.name:
            print(f"\n"
                  f"\033[45m[{self.name.upper():^85}]\033[0m"
                  "\n")
        else:
             print("\n")

        # Print the sorted list
        for an_item in a_sorted_list:
            item_id = an_item[0]
            item_name = an_item[1]
            print(f"+|-• \033[35m[{item_id:>5} - {item_name:<72}]\033[0m")

    def write_md(self):
        """
        Write out the paths collect into a Markdown file.
        """

        # Sort the collection by name
        if self.collection and all(isinstance(value, str) for value in self.collection.values()):
            # If all values are strings, sort by values
            self.collection = dict(sorted(self.collection.items(), key=lambda item: item[1]))
        elif self.collection and all(isinstance(value, dict) for value in self.collection.values()):
            # If all values are dictionaries, sort by keys
            self.collection = dict(sorted(self.collection.items(), key=lambda item: item[0]))
        else:
            print(f"(Collection.write_md) Warning: Mixed value types in collection or empty collection. Skipping sorting for {self.name}.")

        # Create the Markdown file
        write_text(self._md_path, self.md_helper())

    def md_helper(self):
        markdown = []
        import time

        # Get scraped_date
        scraped_ts = getattr(self, 'scrapedTime', None)
        if scraped_ts:
             dt = datetime.fromtimestamp(scraped_ts / 1000.0)
             scraped_date = dt.strftime('%Y-%m-%d')
        else:
             now = datetime.now()
             scraped_date = now.strftime('%Y-%m-%d')

        # Add front matter
        front_matter_lines = ["---",
                              f"type: {self.type}",
                              f"title: {yaml_scalar(self.name)}",
                              f"resource: {self.url}",
                              f"url: {self.url}",
                              f"date: {self.date}",
                              f"scraped_date: {scraped_date}",
                              "---"]
        markdown.append("\n".join(front_matter_lines))

        # The # main heading
        markdown.append(f"# [{self.name}]({self.url})")

        item_list = []
        if self.type == 'Paths' or self.type == 'paths':
            for item_id, item_name in self.collection.items():
                item_url = f"{BASE_URL_PATHS}/{item_id}"
                item_list.append(f"- [ ] `{item_id:>5}`: [(Web Link)]({item_url}) | {item_name}")
        markdown.append("\n".join(item_list))

        return "\n\n".join(markdown) + "\n"
