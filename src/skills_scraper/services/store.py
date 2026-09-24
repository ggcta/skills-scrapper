# Flat-file store: one JSON file per entity is the truth, index.json is a
# derived ledger that can always be rebuilt from those files. No database.
import json
import os
import tempfile
from pathlib import Path

from skills_scraper.config import DATA_FOLDER_NAME

KINDS = ("paths", "courses", "labs")
INDEX_FIELDS = ("name", "datePublished", "scrapedTime")


def write_json(path, data) -> None:
    """
    Write data as pretty UTF-8 JSON, atomically: tmp file in the same folder,
    fsync, then os.replace(). A Ctrl+C can never leave half a file behind.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as jsonfile:
            json.dump(data, jsonfile, ensure_ascii=False, indent=2)
            jsonfile.flush()
            os.fsync(jsonfile.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_json(path):
    """
    Read a JSON file, or None when it does not exist.
    """
    path = Path(path)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as jsonfile:
        return json.load(jsonfile)


class Index:
    """
    data/index.json: {kind: {id: {name, datePublished, scrapedTime}}}.

    Cheap to load, enough for list/search by name, and rebuildable from the
    entity files with rebuild(), so losing it costs nothing.
    """

    def __init__(self, data_dir=DATA_FOLDER_NAME):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "index.json"
        self.tables = read_json(self.path) or {}
        for kind in KINDS:
            self.tables.setdefault(kind, {})

    def save(self) -> None:
        write_json(self.path, self.tables)

    def all(self, kind: str) -> dict:
        return self.tables.get(kind, {})

    def get(self, kind: str, entity_id: str):
        return self.tables.get(kind, {}).get(str(entity_id))

    def upsert(self, kind: str, doc: dict) -> None:
        """
        Merge the index fields of doc into the table, keeping older values
        for fields the doc does not carry (a bare catalog entry has no dates).
        """
        entity_id = str(doc.get("id", "")).strip()
        if not entity_id:
            return
        entry = self.tables.setdefault(kind, {}).setdefault(entity_id, {})
        for field in INDEX_FIELDS:
            if doc.get(field) not in (None, ""):
                entry[field] = doc[field]

    def entity_file(self, kind: str, entity_id: str) -> Path:
        return self.data_dir / kind / f"{entity_id}.json"

    def search(self, kind: str, query: str, field: str = None) -> list:
        """
        Case-insensitive substring search. name/id are answered from the
        index; any other field (or no field: the whole document) opens the
        entity file. Returns the matching documents.
        """
        needle = query.lower()
        results = []
        for entity_id, entry in self.all(kind).items():
            summary = {"id": entity_id, **entry}
            if field in ("name", "id"):
                if needle in str(summary.get(field, "")).lower():
                    results.append(summary)
                continue
            if field is None and (needle in entity_id.lower() or needle in str(entry.get("name", "")).lower()):
                results.append(summary)
                continue
            doc = read_json(self.entity_file(kind, entity_id))
            if not doc:
                continue
            haystack = doc.get(field) if field else doc
            if haystack is None:
                continue
            if isinstance(haystack, list):
                hit = any(needle in str(item).lower() for item in haystack)
            else:
                hit = needle in str(haystack).lower()
            if hit:
                results.append(summary)
        return results

    def rebuild(self) -> dict:
        """
        Rebuild every table from data/<kind>/*.json. Returns counts per kind.
        """
        self.tables = {kind: {} for kind in KINDS}
        for kind in KINDS:
            for entity_file in sorted((self.data_dir / kind).glob("*.json")):
                if entity_file.name.endswith("-prompt.json"):
                    continue
                doc = read_json(entity_file)
                if isinstance(doc, dict):
                    doc.setdefault("id", entity_file.stem)
                    self.upsert(kind, doc)
        self.save()
        return {kind: len(table) for kind, table in self.tables.items()}
