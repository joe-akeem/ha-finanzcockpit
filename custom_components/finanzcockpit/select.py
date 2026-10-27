"""Auswahl des Szenarios der Vorsorge-Simulation."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
        async_add_entities([SzenarioSelect(coordinator)])


class SzenarioSelect(SimulationsEntity, SelectEntity):
    """Wählt das Szenario; die Regler springen auf dessen Werte zurück."""

    _attr_icon = "mdi:directions-fork"

    def __init__(self, coordinator: FinanzcockpitCoordinator) -> None:
        super().__init__(coordinator, "select", "szenario", "Szenario")

    @property
    def options(self) -> list[str]:
        sim = self.coordinator.simulation
        return [s.name for s in sim.szenarien.values()] if sim else []

    @property
    def current_option(self) -> str | None:
        szenario = self.coordinator.szenario
        return szenario.name if szenario else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {"szenario_id": self.coordinator.aktives_szenario}

    async def async_select_option(self, option: str) -> None:
        sim = self.coordinator.simulation
        if sim is None:
            return
        szenario_id = next(s.id for s in sim.szenarien.values() if s.name == option)
        self.coordinator.szenario_waehlen(szenario_id)
