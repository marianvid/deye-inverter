from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from deye_inverter.application.todo import TodoError, TodoNotFoundError
from deye_inverter.web.app import create_app
from tests.conftest import Primed, World


def test_add_edit_tick_delete(world: World) -> None:
    todos = world.services.todos
    assert todos.all() == []
    todos.add("  Check the BMS undervoltage limit ")
    todos.add("Decide how the heater is wired")
    items = todos.set_done(1, True)
    assert [(i.id, i.done) for i in items] == [(2, False), (1, True)]
    assert items[1].text == "Check the BMS undervoltage limit" and items[1].done_on == "2026-10-05"
    assert todos.set_done(1, False)[0].done_on is None
    assert todos.edit(2, "Heater on one phase")[1].text == "Heater on one phase"
    assert [i.id for i in todos.delete(1)] == [2]
    assert todos.add("Next")[-1].id == 3


def test_invalid_text_and_unknown_id(world: World) -> None:
    todos = world.services.todos
    with pytest.raises(TodoError):
        todos.add("   ")
    with pytest.raises(TodoError):
        todos.add("x" * 501)
    with pytest.raises(TodoNotFoundError):
        todos.set_done(9, True)
    with pytest.raises(TodoNotFoundError):
        todos.delete(9)


@pytest.fixture
def logged_in(world: World, primed: Primed) -> Iterator[TestClient]:
    primed()
    with TestClient(create_app(world.services)) as client:
        client.post("/setup", data={"password": "correct horse", "confirm": "correct horse"})
        yield client


def test_todo_api(logged_in: TestClient) -> None:
    client = logged_in
    assert client.get("/todo").status_code == 200
    assert client.get("/api/todo").json() == []
    assert client.post("/api/todo", json={"text": "Check UVP"}).json()[0]["text"] == "Check UVP"
    assert client.post("/api/todo", json={"text": ""}).status_code == 400
    edited = client.post("/api/todo/1", json={"text": "Check the UVP", "done": True}).json()
    assert edited[0]["text"] == "Check the UVP" and edited[0]["done"] is True
    assert client.post("/api/todo/1", json={"text": " "}).status_code == 400
    assert client.post("/api/todo/7", json={"done": True}).status_code == 404
    assert client.delete("/api/todo/7").status_code == 404
    assert client.delete("/api/todo/1").json() == []
