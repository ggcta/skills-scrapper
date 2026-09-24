# The flat-file store: atomic writes, an index that is only a ledger.
from pathlib import Path

from skills_scraper.services.store import Index, read_json, write_json


def test_write_json_leaves_no_temp_files(tmp_path):
    target = tmp_path / "courses" / "1.json"
    write_json(target, {"id": "1", "name": "One"})
    assert read_json(target) == {"id": "1", "name": "One"}
    assert [p.name for p in (tmp_path / "courses").iterdir()] == ["1.json"]
    assert target.read_text(encoding="utf-8").endswith("}\n")


def test_index_upsert_keeps_older_fields(tmp_path):
    index = Index(tmp_path)
    index.upsert("courses", {"id": "1", "name": "One", "datePublished": "2024-01-01"})
    index.upsert("courses", {"id": "1", "name": "One renamed"})
    assert index.get("courses", "1") == {"name": "One renamed", "datePublished": "2024-01-01"}


def test_search_by_name_then_by_file_content(tmp_path):
    write_json(tmp_path / "courses" / "1.json", {"id": "1", "name": "Vertex", "topics": ["ML"],
                                                  "modules": [{"transcript": "hello pipelines"}]})
    index = Index(tmp_path)
    index.rebuild()
    assert [r["id"] for r in index.search("courses", "vert", "name")] == ["1"]
    assert [r["id"] for r in index.search("courses", "ml", "topics")] == ["1"]
    assert [r["id"] for r in index.search("courses", "pipelines")] == ["1"]
    assert index.search("courses", "nothing") == []


def test_rebuild_from_files_ignores_prompt_files(tmp_path):
    write_json(tmp_path / "courses" / "1.json", {"id": "1", "name": "One"})
    write_json(tmp_path / "courses" / "1-prompt.json", {"id": "1", "title": "prompt"})
    write_json(tmp_path / "labs" / "7.json", {"id": "7", "name": "Lab"})
    counts = Index(tmp_path).rebuild()
    assert counts == {"paths": 0, "courses": 1, "labs": 1}
    assert read_json(tmp_path / "index.json")["labs"]["7"]["name"] == "Lab"
