"""Vorsorge-Simulation: Jahr für Jahr bis ins hohe Alter.

Bildet das Rechenmodell aus «Vorsorgeplanung.numbers» (Blätter «Eingaben»
und «Proj Sx») nach: Lohn, Säule 3a, Pensionskasse mit Einkauf und
Umwandlungssatz, AHV mit Plafond und Vorbezug, deutsche Rente und Policen,
Hypothek mit Tragbarkeit, Steuern und die Witwenphase.

Wie data.py ohne Abhängigkeit zu Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import voluptuous as vol
import yaml

from .data import FinanzDaten, FinanzDatenError

# Gesetzliche Eckwerte, die im Modell fest sind
ALTER_REFERENZ = 65
ALTER_PK_FREIZUEGIGKEIT = 58  # Austritt davor: Freizügigkeit, Bezug mit 60 als Kapital
ALTER_FRUEHESTER_BEZUG = 60
MIN_UMWANDLUNGSSATZ = 0.03
SPERRFRIST_EINKAUF = 3
WITWENRENTE_AHV_FAKTOR = 1.2  # Witwe: eigene Rente plus Verwitwetenzuschlag 20 %
ALTER_SIE_ENDE = 95
ALTER_ER_KENNZAHL = 85

STARTWERTE = [
    "frei",
    "saeule3a_er",
    "saeule3a_sie",
    "pk_er",
    "pk_sie",
    "de_policen",
    "de_fonds",
    "liegenschaft",
    "hypothek",
    "darlehen",
]


# --- Eingaben ---------------------------------------------------------------


@dataclass(frozen=True)
class PK:
    """Pensionskasse einer Person."""

    prognose_kapital: float
    prognose_jahr: int
    prognose_pensum: float
    umwandlungssatz: float
    reduktion_pro_jahr: float
    einkaufspotenzial: float
    zusatzsparkonto: float = 0.0


@dataclass(frozen=True)
class Annahmen:
    """Alle Annahmen ausser den Szenarien; Prozentwerte als Bruchteil."""

    geburtsjahr_er: int
    geburtsjahr_sie: int
    planungsalter_er: int
    lohn_er: float
    lohn_sie: float
    lohnwachstum: float
    teuerung: float
    sozialabzuege: float
    kurs_eur: float
    liquiditaetsreserve: float
    zins_liquiditaet: float
    rendite_frei: float
    zins_negativ: float
    rendite_3a: float
    lebenshaltung_heute: float
    lebenshaltung_kinder_selbstaendig: float
    lebenshaltung_ruhestand: float
    kinder_selbstaendig_ab: int
    faktor_nach_tod: float
    ahv_er: float  # pro Jahr, ohne 13.
    ahv_sie: float
    ahv_plafond: float
    ahv_max_einzelrente: float
    ahv_dreizehnte: bool
    ahv_kuerzung_vorbezug: float
    ahv_beitrag_nichterwerbstaetige: float
    pk_verzinsung: float
    pk_witwenrente: float
    pk_er: PK
    pk_sie: PK
    saeule3a_maximalbetrag: float
    de_rente_monat_eur: float
    de_rente_ab: int
    de_anpassung: float
    de_witwenrente: float
    de_policen_auszahlung: int
    de_fonds_rendite: float
    wertsteigerung: float
    hypozins: tuple[tuple[int | None, float], ...]  # (bis Jahr, Satz)
    darlehen_rueckzahlung: int
    eigenmietwert: float
    unterhaltspauschale: float
    eigenmietwert_abgeschafft_ab: int
    tragbarkeit_zins: float
    tragbarkeit_nebenkosten: float
    tragbarkeit_maximum: float
    tragbarkeit_vermoegen_jahre: int
    grenzsatz_kanton: float
    grenzsatz_bund: float
    steuern_heute: float
    einkommen_heute: float
    steuer_stufe2_ab: float
    abzuege: float
    abzuege_faktor_spaeter: float
    vermoegenssteuer: float
    kapitalbezugssteuer: float
    auto_naechster: int
    auto_alle: int
    auto_preis: float
    auto_letzter: int
    dach_jahr: int
    dach_kosten: float
    erbschaft_jahr: int
    erbschaft_betrag: float
    unterhalt: tuple[tuple[float, int], ...]  # (CHF pro Monat, bis Jahr)

    @property
    def grenzsatz(self) -> float:
        return self.grenzsatz_kanton + self.grenzsatz_bund


@dataclass(frozen=True)
class Phase:
    """Ab diesem Jahr gilt dieses Pensum (Bruchteil)."""

    ab: int
    wert: float


@dataclass(frozen=True)
class Einkauf:
    """PK-Einkauf pro Jahr in einem Zeitraum."""

    betrag: float = 0.0
    von: int = 0
    bis: int = 0


@dataclass(frozen=True)
class Szenario:
    """Die Entscheide, die sich zwischen den Szenarien unterscheiden."""

    id: str
    name: str
    pension_er: int  # erstes Jahr ohne Erwerb
    pension_sie: int
    pensum_er: tuple[Phase, ...]
    pensum_sie: tuple[Phase, ...]
    ahv_alter_er: int = ALTER_REFERENZ
    ahv_alter_sie: int = ALTER_REFERENZ
    kapitalbezug_er: float = 0.0
    kapitalbezug_sie: float = 0.0
    einkauf_er: Einkauf = field(default_factory=Einkauf)
    einkauf_sie: Einkauf = field(default_factory=Einkauf)
    saeule3a_maximal: bool = True
    amortisation_bis_pension: float = 0.0
    amortisation_nach_pension: float = 0.0
    amortisation_bei_pension_er: float = 0.0
    amortisation_bei_pension_sie: float = 0.0
    sonderamortisationen: tuple[tuple[int, float], ...] = ()


@dataclass(frozen=True)
class Startwerte:
    """Stand am Ende des Startjahrs; alle Beträge in CHF, Schulden positiv."""

    jahr: int
    frei: float
    saeule3a_er: float
    saeule3a_sie: float
    pk_er: float
    pk_er_jahr: int  # Stand des PK-Guthabens (Ende dieses Jahres)
    pk_sie: float
    pk_sie_jahr: int
    de_policen: float
    de_fonds: float
    liegenschaft: float
    hypothek: float
    darlehen: float


@dataclass(frozen=True)
class Simulation:
    """Inhalt von simulation.yaml mit aufgelösten Startwerten."""

    annahmen: Annahmen
    startwerte: Startwerte
    szenarien: dict[str, Szenario]
    aktives_szenario: str


# --- Ergebnis ---------------------------------------------------------------


@dataclass(frozen=True)
class Jahr:
    """Eine Zeile im Blatt «Proj Sx»; Beträge nominal in CHF."""

    jahr: int
    alter_er: int
    alter_sie: int
    er_lebt: bool
    er_erwerbstaetig: bool
    sie_erwerbstaetig: bool
    pensum_er: float
    pensum_sie: float
    preisindex: float
    lohn_er: float
    lohn_sie: float
    erwerb_netto: float
    einzahlung_3a_er: float
    einzahlung_3a_sie: float
    saeule3a_er: float
    bezug_3a_er: float
    saeule3a_sie: float
    bezug_3a_sie: float
    einkauf_er: float
    pk_er: float
    pk_rente_er: float
    pk_kapital_er: float
    einkauf_sie: float
    pk_sie: float
    pk_rente_sie: float
    pk_kapital_sie: float
    ahv: float
    pk_renten: float
    de_rente: float
    renten: float
    kapitalbezuege_netto: float
    lebenshaltung: float
    unterhalt: float
    auto: float
    dach: float
    erbschaft: float
    ahv_beitraege: float
    hypozins: float
    hypothekarzins: float
    amortisation: float
    hypothek: float
    darlehen_rueckzahlung: float
    darlehen: float
    steuerbares_einkommen: float
    steuern: float
    anlageertrag: float
    einnahmen: float
    ausgaben: float
    saldo: float
    frei: float
    liegenschaft: float
    belehnung: float
    tragbarkeit: float
    nettovermoegen: float

    @property
    def frei_real(self) -> float:
        """Freies Vermögen in heutigen CHF."""
        return self.frei / self.preisindex

    @property
    def renten_real(self) -> float:
        return self.renten / self.preisindex

    @property
    def laufende_ausgaben_real(self) -> float:
        """Laufende Ausgaben ohne Sparen und Amortisation, heutige CHF."""
        laufend = (
            self.lebenshaltung
            + self.unterhalt
            + self.ahv_beitraege
            + self.hypothekarzins
            + self.steuern
        )
        return laufend / self.preisindex


@dataclass(frozen=True)
class Ergebnis:
    """Kennzahlen eines Szenarios (Blatt «Proj Sx», Spalte E)."""

    szenario: Szenario
    jahre: tuple[Jahr, ...]
    beide_pensioniert: int  # erstes Jahr, in dem alle Renten fliessen
    pk_bezug_er: int
    pk_bezug_sie: int
    renten_rentnerjahr: float | None
    ausgaben_rentnerjahr: float | None
    frei_pension_er: float | None
    frei_pension_sie: float | None
    frei_er_85: float | None
    frei_ende: float
    tiefster_stand: float
    tiefster_stand_jahr: int
    erstes_negatives_jahr: int | None
    hypothek_pension_er: float | None
    hypothek_pension_sie: float | None
    belehnung_pension_er: float | None
    tragbarkeit: float | None
    tragbarkeit_ok: bool
    sperrfrist_ok: bool
    steuern_summe: float
    nettovermoegen_ende: float

    @property
    def vorsorgeluecke(self) -> float | None:
        """Ausgaben minus Renten pro Jahr in heutigen CHF, mindestens 0."""
        if self.renten_rentnerjahr is None or self.ausgaben_rentnerjahr is None:
            return None
        return max(0.0, self.ausgaben_rentnerjahr - self.renten_rentnerjahr)

    def jahr(self, jahr: int) -> Jahr | None:
        erstes = self.jahre[0].jahr
        return self.jahre[jahr - erstes] if 0 <= jahr - erstes < len(self.jahre) else None


# --- Rechnung ---------------------------------------------------------------


def _pensum(phasen: tuple[Phase, ...], jahr: int) -> float:
    """Pensum im Jahr; die erste Phase gilt auch vor ihrem Beginn."""
    wert = phasen[0].wert
    for phase in phasen:
        if jahr >= phase.ab:
            wert = phase.wert
    return wert


def _hypozins(a: Annahmen, jahr: int) -> float:
    for bis, satz in a.hypozins:
        if bis is None or jahr <= bis:
            return satz
    return a.hypozins[-1][1]


def _altersgutschrift(a: Annahmen, pk: PK, guthaben: float, stand: int) -> float:
    """Jährliche Altersgutschrift bei 100 %, zurückgerechnet aus der Prognose.

    Das Guthaben wächst vom Stand bis ins Jahr vor der Prognose mit Zins und
    Gutschriften; im Prognosejahr kommt noch ein Jahr Zins dazu.
    """
    zins = a.pk_verzinsung
    jahre = pk.prognose_jahr - 1 - stand
    if jahre <= 0:
        return 0.0
    faktor = (1 + zins) ** jahre
    rente = (faktor - 1) / zins if zins else jahre
    luecke = pk.prognose_kapital / (1 + zins) - guthaben * faktor
    return max(0.0, luecke / (pk.prognose_pensum * rente))


def _fortschreiben(a: Annahmen, guthaben: float, gutschrift: float, jahre: int) -> float:
    """PK-Guthaben über mehrere Jahre mit gleichbleibender Gutschrift."""
    zins = a.pk_verzinsung
    if jahre <= 0:
        return guthaben
    faktor = (1 + zins) ** jahre
    return guthaben * faktor + gutschrift * ((faktor - 1) / zins if zins else jahre)


def simuliere(a: Annahmen, s: Szenario, start: Startwerte) -> Ergebnis:  # noqa: PLR0915
    """Rechnet ein Szenario Jahr für Jahr bis Sie 95 ist."""
    basis = start.jahr
    # Abgeleitete Werte (Blatt «Proj Sx», Zeilen 30 bis 40)
    frueh_er = s.pension_er < a.geburtsjahr_er + ALTER_PK_FREIZUEGIGKEIT
    frueh_sie = s.pension_sie < a.geburtsjahr_sie + ALTER_PK_FREIZUEGIGKEIT
    pk_bezug_er = a.geburtsjahr_er + ALTER_FRUEHESTER_BEZUG if frueh_er else s.pension_er
    pk_bezug_sie = a.geburtsjahr_sie + ALTER_FRUEHESTER_BEZUG if frueh_sie else s.pension_sie
    kapital_er = 1.0 if frueh_er else s.kapitalbezug_er
    kapital_sie = 1.0 if frueh_sie else s.kapitalbezug_sie
    uws_er = max(
        MIN_UMWANDLUNGSSATZ,
        a.pk_er.umwandlungssatz
        - a.pk_er.reduktion_pro_jahr * max(0, ALTER_REFERENZ - (pk_bezug_er - a.geburtsjahr_er)),
    )
    uws_sie = max(
        MIN_UMWANDLUNGSSATZ,
        a.pk_sie.umwandlungssatz
        - a.pk_sie.reduktion_pro_jahr * max(0, ALTER_REFERENZ - (pk_bezug_sie - a.geburtsjahr_sie)),
    )
    bezug_3a_er = max(s.pension_er, a.geburtsjahr_er + ALTER_FRUEHESTER_BEZUG)
    bezug_3a_sie = max(s.pension_sie, a.geburtsjahr_sie + ALTER_FRUEHESTER_BEZUG)
    ahv_ab_er = a.geburtsjahr_er + s.ahv_alter_er
    ahv_ab_sie = a.geburtsjahr_sie + s.ahv_alter_sie
    beide = max(s.pension_er, s.pension_sie, pk_bezug_sie, ahv_ab_sie, ahv_ab_er)
    kuerzung_er = 1 - a.ahv_kuerzung_vorbezug * max(0, ALTER_REFERENZ - s.ahv_alter_er)
    kuerzung_sie = 1 - a.ahv_kuerzung_vorbezug * max(0, ALTER_REFERENZ - s.ahv_alter_sie)
    steuer_schwelle = a.einkommen_heute - a.steuern_heute / a.grenzsatz

    gutschrift_er = _altersgutschrift(a, a.pk_er, start.pk_er, start.pk_er_jahr)
    gutschrift_sie = _altersgutschrift(a, a.pk_sie, start.pk_sie, start.pk_sie_jahr)

    # Stand Ende Startjahr
    p3a_er, p3a_sie = start.saeule3a_er, start.saeule3a_sie
    pk_er = _fortschreiben(
        a, start.pk_er, gutschrift_er * a.pk_er.prognose_pensum, basis - start.pk_er_jahr
    )
    pk_sie = _fortschreiben(
        a, start.pk_sie, gutschrift_sie * a.pk_sie.prognose_pensum, basis - start.pk_sie_jahr
    )
    eingekauft_er = eingekauft_sie = 0.0
    rente_er = rente_sie = 0.0
    hypothek, darlehen, frei = start.hypothek, start.darlehen, start.frei

    jahre: list[Jahr] = []
    for jahr in range(basis + 1, a.geburtsjahr_sie + ALTER_SIE_ENDE + 1):
        alter_er, alter_sie = jahr - a.geburtsjahr_er, jahr - a.geburtsjahr_sie
        lebt = alter_er <= a.planungsalter_er
        erw_er, erw_sie = jahr < s.pension_er, jahr < s.pension_sie
        pensum_er = _pensum(s.pensum_er, jahr) if erw_er else 0.0
        pensum_sie = _pensum(s.pensum_sie, jahr) if erw_sie else 0.0
        lohnindex = (1 + a.lohnwachstum) ** (jahr - basis)
        preisindex = (1 + a.teuerung) ** (jahr - basis)

        lohn_er = a.lohn_er * pensum_er * lohnindex
        lohn_sie = a.lohn_sie * pensum_sie * lohnindex
        erwerb = (lohn_er + lohn_sie) * (1 - a.sozialabzuege)

        # Säule 3a
        max_3a = a.saeule3a_maximalbetrag * preisindex
        ein_3a_er = max_3a if erw_er and s.saeule3a_maximal else 0.0
        ein_3a_sie = max_3a if erw_sie and s.saeule3a_maximal and lohn_sie > max_3a else 0.0
        aus_3a_er = p3a_er * (1 + a.rendite_3a) if jahr == bezug_3a_er else 0.0
        aus_3a_sie = p3a_sie * (1 + a.rendite_3a) if jahr == bezug_3a_sie else 0.0
        p3a_er = 0.0 if jahr >= bezug_3a_er else p3a_er * (1 + a.rendite_3a) + ein_3a_er
        p3a_sie = 0.0 if jahr >= bezug_3a_sie else p3a_sie * (1 + a.rendite_3a) + ein_3a_sie

        # Pensionskasse
        e = s.einkauf_er
        einkauf_er = (
            min(e.betrag, max(0.0, a.pk_er.einkaufspotenzial - eingekauft_er))
            if erw_er and e.von <= jahr <= e.bis
            else 0.0
        )
        eingekauft_er += einkauf_er
        bei_bezug_er = pk_er * (1 + a.pk_verzinsung) if jahr == pk_bezug_er else 0.0
        if jahr == pk_bezug_er:
            rente_er = bei_bezug_er * (1 - kapital_er) * uws_er
        pk_kapital_er = bei_bezug_er * kapital_er
        pk_er = (
            0.0
            if jahr >= pk_bezug_er
            else pk_er * (1 + a.pk_verzinsung) + gutschrift_er * pensum_er * lohnindex + einkauf_er
        )

        e = s.einkauf_sie
        potenzial_sie = a.pk_sie.einkaufspotenzial + a.pk_sie.zusatzsparkonto
        einkauf_sie = (
            min(e.betrag, max(0.0, potenzial_sie - eingekauft_sie))
            if erw_sie and e.von <= jahr <= e.bis
            else 0.0
        )
        eingekauft_sie += einkauf_sie
        bei_bezug_sie = pk_sie * (1 + a.pk_verzinsung) if jahr == pk_bezug_sie else 0.0
        if jahr == pk_bezug_sie:
            rente_sie = bei_bezug_sie * (1 - kapital_sie) * uws_sie
        pk_kapital_sie = bei_bezug_sie * kapital_sie
        pk_sie = (
            0.0
            if jahr >= pk_bezug_sie
            else pk_sie * (1 + a.pk_verzinsung)
            + gutschrift_sie * pensum_sie * lohnindex
            + einkauf_sie
        )

        # AHV: Ehepaar-Plafond, Vorbezug; als Witwe mit Zuschlag bis zur Maximalrente
        ahv_er = a.ahv_er if jahr >= ahv_ab_er else 0.0
        ahv_sie = a.ahv_sie if jahr >= ahv_ab_sie else 0.0
        if lebt:
            ahv = (
                min(ahv_er + ahv_sie, a.ahv_plafond)
                * (ahv_er * kuerzung_er + ahv_sie * kuerzung_sie)
                / (ahv_er + ahv_sie)
                if ahv_er + ahv_sie
                else 0.0
            )
        else:
            ahv = (
                min(ahv_sie * WITWENRENTE_AHV_FAKTOR, a.ahv_max_einzelrente) * kuerzung_sie
                if ahv_sie
                else 0.0
            )
        ahv *= preisindex * (13 / 12 if a.ahv_dreizehnte else 1)

        pk_renten = rente_er * (1 if lebt else a.pk_witwenrente) + rente_sie
        de_rente = (
            a.de_rente_monat_eur
            * 12
            * a.kurs_eur
            * (1 + a.de_anpassung) ** (jahr - basis)
            * (1 if lebt else a.de_witwenrente)
            if jahr >= a.de_rente_ab
            else 0.0
        )
        renten = ahv + pk_renten + de_rente
        policen = (
            start.de_policen
            + start.de_fonds * (1 + a.de_fonds_rendite) ** (a.de_policen_auszahlung - basis)
            if jahr == a.de_policen_auszahlung
            else 0.0
        )
        kapital_netto = (aus_3a_er + aus_3a_sie + pk_kapital_er + pk_kapital_sie + policen) * (
            1 - a.kapitalbezugssteuer
        )

        # Ausgaben
        ruhestand = not erw_er and not erw_sie
        if ruhestand:
            budget = a.lebenshaltung_ruhestand
        elif jahr >= a.kinder_selbstaendig_ab:
            budget = a.lebenshaltung_kinder_selbstaendig
        else:
            budget = a.lebenshaltung_heute
        lebenshaltung = preisindex * budget * (1 if lebt else a.faktor_nach_tod)
        unterhalt = 12 * sum(betrag for betrag, bis in a.unterhalt if jahr <= bis)
        auto = (
            a.auto_preis * preisindex
            if a.auto_naechster <= jahr <= a.auto_letzter
            and (jahr - a.auto_naechster) % a.auto_alle == 0
            else 0.0
        )
        dach = a.dach_kosten * preisindex if jahr == a.dach_jahr else 0.0
        erbschaft = a.erbschaft_betrag if jahr == a.erbschaft_jahr else 0.0
        ahv_beitraege = (
            ((alter_er < ALTER_REFERENZ) + (alter_sie < ALTER_REFERENZ))
            * a.ahv_beitrag_nichterwerbstaetige
            * preisindex
            if ruhestand
            else 0.0
        )

        # Hypothek und Darlehen
        satz = _hypozins(a, jahr)
        hypothekarzins = hypothek * satz
        amortisation = min(
            hypothek,
            (s.amortisation_bis_pension if jahr < s.pension_er else s.amortisation_nach_pension)
            + sum(betrag for j, betrag in s.sonderamortisationen if j == jahr)
            + (s.amortisation_bei_pension_er if jahr == s.pension_er else 0.0)
            + (s.amortisation_bei_pension_sie if jahr == s.pension_sie else 0.0),
        )
        hypothek -= amortisation
        rueckzahlung = darlehen if jahr == a.darlehen_rueckzahlung else 0.0
        darlehen -= rueckzahlung

        # Steuern (lineares Modell, auf heute kalibriert)
        eigenmietwert = (
            a.eigenmietwert * preisindex * (1 - a.unterhaltspauschale) - hypothekarzins
            if jahr < a.eigenmietwert_abgeschafft_ab
            else 0.0
        )
        abzuege = (
            a.abzuege
            * preisindex
            * (a.abzuege_faktor_spaeter if jahr >= a.kinder_selbstaendig_ab or ruhestand else 1)
        )
        steuerbar = max(
            0.0,
            erwerb
            + renten
            - ein_3a_er
            - ein_3a_sie
            - einkauf_er
            - einkauf_sie
            - unterhalt
            + eigenmietwert
            - abzuege,
        )
        stufe2 = a.steuer_stufe2_ab * preisindex
        steuern = (
            max(0.0, min(steuerbar, stufe2) - steuer_schwelle * preisindex) * a.grenzsatz
            + max(0.0, steuerbar - stufe2) * a.grenzsatz
            + max(0.0, frei) * a.vermoegenssteuer
        )

        # Freies Vermögen: Reserve zum Liquiditätszins, Rest zur Anlagerendite
        reserve = a.liquiditaetsreserve * preisindex
        ertrag = (
            min(max(frei, 0.0), reserve) * a.zins_liquiditaet
            + max(frei - reserve, 0.0) * a.rendite_frei
            + min(frei, 0.0) * a.zins_negativ
        )
        einnahmen = erwerb + renten + kapital_netto + erbschaft
        ausgaben = (
            lebenshaltung
            + unterhalt
            + auto
            + dach
            + ahv_beitraege
            + hypothekarzins
            + amortisation
            + rueckzahlung
            + steuern
            + ein_3a_er
            + ein_3a_sie
            + einkauf_er
            + einkauf_sie
        )
        frei += ertrag + einnahmen - ausgaben

        liegenschaft = start.liegenschaft * (1 + a.wertsteigerung) ** (jahr - basis)
        einkommen = lohn_er + lohn_sie + renten
        if einkommen:
            vermoegen = (
                max(0.0, frei) / a.tragbarkeit_vermoegen_jahre
                if a.tragbarkeit_vermoegen_jahre > 0
                else 0.0
            )
            tragbarkeit = (
                hypothek * a.tragbarkeit_zins + liegenschaft * a.tragbarkeit_nebenkosten
            ) / (einkommen + vermoegen)
        else:
            tragbarkeit = 0.0

        jahre.append(
            Jahr(
                jahr=jahr,
                alter_er=alter_er,
                alter_sie=alter_sie,
                er_lebt=lebt,
                er_erwerbstaetig=erw_er,
                sie_erwerbstaetig=erw_sie,
                pensum_er=pensum_er,
                pensum_sie=pensum_sie,
                preisindex=preisindex,
                lohn_er=lohn_er,
                lohn_sie=lohn_sie,
                erwerb_netto=erwerb,
                einzahlung_3a_er=ein_3a_er,
                einzahlung_3a_sie=ein_3a_sie,
                saeule3a_er=p3a_er,
                bezug_3a_er=aus_3a_er,
                saeule3a_sie=p3a_sie,
                bezug_3a_sie=aus_3a_sie,
                einkauf_er=einkauf_er,
                pk_er=pk_er,
                pk_rente_er=rente_er,
                pk_kapital_er=pk_kapital_er,
                einkauf_sie=einkauf_sie,
                pk_sie=pk_sie,
                pk_rente_sie=rente_sie,
                pk_kapital_sie=pk_kapital_sie,
                ahv=ahv,
                pk_renten=pk_renten,
                de_rente=de_rente,
                renten=renten,
                kapitalbezuege_netto=kapital_netto,
                lebenshaltung=lebenshaltung,
                unterhalt=unterhalt,
                auto=auto,
                dach=dach,
                erbschaft=erbschaft,
                ahv_beitraege=ahv_beitraege,
                hypozins=satz,
                hypothekarzins=hypothekarzins,
                amortisation=amortisation,
                hypothek=hypothek,
                darlehen_rueckzahlung=rueckzahlung,
                darlehen=darlehen,
                steuerbares_einkommen=steuerbar,
                steuern=steuern,
                anlageertrag=ertrag,
                einnahmen=einnahmen,
                ausgaben=ausgaben,
                saldo=einnahmen - ausgaben,
                frei=frei,
                liegenschaft=liegenschaft,
                belehnung=hypothek / liegenschaft if liegenschaft else 0.0,
                tragbarkeit=tragbarkeit,
                nettovermoegen=frei
                + p3a_er
                + p3a_sie
                + pk_er
                + pk_sie
                + liegenschaft
                - hypothek
                - darlehen,
            )
        )

    return _kennzahlen(
        a,
        s,
        tuple(jahre),
        Bezuege(beide, pk_bezug_er, pk_bezug_sie, kapital_er, kapital_sie),
    )


@dataclass(frozen=True)
class Bezuege:
    """Abgeleitete Jahre und Kapitalanteile eines Szenarios."""

    beide_pensioniert: int
    pk_er: int
    pk_sie: int
    kapital_er: float
    kapital_sie: float


def _kennzahlen(a: Annahmen, s: Szenario, jahre: tuple[Jahr, ...], b: Bezuege) -> Ergebnis:
    erstes = jahre[0].jahr
    beide = b.beide_pensioniert

    def im(jahr: int) -> Jahr | None:
        return jahre[jahr - erstes] if 0 <= jahr - erstes < len(jahre) else None

    rentnerjahr, pension_er, pension_sie = im(beide), im(s.pension_er), im(s.pension_sie)
    tiefster = min(jahre, key=lambda j: j.frei)
    negativ = next((j.jahr for j in jahre if j.frei < 0), None)
    tragbarkeit = rentnerjahr.tragbarkeit if rentnerjahr else None
    sperrfrist_verletzt = (
        b.kapital_er > 0
        and s.einkauf_er.betrag > 0
        and s.einkauf_er.bis > b.pk_er - SPERRFRIST_EINKAUF - 1
    ) or (
        b.kapital_sie > 0
        and s.einkauf_sie.betrag > 0
        and s.einkauf_sie.bis > b.pk_sie - SPERRFRIST_EINKAUF - 1
    )
    ende = jahre[-1]
    er_85 = im(a.geburtsjahr_er + ALTER_ER_KENNZAHL)

    return Ergebnis(
        szenario=s,
        jahre=jahre,
        beide_pensioniert=beide,
        pk_bezug_er=b.pk_er,
        pk_bezug_sie=b.pk_sie,
        renten_rentnerjahr=rentnerjahr.renten_real if rentnerjahr else None,
        ausgaben_rentnerjahr=rentnerjahr.laufende_ausgaben_real if rentnerjahr else None,
        frei_pension_er=pension_er.frei_real if pension_er else None,
        frei_pension_sie=pension_sie.frei_real if pension_sie else None,
        frei_er_85=er_85.frei_real if er_85 else None,
        frei_ende=ende.frei_real,
        tiefster_stand=tiefster.frei,
        tiefster_stand_jahr=tiefster.jahr,
        erstes_negatives_jahr=negativ,
        hypothek_pension_er=pension_er.hypothek if pension_er else None,
        hypothek_pension_sie=pension_sie.hypothek if pension_sie else None,
        belehnung_pension_er=pension_er.belehnung if pension_er else None,
        tragbarkeit=tragbarkeit,
        tragbarkeit_ok=tragbarkeit is not None and tragbarkeit <= a.tragbarkeit_maximum,
        sperrfrist_ok=not sperrfrist_verletzt,
        steuern_summe=sum(j.steuern for j in jahre),
        nettovermoegen_ende=ende.nettovermoegen / ende.preisindex,
    )


# --- Regler: Parameter, die sich in Home Assistant verändern lassen ----------


@dataclass(frozen=True)
class Regler:
    """Ein Parameter des aktiven Szenarios, der sich übersteuern lässt."""

    schluessel: str
    name: str
    art: str  # jahr_er, jahr_sie, alter, prozent, betrag
    icon: str


REGLER = [
    Regler("pension_er", "Pensionierung Er (Jahr)", "jahr_er", "mdi:calendar-account"),
    Regler("pension_sie", "Pensionierung Sie (Jahr)", "jahr_sie", "mdi:calendar-account"),
    Regler("pensum_er", "Pensum Er (letzte Phase)", "prozent", "mdi:briefcase-clock"),
    Regler("pensum_er_ab", "Pensum Er ab Jahr", "jahr_er", "mdi:calendar-arrow-right"),
    Regler("pensum_sie", "Pensum Sie (letzte Phase)", "prozent", "mdi:briefcase-clock"),
    Regler("pensum_sie_ab", "Pensum Sie ab Jahr", "jahr_sie", "mdi:calendar-arrow-right"),
    Regler("ahv_alter_er", "AHV-Bezug Er ab Alter", "alter", "mdi:account-clock"),
    Regler("ahv_alter_sie", "AHV-Bezug Sie ab Alter", "alter", "mdi:account-clock"),
    Regler("kapitalbezug_er", "PK-Kapitalbezug Er", "prozent", "mdi:cash-fast"),
    Regler("kapitalbezug_sie", "PK-Kapitalbezug Sie", "prozent", "mdi:cash-fast"),
    Regler("einkauf_er", "PK-Einkauf Er pro Jahr", "betrag", "mdi:cash-plus"),
    Regler("einkauf_sie", "PK-Einkauf Sie pro Jahr", "betrag", "mdi:cash-plus"),
    Regler("amortisation", "Amortisation pro Jahr bis Pension Er", "betrag", "mdi:home-minus"),
]
REGLER_NACH_SCHLUESSEL = {r.schluessel: r for r in REGLER}


def regler_wert(s: Szenario, schluessel: str) -> float:
    """Wert eines Reglers im Szenario; Prozente als 0 bis 100."""
    match schluessel:
        case "pension_er" | "pension_sie" | "ahv_alter_er" | "ahv_alter_sie":
            return float(getattr(s, schluessel))
        case "pensum_er" | "pensum_sie":
            return round(getattr(s, schluessel)[-1].wert * 100, 6)
        case "pensum_er_ab" | "pensum_sie_ab":
            return float(getattr(s, schluessel.removesuffix("_ab"))[-1].ab)
        case "kapitalbezug_er" | "kapitalbezug_sie":
            return round(getattr(s, schluessel) * 100, 6)
        case "einkauf_er" | "einkauf_sie":
            return getattr(s, schluessel).betrag
        case "amortisation":
            return s.amortisation_bis_pension
    raise KeyError(schluessel)


def mit_anpassungen(s: Szenario, anpassungen: dict[str, float]) -> Szenario:
    """Wendet die Regler-Werte auf ein Szenario an."""
    # Erst die Phasen-Beginne, damit der Pensum-Regler die richtige Phase trifft
    for schluessel in sorted(anpassungen, key=lambda k: not k.endswith("_ab")):
        wert = anpassungen[schluessel]
        match schluessel:
            case "pension_er" | "pension_sie" | "ahv_alter_er" | "ahv_alter_sie":
                s = replace(s, **{schluessel: int(wert)})
            case "pensum_er" | "pensum_sie":
                phasen = getattr(s, schluessel)
                letzte = replace(phasen[-1], wert=wert / 100)
                s = replace(s, **{schluessel: (*phasen[:-1], letzte)})
            case "pensum_er_ab" | "pensum_sie_ab":
                name = schluessel.removesuffix("_ab")
                phasen = getattr(s, name)
                if len(phasen) == 1:
                    # Eine zweite Phase mit gleichem Pensum, die der Pensum-Regler dann ändert
                    phasen = (*phasen, phasen[0])
                vorher = phasen[-2].ab if len(phasen) > 1 else int(wert)
                letzte = replace(phasen[-1], ab=max(int(wert), vorher))
                s = replace(s, **{name: (*phasen[:-1], letzte)})
            case "kapitalbezug_er" | "kapitalbezug_sie":
                s = replace(s, **{schluessel: wert / 100})
            case "einkauf_er" | "einkauf_sie":
                s = replace(s, **{schluessel: replace(getattr(s, schluessel), betrag=wert)})
            case "amortisation":
                s = replace(s, amortisation_bis_pension=wert)
    return s


# --- simulation.yaml einlesen ----------------------------------------------


def _zahl(minimum: float | None = None, maximum: float | None = None) -> Any:
    def pruefen(wert: Any) -> float:
        if isinstance(wert, bool) or not isinstance(wert, int | float):
            raise vol.Invalid("muss eine Zahl sein")
        if minimum is not None and wert < minimum:
            raise vol.Invalid(f"muss mindestens {minimum} sein")
        if maximum is not None and wert > maximum:
            raise vol.Invalid(f"darf höchstens {maximum} sein")
        return float(wert)

    return pruefen


def _ganzzahl(minimum: int, maximum: int) -> Any:
    def pruefen(wert: Any) -> int:
        if isinstance(wert, bool) or not isinstance(wert, int):
            raise vol.Invalid("muss eine ganze Zahl sein")
        if not minimum <= wert <= maximum:
            raise vol.Invalid(f"muss zwischen {minimum} und {maximum} liegen")
        return wert

    return pruefen


def _prozent(maximum: float = 100) -> Any:
    """Prozentzahl in der Datei, Bruchteil im Modell."""
    zahl = _zahl(0, maximum)
    return lambda wert: zahl(wert) / 100


def _ja_nein(wert: Any) -> bool:
    if not isinstance(wert, bool):
        raise vol.Invalid("muss true oder false sein")
    return wert


def _text(wert: Any) -> str:
    if not isinstance(wert, str | int) or not str(wert).strip():
        raise vol.Invalid("muss ein Text sein")
    return str(wert).strip()


JAHR = _ganzzahl(1900, 2200)
ALTER = _ganzzahl(0, 120)
BETRAG = _zahl(0)
PROZENT = _prozent()

QUELLE = vol.Schema(
    {
        vol.Optional("konten"): [_text],
        vol.Optional("toepfe"): [_text],
        vol.Optional("wert"): _zahl(),
    }
)
PK_QUELLE = QUELLE.extend({vol.Optional("jahr"): JAHR})

PK_SCHEMA = {
    vol.Required("prognose_kapital"): BETRAG,
    vol.Required("prognose_jahr"): JAHR,
    vol.Optional("prognose_pensum", default=100): _prozent(),
    vol.Required("umwandlungssatz"): PROZENT,
    vol.Optional("reduktion_pro_jahr", default=0): PROZENT,
    vol.Optional("einkaufspotenzial", default=0): BETRAG,
    vol.Optional("zusatzsparkonto", default=0): BETRAG,
}
PHASE = vol.Schema({vol.Required("ab"): JAHR, vol.Required("wert"): PROZENT})
EINKAUF = vol.Schema(
    {
        vol.Required("betrag"): BETRAG,
        vol.Required("von"): JAHR,
        vol.Required("bis"): JAHR,
    }
)
SZENARIO = vol.Schema(
    {
        vol.Required("id"): vol.All(_text, vol.Match(r"^[a-z0-9_]+$", msg="nur a-z, 0-9, _")),
        vol.Required("name"): _text,
        vol.Required("pension"): {vol.Required("er"): JAHR, vol.Required("sie"): JAHR},
        vol.Required("pensum"): {
            vol.Required("er"): vol.All([PHASE], vol.Length(min=1, msg="mindestens eine Phase")),
            vol.Required("sie"): vol.All([PHASE], vol.Length(min=1, msg="mindestens eine Phase")),
        },
        vol.Optional("ahv_ab_alter", default={}): {
            vol.Optional("er", default=ALTER_REFERENZ): _ganzzahl(63, 70),
            vol.Optional("sie", default=ALTER_REFERENZ): _ganzzahl(63, 70),
        },
        vol.Optional("pk_kapitalbezug", default={}): {
            vol.Optional("er", default=0): PROZENT,
            vol.Optional("sie", default=0): PROZENT,
        },
        vol.Optional("pk_einkauf", default={}): {
            vol.Optional("er"): EINKAUF,
            vol.Optional("sie"): EINKAUF,
        },
        vol.Optional("saeule3a_maximal", default=True): _ja_nein,
        vol.Optional("amortisation", default={}): {
            vol.Optional("bis_pension", default=0): BETRAG,
            vol.Optional("nach_pension", default=0): BETRAG,
            vol.Optional("bei_pension_er", default=0): BETRAG,
            vol.Optional("bei_pension_sie", default=0): BETRAG,
            vol.Optional("sonder", default=[]): [
                {vol.Required("jahr"): JAHR, vol.Required("betrag"): BETRAG}
            ],
        },
    }
)

SCHEMA = vol.Schema(
    {
        vol.Required("personen"): {
            vol.Required("er"): {
                vol.Required("geburtsjahr"): JAHR,
                vol.Required("lohn"): BETRAG,
                vol.Optional("planungsalter", default=90): ALTER,
            },
            vol.Required("sie"): {
                vol.Required("geburtsjahr"): JAHR,
                vol.Required("lohn"): BETRAG,
            },
        },
        vol.Optional("wirtschaft", default={}): {
            vol.Optional("lohnwachstum", default=1.0): PROZENT,
            vol.Optional("teuerung", default=1.0): PROZENT,
            vol.Optional("sozialabzuege", default=13): PROZENT,
            vol.Optional("kurs_eur"): _zahl(0),
        },
        vol.Optional("anlagen", default={}): {
            vol.Optional("liquiditaetsreserve", default=0): BETRAG,
            vol.Optional("zins_liquiditaet", default=0): PROZENT,
            vol.Optional("rendite_frei", default=0): PROZENT,
            vol.Optional("zins_negativ", default=0): PROZENT,
            vol.Optional("rendite_3a", default=0): PROZENT,
        },
        vol.Required("lebenshaltung"): {
            vol.Required("heute"): BETRAG,
            vol.Required("kinder_selbstaendig"): BETRAG,
            vol.Required("ruhestand"): BETRAG,
            vol.Optional("kinder_selbstaendig_ab", default=1900): JAHR,
            vol.Optional("faktor_nach_tod", default=75): PROZENT,
        },
        vol.Required("ahv"): {
            vol.Required("rente_er"): BETRAG,
            vol.Required("rente_sie"): BETRAG,
            vol.Optional("plafond", default=45360): BETRAG,
            vol.Optional("max_einzelrente", default=30240): BETRAG,
            vol.Optional("dreizehnte", default=True): _ja_nein,
            vol.Optional("kuerzung_vorbezug", default=6.8): PROZENT,
            vol.Optional("beitrag_nichterwerbstaetige", default=0): BETRAG,
        },
        vol.Required("pk"): {
            vol.Optional("verzinsung", default=1.0): PROZENT,
            vol.Optional("witwenrente", default=60): PROZENT,
            vol.Required("er"): PK_SCHEMA,
            vol.Required("sie"): PK_SCHEMA,
        },
        vol.Optional("saeule3a", default={}): {
            vol.Optional("maximalbetrag", default=7258): BETRAG,
        },
        vol.Optional("deutschland", default={}): {
            vol.Optional("rente", default=0): BETRAG,
            vol.Optional("rente_ab", default=2200): JAHR,
            vol.Optional("anpassung", default=0): PROZENT,
            vol.Optional("witwenrente", default=55): PROZENT,
            vol.Optional("policen_auszahlung", default=2200): JAHR,
            vol.Optional("fonds_rendite", default=0): PROZENT,
        },
        vol.Optional("immobilie", default={}): {
            vol.Optional("wertsteigerung", default=0): PROZENT,
            vol.Optional("hypozins", default=[{"satz": 0}]): vol.All(
                [{vol.Optional("bis"): JAHR, vol.Required("satz"): PROZENT}],
                vol.Length(min=1, msg="mindestens ein Zinssatz"),
            ),
            vol.Optional("darlehen_rueckzahlung", default=2200): JAHR,
            vol.Optional("eigenmietwert", default=0): BETRAG,
            vol.Optional("unterhaltspauschale", default=20): PROZENT,
            vol.Optional("eigenmietwert_abgeschafft_ab", default=2029): JAHR,
            vol.Optional("tragbarkeit", default={}): {
                vol.Optional("zins", default=5): PROZENT,
                vol.Optional("nebenkosten", default=1): PROZENT,
                vol.Optional("maximum", default=33): PROZENT,
                vol.Optional("vermoegen_jahre", default=0): _ganzzahl(0, 100),
            },
        },
        vol.Required("steuern"): {
            vol.Required("grenzsatz_kanton"): PROZENT,
            vol.Required("grenzsatz_bund"): PROZENT,
            vol.Required("steuern_heute"): BETRAG,
            vol.Required("einkommen_heute"): BETRAG,
            vol.Optional("stufe2_ab", default=100000): BETRAG,
            vol.Optional("abzuege", default=0): BETRAG,
            vol.Optional("abzuege_faktor_spaeter", default=100): PROZENT,
            vol.Optional("vermoegen", default=0): PROZENT,
            vol.Optional("kapitalbezug", default=0): PROZENT,
        },
        vol.Optional("ausgaben", default={}): {
            vol.Optional("auto", default={}): {
                vol.Optional("naechster", default=2200): JAHR,
                vol.Optional("alle", default=8): _ganzzahl(1, 50),
                vol.Optional("preis", default=0): BETRAG,
                vol.Optional("letzter", default=2200): JAHR,
            },
            vol.Optional("dach", default={}): {
                vol.Optional("jahr", default=2200): JAHR,
                vol.Optional("kosten", default=0): BETRAG,
            },
            vol.Optional("erbschaft", default={}): {
                vol.Optional("jahr", default=2200): JAHR,
                vol.Optional("betrag", default=0): BETRAG,
            },
            vol.Optional("unterhalt", default=[]): [
                {vol.Required("betrag"): BETRAG, vol.Required("bis"): JAHR}
            ],
        },
        vol.Required("startwerte"): {
            vol.Optional("jahr"): JAHR,
            vol.Required("frei"): QUELLE,
            vol.Optional("zweckgebunden", default=0): BETRAG,
            vol.Optional("offene_rechnungen", default=0): BETRAG,
            vol.Optional("aufstockung_hypothek", default=0): BETRAG,
            vol.Optional("saeule3a_er"): QUELLE,
            vol.Optional("saeule3a_sie"): QUELLE,
            vol.Optional("pk_er"): PK_QUELLE,
            vol.Optional("pk_sie"): PK_QUELLE,
            vol.Optional("de_policen"): QUELLE,
            vol.Optional("de_fonds"): QUELLE,
            vol.Optional("liegenschaft"): QUELLE,
            vol.Optional("hypothek"): QUELLE,
            vol.Optional("darlehen"): QUELLE,
        },
        vol.Required("szenarien"): vol.All(
            [SZENARIO], vol.Length(min=1, msg="mindestens ein Szenario")
        ),
        vol.Optional("aktives_szenario"): _text,
    }
)

MELDUNGEN = {
    "extra keys not allowed": "unbekannter Eintrag",
    "required key not provided": "fehlt",
    "expected a dictionary": "muss ein Objekt sein",
    "expected a list": "muss eine Liste sein",
}


def lade_simulation(pfad: Path, daten: FinanzDaten) -> Simulation:
    """Liest und prüft simulation.yaml und löst die Startwerte auf."""
    try:
        inhalt = yaml.safe_load(pfad.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise FinanzDatenError(f"{pfad.name}: ungültiges YAML ({err})") from err

    try:
        roh = SCHEMA(inhalt)
    except vol.MultipleInvalid as err:
        fehler = sorted(
            f"{pfad.name}, {'.'.join(str(p) for p in e.path) or 'Datei'}: "
            f"{MELDUNGEN.get(e.msg, e.msg)}"
            for e in err.errors
        )
        raise FinanzDatenError("\n".join(fehler)) from err

    fehler: list[str] = []
    szenarien: dict[str, Szenario] = {}
    for eintrag in roh["szenarien"]:
        szenario = _szenario(eintrag)
        if szenario.id in szenarien:
            fehler.append(f"{pfad.name}: Szenario '{szenario.id}' ist doppelt")
        szenarien[szenario.id] = szenario

    aktiv = roh.get("aktives_szenario", next(iter(szenarien)))
    if aktiv not in szenarien:
        fehler.append(f"{pfad.name}: aktives_szenario '{aktiv}' gibt es nicht")

    annahmen = _annahmen(roh, daten, pfad.name, fehler)
    startwerte = _startwerte(roh["startwerte"], daten, pfad.name, fehler)
    if fehler:
        raise FinanzDatenError("\n".join(fehler))
    return Simulation(
        annahmen=annahmen, startwerte=startwerte, szenarien=szenarien, aktives_szenario=aktiv
    )


def _szenario(r: dict[str, Any]) -> Szenario:
    def phasen(liste: list[dict[str, Any]]) -> tuple[Phase, ...]:
        return tuple(Phase(p["ab"], p["wert"]) for p in sorted(liste, key=lambda p: p["ab"]))

    einkauf = r["pk_einkauf"]
    amort = r["amortisation"]
    return Szenario(
        id=r["id"],
        name=r["name"],
        pension_er=r["pension"]["er"],
        pension_sie=r["pension"]["sie"],
        pensum_er=phasen(r["pensum"]["er"]),
        pensum_sie=phasen(r["pensum"]["sie"]),
        ahv_alter_er=r["ahv_ab_alter"]["er"],
        ahv_alter_sie=r["ahv_ab_alter"]["sie"],
        kapitalbezug_er=r["pk_kapitalbezug"]["er"],
        kapitalbezug_sie=r["pk_kapitalbezug"]["sie"],
        einkauf_er=Einkauf(**einkauf["er"]) if "er" in einkauf else Einkauf(),
        einkauf_sie=Einkauf(**einkauf["sie"]) if "sie" in einkauf else Einkauf(),
        saeule3a_maximal=r["saeule3a_maximal"],
        amortisation_bis_pension=amort["bis_pension"],
        amortisation_nach_pension=amort["nach_pension"],
        amortisation_bei_pension_er=amort["bei_pension_er"],
        amortisation_bei_pension_sie=amort["bei_pension_sie"],
        sonderamortisationen=tuple((s["jahr"], s["betrag"]) for s in amort["sonder"]),
    )


def _annahmen(r: dict[str, Any], daten: FinanzDaten, datei: str, fehler: list[str]) -> Annahmen:
    w, an, lh, ahv, pk = r["wirtschaft"], r["anlagen"], r["lebenshaltung"], r["ahv"], r["pk"]
    de, im, st, aus = r["deutschland"], r["immobilie"], r["steuern"], r["ausgaben"]

    kurs_eur = w.get("kurs_eur")
    if kurs_eur is None:
        kurs = daten.aktueller_kurs("EUR")
        if kurs is not None:
            kurs_eur = float(kurs.kurs)
        elif de["rente"]:
            fehler.append(f"{datei}: kein EUR-Kurs (wirtschaft.kurs_eur oder kurse.csv)")
    if st["grenzsatz_kanton"] + st["grenzsatz_bund"] <= 0:
        fehler.append(f"{datei}, steuern: die Grenzsteuersätze ergeben 0 %")

    def pk_daten(p: dict[str, Any]) -> PK:
        return PK(**p)

    return Annahmen(
        geburtsjahr_er=r["personen"]["er"]["geburtsjahr"],
        geburtsjahr_sie=r["personen"]["sie"]["geburtsjahr"],
        planungsalter_er=r["personen"]["er"]["planungsalter"],
        lohn_er=r["personen"]["er"]["lohn"],
        lohn_sie=r["personen"]["sie"]["lohn"],
        lohnwachstum=w["lohnwachstum"],
        teuerung=w["teuerung"],
        sozialabzuege=w["sozialabzuege"],
        kurs_eur=kurs_eur or 1.0,
        liquiditaetsreserve=an["liquiditaetsreserve"],
        zins_liquiditaet=an["zins_liquiditaet"],
        rendite_frei=an["rendite_frei"],
        zins_negativ=an["zins_negativ"],
        rendite_3a=an["rendite_3a"],
        lebenshaltung_heute=lh["heute"],
        lebenshaltung_kinder_selbstaendig=lh["kinder_selbstaendig"],
        lebenshaltung_ruhestand=lh["ruhestand"],
        kinder_selbstaendig_ab=lh["kinder_selbstaendig_ab"],
        faktor_nach_tod=lh["faktor_nach_tod"],
        ahv_er=ahv["rente_er"] * 12,
        ahv_sie=ahv["rente_sie"] * 12,
        ahv_plafond=ahv["plafond"],
        ahv_max_einzelrente=ahv["max_einzelrente"],
        ahv_dreizehnte=ahv["dreizehnte"],
        ahv_kuerzung_vorbezug=ahv["kuerzung_vorbezug"],
        ahv_beitrag_nichterwerbstaetige=ahv["beitrag_nichterwerbstaetige"],
        pk_verzinsung=pk["verzinsung"],
        pk_witwenrente=pk["witwenrente"],
        pk_er=pk_daten(pk["er"]),
        pk_sie=pk_daten(pk["sie"]),
        saeule3a_maximalbetrag=r["saeule3a"]["maximalbetrag"],
        de_rente_monat_eur=de["rente"],
        de_rente_ab=de["rente_ab"],
        de_anpassung=de["anpassung"],
        de_witwenrente=de["witwenrente"],
        de_policen_auszahlung=de["policen_auszahlung"],
        de_fonds_rendite=de["fonds_rendite"],
        wertsteigerung=im["wertsteigerung"],
        hypozins=tuple((z.get("bis"), z["satz"]) for z in im["hypozins"]),
        darlehen_rueckzahlung=im["darlehen_rueckzahlung"],
        eigenmietwert=im["eigenmietwert"],
        unterhaltspauschale=im["unterhaltspauschale"],
        eigenmietwert_abgeschafft_ab=im["eigenmietwert_abgeschafft_ab"],
        tragbarkeit_zins=im["tragbarkeit"]["zins"],
        tragbarkeit_nebenkosten=im["tragbarkeit"]["nebenkosten"],
        tragbarkeit_maximum=im["tragbarkeit"]["maximum"],
        tragbarkeit_vermoegen_jahre=im["tragbarkeit"]["vermoegen_jahre"],
        grenzsatz_kanton=st["grenzsatz_kanton"],
        grenzsatz_bund=st["grenzsatz_bund"],
        steuern_heute=st["steuern_heute"],
        einkommen_heute=st["einkommen_heute"],
        steuer_stufe2_ab=st["stufe2_ab"],
        abzuege=st["abzuege"],
        abzuege_faktor_spaeter=st["abzuege_faktor_spaeter"],
        vermoegenssteuer=st["vermoegen"],
        kapitalbezugssteuer=st["kapitalbezug"],
        auto_naechster=aus["auto"]["naechster"],
        auto_alle=aus["auto"]["alle"],
        auto_preis=aus["auto"]["preis"],
        auto_letzter=aus["auto"]["letzter"],
        dach_jahr=aus["dach"]["jahr"],
        dach_kosten=aus["dach"]["kosten"],
        erbschaft_jahr=aus["erbschaft"]["jahr"],
        erbschaft_betrag=aus["erbschaft"]["betrag"],
        unterhalt=tuple((u["betrag"], u["bis"]) for u in aus["unterhalt"]),
    )


def _startwerte(r: dict[str, Any], daten: FinanzDaten, datei: str, fehler: list[str]) -> Startwerte:
    """Summiert die Saldi der angegebenen Konten und Töpfe in CHF."""
    verwendet: dict[str, str] = {}
    werte: dict[str, float] = {}
    staende: dict[str, date | None] = {}
    neuester: date | None = None

    for name in STARTWERTE:
        quelle = r.get(name, {})
        wo = f"{datei}, startwerte.{name}"
        konto_ids = list(quelle.get("konten", []))
        for konto_id in konto_ids:
            if konto_id not in daten.konten:
                fehler.append(f"{wo}: unbekanntes Konto '{konto_id}'")
        for topf in quelle.get("toepfe", []):
            im_topf = [k.id for k in daten.konten.values() if k.topf == topf]
            if not im_topf:
                fehler.append(f"{wo}: kein Konto im Topf '{topf}'")
            konto_ids += im_topf

        summe = Decimal(0)
        stand: date | None = None
        for konto_id in dict.fromkeys(konto_ids):
            if konto_id not in daten.konten:
                continue
            if (frueher := verwendet.setdefault(konto_id, name)) != name:
                fehler.append(f"{wo}: Konto '{konto_id}' ist schon in startwerte.{frueher}")
                continue
            saldo = daten.aktueller_saldo(konto_id)
            if saldo is None:
                fehler.append(f"{wo}: Konto '{konto_id}' hat keinen Saldo")
                continue
            summe += daten.wert_chf(konto_id) or Decimal(0)
            stand = max(stand, saldo.datum) if stand else saldo.datum

        werte[name] = float(summe) + quelle.get("wert", 0.0)
        staende[name] = stand
        if stand and not name.startswith("pk_"):
            neuester = max(neuester, stand) if neuester else stand

    jahr = r.get("jahr") or (neuester.year if neuester else date.today().year)

    def pk_jahr(name: str) -> int:
        # Ein PK-Saldo per 1.1. entspricht dem Stand Ende Vorjahr (Vorsorgeausweis)
        if "jahr" in r.get(name, {}):
            return r[name]["jahr"]
        stand = staende[name]
        return (stand - timedelta(days=1)).year if stand else jahr

    return Startwerte(
        jahr=jahr,
        frei=werte["frei"]
        - r["zweckgebunden"]
        - r["offene_rechnungen"]
        + r["aufstockung_hypothek"],
        saeule3a_er=werte["saeule3a_er"],
        saeule3a_sie=werte["saeule3a_sie"],
        pk_er=werte["pk_er"],
        pk_er_jahr=pk_jahr("pk_er"),
        pk_sie=werte["pk_sie"],
        pk_sie_jahr=pk_jahr("pk_sie"),
        de_policen=werte["de_policen"],
        de_fonds=werte["de_fonds"],
        liegenschaft=werte["liegenschaft"],
        # Schulden werden als negative Saldi erfasst, im Modell sind sie positiv
        hypothek=abs(werte["hypothek"]) + r["aufstockung_hypothek"],
        darlehen=abs(werte["darlehen"]),
    )
