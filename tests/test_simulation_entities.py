"""Tests für Szenario-Auswahl, Regler und Kennzahlen in Home Assistant."""

from datetime import timedelta
from pathlib import Path
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.finanzcockpit.const import DOMAIN, SERVICE_RELOAD, STORE_KEY
from custom_components.finanzcockpit.simulation import REGLER

FRONTEND = Path(__file__).parent.parent / "custom_components" / DOMAIN / "frontend"
SZENARIO = "select.finanzcockpit_sim_szenario"
LUECKE = "sensor.finanzcockpit_sim_vorsorgeluecke"
PENSUM_ER = "number.finanzcockpit_sim_pensum_er"


async def richte_ein(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Finanzcockpit")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def setze(hass: HomeAssistant, entity_id: str, wert: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": wert}, blocking=True
    )


async def test_entitaeten(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)

    auswahl = hass.states.get(SZENARIO)
    assert auswahl.state == "Er 80 % ab 2030, Sie 60 % ab 2028"
    assert auswahl.attributes["options"] == ["Status quo", "Er 80 % ab 2030, Sie 60 % ab 2028"]

    for regler in REGLER:
        assert hass.states.get(f"number.finanzcockpit_sim_{regler.schluessel}") is not None
    assert hass.states.get(PENSUM_ER).state == "80"
    pension = hass.states.get("number.finanzcockpit_sim_pension_er")
    assert (pension.attributes["min"], pension.attributes["max"]) == (2022, 2042)

    luecke = hass.states.get(LUECKE)
    assert luecke.attributes["unit_of_measurement"] == "CHF"
    assert float(luecke.state) > 0
    assert hass.states.get("sensor.finanzcockpit_sim_erstes_negatives_jahr").state == "nie"
    assert hass.states.get("sensor.finanzcockpit_sim_tragbarkeit").attributes["erfuellt"]

    verlauf = hass.states.get("sensor.finanzcockpit_sim_verlauf")
    assert verlauf.state == auswahl.state
    jahre = verlauf.attributes["jahre"]
    assert (jahre[0]["jahr"], jahre[-1]["jahr"]) == (2027, 2078)
    assert verlauf.attributes["pension_er"] == 2037

    vergleich = hass.states.get("sensor.finanzcockpit_sim_vergleich")
    assert vergleich.state == "2"
    szenarien = vergleich.attributes["szenarien"]
    assert [s["id"] for s in szenarien] == ["status_quo", "teilzeit"]
    assert [s["aktiv"] for s in szenarien] == [False, True]
    assert szenarien[1]["vorsorgeluecke"] == float(luecke.state)


async def test_regler_rechnet_neu(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)
    vorher = float(hass.states.get("sensor.finanzcockpit_sim_frei_pension_er").state)

    await setze(hass, PENSUM_ER, 100)

    pensum = hass.states.get(PENSUM_ER)
    assert pensum.state == "100"
    assert pensum.attributes["angepasst"]
    assert pensum.attributes["szenario_wert"] == 80
    nachher = float(hass.states.get("sensor.finanzcockpit_sim_frei_pension_er").state)
    assert nachher > vorher
    assert hass.states.get("sensor.finanzcockpit_sim_verlauf").attributes["angepasst"]
    # Der Vergleich zeigt die Szenarien so, wie sie in der Datei stehen
    vergleich = hass.states.get("sensor.finanzcockpit_sim_vergleich").attributes["szenarien"]
    assert vergleich[1]["frei_pension_er"] == vorher

    # Zurück auf den Szenario-Wert gilt nicht mehr als Anpassung
    await setze(hass, PENSUM_ER, 80)
    assert not hass.states.get(PENSUM_ER).attributes["angepasst"]
    assert float(hass.states.get("sensor.finanzcockpit_sim_frei_pension_er").state) == vorher


async def test_zuruecksetzen(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)
    await setze(hass, "number.finanzcockpit_sim_pension_sie", 2050)
    assert hass.states.get("number.finanzcockpit_sim_pension_sie").state == "2050"

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.finanzcockpit_sim_zuruecksetzen"},
        blocking=True,
    )

    assert hass.states.get("number.finanzcockpit_sim_pension_sie").state == "2045"


async def test_szenario_wechsel_verwirft_anpassungen(
    hass: HomeAssistant, daten_verzeichnis
) -> None:
    await richte_ein(hass)
    await setze(hass, PENSUM_ER, 60)

    await hass.services.async_call(
        "select", "select_option", {"entity_id": SZENARIO, "option": "Status quo"}, blocking=True
    )

    assert hass.states.get(SZENARIO).state == "Status quo"
    assert hass.states.get(PENSUM_ER).state == "100"
    assert not hass.states.get(PENSUM_ER).attributes["angepasst"]
    assert hass.states.get("sensor.finanzcockpit_sim_verlauf").state == "Status quo"


