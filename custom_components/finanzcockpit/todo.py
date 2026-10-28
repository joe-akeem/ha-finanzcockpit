"""Aufgaben aus strategie.md als To-do-Liste."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FinanzcockpitConfigEntry
from .const import DOMAIN, STRATEGIE_FILE
from .coordinator import FinanzcockpitCoordinator
from .strategie import (
    StrategieError,
    aufgabe_aendern,
    aufgabe_hinzufuegen,
    aufgaben_loeschen,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FinanzcockpitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.data.strategie is not None:
        async_add_entities([AufgabenListe(coordinator)])


class AufgabenListe(CoordinatorEntity[FinanzcockpitCoordinator], TodoListEntity):
    """To-do-Liste, die direkt in strategie.md liest und schreibt.

    Das Attribut «strategie» enthält den übrigen Text für das Dashboard,
    «aufgaben» die Aufgaben mit Abschnitt für die Aufgaben-Karte.
    """

    _attr_name = "Aufgaben"
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )
    # Der Text ändert sich selten und braucht keine Historie
    _unrecorded_attributes = frozenset({"strategie", "aufgaben"})

    def __init__(self, coordinator: FinanzcockpitCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = f"todo.{DOMAIN}_aufgaben"
        self._attr_unique_id = f"{DOMAIN}_aufgaben"
        self._pfad = coordinator.verzeichnis / STRATEGIE_FILE

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.strategie is not None

    @property
    def todo_items(self) -> list[TodoItem] | None:
        strategie = self.coordinator.data.strategie
        if strategie is None:
            return None
        return [
            TodoItem(
                uid=a.uid,
                summary=a.text,
                status=TodoItemStatus.COMPLETED if a.erledigt else TodoItemStatus.NEEDS_ACTION,
                description=a.abschnitt,
            )
            for a in strategie.aufgaben
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        strategie = self.coordinator.data.strategie
        if strategie is None:
            return {"strategie": None, "aufgaben": []}
        return {
            "strategie": strategie.text,
            "aufgaben": [
                {"uid": a.uid, "text": a.text, "erledigt": a.erledigt, "abschnitt": a.abschnitt}
                for a in strategie.aufgaben
            ],
        }

    async def async_create_todo_item(self, item: TodoItem) -> None:
        await self._schreiben(aufgabe_hinzufuegen, self._pfad, item.summary or "")

    async def async_update_todo_item(self, item: TodoItem) -> None:
        erledigt = None if item.status is None else item.status == TodoItemStatus.COMPLETED
        await self._schreiben(
            lambda: aufgabe_aendern(
                self._pfad, item.uid or "", text=item.summary, erledigt=erledigt
            )
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        await self._schreiben(aufgaben_loeschen, self._pfad, uids)

    async def _schreiben(self, funktion: Callable[..., None], *args: Any) -> None:
        try:
            await self.hass.async_add_executor_job(funktion, *args)
        except StrategieError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            # Auch nach einem Fehler den aktuellen Stand der Datei zeigen
            await self.coordinator.async_refresh()
