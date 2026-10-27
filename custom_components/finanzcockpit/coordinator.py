"""Coordinator, der die Dateien regelmässig neu einliest."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DATA_DIR, DOMAIN, STORE_KEY, STORE_VERSION, UPDATE_INTERVAL
from .data import FinanzDaten, FinanzDatenError, lade_daten
from .simulation import (
    REGLER_NACH_SCHLUESSEL,
    Ergebnis,
    Simulation,
    Szenario,
    mit_anpassungen,
    regler_wert,
    simuliere,
)

_LOGGER = logging.getLogger(__name__)
SPEICHERN_NACH = 2  # Sekunden; fasst schnelle Regler-Änderungen zusammen


class FinanzcockpitCoordinator(DataUpdateCoordinator[FinanzDaten]):
    """Liest die Dateien und rechnet die Vorsorge-Simulation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.verzeichnis = Path(hass.config.path(DATA_DIR))
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, STORE_KEY)
        # Gewähltes Szenario und Regler-Werte, die vom Szenario abweichen
        self.aktives_szenario: str | None = None
        self.anpassungen: dict[str, float] = {}
        self._cache: tuple[tuple[Any, ...], Ergebnis, dict[str, Ergebnis]] | None = None

    async def async_auswahl_laden(self) -> None:
        """Lädt Szenario und Regler-Werte vom letzten Mal."""
        gespeichert = await self._store.async_load() or {}
        self.aktives_szenario = gespeichert.get("szenario")
        self.anpassungen = dict(gespeichert.get("anpassungen", {}))

    async def _async_update_data(self) -> FinanzDaten:
        try:
            daten = await self.hass.async_add_executor_job(lade_daten, self.verzeichnis)
        except FinanzDatenError as err:
            raise UpdateFailed(str(err)) from err
        self._auswahl_pruefen(daten.simulation)
        return daten

    def _auswahl_pruefen(self, simulation: Simulation | None) -> None:
        """Verwirft eine Auswahl, die nach einer Änderung der Datei nicht mehr passt."""
        if simulation is None:
            return
        if self.aktives_szenario not in simulation.szenarien:
            self.aktives_szenario = simulation.aktives_szenario
            self.anpassungen = {}
        self.anpassungen = {
            k: v for k, v in self.anpassungen.items() if k in REGLER_NACH_SCHLUESSEL
        }

    @property
    def simulation(self) -> Simulation | None:
        return self.data.simulation if self.data else None

    @property
    def szenario(self) -> Szenario | None:
        """Das gewählte Szenario ohne Regler-Anpassungen."""
        sim = self.simulation
        return sim.szenarien.get(self.aktives_szenario or "") if sim else None

    def _rechnen(self) -> tuple[Ergebnis, dict[str, Ergebnis]] | None:
        sim, szenario = self.simulation, self.szenario
        if sim is None or szenario is None:
            return None
        schluessel = (id(sim), szenario.id, tuple(sorted(self.anpassungen.items())))
        if self._cache is None or self._cache[0] != schluessel:
            alle = {
                s.id: simuliere(sim.annahmen, s, sim.startwerte) for s in sim.szenarien.values()
            }
            aktiv = (
                simuliere(sim.annahmen, mit_anpassungen(szenario, self.anpassungen), sim.startwerte)
                if self.anpassungen
                else alle[szenario.id]
            )
            self._cache = (schluessel, aktiv, alle)
        return self._cache[1], self._cache[2]

    @property
    def ergebnis(self) -> Ergebnis | None:
        """Ergebnis des gewählten Szenarios mit den Regler-Werten."""
        gerechnet = self._rechnen()
        return gerechnet[0] if gerechnet else None

    @property
    def vergleich(self) -> dict[str, Ergebnis]:
        """Ergebnisse aller Szenarien, wie sie in der Datei stehen."""
        gerechnet = self._rechnen()
        return gerechnet[1] if gerechnet else {}

    def regler(self, schluessel: str) -> float | None:
        """Aktueller Wert eines Reglers."""
        szenario = self.szenario
        if szenario is None:
            return None
        return regler_wert(mit_anpassungen(szenario, self.anpassungen), schluessel)

    @callback
    def szenario_waehlen(self, szenario_id: str) -> None:
        """Wechselt das Szenario und verwirft die Regler-Anpassungen."""
        self.aktives_szenario = szenario_id
        self.anpassungen = {}
        self._geaendert()

    @callback
    def anpassen(self, schluessel: str, wert: float) -> None:
        """Übersteuert einen Parameter des gewählten Szenarios."""
        szenario = self.szenario
        if szenario is None:
            return
        if wert == regler_wert(szenario, schluessel):
            self.anpassungen.pop(schluessel, None)
        else:
            self.anpassungen[schluessel] = wert
        self._geaendert()

    @callback
    def zuruecksetzen(self) -> None:
        """Verwirft alle Regler-Anpassungen."""
        self.anpassungen = {}
        self._geaendert()

    @callback
    def _geaendert(self) -> None:
        self._store.async_delay_save(
            lambda: {"szenario": self.aktives_szenario, "anpassungen": self.anpassungen},
            SPEICHERN_NACH,
        )
        self.async_update_listeners()
