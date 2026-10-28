"""Strategie und Aufgaben aus strategie.md.

Die Datei ist freier Markdown-Text. Zeilen wie «- [ ] Text» oder «- [x] Text»
sind Aufgaben: Home Assistant zeigt sie als To-do-Liste und schreibt
Änderungen (abhaken, umbenennen, hinzufügen, löschen) in die Datei zurück.
Der übrige Text erscheint im Dashboard als Strategie.

Dieses Modul hat bewusst keine Abhängigkeit zu Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile

AUFGABE = re.compile(r"^(?P<einzug>\s*)[-*] \[(?P<status>[ xX])\] (?P<text>.+?)\s*$")
TITEL = re.compile(r"^(?P<ebene>#{1,6})\s")
# Überschrift für neue Aufgaben, wenn die Datei noch keine enthält
NEUE_AUFGABEN = "## Aufgaben"


@dataclass(frozen=True)
class Aufgabe:
    """Eine Zeile «- [ ] …» in strategie.md."""

    uid: str
    text: str
    erledigt: bool
    # Überschrift, unter der die Aufgabe steht
    abschnitt: str | None


@dataclass(frozen=True)
class Strategie:
    """Inhalt von strategie.md."""

    # Markdown ohne die Aufgaben und ohne leer gewordene Überschriften
    text: str
    aufgaben: list[Aufgabe]


class StrategieError(Exception):
    """strategie.md kann nicht wie gewünscht geändert werden."""


def lade_strategie(pfad: Path) -> Strategie:
    """Liest strategie.md."""
    return parse_strategie(pfad.read_text(encoding="utf-8"))


def parse_strategie(inhalt: str) -> Strategie:
    zeilen = inhalt.splitlines()
    aufgaben = [a for _, a in _aufgaben(zeilen)]
    text = [z for z in zeilen if not AUFGABE.match(z)]
    return Strategie(text=_ohne_leere_abschnitte(text), aufgaben=aufgaben)


def _aufgaben(zeilen: list[str]) -> list[tuple[int, Aufgabe]]:
    """Aufgaben mit Zeilennummer; die uid bleibt beim Abhaken gleich."""
    gefunden: list[tuple[int, Aufgabe]] = []
    gesehen: dict[str, int] = {}
    abschnitt: str | None = None
    for nr, zeile in enumerate(zeilen):
        if TITEL.match(zeile):
            abschnitt = zeile.lstrip("#").strip()
            continue
        if not (treffer := AUFGABE.match(zeile)):
            continue
        text = treffer["text"]
        # Gleicher Text mehrmals: die Reihenfolge unterscheidet
        anzahl = gesehen[text] = gesehen.get(text, 0) + 1
        uid = hashlib.sha1(f"{text}\n{anzahl}".encode()).hexdigest()[:12]
        gefunden.append(
            (
                nr,
                Aufgabe(uid=uid, text=text, erledigt=treffer["status"] != " ", abschnitt=abschnitt),
            )
        )
    return gefunden


def _ohne_leere_abschnitte(zeilen: list[str]) -> str:
    """Entfernt Überschriften, unter denen nach den Aufgaben nichts mehr steht."""
    # Wiederholen, bis nichts mehr wegfällt: ohne «### Jetzt» ist auch «## Aufgaben» leer
    while (behalten := _ohne_leere_titel(zeilen)) != zeilen:
        zeilen = behalten
    # Mehrere Leerzeilen hintereinander zusammenfassen
    return re.sub(r"\n{3,}", "\n\n", "\n".join(zeilen)).strip() + "\n"


def _ohne_leere_titel(zeilen: list[str]) -> list[str]:
    behalten: list[str] = []
    for nr, zeile in enumerate(zeilen):
        if titel := TITEL.match(zeile):
            ebene = len(titel["ebene"])
            folgende = (z for z in zeilen[nr + 1 :] if z.strip())
            naechste = next(folgende, None)
            # Leer: es folgt nichts oder eine gleich hohe bzw. höhere Überschrift
            if naechste is None or (
                (t := TITEL.match(naechste)) is not None and len(t["ebene"]) <= ebene
            ):
                continue
        behalten.append(zeile)
    return behalten


def aufgabe_aendern(
    pfad: Path, uid: str, *, text: str | None = None, erledigt: bool | None = None
) -> None:
    """Hakt eine Aufgabe ab, öffnet sie wieder oder ändert ihren Text."""
    zeilen = _lies(pfad)
    nr = _zeile(zeilen, uid)
    treffer = AUFGABE.match(zeilen[nr])
    assert treffer is not None
    status = treffer["status"] if erledigt is None else ("x" if erledigt else " ")
    neu = _einzeilig(text) if text is not None else treffer["text"]
    zeilen[nr] = f"{treffer['einzug']}- [{status}] {neu}"
    _schreibe(pfad, zeilen)


def aufgabe_hinzufuegen(pfad: Path, text: str) -> None:
    """Hängt eine offene Aufgabe nach der letzten Aufgabe an."""
    zeilen = _lies(pfad) if pfad.exists() else []
    neu = f"- [ ] {_einzeilig(text)}"
    if vorhandene := _aufgaben(zeilen):
        letzte = vorhandene[-1][0]
        einzug = AUFGABE.match(zeilen[letzte])
        assert einzug is not None
        zeilen.insert(letzte + 1, einzug["einzug"] + neu)
    else:
        while zeilen and not zeilen[-1].strip():
            zeilen.pop()
        zeilen += ["", NEUE_AUFGABEN, "", neu] if zeilen else [NEUE_AUFGABEN, "", neu]
    _schreibe(pfad, zeilen)


def aufgaben_loeschen(pfad: Path, uids: list[str]) -> None:
    """Entfernt Aufgaben aus der Datei."""
    zeilen = _lies(pfad)
    weg = {_zeile(zeilen, uid) for uid in uids}
    _schreibe(pfad, [z for nr, z in enumerate(zeilen) if nr not in weg])


def _zeile(zeilen: list[str], uid: str) -> int:
    for nr, aufgabe in _aufgaben(zeilen):
        if aufgabe.uid == uid:
            return nr
    raise StrategieError(f"Aufgabe nicht gefunden (wurde strategie.md geändert?): {uid}")


def _einzeilig(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise StrategieError("Eine Aufgabe braucht einen Text")
    return text


def _lies(pfad: Path) -> list[str]:
    try:
        return pfad.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as err:
        raise StrategieError(f"{pfad} fehlt") from err


def _schreibe(pfad: Path, zeilen: list[str]) -> None:
    """Schreibt über eine temporäre Datei, damit nie eine halbe Datei entsteht."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=pfad.parent, prefix=".strategie-", delete=False
    ) as datei:
        datei.write("\n".join(zeilen) + "\n")
    os.replace(datei.name, pfad)
