"""Regler, die Parameter des gewählten Szenarios übersteuern."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FinanzcockpitConfigEntry
from .coordinator import FinanzcockpitCoordinator
from .data import BASISWAEHRUNG
from .entity import SimulationsEntity
from .simulation import REGLER, Regler, regler_wert

# Bereich der Jahres-Regler relativ zum Geburtsjahr
ALTER_MIN, ALTER_MAX = 50, 70


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FinanzcockpitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.simulation is not None:
        async_add_entities(ReglerNumber(coordinator, regler) for regler in REGLER)


class ReglerNumber(SimulationsEntity, NumberEntity):
    """Ein Parameter des Szenarios; Änderungen rechnen sofort neu."""

    def __init__(self, coordinator: FinanzcockpitCoordinator, regler: Regler) -> None:
        super().__init__(coordinator, "number", regler.schluessel, regler.name)
        self.regler = regler
        self._attr_icon = regler.icon
        match regler.art:
            case "prozent":
                self._attr_native_min_value, self._attr_native_max_value = 0, 100
                self._attr_native_step = 5
                self._attr_native_unit_of_measurement = PERCENTAGE
                self._attr_mode = NumberMode.SLIDER
            case "betrag":
                self._attr_native_min_value, self._attr_native_max_value = 0, 200_000
                self._attr_native_step = 1000
                self._attr_native_unit_of_measurement = BASISWAEHRUNG
                self._attr_mode = NumberMode.BOX
            case "alter":
                self._attr_native_min_value, self._attr_native_max_value = 63, 65
                self._attr_native_step = 1
                self._attr_native_unit_of_measurement = "Jahre"
                self._attr_mode = NumberMode.SLIDER
            case _:
                self._attr_native_step = 1
                self._attr_mode = NumberMode.BOX

    @property
    def native_min_value(self) -> float:
        sim = self.coordinator.simulation
        if (geburtsjahr := self._geburtsjahr()) is not None and sim is not None:
            # Pensum-Phasen können schon vor dem 50. Altersjahr beginnen
            return min(sim.startwerte.jahr, geburtsjahr + ALTER_MIN)
        return self._attr_native_min_value

    @property
    def native_max_value(self) -> float:
        if (geburtsjahr := self._geburtsjahr()) is not None:
            return geburtsjahr + ALTER_MAX
        return self._attr_native_max_value

    def _geburtsjahr(self) -> int | None:
        sim = self.coordinator.simulation
        if sim is None or not self.regler.art.startswith("jahr_"):
            return None
        a = sim.annahmen
        return a.geburtsjahr_er if self.regler.art == "jahr_er" else a.geburtsjahr_sie

    @property
    def native_value(self) -> float | None:
        wert = self.coordinator.regler(self.regler.schluessel)
        # Ganze Zahlen ohne Nachkommastelle, sonst zeigt das Eingabefeld «2037,0»
        return int(wert) if wert is not None and wert.is_integer() else wert

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        szenario = self.coordinator.szenario
        return {
            "angepasst": self.regler.schluessel in self.coordinator.anpassungen,
            "szenario_wert": regler_wert(szenario, self.regler.schluessel) if szenario else None,
        }

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.anpassen(self.regler.schluessel, value)
