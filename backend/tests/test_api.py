import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs the lifespan: seeding, MCP session manager
        yield c


def test_meta_and_seed(client):
    assert client.get("/api/meta").status_code == 200
    models = client.get("/api/models").json()
    assert any(m["provider"] == "mock" for m in models)
    names = {g["name"] for g in client.get("/api/graphs").json()}
    assert {"Swarm (messages only)", "Blackboard", "Hierarchy (2 levels)"} <= names


def test_templates_and_create(client):
    catalog = client.get("/api/templates").json()
    assert len(catalog) == 12
    mock = next(m for m in client.get("/api/models").json() if m["provider"] == "mock")
    g = client.post("/api/graphs/from-template", json={"template_id": "debate", "model_id": mock["id"]}).json()
    check = client.post("/api/graphs/validate", json={"name": g["name"], "data": g["data"]}).json()
    assert check["ok"], check
    assert client.delete(f"/api/graphs/{g['id']}").json() == {"ok": True}
    assert client.post("/api/graphs/from-template", json={"template_id": "nope", "model_id": mock["id"]}).status_code == 404


def test_dataset_upload_errors_are_reported(client):
    r = client.post("/api/datasets", files={"file": ("d.jsonl", b'{"task": "t", "files": "no/such/folder"}\n')})
    assert r.status_code == 400 and "folder not found" in r.json()["detail"]
    r = client.post("/api/datasets", files={"file": ("d.jsonl", b'{"task": "2+2?", "answer": "4"}\n')}, data={"name": "t"})
    assert r.status_code == 200 and r.json()["item_count"] == 1
    client.delete(f"/api/datasets/{r.json()['id']}")