async def test_auswahl_wird_gespeichert(
    hass: HomeAssistant, daten_verzeichnis, hass_storage
) -> None:
    await richte_ein(hass)
    await setze(hass, PENSUM_ER, 60)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()

    assert hass_storage[STORE_KEY]["data"] == {
        "szenario": "teilzeit",
        "anpassungen": {"pensum_er": 60.0},
    }


async def test_auswahl_bleibt_nach_neustart(
    hass: HomeAssistant, daten_verzeichnis, hass_storage
) -> None:
    hass_storage[STORE_KEY] = {
        "version": 1,
        "key": STORE_KEY,
        "data": {"szenario": "status_quo", "anpassungen": {"pension_er": 2036, "alt": 1}},
    }

    await richte_ein(hass)

    assert hass.states.get(SZENARIO).state == "Status quo"
    assert hass.states.get("number.finanzcockpit_sim_pension_er").state == "2036"


async def test_unbekanntes_gespeichertes_szenario(
    hass: HomeAssistant, daten_verzeichnis, hass_storage
) -> None:
    hass_storage[STORE_KEY] = {
        "version": 1,
        "key": STORE_KEY,
        "data": {"szenario": "geloescht", "anpassungen": {"pension_er": 2036}},
    }

    await richte_ein(hass)

    # Das aktive Szenario aus der Datei gilt, ohne die alten Anpassungen
    assert hass.states.get(SZENARIO).state == "Er 80 % ab 2030, Sie 60 % ab 2028"
    assert hass.states.get("number.finanzcockpit_sim_pension_er").state == "2037"


async def test_ohne_simulation(hass: HomeAssistant, daten_verzeichnis) -> None:
    (daten_verzeichnis / "simulation.yaml").unlink()

    await richte_ein(hass)

    eintraege = er.async_entries_for_config_entry(
        er.async_get(hass), hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )
    assert eintraege
    assert not [e for e in eintraege if "_sim_" in e.entity_id]


async def test_fehler_in_simulation(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)
    datei = daten_verzeichnis / "simulation.yaml"
    datei.write_text(datei.read_text(encoding="utf-8") + "\nunbekannt: 1\n", encoding="utf-8")

    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()
    await hass.async_block_till_done()

    # Wie bei konten.yaml: alles ist nicht verfügbar, bis die Datei korrigiert ist
    assert hass.states.get(LUECKE).state == "unavailable"
    assert hass.states.get("sensor.finanzcockpit_lohnkonto").state == "unavailable"

    datei.write_text(datei.read_text(encoding="utf-8").replace("unbekannt: 1", ""), "utf-8")
    await hass.services.async_call(DOMAIN, SERVICE_RELOAD, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(LUECKE).state != "unavailable"


def vorlage(name: str) -> str:
    """Liest ein Jinja-Template aus dem Frontend und setzt die Konstanten ein."""
    js = (FRONTEND / "finanzcockpit.js").read_text(encoding="utf-8")
    text = re.search(rf"const {name} = `(.*?)`;", js, re.DOTALL).group(1)
    return (
        text.replace("${VERLAUF}", f"sensor.{DOMAIN}_sim_verlauf")
        .replace("${SIM}", f"{DOMAIN}_sim_")
        .replace("${PLATTFORM}", DOMAIN)
    )


async def test_vergleichstabelle(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)

    tabelle = Template(vorlage("VERGLEICHSTABELLE"), hass).async_render().strip().splitlines()

    assert tabelle[0] == "| Kennzahl | status_quo | **teilzeit ◀** |"
    assert tabelle[1] == "|:--|--:|--:|"
    zeilen = {z.split(" | ")[0].removeprefix("| "): z for z in tabelle[2:12]}
    assert len(zeilen) == 10
    assert zeilen["Vermögen aufgebraucht"].endswith("| nie | nie |")
    assert re.fullmatch(
        r"\| Tragbarkeit im Ruhestand \| \d+\.\d % \| \d+\.\d % \|",
        zeilen["Tragbarkeit im Ruhestand"],
    )
    luecke = float(hass.states.get(LUECKE).state)
    assert zeilen["Vorsorgelücke pro Monat"].endswith(f"| {luecke:,.0f} |".replace(",", "'"))
    assert "- **teilzeit**: Er 80 % ab 2030, Sie 60 % ab 2028" in tabelle


async def test_warnungen(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass)
    text = Template(vorlage("WARNUNGEN"), hass)

    assert text.async_render().strip() == "✅ Vermögen reicht, Tragbarkeit erfüllt."

    # Früh pensioniert mit hoher Hypothek: Vermögen und Tragbarkeit reichen nicht
    await setze(hass, "number.finanzcockpit_sim_pension_er", 2028)
    await setze(hass, "number.finanzcockpit_sim_amortisation", 0)
    gerendert = text.async_render()
    assert "⚠️ Das freie Vermögen wird" in gerendert
    assert "*Regler weichen vom Szenario ab.*" in gerendert
