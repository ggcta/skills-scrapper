from datetime import datetime
import json

from bs4 import BeautifulSoup
import requests
from skills_scraper.config import BASE_URL, BASE_URL_PATHS, DATA_FOLDER_NAME, OUTPUT_FOLDER_NAME
from skills_scraper.model.serialize import Serialize
from pathlib import Path as PathlibPath


# Base entity for collection: Courses, Paths, Labs.
class Collection(Serialize):
    """
    Base entity for collection: Courses, Paths, Lab.
    """

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL,
                 collection: dict = None):
        self.name = name
        self.url = url
        self.date = str(datetime.today().date())
        self.collection = collection or {}

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
        Convert the entity's data to a dictionary.
        """
        import time

        collection_dict = {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
        collection_dict['type'] = self.type
        
        return collection_dict
    
    # Load the collection from a JSON file
    def load_json(self):
        """
        Load the collection from the Database (TinyDB).
        """
        from skills_scraper.services.database import Database
        
        db = Database()
        # Use plural table name
        table_name = f"{self.type.lower()}"
        if self.type.lower() == 'path': table_name = 'paths' # just in case
        
        # Collection usually stores a dict of {id: name}
        # But TinyDB stores documents {id: ..., name: ..., type: ...}
        # We need to reconstruction the collection dict {id: name} from DB docs
        
        docs = db.all(table_name)
        self.collection = {}
        for doc in docs:
            doc_id = doc.get('id')
            doc_name = doc.get('name')
            if doc_id:
                self.collection[doc_id] = doc_name

    # Save the collection to a JSON file
    def save_json(self):
        """
        Save the collection to the Database (TinyDB).
        This will UPSERT items.
        """
        import time
        # Update scrapedTime
        self.scrapedTime = int(time.time() * 1000)

        # Sync items to TinyDB
        try:
            from skills_scraper.services.database import Database
            db = Database()
            
            # Determine table name (Plural: Paths, Courses, Labs)
            # self.type is usually plural e.g. 'Paths'
            table_name = self.type.lower()
            
            if self.collection:
                for item_id, item_val in self.collection.items():
                    # item_val is usually name (str) or dict?
                    name = item_val
                    if isinstance(item_val, dict):
                        name = item_val.get('name', 'Unknown')
                    
                    # We need to fetch existing doc to preserve other fields if any?
                    # Or just upsert id/name/type?
                    # If we only have ID and Name in collection, we might overwrite other details if we are not careful
                    # But Collection.save_json is usually called after fetching a list of items (id, name).
                    # If we upsert {id, name, type}, it matches TinyDB upsert logic which updates fields.
                    
                    doc = {
                        'id': item_id,
                        'name': name,
                        'type': table_name
                    }
                    db.upsert(table_name, doc)
                    
        except Exception as e:
            print(f"(Collection.save_json) Error syncing to DB: {e}")

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
        markdown_list = self.md_helper()
        with open(self._md_path, 'w', encoding='utf-8', newline='\n') as md_file:
            md_file.write(markdown_list)

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
                              f"name: '{self.name}'",
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
