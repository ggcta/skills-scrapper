import html
import json
from skills_scraper.config.settings import BASE_URL_COURSES, BASE_URL_LAB, BASE_URL_PATHS, DATA_FOLDER_NAME, OUTPUT_FOLDER_NAME
from pathlib import Path as PathlibPath
from skills_scraper.utils.utils import util_replace_quote_marks, util_replace_special_chars, util_strip_html_tags
from skills_scraper.model.serialize import Serialize


class BaseEntity(Serialize):
    """
    Base class for all entities including Path, Course, and Lab.
    """

    def __init__(self,
                 id: str,
                 name: str,
                 description: str):
        self.id = id
        self.name = name
        self.description = description

    @property
    def type(self):
        """
        Dynamically determine the type based on the class name.
        """

        return self.__class__.__name__

    @property
    def url(self):
        """
        Dynamically generate the URL based on the type.
        """

        base_url = {
            "Path": BASE_URL_PATHS,
            "Course": BASE_URL_COURSES,
            "Lab": BASE_URL_LAB
        }.get(self.type, None)

        if not base_url:
            raise ValueError(f"Invalid entity type: {self.type}")

        return f"{base_url}/{self.id}"

    # Properties to get the JSON and Markdown file names and paths
    @property
    def _json_name(self):
        """
        Generate the JSON file name based on the entity ID.
        """

        return f'{self.id}.json'
    
    # Properties to get the JSON and Markdown file names and paths
    @property
    def _md_name(self):
        """
        Generate the Markdown file name based on the entity name.
        """

        # Replace special characters in the name for the Markdown file name
        # and ensure it ends with .md
        return f'{util_replace_special_chars(self.name)}.md'

    # Properties to get the JSON and Markdown file names and paths
    @property
    def _json_path(self):
        """
        Get the JSON file path based on the entity type.
        """

        return PathlibPath(DATA_FOLDER_NAME) / f'{self.type.lower()}s' / self._json_name

    # Properties to get the JSON and Markdown file names and paths
    @property
    def _md_path(self):
        """
        Get the Markdown file path based on the entity type.
        """

        return PathlibPath(OUTPUT_FOLDER_NAME) / f'{self.type.lower()}s' / self._md_name

    # Convert the entity's data to a dictionary without private attributes
    def to_dict(self):
        """
        Convert the entity's data to a dictionary.
        """
        import time

        # Convert the entity data to a dictionary, excluding private attributes
        # and adding the type and URL
        # Also exclude 'driver' as it is not serializable
        the_dict = {k: v for k, v in self.__dict__.items() if not k.startswith('_') and k != 'driver'}
        the_dict['type'] = self.type
        the_dict['url'] = self.url
        
        # Add scrapedTime (epoch in milliseconds)
        the_dict['scrapedTime'] = int(time.time() * 1000)
        
        return the_dict

    # Load the entity data from a JSON file
    def load_json(self):
        """
        Load the entity data from the Database (TinyDB).
        If the entity doesn't exist, load an empty {}.
        """
        from skills_scraper.services.database import Database
        import logging
        
        db = Database()
        # Use plural table name
        table_name = f"{self.type.lower()}s"
        if self.type.lower().endswith('s'):
            table_name = self.type.lower()
            
        data = db.get(table_name, self.id)
        
        if data:
            self.__dict__.update(data)
        else:
            # If not found in DB, we could try file system as fallback?
            # For now, let's assume DB is source of truth.
            # But during migration or mixed state, file might exist.
            # Plan said: "Update load_json to fetch data from Database service (TinyDB) instead of file system."
            # So we strictly use DB.
            pass

    def save_json(self):
        """
        Save the entity data to the Database (TinyDB) AND a JSON file (Backup).
        """
        
        # Convert the entity data to a dictionary
        entity_data = self.to_dict()

        # 1. UPSERT to Database
        try:
            from skills_scraper.services.database import Database
            db = Database()
            # Use plural table name (e.g. 'Course' -> 'courses')
            table_name = f"{self.type.lower()}s"
            if self.type.lower().endswith('s'):
                table_name = self.type.lower()
                
            db.upsert(table_name, entity_data)
        except Exception as e:
            print(f"(BaseEntity.save_json) Error syncing to DB: {e}")

        # 2. SAVE to individual JSON file (Backup)
        # Create the folder if it doesn't exist
        if not self._json_path.parent.exists():
            self._json_path.parent.mkdir(parents=True, exist_ok=True)

        # Create the JSON file if it doesn't exist
        # Save the data to a JSON file with UTF-8 encoding and Unix line endings
        try:
            with open(self._json_path, 'w',
                    encoding='utf-8',
                    newline='\n') as jsonfile:
                json.dump(entity_data,
                        jsonfile,
                        ensure_ascii=False,
                        indent=2)
        except IOError as e:
            print(f"(BaseEntity.save_json) Error writing JSON to file: {self._json_path}")
            print(e)
        except json.JSONDecodeError:
            print(f"(BaseEntity.save_json) Error decoding JSON from file: {self._json_path}")
        except Exception as e:
            print(f"(BaseEntity.save_json) An unexpected error occurred: {e}")

    def generate_front_matter(self) -> str:
        """
        Generate the front matter for the Markdown file.

        Order:
        - id
        - name
        - type
        - url
        - date_published
        - topics
        - scraped_date
        """
        from datetime import datetime
        import time

        front_matter_lines = ["---"]
        if hasattr(self, 'id'):
            front_matter_lines.append(f"id: '{self.id}'")
        if hasattr(self, 'name'):
            front_matter_lines.append(f"name: '{self.name}'")
        if hasattr(self, 'type'):
            front_matter_lines.append(f"type: {self.type}")
        if hasattr(self, 'url'):
            front_matter_lines.append(f"url: {self.url}")
        if hasattr(self, 'datePublished'):
            front_matter_lines.append(f"date_published: {self.datePublished}")
        if hasattr(self, 'topics'):
            front_matter_lines.append(f"topics:\n" + "\n".join([f"  - {topic}" for topic in self.topics]))
            
        # Add scraped_date
        scraped_ts = getattr(self, 'scrapedTime', None)
        if scraped_ts:
             dt = datetime.fromtimestamp(scraped_ts / 1000.0)
             front_matter_lines.append(f"scraped_date: {dt.strftime('%Y-%m-%d')}")
        else:
             # If not present, use current time
             now = datetime.now()
             front_matter_lines.append(f"scraped_date: {now.strftime('%Y-%m-%d')}")

        front_matter_lines.append("---")
        return "\n".join(front_matter_lines)

    def generate_markdown(self, **kwargs) -> str:
        """
        Generate the Markdown representation of the entity.
        """

        # Convert the Path object to a dictionary
        markdown = []
        markdown.append(self.generate_front_matter())

        return "\n\n".join(markdown) + "\n"

    def save_markdown(self, **kwargs) -> None:
        """
        Save the Path data to a Markdown file.
        passes kwargs to generate_markdown
        """

        mdtext = self.generate_markdown(**kwargs)

        # Create the folder if it doesn't exist
        if not self._md_path.parent.exists():
            self._md_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the markdown content to a file, overwrite if exists
        with open(self._md_path, "w", encoding="utf-8", newline='\n') as mdfile:
            mdfile.write(mdtext)

    def clean_text(self, text: str) -> str:
        """
        Utility method to clean and format text.
        """
        if not text:
            return ""

        text = util_strip_html_tags(html.unescape(text))
        text = text.replace('\r\n', '\n')
        return util_replace_quote_marks(text).strip()
