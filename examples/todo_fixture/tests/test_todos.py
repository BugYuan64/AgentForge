from fastapi.testclient import TestClient


def test_post_creates_todo() -> None:
    from todo_app.main import create_app

    with TestClient(create_app()) as client:
        response = client.post("/todos", json={"title": "学习 AgentForge"})

    assert response.status_code == 201
    assert response.json() == {"id": 1, "title": "学习 AgentForge", "completed": False}


def test_get_existing_todo() -> None:
    from todo_app.main import create_app

    with TestClient(create_app()) as client:
        client.post("/todos", json={"title": "first"})
        response = client.get("/todos/1")

    assert response.status_code == 200
    assert response.json() == {"id": 1, "title": "first", "completed": False}


def test_new_app_starts_empty() -> None:
    from todo_app.main import create_app

    with TestClient(create_app()) as first, TestClient(create_app()) as second:
        first_created = first.post("/todos", json={"title": "first"})
        second_created = second.post("/todos", json={"title": "second"})
        first_lookup = first.get("/todos/1")

    assert first_created.json()["id"] == 1
    assert second_created.json()["id"] == 1
    assert first_lookup.status_code == 200
    assert first_lookup.json()["title"] == "first"


def test_non_integer_id_is_rejected() -> None:
    from todo_app.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/todos/not-an-int")

    assert response.status_code == 422


def test_get_missing_todo_returns_404() -> None:
    from todo_app.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/todos/999")

    assert response.status_code == 404
