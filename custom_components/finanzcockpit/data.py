"""Einlesen und Prüfen der Finanzcockpit-Dateien.

Dieses Modul hat bewusst keine Abhängigkeit zu Home Assistant,
damit es sich einfach testen lässt.
"""

from __future__ import annotations

from collections.abc import Iterator
import csv
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

import yaml

from .const import KONTEN_FILE, KURSE_FILE, SALDI_FILE, SIMULATION_FILE

if TYPE_CHECKING:
    from .simulation import Simulation

BASISWAEHRUNG = "CHF"
WAEHRUNGEN = ["CHF", "EUR", "USD"]
ANLAGEKLASSEN = {
    "liquiditaet": "Liquidität",
    "obligationen": "Obligationen",
    "aktien": "Aktien",
    "immobilien": "Immobilien",
    "rohstoffe": "Rohstoffe",
}
ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
# Konto-IDs mit diesen Präfixen würden mit den Summen- und Simulations-Sensoren kollidieren
RESERVIERTE_PRAEFIXE = ("summe_", "sim_")
LAND_PATTERN = re.compile(r"^[A-Z]{2}$")
IBAN_PATTERN = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
SALDI_SPALTEN = ["datum", "konto_id", "betrag"]
KURSE_SPALTEN = ["datum", "waehrung", "kurs"]
RAPPEN = Decimal("0.01")


class FinanzDatenError(Exception):
    """Fehler in den Finanzcockpit-Dateien."""


@dataclass(frozen=True)
class Konto:
    """Stammdaten eines Kontos."""

    id: str
    name: str
    waehrung: str
    topf: str
    # Anteil je Anlageklasse als Bruchteil, Summe 1
    anlageklassen: dict[str, Decimal]
    institut: str | None = None
    rhythmus: str | None = None
    iban: str | None = None
    eigentuemer: str | None = None
    land: str | None = None


@dataclass(frozen=True)
class Saldo:
    """Ein erfasster Kontostand."""

    datum: date
    konto_id: str
    betrag: Decimal


@dataclass(frozen=True)
class Kurs:
    """Wechselkurs: so viele CHF kostet eine Einheit der Währung."""

    datum: date
    waehrung: str
    kurs: Decimal
    quelle: str = KURSE_FILE


@dataclass(frozen=True)
class FinanzDaten:
    """Alle eingelesenen Daten."""

    konten: dict[str, Konto]
    # Pro Konto nach Datum sortiert, höchstens ein Saldo pro Tag
    saldi: dict[str, list[Saldo]]
    # Pro Fremdwährung nach Datum sortiert
    kurse: dict[str, list[Kurs]]
    # Inhalt von simulation.yaml, falls vorhanden
    simulation: Simulation | None = None

    def aktueller_saldo(self, konto_id: str) -> Saldo | None:
        """Gibt den neuesten Saldo eines Kontos zurück."""
        verlauf = self.saldi.get(konto_id)
        return verlauf[-1] if verlauf else None

    def aktueller_kurs(self, waehrung: str) -> Kurs | None:
        """Gibt den neuesten Kurs zurück, für CHF None."""
        verlauf = self.kurse.get(waehrung)
        return verlauf[-1] if verlauf else None

    def wert_chf(self, konto_id: str) -> Decimal | None:
        """Neuester Saldo eines Kontos in CHF."""
        saldo = self.aktueller_saldo(konto_id)
        if saldo is None:
            return None
        kurs = self.aktueller_kurs(self.konten[konto_id].waehrung)
        return (saldo.betrag * (kurs.kurs if kurs else 1)).quantize(RAPPEN)

    def total_chf(self) -> Decimal:
        """Summe aller Konten in CHF."""
        return sum((self.wert_chf(k) or Decimal(0) for k in self.konten), Decimal(0))

    def summe_original(self, waehrung: str) -> Decimal:
        """Summe aller Konten einer Währung in dieser Währung."""
        return sum(
            (
                saldo.betrag
                for konto in self.konten.values()
                if konto.waehrung == waehrung and (saldo := self.aktueller_saldo(konto.id))
            ),
            Decimal(0),
        )

    def summe_nach_waehrung(self) -> dict[str, Decimal]:
        """Summe in CHF je Währung, alle Währungen sind enthalten."""
        summen = dict.fromkeys(WAEHRUNGEN, Decimal(0))
        for konto in self.konten.values():
            summen[konto.waehrung] += self.wert_chf(konto.id) or Decimal(0)
        return summen

    def summe_nach_anlageklasse(self) -> dict[str, Decimal]:
        """Summe in CHF je Anlageklasse, alle Klassen sind enthalten."""
        summen = dict.fromkeys(ANLAGEKLASSEN, Decimal(0))
        for konto in self.konten.values():
            wert = self.wert_chf(konto.id) or Decimal(0)
            for klasse, anteil in konto.anlageklassen.items():
                summen[klasse] += wert * anteil
        return {klasse: summe.quantize(RAPPEN) for klasse, summe in summen.items()}


