"""Tests für das Einlesen der Dateien."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from custom_components.finanzcockpit.data import (
    FinanzDatenError,
    Kurs,
    format_iban,
    lade_daten,
)

EXAMPLES = Path(__file__).parent.parent / "examples"


def schreibe(verzeichnis: Path, konten: str, saldi: str) -> Path:
    (verzeichnis / "konten.yaml").write_text(konten, encoding="utf-8")
    (verzeichnis / "saldi.csv").write_text(saldi, encoding="utf-8")
    return verzeichnis


KONTEN = """
konten:
  - id: lohnkonto
    name: Lohnkonto
    waehrung: chf
    topf: Frei
    anlageklasse: liquiditaet
"""
LEER = "datum;konto_id;betrag\n"


def test_beispieldaten():
    daten = lade_daten(EXAMPLES)

    assert set(daten.konten) == {
        "lohnkonto",
        "steuern",
        "festgeld_eur",
        "saeule3a_er",
        "depot_usd",
        "pk_er",
        "liegenschaft",
        "hypothek",
    }
    assert daten.konten["festgeld_eur"].waehrung == "EUR"
    # Die Korrektur am selben Tag gewinnt
    assert daten.aktueller_saldo("lohnkonto").betrag == Decimal("11805.40")
    assert daten.aktueller_saldo("lohnkonto").datum == date(2026, 10, 31)
    assert len(daten.saldi["lohnkonto"]) == 2
    # Apostroph als Tausendertrennzeichen
    assert daten.aktueller_saldo("saeule3a_er").betrag == Decimal("18400.50")
    # Der neueste Kurs gilt
    assert daten.wert_chf("festgeld_eur") == Decimal("18640.00")
    assert daten.wert_chf("depot_usd") == Decimal("12169.50")
    assert daten.total_chf() == Decimal("491415.40")


def test_summen(tmp_path):
    konten = """
konten:
  - id: chf
    name: CHF-Konto
    waehrung: CHF
    topf: T
    anlageklasse: liquiditaet
  - id: eur
    name: EUR-Depot
    waehrung: EUR
    topf: T
    anlageklasse: {aktien: 60, Obligationen: 40}
