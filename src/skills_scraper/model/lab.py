# Description: This file contains the Lab class which is a subclass of BaseEntity.
from skills_scraper.model.base_entity import BaseEntity

# Lab entity based on BaseEntity
class Lab(BaseEntity):
    """
    Class representing a Lab entity.
    """

    def __init__(self,
                 id: str,
                 name: str = None,
                 description: str = None,
                 steps: dict = None):
        super().__init__(id,
                         name,
                         description
                         )
        self.steps = steps or {}

    # TODO: fetch_data() for fetching a lab's data

    def generate_markdown(self, toc_only: bool = False, **kwargs):
        """
        Generate the Markdown content for the Lab entity.
        :param toc_only: If True, only generate table of contents (structure).
        """

        markdown = []
        markdown.append(self.generate_front_matter())

        markdown.append(f"# [{self.name}]({self.url})")

        if not toc_only:
            if hasattr(self, 'description') and self.description:
                markdown.append(f"{self.description}")

        if hasattr(self, 'steps') and self.steps:
            for step_number, step_text in self.steps.items():
                markdown.append(f"## Step {step_number}: {step_text}")

        return "\n\n".join(markdown) + "\n"
