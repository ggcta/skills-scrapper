import html
import json
from skills_scraper.config import BASE_URL_COURSES, BASE_URL_LAB, BASE_URL_PATHS, DATA_FOLDER_NAME, OUTPUT_FOLDER_NAME
from pathlib import Path as PathlibPath
from skills_scraper.utils.utils import util_replace_quote_marks, util_replace_special_chars, util_strip_html_tags
from skills_scraper.model.serialize import Serialize
from skills_scraper.services.store import Index, read_json, write_json


def yaml_scalar(value) -> str:
    """A string as a valid, fully escaped YAML scalar (JSON strings are YAML)."""
    return json.dumps(str(value) if value is not None else "", ensure_ascii=False)


def yaml_list(values) -> str:
    """A flow-style YAML list of strings, [] when empty."""
    return "[" + ", ".join(yaml_scalar(v) for v in values) + "]"


def first_sentence(text: str, limit: int = 240) -> str:
    """The first sentence of a description, capped, for the one-line OKF summary."""
    first = text.strip().split("\n")[0]
    for mark in (". ", "! ", "? "):
        if mark in first:
            first = first.split(mark)[0] + mark.strip()
            break
    return first if len(first) <= limit else first[:limit - 3].rstrip() + "..."


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

    @property
    def _kind(self):
        """
        Table name in the index: paths, courses, labs.
        """
        return f"{self.type.lower()}s"

    # Load the entity data from its JSON file
    def load_json(self):
        """
        Load the entity data from data/<kind>/<id>.json, the source of truth.
        Nothing happens when the file does not exist yet.
        """
        data = read_json(self._json_path)
        if data:
            self.__dict__.update(data)

    def save_json(self):
        """
        Write the entity to its JSON file (atomically) and update the index.
        """
        entity_data = self.to_dict()
        try:
            write_json(self._json_path, entity_data)
        except OSError as e:
            print(f"(BaseEntity.save_json) Error writing JSON to file: {self._json_path}")
            print(e)
            return

        index = Index()
        index.upsert(self._kind, entity_data)
        index.save()

    def generate_front_matter(self) -> str:
        """
        Generate the YAML front matter for the Markdown file.

        The keys are a superset of Open Knowledge Format v0.2 (type, title,
        description, resource, tags, sources, generated) plus this tool's own
        keys (id, portal) and the legacy names existing vaults query on
        (url, date_published, topics, scraped_date). Scalars go through
        json.dumps, which is valid YAML and never breaks on a quote.
        """
        from datetime import datetime
        from skills_scraper import __version__

        scraped_ts = getattr(self, 'scrapedTime', None)
        scraped_at = datetime.fromtimestamp(scraped_ts / 1000.0) if scraped_ts else datetime.now()
        scraped_at = scraped_at.astimezone()
        date_published = getattr(self, 'datePublished', None) or None
        topics = getattr(self, 'topics', None) or []
        description = self.description or ""

        lines = ["---"]
        lines.append(f"id: {yaml_scalar(self.id)}")
        lines.append(f"title: {yaml_scalar(self.name)}")
        lines.append(f"type: {self.type}")
        lines.append("portal: public")
        if description:
            lines.append(f"description: {yaml_scalar(first_sentence(description))}")
        lines.append(f"resource: {self.url}")
        if topics:
            lines.append(f"tags: {yaml_list(topics)}")
        lines.append("sources:")
        lines.append(f"  - resource: {self.url}")
        lines.append(f"    title: {yaml_scalar(f'Google Skills {self.type.lower()} {self.id}')}")
        lines.append("    author: Google Cloud")
        if date_published:
            lines.append(f"    last_modified: {date_published}")
        lines.append("generated:")
        lines.append(f"  by: skills-scraper/{__version__}")
        lines.append(f"  at: {scraped_at.isoformat(timespec='seconds')}")
        # Legacy names, kept so existing vault queries keep working.
        lines.append(f"url: {self.url}")
        if date_published:
            lines.append(f"date_published: {date_published}")
        if hasattr(self, 'topics'):
            lines.append(f"topics: {yaml_list(topics)}")
        lines.append(f"scraped_date: {scraped_at.strftime('%Y-%m-%d')}")
        lines.append("---")
        return "\n".join(lines)

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