"""
    saldi = LEER + "2026-10-31;chf;1000\n2026-10-31;eur;1000\n"
    kurse = "datum;waehrung;kurs\n2026-10-31;EUR;0.9\n"
    (tmp_path / "kurse.csv").write_text(kurse, encoding="utf-8")
    daten = lade_daten(schreibe(tmp_path, konten, saldi))

    assert daten.total_chf() == Decimal(1900)
    assert daten.summe_nach_waehrung() == {
        "CHF": Decimal(1000),
        "EUR": Decimal(900),
        "USD": Decimal(0),
    }
    assert daten.summe_original("EUR") == Decimal(1000)
    assert daten.summe_nach_anlageklasse() == {
        "liquiditaet": Decimal(1000),
        "obligationen": Decimal(360),
        "aktien": Decimal(540),
        "immobilien": Decimal(0),
        "rohstoffe": Decimal(0),
    }


def test_kurse_nur_bei_fremdwaehrungen_noetig(tmp_path):
    daten = lade_daten(schreibe(tmp_path, KONTEN, LEER))

    assert daten.kurse == {}
    assert daten.total_chf() == 0


def test_fehlender_kurs(tmp_path):
    konten = KONTEN.replace("waehrung: chf", "waehrung: usd")
    (tmp_path / "kurse.csv").write_text("datum;waehrung;kurs\n2026-10-31;EUR;0.9\n")
    with pytest.raises(FinanzDatenError, match="Kein Kurs für USD"):
        lade_daten(schreibe(tmp_path, konten, LEER))


def test_fehlende_kursdatei(tmp_path):
    konten = KONTEN.replace("waehrung: chf", "waehrung: eur")
    with pytest.raises(
        FinanzDatenError, match=r"Kein Kurs für EUR: weder online noch in kurse\.csv"
    ):
        lade_daten(schreibe(tmp_path, konten, LEER))


@pytest.mark.parametrize(
    ("kurse", "meldung"),
    [
        ("datum;waehrung;kurs\n2026-10-31;CHF;1\n", "Währung 'CHF'"),
        ("datum;waehrung;kurs\n2026-10-31;EUR;0\n", "keine positive Zahl"),
        ("datum;waehrung;kurs\n31.10.2026;EUR;0.9\n", "JJJJ-MM-TT"),
        ("datum;kurs\n", "erste Zeile"),
    ],
)
def test_ungueltige_kurse(tmp_path, kurse, meldung):
    (tmp_path / "kurse.csv").write_text(kurse, encoding="utf-8")
    with pytest.raises(FinanzDatenError, match=meldung):
        lade_daten(schreibe(tmp_path, KONTEN, LEER))


def test_waehrung_wird_normalisiert(tmp_path):
    daten = lade_daten(schreibe(tmp_path, KONTEN, "datum;konto_id;betrag\n"))

    assert daten.konten["lohnkonto"].waehrung == "CHF"
    assert daten.aktueller_saldo("lohnkonto") is None


def test_saldi_werden_nach_datum_sortiert(tmp_path):
    saldi = "datum;konto_id;betrag\n2026-10-31;lohnkonto;2\n2026-09-30;lohnkonto;1\n"
    daten = lade_daten(schreibe(tmp_path, KONTEN, saldi))

    assert [s.betrag for s in daten.saldi["lohnkonto"]] == [Decimal(1), Decimal(2)]


def test_iban_und_land(tmp_path):
    konten = KONTEN + "    iban: ch93 0076 2011 6238 5295 7\n    eigentuemer: Sie\n"
    konto = lade_daten(schreibe(tmp_path, konten, "datum;konto_id;betrag\n")).konten["lohnkonto"]

    assert konto.iban == "CH9300762011623852957"
    assert konto.land == "CH"
    assert konto.eigentuemer == "Sie"
    assert format_iban(konto.iban) == "CH93 0076 2011 6238 5295 7"


def test_anlageklasse_mit_umlaut_und_aufteilung(tmp_path):
    konten = KONTEN.replace("liquiditaet", "{Liquidität: 50.5, aktien: 49.5}")
    konto = lade_daten(schreibe(tmp_path, konten, LEER)).konten["lohnkonto"]

    assert konto.anlageklassen == {
        "liquiditaet": Decimal("0.505"),
        "aktien": Decimal("0.495"),
    }


def test_land_ohne_iban(tmp_path):
    konten = KONTEN + "    land: de\n"
    konto = lade_daten(schreibe(tmp_path, konten, "datum;konto_id;betrag\n")).konten["lohnkonto"]

    assert konto.land == "DE"
    assert konto.iban is None


def test_fehlende_datei(tmp_path):
    with pytest.raises(FinanzDatenError, match="Datei fehlt"):
        lade_daten(tmp_path)


@pytest.mark.parametrize(
    ("konten", "meldung"),
    [
        ("konten: keine_liste", "Liste unter 'konten:'"),
        (KONTEN.replace("id: lohnkonto", "id: Lohn-Konto"), "'id'"),
        (KONTEN.replace("waehrung: chf", "waehrung: GBP"), "'waehrung'"),
        (KONTEN.replace("    topf: Frei\n", ""), "'topf' fehlt"),
        (KONTEN + KONTEN.replace("konten:", ""), "doppelt"),
        (KONTEN.replace("id: lohnkonto", "id: summe_total"), "nicht mit summe_"),
        (KONTEN.replace("    anlageklasse: liquiditaet\n", ""), "'anlageklasse' fehlt"),
        (KONTEN.replace("liquiditaet", "gold"), "unbekannte Anlageklasse 'gold'"),
        (KONTEN.replace("liquiditaet", "{aktien: 60, obligationen: 30}"), "ergeben 90 %"),
        (KONTEN.replace("liquiditaet", "{aktien: viel}"), "keine Prozentzahl"),
        (KONTEN.replace("liquiditaet", "{aktien: -10, obligationen: 110}"), "keine Prozentzahl"),
        (KONTEN + "    iban: CH94 0076 2011 6238 5295 7", "'iban' ist ungültig"),
        (KONTEN + "    iban: CH93", "'iban' ist ungültig"),
        (KONTEN + "    land: Schweiz", "Ländercode"),
        (KONTEN + "    land: NO", "Anführungszeichen"),
        (KONTEN + "    iban: CH9300762011623852957\n    land: DE", "passt nicht zur IBAN"),
    ],
)
def test_ungueltige_konten(tmp_path, konten, meldung):
    with pytest.raises(FinanzDatenError, match=meldung):
        lade_daten(schreibe(tmp_path, konten, "datum;konto_id;betrag\n"))


@pytest.mark.parametrize(
    ("saldi", "meldung"),
    [
        ("datum,konto_id,betrag\n", "erste Zeile"),
        ("datum;konto_id;betrag\n31.10.2026;lohnkonto;1\n", "JJJJ-MM-TT"),
        ("datum;konto_id;betrag\n2026-10-31;unbekannt;1\n", "unbekanntes Konto"),
        ("datum;konto_id;betrag\n2026-10-31;lohnkonto;abc\n", "keine Zahl"),
        ("datum;konto_id;betrag\n2026-10-31;lohnkonto\n", "3 Werte"),
    ],
)
def test_ungueltige_saldi(tmp_path, saldi, meldung):
    with pytest.raises(FinanzDatenError, match=meldung):
        lade_daten(schreibe(tmp_path, KONTEN, saldi))


def test_alle_fehler_werden_gemeldet(tmp_path):
    saldi = "datum;konto_id;betrag\n2026-10-31;x;1\n2026-10-31;y;1\n"
    with pytest.raises(FinanzDatenError) as err:
        lade_daten(schreibe(tmp_path, KONTEN, saldi))

    assert "Zeile 2" in str(err.value)
    assert "Zeile 3" in str(err.value)


def test_online_kurse_ohne_kursdatei(tmp_path):
    konten = KONTEN.replace("waehrung: chf", "waehrung: eur")
    online = {"EUR": Kurs(date(2026, 10, 27), "EUR", Decimal("0.9239"), "EZB")}

    daten = lade_daten(schreibe(tmp_path, konten, LEER), online)

    assert daten.aktueller_kurs("EUR").quelle == "EZB"


def test_neuester_kurs_gilt_egal_woher(tmp_path):
    konten = KONTEN.replace("waehrung: chf", "waehrung: eur")
    kurse = "datum;waehrung;kurs\n2026-10-27;EUR;0.95\n2026-09-30;EUR;0.93\n"
    (tmp_path / "kurse.csv").write_text(kurse, encoding="utf-8")
    verzeichnis = schreibe(tmp_path, konten, LEER)

    # Am selben Tag hat die Datei Vorrang
    online = {"EUR": Kurs(date(2026, 10, 27), "EUR", Decimal("0.9239"), "EZB")}
    kurs = lade_daten(verzeichnis, online).aktueller_kurs("EUR")
    assert (kurs.kurs, kurs.quelle) == (Decimal("0.95"), "kurse.csv")

    # Ein neuerer Online-Kurs gewinnt, die Datei bleibt als Verlauf
    online = {"EUR": Kurs(date(2026, 10, 28), "EUR", Decimal("0.9239"), "EZB")}
    daten = lade_daten(verzeichnis, online)
    assert daten.aktueller_kurs("EUR").quelle == "EZB"
    assert len(daten.kurse["EUR"]) == 3
