"""Wechselkurse aus dem Internet.

EUR und USD kommen von der Europäischen Zentralbank (Frankfurter-API),
Bitcoin von CoinGecko. Beide APIs sind frei und brauchen keinen
Schlüssel. Abgefragt wird nur, wie viele CHF eine Einheit kostet.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp

from .data import BASISWAEHRUNG, Kurs

KURSE_URL = "https://api.frankfurter.dev/v1/latest"
QUELLE = "EZB"
KRYPTO_URL = "https://api.coingecko.com/api/v3/simple/price"
KRYPTO_QUELLE = "CoinGecko"
# Währungscode → ID bei CoinGecko
KRYPTO_IDS = {"BTC": "bitcoin"}
TIMEOUT = aiohttp.ClientTimeout(total=20)


class KurseOnlineError(Exception):
    """Die Kurse konnten nicht geholt werden."""


async def hole_kurse(session: aiohttp.ClientSession, waehrungen: set[str]) -> dict[str, Kurs]:
    """Holt den neuesten Referenzkurs je Währung in CHF."""
    kurse: dict[str, Kurs] = {}
    for waehrung in sorted(waehrungen):
        try:
            if krypto_id := KRYPTO_IDS.get(waehrung):
                params = {
                    "ids": krypto_id,
                    "vs_currencies": BASISWAEHRUNG.lower(),
                    "include_last_updated_at": "true",
                }
                inhalt = (await _hole(session, KRYPTO_URL, params))[krypto_id]
                kurs = Decimal(str(inhalt[BASISWAEHRUNG.lower()]))
                datum = datetime.fromtimestamp(inhalt["last_updated_at"], UTC).date()
                quelle = KRYPTO_QUELLE
            else:
                params = {"base": waehrung, "symbols": BASISWAEHRUNG}
                inhalt = await _hole(session, KURSE_URL, params)
                kurs = Decimal(str(inhalt["rates"][BASISWAEHRUNG]))
                datum = date.fromisoformat(inhalt["date"])
                quelle = QUELLE
        except (aiohttp.ClientError, TimeoutError) as err:
            raise KurseOnlineError(f"{waehrung}: {err}") from err
        except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation) as err:
            raise KurseOnlineError(f"{waehrung}: unerwartete Antwort ({err})") from err
        if not kurs.is_finite() or kurs <= 0:
            raise KurseOnlineError(f"{waehrung}: ungültiger Kurs {kurs}")
        kurse[waehrung] = Kurs(datum=datum, waehrung=waehrung, kurs=kurs, quelle=quelle)
    return kurse


async def _hole(session: aiohttp.ClientSession, url: str, params: dict[str, str]) -> Any:
    async with session.get(url, params=params, timeout=TIMEOUT) as antwort:
        antwort.raise_for_status()
        return await antwort.json()


def kurse_speichern(kurse: dict[str, Kurs]) -> dict[str, Any]:
    """Wandelt die Kurse in eine Form, die sich als JSON speichern lässt."""
    return {
        k.waehrung: {"datum": k.datum.isoformat(), "kurs": str(k.kurs), "quelle": k.quelle}
        for k in kurse.values()
    }


def kurse_laden(gespeichert: dict[str, Any]) -> dict[str, Kurs]:
    """Gegenstück zu kurse_speichern; Unlesbares wird übersprungen."""
    kurse: dict[str, Kurs] = {}
    for waehrung, wert in gespeichert.items():
        try:
            kurse[waehrung] = Kurs(
                datum=date.fromisoformat(wert["datum"]),
                waehrung=waehrung,
                kurs=Decimal(wert["kurs"]),
                quelle=wert.get("quelle", QUELLE),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    return kurse
