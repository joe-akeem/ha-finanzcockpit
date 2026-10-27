"""Setzt die Regler der Vorsorge-Simulation zurück."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FinanzcockpitConfigEntry
from .coordinator import FinanzcockpitCoordinator
from .entity import SimulationsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FinanzcockpitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.simulation is not None:
        async_add_entities([ZuruecksetzenButton(coordinator)])


class ZuruecksetzenButton(SimulationsEntity, ButtonEntity):
    """Übernimmt wieder die Werte des Szenarios aus simulation.yaml."""

    _attr_icon = "mdi:restore"

    def __init__(self, coordinator: FinanzcockpitCoordinator) -> None:
        super().__init__(coordinator, "button", "zuruecksetzen", "Regler zurücksetzen")

    async def async_press(self) -> None:
        self.coordinator.zuruecksetzen()
