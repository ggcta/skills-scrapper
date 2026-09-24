import json

# Class to serialize objects to JSON
class Serialize:

    # Convert object to dictionary containing non-private attributes
    def to_dict(self):
        return {key.lstrip('_'): value for key, value in self.__dict__.items()}

    # Convert object to JSON string
    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
