"""Tests für Einrichtung, Sensoren und Labels."""

from pathlib import Path
import re

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.helpers.template import Template
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finanzcockpit.const import DOMAIN, SERVICE_RELOAD

FRONTEND = Path(__file__).parent.parent / "custom_components" / DOMAIN / "frontend"


async def richte_ein(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Finanzcockpit")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_sensoren(hass: HomeAssistant, daten_verzeichnis) -> None:
    entry = await richte_ein(hass)
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get("sensor.finanzcockpit_lohnkonto")
    assert float(state.state) == 11805.40
    assert state.attributes["unit_of_measurement"] == "CHF"
    assert state.attributes["state_class"] == "total"
    assert state.attributes["topf"] == "Frei verfügbar"
    assert state.attributes["stand"] == "2026-10-31"
    assert state.attributes["iban"] == "CH93 0076 2011 6238 5295 7"
    assert state.attributes["land"] == "CH"
    assert state.attributes["eigentuemer"] == "Gemeinsam"

    assert state.attributes["anlageklasse"] == {"Liquidität": 100.0}
    assert state.attributes["wert_chf"] == 11805.40

    eur = hass.states.get("sensor.finanzcockpit_festgeld_eur")
    assert eur.attributes["unit_of_measurement"] == "EUR"
    assert eur.attributes["wert_chf"] == 18640.00


async def test_summen(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)

    total = hass.states.get("sensor.finanzcockpit_summe_total")
    assert float(total.state) == 491415.40
    assert total.attributes["unit_of_measurement"] == "CHF"

    eur = hass.states.get("sensor.finanzcockpit_summe_waehrung_eur")
    assert float(eur.state) == 18640.00
    assert eur.attributes["betrag"] == 20000.0
    assert eur.attributes["kurs"] == 0.932
    assert eur.attributes["kurs_stand"] == "2026-10-31"
    assert eur.attributes["anteil"] == 3.8
    assert float(hass.states.get("sensor.finanzcockpit_summe_waehrung_usd").state) == 12169.50

    aktien = hass.states.get("sensor.finanzcockpit_summe_anlageklasse_aktien")
    # 45 % der Säule 3a, 85 % des Depots und 30 % der Pensionskasse
    assert float(aktien.state) == round(18400.50 * 0.45 + 12169.50 * 0.85 + 96000 * 0.30, 2)
    assert aktien.name == "Anlageklasse Aktien"
    anteile = [
        hass.states.get(f"sensor.finanzcockpit_summe_anlageklasse_{k}").attributes["anteil"]
        for k in ("liquiditaet", "obligationen", "aktien", "immobilien", "rohstoffe")
    ]
    assert sum(anteile) == pytest.approx(100, abs=0.2)


async def test_kontentabelle(hass: HomeAssistant, daten_verzeichnis) -> None:
    """Die Markdown-Tabelle der Dashboard-Strategie rendert eine Zeile pro Konto."""
    await richte_ein(hass)
    # Eine Entität der Integration ohne Zustand (z.B. deaktiviert) darf nicht stören
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "geist", suggested_object_id="finanzcockpit_geist"
    )
    js = (FRONTEND / "finanzcockpit.js").read_text(encoding="utf-8")
    vorlage = re.search(r"const KONTENTABELLE = `(.*?)`;", js, re.DOTALL).group(1)
    vorlage = vorlage.replace("${PLATTFORM}", DOMAIN)

    tabelle = Template(vorlage, hass).async_render().strip().splitlines()

    # Kopf, 8 Konten, Total; Summen- und Simulations-Entitäten sind keine Konten
    assert len(tabelle) == 2 + 8 + 1
    assert tabelle[-1] == "| **Total** | | | **491'415** |"
    assert "| Hypothek | Wohnen | -455'000 CHF | -455'000 |" in tabelle
    assert "| Festgeld EUR | Notgroschen | 20'000 EUR | 18'640 |" in tabelle


async def test_labels(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)

    label = lr.async_get(hass).async_get_label_by_name("Topf: Steuern")
    assert label is not None
    eintrag = er.async_get(hass).async_get("sensor.finanzcockpit_steuern")
    assert label.label_id in eintrag.labels


async def test_topfwechsel_ersetzt_label(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)
    konten = daten_verzeichnis / "konten.yaml"
    konten.write_text(
        konten.read_text(encoding="utf-8").replace("topf: Steuern", "topf: Reserve"),
        encoding="utf-8",
    )

    await hass.services.async_call(DOMAIN, SERVICE_RELOAD, blocking=True)
    await hass.async_block_till_done()

    labels = lr.async_get(hass)
    eintrag = er.async_get(hass).async_get("sensor.finanzcockpit_steuern")
    assert eintrag.labels == {labels.async_get_label_by_name("Topf: Reserve").label_id}


async def test_ungueltige_daten(hass: HomeAssistant, daten_verzeichnis) -> None:
    (daten_verzeichnis / "saldi.csv").write_text("falsch\n", encoding="utf-8")

    entry = await richte_ein(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY
