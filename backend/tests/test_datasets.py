import json
from pathlib import Path

import pytest

from app.datasets import DatasetError, normalize_item, parse_dataset, select_files


@pytest.fixture()
def bench(tmp_path: Path) -> Path:
    for rel, text in {
        "repo1/calc.py": "def add(a, b):\n    return a - b\n",
        "repo1/test_calc.py": "from calc import add\n",
        "repo1/README.md": "# repo1\n",
        "repo1/src/util/helpers.py": "X = 1\n",
        "repo1/__pycache__/calc.cpython-312.pyc": "junk",
        "repo1/node_modules/x/index.js": "js",
        "tasks/t1/a.txt": "one",
        "tasks/t2/b.txt": "two",
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_field_aliases():
    items = parse_dataset("d.jsonl", b'{"question": "2+2?", "expected": 4}\n{"prompt": "hi", "label": "x"}\n')
    assert items[0]["task"] == "2+2?" and items[0]["answer"] == "4"
    assert items[1]["answer"] == "x"


def test_csv_and_inline_files():
    items = parse_dataset("d.csv", b'task,answer,files\nfix,DONE,"{""a.py"": ""x""}"\n')
    assert items[0]["meta"]["files"] == {"a.py": "x"}


@pytest.mark.parametrize("glob, expected", [
    ([], ["README.md", "__pycache__/calc.cpython-312.pyc", "calc.py", "node_modules/x/index.js", "src/util/helpers.py", "test_calc.py"]),
    (["*.py"], ["calc.py", "src/util/helpers.py", "test_calc.py"]),
    (["**/*.py", "!**/__pycache__/**"], ["calc.py", "src/util/helpers.py", "test_calc.py"]),
    (["src/**"], ["src/util/helpers.py"]),
    (["re:^test_.*\\.py$"], ["test_calc.py"]),
    (["!node_modules/**", "!**/*.pyc"], ["README.md", "calc.py", "src/util/helpers.py", "test_calc.py"]),
    (["*.[pm][yd]"], ["README.md", "calc.py", "src/util/helpers.py", "test_calc.py"]),
])
def test_select_files(bench: Path, glob, expected):
    picked = [rel for rel, _ in select_files({"dir": str(bench / "repo1"), "glob": glob})]
    assert sorted(picked) == sorted(expected)


def test_folder_forms(bench: Path):
    d = str(bench / "repo1")
    a = normalize_item({"task": "t", "files": d, "files_glob": "*.py; !test_*"})
    assert a["meta"]["files_from"] == {"dir": str(Path(d).resolve()), "glob": ["*.py", "!test_*"]}
    b = normalize_item({"task": "t", "files": {"dir": d, "glob": ["*.md"]}})
    assert b["meta"]["files_from"]["glob"] == ["*.md"]
    c = parse_dataset("b.csv", b"task,files,files_glob\nfix,repo1,*.py\n", base_dir=bench)
    assert c[0]["meta"]["files_from"]["dir"] == str((bench / "repo1").resolve())


def test_dataset_default_folder_with_placeholder(bench: Path):
    rows = [{"id": "t1", "task": "a"}, {"id": "t2", "task": "b"}, {"task": "c", "files": {"x": "y"}}]
    items = parse_dataset("d.jsonl", "\n".join(map(json.dumps, rows)).encode(), base_dir=bench, defaults={"files": "tasks/{id}"})
    assert items[0]["meta"]["files_from"]["dir"].endswith("t1")
    assert items[1]["meta"]["files_from"]["dir"].endswith("t2")
    assert items[2]["meta"] == {"files": {"x": "y"}}  # an item's own files win


@pytest.mark.parametrize("row, error", [
    ({"task": "t", "files": "nope"}, "folder not found"),
    ({"task": "t", "files": "repo1", "files_glob": "*.rs"}, "no files match"),
    ({"task": "t", "files": "repo1", "files_glob": "re:(["}, "bad regex"),
    ({"task": "t", "files": "tasks/{missing}"}, "placeholder"),
    ({"answer": "x"}, "no task field"),
])
def test_errors(bench: Path, row, error):
    with pytest.raises(DatasetError, match=error.replace("(", r"\(")):
        normalize_item(row, bench)
