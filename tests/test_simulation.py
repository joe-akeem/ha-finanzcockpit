"""Tests für die Vorsorge-Simulation (ohne Home Assistant)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from custom_components.finanzcockpit.data import FinanzDaten, FinanzDatenError, lade_daten
from custom_components.finanzcockpit.simulation import (
    Einkauf,
    Phase,
    Simulation,
    lade_simulation,
    mit_anpassungen,
    regler_wert,
    simuliere,
)

EXAMPLES = Path(__file__).parent.parent / "examples"
LEER = FinanzDaten(konten={}, saldi={}, kurse={})

# Kleines Modell mit runden Zahlen, damit sich Erwartungen von Hand rechnen lassen
BASIS: dict[str, Any] = {
    "personen": {
        "er": {"geburtsjahr": 1970, "lohn": 100000, "planungsalter": 85},
        "sie": {"geburtsjahr": 1975, "lohn": 80000},
    },
    "wirtschaft": {"lohnwachstum": 0, "teuerung": 0, "sozialabzuege": 10, "kurs_eur": 1},
    "lebenshaltung": {"heute": 50000, "kinder_selbstaendig": 50000, "ruhestand": 40000},
    "ahv": {"rente_er": 2000, "rente_sie": 2000, "dreizehnte": False},
    "pk": {
        "verzinsung": 0,
        "witwenrente": 60,
        "er": {"prognose_kapital": 0, "prognose_jahr": 2035, "umwandlungssatz": 5},
        "sie": {"prognose_kapital": 0, "prognose_jahr": 2040, "umwandlungssatz": 5},
    },
    "steuern": {
        "grenzsatz_kanton": 10,
        "grenzsatz_bund": 0,
        "steuern_heute": 0,
        "einkommen_heute": 0,
    },
    "startwerte": {"jahr": 2026, "frei": {"wert": 100000}},
    "szenarien": [
        {
            "id": "basis",
            "name": "Basis",
            "pension": {"er": 2035, "sie": 2040},
            "pensum": {"er": [{"ab": 2026, "wert": 100}], "sie": [{"ab": 2026, "wert": 50}]},
            "saeule3a_maximal": False,
        }
    ],
}


def lade(tmp_path: Path, daten: FinanzDaten = LEER, **aenderungen: Any) -> Simulation:
    """Schreibt BASIS mit Änderungen (Pfad mit Punkten) und liest sie ein."""
    inhalt = yaml.safe_load(yaml.safe_dump(BASIS))
    for pfad, wert in aenderungen.items():
        *eltern, name = pfad.split("__")
        ziel = inhalt
        for teil in eltern:
            ziel = ziel[int(teil)] if isinstance(ziel, list) else ziel.setdefault(teil, {})
        ziel[name] = wert
    datei = tmp_path / "simulation.yaml"
    datei.write_text(yaml.safe_dump(inhalt, allow_unicode=True), encoding="utf-8")
    return lade_simulation(datei, daten)


def rechne(sim: Simulation, **szenario: Any):
    s = replace(sim.szenarien[sim.aktives_szenario], **szenario)
    return simuliere(sim.annahmen, s, sim.startwerte)


def test_beispiel_startwerte_aus_konten():
    sim = lade_daten(EXAMPLES).simulation

    assert sim is not None
    start = sim.startwerte
    assert start.jahr == 2026
    # Lohnkonto + Festgeld (EUR in CHF) + Depot (USD in CHF) - zweckgebunden
    assert start.frei == pytest.approx(11805.40 + 18640.00 + 12169.50 - 5000)
    assert start.saeule3a_er == pytest.approx(18400.50)
    # Saldo per 1.1.2026 gilt als Stand Ende 2025
    assert (start.pk_er, start.pk_er_jahr) == (96000, 2025)
    assert (start.pk_sie, start.pk_sie_jahr) == (48000, 2025)
    assert (start.liegenschaft, start.hypothek) == (780000, 455000)
    assert sim.aktives_szenario == "teilzeit"

    for szenario in sim.szenarien.values():
        ergebnis = simuliere(sim.annahmen, szenario, start)
        assert ergebnis.jahre[0].jahr == 2027
        assert ergebnis.jahre[-1].jahr == 1983 + 95


def test_lohn_und_pensum(tmp_path):
    sim = lade(tmp_path)
    s = sim.szenarien["basis"]
    ergebnis = rechne(sim, pensum_er=(Phase(2026, 1.0), Phase(2030, 0.8)))

    assert ergebnis.jahr(2029).lohn_er == 100000
    assert ergebnis.jahr(2030).lohn_er == 80000
    assert ergebnis.jahr(2035).lohn_er == 0  # pensioniert
    assert ergebnis.jahr(2027).lohn_sie == 40000
    assert ergebnis.jahr(2027).erwerb_netto == pytest.approx((100000 + 40000) * 0.9)
    assert s.pensum_sie[0].wert == 0.5


def test_ahv_plafond_und_vorbezug(tmp_path):
    sim = lade(tmp_path, ahv__plafond=40000)
    ergebnis = rechne(sim, ahv_alter_er=63)

    # Er bezieht ab 63 (2033) mit 2 x 6.8 % Kürzung, allein unter dem Plafond
    assert ergebnis.jahr(2033).ahv == pytest.approx(24000 * (1 - 2 * 0.068))
    # Ab 2040 beide: Summe 48'000 auf 40'000 begrenzt, Kürzung anteilig
    gewichtet = (24000 * (1 - 2 * 0.068) + 24000) / 48000
    assert ergebnis.jahr(2040).ahv == pytest.approx(40000 * gewichtet)


def test_witwenphase(tmp_path):
    sim = lade(tmp_path)
    ergebnis = rechne(sim)

    lebt, witwe = ergebnis.jahr(2055), ergebnis.jahr(2056)  # Er wird 2056 86
    assert lebt.er_lebt and not witwe.er_lebt
    # Eigene AHV plus 20 % Zuschlag, höchstens die Maximalrente
    assert witwe.ahv == pytest.approx(min(24000 * 1.2, 30240))
    assert witwe.lebenshaltung == pytest.approx(40000 * 0.75)
    assert witwe.pk_renten == pytest.approx(lebt.pk_rente_er * 0.6 + lebt.pk_rente_sie)


def test_pk_prognose_wird_erreicht(tmp_path):
    """Die zurückgerechnete Altersgutschrift ergibt genau das prognostizierte Kapital."""
    sim = lade(
        tmp_path,
        pk__verzinsung=2,
        pk__er={"prognose_kapital": 500000, "prognose_jahr": 2035, "umwandlungssatz": 6},
        startwerte__pk_er={"wert": 200000, "jahr": 2024},
    )
    ergebnis = rechne(sim, kapitalbezug_er=0.25)

    jahr = ergebnis.jahr(2035)
    assert jahr.pk_kapital_er == pytest.approx(500000 * 0.25)
    assert jahr.pk_rente_er == pytest.approx(500000 * 0.75 * 0.06)
    assert ergebnis.jahr(2034).pk_er > 0
    assert jahr.pk_er == 0


def test_freizuegigkeit_vor_58(tmp_path):
    sim = lade(
        tmp_path, pk__sie={"prognose_kapital": 0, "prognose_jahr": 2040, "umwandlungssatz": 5}
    )
    ergebnis = rechne(sim, pension_sie=2030)  # Sie ist 55

    # Bezug erst mit 60, dann zwingend als Kapital
    assert ergebnis.pk_bezug_sie == 1975 + 60
    assert ergebnis.jahr(2035).pk_rente_sie == 0


def test_umwandlungssatz_bei_vorbezug(tmp_path):
    sim = lade(
        tmp_path,
        pk__er={
            "prognose_kapital": 100000,
            "prognose_jahr": 2033,
            "umwandlungssatz": 5.6,
            "reduktion_pro_jahr": 0.2,
        },
        startwerte__pk_er={"wert": 100000, "jahr": 2026},
    )
    ergebnis = rechne(sim, pension_er=2032)  # mit 62

    # 3 Jahre vor 65: 5.6 % - 3 x 0.2 Punkte = 5.0 % (ohne Zins bleibt das Guthaben 100'000)
    assert ergebnis.jahr(2031).pk_er == pytest.approx(100000)
    assert ergebnis.jahr(2032).pk_rente_er == pytest.approx(5000)


def test_einkauf_begrenzt_und_sperrfrist(tmp_path):
    sim = lade(
        tmp_path,
        pk__er={
            "prognose_kapital": 0,
            "prognose_jahr": 2035,
            "umwandlungssatz": 5,
            "einkaufspotenzial": 50000,
        },
    )
    ergebnis = rechne(sim, einkauf_er=Einkauf(20000, 2028, 2032), kapitalbezug_er=0.5)

    einkaeufe = [ergebnis.jahr(j).einkauf_er for j in range(2028, 2033)]
    assert einkaeufe == [20000, 20000, 10000, 0, 0]
    # 2032 liegt weniger als 3 Jahre vor dem Kapitalbezug 2035
    assert not ergebnis.sperrfrist_ok
    assert rechne(sim, einkauf_er=Einkauf(20000, 2028, 2031), kapitalbezug_er=0.5).sperrfrist_ok
    assert rechne(sim, einkauf_er=Einkauf(20000, 2028, 2032)).sperrfrist_ok  # nur Rente


def test_hypothek(tmp_path):
    sim = lade(
        tmp_path,
        immobilie={
            "hypozins": [{"bis": 2029, "satz": 1}, {"satz": 2}],
            "tragbarkeit": {"zins": 5, "nebenkosten": 1, "maximum": 33},
        },
        startwerte__liegenschaft={"wert": 1000000},
        startwerte__hypothek={"wert": -600000},
    )
    ergebnis = rechne(sim, amortisation_bis_pension=10000, amortisation_bei_pension_er=100000)

    assert ergebnis.jahr(2027).hypothekarzins == pytest.approx(6000)
    assert ergebnis.jahr(2030).hypothekarzins == pytest.approx(570000 * 0.02)
    assert ergebnis.jahr(2034).hypothek == 520000
    assert ergebnis.jahr(2035).hypothek == 420000
    assert ergebnis.belehnung_pension_er == pytest.approx(0.42)
    j = ergebnis.jahr(ergebnis.beide_pensioniert)
    assert ergebnis.tragbarkeit == pytest.approx((420000 * 0.05 + 1000000 * 0.01) / j.renten)


def test_steuern_auf_heute_kalibriert(tmp_path):
    sim = lade(
        tmp_path,
        steuern={
            "grenzsatz_kanton": 15,
            "grenzsatz_bund": 5,
            "steuern_heute": 20000,
            "einkommen_heute": 120000,
            "stufe2_ab": 1000000,
        },
    )
    ergebnis = rechne(sim)
    j = ergebnis.jahr(2027)

    # Ab der Schwelle 120'000 - 20'000/20 % wird mit dem Grenzsatz besteuert
    schwelle = 120000 - 20000 / 0.2
    assert j.steuerbares_einkommen == pytest.approx(140000 * 0.9)
    assert j.steuern == pytest.approx((140000 * 0.9 - schwelle) * 0.2)


def test_freies_vermoegen(tmp_path):
    sim = lade(
        tmp_path, anlagen={"liquiditaetsreserve": 50000, "zins_liquiditaet": 1, "rendite_frei": 4}
    )
    j = rechne(sim).jahr(2027)

    assert j.anlageertrag == pytest.approx(50000 * 0.01 + 50000 * 0.04)
    assert j.frei == pytest.approx(100000 + j.anlageertrag + j.einnahmen - j.ausgaben)


def test_regler():
    sim = lade_daten(EXAMPLES).simulation
    s = sim.szenarien["teilzeit"]

    assert regler_wert(s, "pensum_er") == 80
    assert regler_wert(s, "pensum_er_ab") == 2030
    assert regler_wert(s, "kapitalbezug_sie") == 100
    assert regler_wert(s, "einkauf_er") == 20000

    angepasst = mit_anpassungen(s, {"pensum_er": 60, "pensum_er_ab": 2032, "einkauf_er": 0})
    assert angepasst.pensum_er == (Phase(2026, 1.0), Phase(2032, 0.6))
    assert angepasst.einkauf_er == Einkauf(0, 2028, 2033)

    # Mit nur einer Phase legt «ab Jahr» eine zweite Phase an
    status_quo = sim.szenarien["status_quo"]
    einzeln = mit_anpassungen(status_quo, {"pensum_er": 70, "pensum_er_ab": 2031})
    assert einzeln.pensum_er == (Phase(2026, 1.0), Phase(2031, 0.7))


@pytest.mark.parametrize(
    ("aenderungen", "meldung"),
    [
        ({"unbekannt": 1}, "simulation.yaml, unbekannt: unbekannter Eintrag"),
        ({"personen__er__lohn": "viel"}, "personen.er.lohn: muss eine Zahl sein"),
        ({"wirtschaft__teuerung": 150}, "wirtschaft.teuerung: darf höchstens 100 sein"),
        ({"szenarien__0__pension": {"er": 2035}}, "szenarien.0.pension.sie: fehlt"),
        ({"aktives_szenario": "x"}, "aktives_szenario 'x' gibt es nicht"),
        ({"startwerte__frei": {"konten": ["gibts_nicht"]}}, "unbekanntes Konto 'gibts_nicht'"),
        ({"startwerte__frei": {"toepfe": ["Leer"]}}, "kein Konto im Topf 'Leer'"),
        ({"ahv__dreizehnte": "ja"}, "ahv.dreizehnte: muss true oder false sein"),
    ],
)
def test_fehler(tmp_path, aenderungen, meldung):
    with pytest.raises(FinanzDatenError, match=meldung):
        lade(tmp_path, **aenderungen)


def test_konto_doppelt_verwendet(tmp_path):
    daten = lade_daten(EXAMPLES)
    with pytest.raises(FinanzDatenError, match=r"'lohnkonto' ist schon in startwerte\.frei"):
        lade(
            tmp_path,
            daten,
            startwerte__frei={"toepfe": ["Frei verfügbar"]},
            startwerte__saeule3a_er={"konten": ["lohnkonto"]},
        )


def test_simulation_ist_optional(tmp_path):
    for datei in ("konten.yaml", "saldi.csv", "kurse.csv"):
        (tmp_path / datei).write_bytes((EXAMPLES / datei).read_bytes())

    assert lade_daten(tmp_path).simulation is None
