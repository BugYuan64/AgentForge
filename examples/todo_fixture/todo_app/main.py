"""In-memory Todo HTTP API for the fixed M4 baseline."""

from fastapi import FastAPI
from pydantic import BaseModel


class TodoCreate(BaseModel):
    title: str


def create_app() -> FastAPI:
    application = FastAPI()
    todos: dict[int, dict[str, int | str | bool]] = {}
    next_id = 1

    @application.post("/todos", status_code=201)
    def create_todo(payload: TodoCreate) -> dict[str, int | str | bool]:
        nonlocal next_id
        todo = {"id": next_id, "title": payload.title, "completed": False}
        todos[next_id] = todo
        next_id += 1
        return todo

    @application.get("/todos/{todo_id}")
    def get_todo(todo_id: int) -> dict[str, int | str | bool] | dict[str, str]:
        return todos.get(todo_id, {"detail": "Todo not found"})

    return application


app = create_app()
