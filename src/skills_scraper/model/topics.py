from skills_scraper.model.course import Course
from skills_scraper.model.collection import Collection
from skills_scraper.config.settings import BASE_URL


class Topics(Collection):
    """
    Class representing a collection of topics.
    """

    def __init__(self,
                 name: str = None,
                 url: str = BASE_URL,
                 collection: dict = None):
        super().__init__(name, url, collection)

    def to_dict(self):
        """
        Convert the Topics object to a dictionary representation.\n
        Sort the collection by keys.\n
        """

        # Sort the collection by keys
        if self.collection:
            self.collection = dict(sorted(self.collection.items()))

        return {
            "type": self.type,
            "name": self.name,
            "url": self.url,
            "date": self.date,
            "collection": self.collection
        }

    def extract_topics(self, course_collection: dict):
        """
        Gather all unique topics from the downloaded courses.

        :param courses_collection: `Courses.collection`.
        """

        if not isinstance(course_collection.collection, dict):
            raise TypeError("The course_collection must be of type dict.")

        for course_id, course_name in course_collection.collection.items():
            course = Course(id=course_id)

            if course._json_path.exists():
                course.load_json()

                if hasattr(course, 'topics'):
                    for topic in course.topics:
                        if topic not in self.collection:
                            self.collection[topic] = {}
                        self.collection[topic][course_id] = course_name

        self.save_json()
