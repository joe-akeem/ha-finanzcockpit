"""Tests für strategie.md: Einlesen, Aufgaben ändern und die To-do-Liste."""

from pathlib import Path

from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finanzcockpit.const import DOMAIN
from custom_components.finanzcockpit.strategie import (
    StrategieError,
    aufgabe_aendern,
    aufgabe_hinzufuegen,
    aufgaben_loeschen,
    lade_strategie,
    parse_strategie,
)

AUFGABEN = "todo.finanzcockpit_aufgaben"
TEXT = """# Strategie

Einleitung.

## Aufgaben

### Jetzt

- [x] Konto eröffnen
- [ ] 3a einzahlen
  - [ ] Unterpunkt

## Danach

Noch Text.
- [ ] 3a einzahlen
"""


def test_einlesen() -> None:
    strategie = parse_strategie(TEXT)

    assert [(a.text, a.erledigt, a.abschnitt) for a in strategie.aufgaben] == [
        ("Konto eröffnen", True, "Jetzt"),
        ("3a einzahlen", False, "Jetzt"),
        ("Unterpunkt", False, "Jetzt"),
        ("3a einzahlen", False, "Danach"),
    ]
    # Gleicher Text, trotzdem unterschiedliche uid
    assert len({a.uid for a in strategie.aufgaben}) == 4
    # Leer gewordene Überschriften verschwinden, der übrige Text bleibt
    assert strategie.text == "# Strategie\n\nEinleitung.\n\n## Danach\n\nNoch Text.\n"


def test_aendern(tmp_path: Path) -> None:
    pfad = tmp_path / "strategie.md"
    pfad.write_text(TEXT, encoding="utf-8")
    zweite = lade_strategie(pfad).aufgaben[1]

    aufgabe_aendern(pfad, zweite.uid, erledigt=True)
    assert "- [x] 3a einzahlen\n  - [ ] Unterpunkt" in pfad.read_text(encoding="utf-8")
    # Abhaken ändert die uid nicht
    assert lade_strategie(pfad).aufgaben[1].uid == zweite.uid

    aufgabe_aendern(pfad, zweite.uid, text="  3a  einzahlen (7'258) ")
    assert "- [x] 3a einzahlen (7'258)" in pfad.read_text(encoding="utf-8")

    unterpunkt = lade_strategie(pfad).aufgaben[2]
    aufgaben_loeschen(pfad, [unterpunkt.uid])
    assert "Unterpunkt" not in pfad.read_text(encoding="utf-8")

    with pytest.raises(StrategieError):
        aufgabe_aendern(pfad, "unbekannt", erledigt=True)
    with pytest.raises(StrategieError):
        aufgabe_aendern(pfad, zweite.uid, text=" ")


def test_hinzufuegen(tmp_path: Path) -> None:
    pfad = tmp_path / "strategie.md"
    pfad.write_text(TEXT, encoding="utf-8")
    aufgabe_hinzufuegen(pfad, "Neu")
    assert pfad.read_text(encoding="utf-8").endswith("- [ ] 3a einzahlen\n- [ ] Neu\n")

    # Ohne Aufgaben entsteht ein Abschnitt «Aufgaben»
    pfad.write_text("# Strategie\n\nText.\n\n", encoding="utf-8")
    aufgabe_hinzufuegen(pfad, "Erste")
    assert (
        pfad.read_text(encoding="utf-8") == "# Strategie\n\nText.\n\n## Aufgaben\n\n- [ ] Erste\n"
    )


async def richte_ein(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Finanzcockpit")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def eintraege(hass: HomeAssistant) -> list[dict]:
    antwort = await hass.services.async_call(
        TODO_DOMAIN, "get_items", {"entity_id": AUFGABEN}, blocking=True, return_response=True
    )
    return antwort[AUFGABEN]["items"]


async def test_todo_liste(hass: HomeAssistant, daten_verzeichnis: Path) -> None:
    await richte_ein(hass)
    pfad = daten_verzeichnis / "strategie.md"

    zustand = hass.states.get(AUFGABEN)
    assert zustand.state == "3"
    assert "## Leitplanken" in zustand.attributes["strategie"]
    assert "Sparkonto für den Notgroschen" not in zustand.attributes["strategie"]
    assert "Aufgaben" not in zustand.attributes["strategie"].splitlines()[-1]
    assert zustand.attributes["aufgaben"][1] == {
        "uid": zustand.attributes["aufgaben"][1]["uid"],
        "text": "3a-Einzahlung bis 20. Dezember",
        "erledigt": False,
        "abschnitt": "Dieses Jahr",
    }
    items = await eintraege(hass)
    assert [(i["summary"], i["status"]) for i in items][:2] == [
        ("Sparkonto für den Notgroschen eröffnen", "completed"),
        ("3a-Einzahlung bis 20. Dezember", "needs_action"),
    ]
    assert items[1]["description"] == "Dieses Jahr"

    await hass.services.async_call(
        TODO_DOMAIN,
        "update_item",
        {"entity_id": AUFGABEN, "item": "3a-Einzahlung bis 20. Dezember", "status": "completed"},
        blocking=True,
    )
    assert "- [x] 3a-Einzahlung bis 20. Dezember" in pfad.read_text(encoding="utf-8")
    assert hass.states.get(AUFGABEN).state == "2"

    await hass.services.async_call(
        TODO_DOMAIN, "add_item", {"entity_id": AUFGABEN, "item": "Dachcheck"}, blocking=True
    )
    await hass.services.async_call(
        TODO_DOMAIN,
        "remove_item",
        {"entity_id": AUFGABEN, "item": "Fondssparplan starten"},
        blocking=True,
    )
    text = pfad.read_text(encoding="utf-8")
    assert text.endswith("- [ ] Festhypothek vor Ablauf neu offerieren lassen\n- [ ] Dachcheck\n")
    assert "Fondssparplan" not in text
    assert hass.states.get(AUFGABEN).state == "2"


async def test_datei_inzwischen_geaendert(hass: HomeAssistant, daten_verzeichnis: Path) -> None:
    await richte_ein(hass)
    (daten_verzeichnis / "strategie.md").write_text("# Leer\n", encoding="utf-8")

    with pytest.raises(HomeAssistantError, match="nicht gefunden"):
        await hass.services.async_call(
            TODO_DOMAIN,
            "update_item",
            {"entity_id": AUFGABEN, "item": "Fondssparplan starten", "status": "completed"},
            blocking=True,
        )
    # Danach zeigt die Liste den neuen Stand der Datei
    assert hass.states.get(AUFGABEN).state == "0"


async def test_ohne_strategie(hass: HomeAssistant, daten_verzeichnis: Path) -> None:
    (daten_verzeichnis / "strategie.md").unlink()
    await richte_ein(hass)

    assert hass.states.get(AUFGABEN) is None
