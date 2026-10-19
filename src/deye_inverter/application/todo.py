"""The owner's to-do list: short notes of what is left to do, kept with the application."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any

from deye_inverter.ports import Clock, KeyValueStore

TODO_ITEMS = "todo_items"
MAX_TEXT_LENGTH = 500


class TodoError(ValueError):
    """An item's text is empty or too long."""


class TodoNotFoundError(TodoError):
    """No item has the given id."""


@dataclass(frozen=True)
class TodoItem:
    """One thing to do: its id, text, whether it is done, and the days it was added and done."""

    id: int
    text: str
    done: bool
    added: str
    done_on: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """The item as a JSON-ready dict."""
        return asdict(self)


class TodoService:
    """Adds, edits, ticks and removes to-do items; open items come first, oldest first."""

    def __init__(self, store: KeyValueStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def all(self) -> list[TodoItem]:
        """Every item: open ones first, then done ones, each group in the order added."""
        raw = self._store.get(TODO_ITEMS)
        items = [TodoItem(**item) for item in json.loads(raw)] if raw else []
        return sorted(items, key=lambda item: (item.done, item.id))

    def add(self, text: str) -> list[TodoItem]:
        """Adds an open item with the trimmed text (1 to 500 characters); returns all items."""
        items = self.all()
        next_id = max((item.id for item in items), default=0) + 1
        self._write([*items, TodoItem(next_id, _clean(text), False, self._today())])
        return self.all()

    def edit(self, item_id: int, text: str) -> list[TodoItem]:
        """Replaces the item's text with the trimmed text; returns all items."""
        clean = _clean(text)
        return self._change(item_id, lambda item: replace(item, text=clean))

    def set_done(self, item_id: int, done: bool) -> list[TodoItem]:
        """Ticks the item done (dated today) or reopens it; returns all items."""
        done_on = self._today() if done else None
        return self._change(item_id, lambda item: replace(item, done=done, done_on=done_on))

    def delete(self, item_id: int) -> list[TodoItem]:
        """Removes the item; returns the remaining items."""
        items = self.all()
        self._find(items, item_id)
        self._write([item for item in items if item.id != item_id])
        return self.all()

    def _change(self, item_id: int, change: Callable[[TodoItem], TodoItem]) -> list[TodoItem]:
        items = self.all()
        target = self._find(items, item_id)
        self._write([change(item) if item is target else item for item in items])
        return self.all()

    @staticmethod
    def _find(items: list[TodoItem], item_id: int) -> TodoItem:
        for item in items:
            if item.id == item_id:
                return item
        raise TodoNotFoundError(f"No to-do item {item_id}")

    def _today(self) -> str:
        return self._clock.now().date().isoformat()

    def _write(self, items: list[TodoItem]) -> None:
        self._store.put(TODO_ITEMS, json.dumps([item.as_dict() for item in items]))


def _clean(text: str) -> str:
    clean = text.strip()
    if not clean or len(clean) > MAX_TEXT_LENGTH:
        raise TodoError(f"A to-do item needs 1 to {MAX_TEXT_LENGTH} characters")
    return clean