def lade_daten(verzeichnis: Path, online: dict[str, Kurs] | None = None) -> FinanzDaten:
    """Liest konten.yaml, saldi.csv, kurse.csv und simulation.yaml aus dem Verzeichnis.

    `online` sind die zuletzt online geholten Kurse je Währung.
    """
    # Erst hier importiert, weil simulation.py auf dieses Modul aufbaut
    from .simulation import lade_simulation  # noqa: PLC0415

    konten = lade_konten(verzeichnis / KONTEN_FILE)
    saldi = lade_saldi(verzeichnis / SALDI_FILE, konten)
    fremdwaehrungen = {k.waehrung for k in konten.values()} - {BASISWAEHRUNG}
    kurse = lade_kurse(verzeichnis / KURSE_FILE, fremdwaehrungen, online or {})
    daten = FinanzDaten(konten=konten, saldi=saldi, kurse=kurse)
    if (pfad := verzeichnis / SIMULATION_FILE).is_file():
        daten = replace(daten, simulation=lade_simulation(pfad, daten))
    return daten


def lade_konten(pfad: Path) -> dict[str, Konto]:
    """Liest und prüft die Kontenliste."""
    if not pfad.is_file():
        raise FinanzDatenError(f"Datei fehlt: {pfad}")

    try:
        inhalt = yaml.safe_load(pfad.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise FinanzDatenError(f"{pfad.name}: ungültiges YAML ({err})") from err

    if not isinstance(inhalt, dict) or not isinstance(inhalt.get("konten"), list):
        raise FinanzDatenError(f"{pfad.name}: erwartet wird eine Liste unter 'konten:'")

    fehler: list[str] = []
    konten: dict[str, Konto] = {}
    for nr, eintrag in enumerate(inhalt["konten"], start=1):
        konto = _lese_konto(eintrag, f"{pfad.name}, Konto {nr}", konten, fehler)
        if konto is not None:
            konten[konto.id] = konto

    if fehler:
        raise FinanzDatenError("\n".join(fehler))
    return konten


def _lese_konto(
    eintrag: object, wo: str, konten: dict[str, Konto], fehler: list[str]
) -> Konto | None:
    """Prüft einen Eintrag der Kontenliste und hängt Fehler an."""
    if not isinstance(eintrag, dict):
        fehler.append(f"{wo}: Eintrag ist kein Objekt")
        return None

    konto_id = str(eintrag.get("id", "")).strip()
    if not ID_PATTERN.match(konto_id):
        fehler.append(f"{wo}: 'id' fehlt oder enthält andere Zeichen als a-z, 0-9, _")
        return None
    if konto_id.startswith(RESERVIERTE_PRAEFIXE):
        fehler.append(f"{wo}: 'id' darf nicht mit {' oder '.join(RESERVIERTE_PRAEFIXE)} beginnen")
        return None
    if konto_id in konten:
        fehler.append(f"{wo}: 'id' {konto_id} ist doppelt")
        return None

    wo = f"{wo} ({konto_id})"
    fehler_vorher = len(fehler)
    name = str(eintrag.get("name", "")).strip()
    topf = str(eintrag.get("topf", "")).strip()
    waehrung = str(eintrag.get("waehrung", "")).strip().upper()
    if not name:
        fehler.append(f"{wo}: 'name' fehlt")
    if not topf:
        fehler.append(f"{wo}: 'topf' fehlt")
    if waehrung not in WAEHRUNGEN:
        fehler.append(f"{wo}: 'waehrung' muss eine von {', '.join(WAEHRUNGEN)} sein")
    anlageklassen = _anlageklassen(eintrag.get("anlageklasse"), wo, fehler)
    iban, land = _iban_und_land(eintrag, wo, fehler)
    if len(fehler) > fehler_vorher:
        return None

    return Konto(
        id=konto_id,
        name=name,
        waehrung=waehrung,
        topf=topf,
        anlageklassen=anlageklassen,
        institut=_optional(eintrag.get("institut")),
        rhythmus=_optional(eintrag.get("rhythmus")),
        iban=iban,
        eigentuemer=_optional(eintrag.get("eigentuemer")),
        land=land,
    )


def _anlageklassen(wert: object, wo: str, fehler: list[str]) -> dict[str, Decimal]:
    """Liest eine Anlageklasse oder eine Aufteilung in Prozent.

    Beispiele: «anlageklasse: aktien» oder
    «anlageklasse: {aktien: 60, obligationen: 40}».
    """
    erlaubt = ", ".join(ANLAGEKLASSEN)
    if isinstance(wert, str) and wert.strip():
        prozente: dict[Any, Any] = {wert: 100}
    elif isinstance(wert, dict) and wert:
        prozente = wert
    else:
        fehler.append(f"{wo}: 'anlageklasse' fehlt (eine von {erlaubt} oder eine Aufteilung)")
        return {}

    fehler_vorher = len(fehler)
    anteile: dict[str, Decimal] = {}
    for name, prozent in prozente.items():
        klasse = str(name).strip().lower().replace("ä", "ae")
        if klasse not in ANLAGEKLASSEN:
            fehler.append(f"{wo}: unbekannte Anlageklasse '{name}' (erlaubt: {erlaubt})")
            continue
        try:
            if isinstance(prozent, bool):
                raise InvalidOperation
            zahl = Decimal(str(prozent))
            if not zahl.is_finite() or zahl < 0:
                raise InvalidOperation
        except InvalidOperation:
            fehler.append(f"{wo}: Anteil '{prozent}' für {name} ist keine Prozentzahl")
            continue
        anteile[klasse] = anteile.get(klasse, Decimal(0)) + zahl

    if len(fehler) > fehler_vorher:
        return {}
    if (summe := sum(anteile.values())) != 100:
        fehler.append(f"{wo}: die Anteile der Anlageklassen ergeben {summe} %, nicht 100 %")
        return {}
    return {klasse: zahl / 100 for klasse, zahl in anteile.items() if zahl}


def lade_saldi(pfad: Path, konten: dict[str, Konto]) -> dict[str, list[Saldo]]:
    """Liest und prüft die Saldi.

    Gibt es für ein Konto mehrere Einträge am selben Tag, gilt der
    letzte. So lässt sich ein Fehler korrigieren, indem man eine
    neue Zeile anhängt.
    """
    if not pfad.is_file():
        raise FinanzDatenError(f"Datei fehlt: {pfad}")

    fehler: list[str] = []
    pro_tag: dict[tuple[str, date], Saldo] = {}
    for wo, (datum_text, konto_id, betrag_text) in _lies_csv(pfad, SALDI_SPALTEN, fehler):
        datum = _parse_datum(datum_text, wo, fehler)
        if datum is None:
            continue
        if konto_id not in konten:
            fehler.append(f"{wo}: unbekanntes Konto '{konto_id}'")
            continue
        try:
            betrag = _parse_betrag(betrag_text)
        except InvalidOperation:
            fehler.append(f"{wo}: Betrag '{betrag_text}' ist keine Zahl")
            continue

        pro_tag[(konto_id, datum)] = Saldo(datum=datum, konto_id=konto_id, betrag=betrag)

    if fehler:
        raise FinanzDatenError("\n".join(fehler))

    saldi: dict[str, list[Saldo]] = {}
    for saldo in sorted(pro_tag.values(), key=lambda s: s.datum):
        saldi.setdefault(saldo.konto_id, []).append(saldo)
    return saldi


def lade_kurse(pfad: Path, benoetigt: set[str], online: dict[str, Kurs]) -> dict[str, list[Kurs]]:
    """Liest die Wechselkurse und ergänzt sie um die Online-Kurse.

    Die Datei ist optional. Am selben Tag hat ein Kurs aus der Datei
    Vorrang vor dem Online-Kurs. Für jede Fremdwährung muss mindestens
    ein Kurs vorhanden sein.
    """
    fehler: list[str] = []
    pro_tag: dict[tuple[str, date], Kurs] = {
        (kurs.waehrung, kurs.datum): kurs for kurs in online.values()
    }
    zeilen = _lies_csv(pfad, KURSE_SPALTEN, fehler) if pfad.is_file() else iter(())
    for wo, (datum_text, waehrung_text, kurs_text) in zeilen:
        datum = _parse_datum(datum_text, wo, fehler)
        if datum is None:
            continue
        waehrung = waehrung_text.upper()
        if waehrung not in WAEHRUNGEN or waehrung == BASISWAEHRUNG:
            fremd = ", ".join(w for w in WAEHRUNGEN if w != BASISWAEHRUNG)
            fehler.append(f"{wo}: Währung '{waehrung_text}' muss eine von {fremd} sein")
            continue
        try:
            kurs = _parse_betrag(kurs_text)
            if kurs <= 0:
                raise InvalidOperation
        except InvalidOperation:
            fehler.append(f"{wo}: Kurs '{kurs_text}' ist keine positive Zahl")
            continue

        pro_tag[(waehrung, datum)] = Kurs(datum=datum, waehrung=waehrung, kurs=kurs)

    kurse: dict[str, list[Kurs]] = {}
    for kurs in sorted(pro_tag.values(), key=lambda k: k.datum):
        kurse.setdefault(kurs.waehrung, []).append(kurs)

    if fehlend := benoetigt - set(kurse):
        fehler.append(
            f"Kein Kurs für {', '.join(sorted(fehlend))}: weder online noch in {pfad.name}"
        )
    if fehler:
        raise FinanzDatenError("\n".join(fehler))
    return kurse


def _lies_csv(pfad: Path, spalten: list[str], fehler: list[str]) -> Iterator[tuple[str, list[str]]]:
    """Liefert Ortsangabe und Werte jeder Datenzeile.

    Leere Zeilen und Zeilen, die mit # beginnen, werden übersprungen.
    Die erste übrige Zeile muss die Spaltennamen enthalten.
    """
    with pfad.open(encoding="utf-8", newline="") as datei:
        zeilen = (
            (nr, zeile)
            for nr, zeile in enumerate(datei, start=1)
            if zeile.strip() and not zeile.lstrip().startswith("#")
        )
        try:
            _, kopf = next(zeilen)
        except StopIteration as err:
            raise FinanzDatenError(f"{pfad.name}: Datei ist leer") from err

        if [s.strip().lower() for s in kopf.strip().split(";")] != spalten:
            raise FinanzDatenError(f"{pfad.name}: erste Zeile muss '{';'.join(spalten)}' sein")

        for nr, zeile in zeilen:
            werte = next(csv.reader([zeile], delimiter=";"))
            wo = f"{pfad.name}, Zeile {nr}"
            if len(werte) != len(spalten):
                fehler.append(f"{wo}: erwartet werden {len(spalten)} Werte, gefunden {len(werte)}")
                continue
            yield wo, [w.strip() for w in werte]


def _parse_datum(text: str, wo: str, fehler: list[str]) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        fehler.append(f"{wo}: Datum '{text}' ist nicht im Format JJJJ-MM-TT")
        return None


def _parse_betrag(text: str) -> Decimal:
    """Akzeptiert z.B. 49070, -330000, 49'070.50 oder 49070,50."""
    bereinigt = text.replace("'", "").replace("’", "").replace(" ", "").replace(",", ".")
    if not bereinigt:
        raise InvalidOperation
    betrag = Decimal(bereinigt)
    if not betrag.is_finite():
        raise InvalidOperation
    return betrag


def _iban_und_land(
    eintrag: dict[str, Any], wo: str, fehler: list[str]
) -> tuple[str | None, str | None]:
    """Normalisiert und prüft IBAN und Ländercode.

    Ohne Ländercode wird das Land aus der IBAN übernommen.
    """
    iban = _optional(eintrag.get("iban"))
    if iban is not None:
        iban = re.sub(r"\s", "", iban).upper()
        if not _iban_gueltig(iban):
            fehler.append(f"{wo}: 'iban' ist ungültig (Prüfziffer oder Format)")

    land_wert = eintrag.get("land")
    if isinstance(land_wert, bool):
        # YAML liest z.B. NO (Norwegen) als false
        fehler.append(f"{wo}: 'land' bitte in Anführungszeichen setzen")
        return iban, None

    land = _optional(land_wert)
    if land is None:
        return iban, iban[:2] if iban else None

    land = land.upper()
    if not LAND_PATTERN.match(land):
        fehler.append(f"{wo}: 'land' muss ein Ländercode wie CH oder DE sein")
    elif iban is not None and land != iban[:2]:
        fehler.append(f"{wo}: 'land' {land} passt nicht zur IBAN")
    return iban, land


def _iban_gueltig(iban: str) -> bool:
    """Prüft Format und Prüfziffer (ISO 13616, Modulo 97)."""
    if not IBAN_PATTERN.match(iban):
        return False
    umgestellt = iban[4:] + iban[:4]
    return int("".join(str(int(z, 36)) for z in umgestellt)) % 97 == 1


def format_iban(iban: str) -> str:
    """Gruppiert eine IBAN in Viererblöcke, z.B. CH93 0076 2011 6238 5295 7."""
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def _optional(wert: object) -> str | None:
    text = str(wert).strip() if wert is not None else ""
    return text or None
