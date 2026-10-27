"""Wechselkurse der Europäischen Zentralbank über die Frankfurter-API.

Die API ist frei und braucht keinen Schlüssel. Abgefragt wird nur,
wie viele CHF eine Einheit der Fremdwährung kostet.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp

from .data import BASISWAEHRUNG, Kurs

KURSE_URL = "https://api.frankfurter.dev/v1/latest"
QUELLE = "EZB"
TIMEOUT = aiohttp.ClientTimeout(total=20)


class KurseOnlineError(Exception):
    """Die Kurse konnten nicht geholt werden."""


async def hole_kurse(session: aiohttp.ClientSession, waehrungen: set[str]) -> dict[str, Kurs]:
    """Holt den neuesten Referenzkurs je Währung in CHF."""
    kurse: dict[str, Kurs] = {}
    for waehrung in sorted(waehrungen):
        params = {"base": waehrung, "symbols": BASISWAEHRUNG}
        try:
            async with session.get(KURSE_URL, params=params, timeout=TIMEOUT) as antwort:
                antwort.raise_for_status()
                inhalt: dict[str, Any] = await antwort.json()
            kurs = Decimal(str(inhalt["rates"][BASISWAEHRUNG]))
            datum = date.fromisoformat(inhalt["date"])
        except (aiohttp.ClientError, TimeoutError) as err:
            raise KurseOnlineError(f"{waehrung}: {err}") from err
        except (KeyError, TypeError, ValueError, InvalidOperation) as err:
            raise KurseOnlineError(f"{waehrung}: unerwartete Antwort ({err})") from err
        if not kurs.is_finite() or kurs <= 0:
            raise KurseOnlineError(f"{waehrung}: ungültiger Kurs {kurs}")
        kurse[waehrung] = Kurs(datum=datum, waehrung=waehrung, kurs=kurs, quelle=QUELLE)
    return kurse


def kurse_speichern(kurse: dict[str, Kurs]) -> dict[str, Any]:
    """Wandelt die Kurse in eine Form, die sich als JSON speichern lässt."""
    return {k.waehrung: {"datum": k.datum.isoformat(), "kurs": str(k.kurs)} for k in kurse.values()}


def kurse_laden(gespeichert: dict[str, Any]) -> dict[str, Kurs]:
    """Gegenstück zu kurse_speichern; Unlesbares wird übersprungen."""
    kurse: dict[str, Kurs] = {}
    for waehrung, wert in gespeichert.items():
        try:
            kurse[waehrung] = Kurs(
                datum=date.fromisoformat(wert["datum"]),
                waehrung=waehrung,
                kurs=Decimal(wert["kurs"]),
                quelle=QUELLE,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    return kurse
