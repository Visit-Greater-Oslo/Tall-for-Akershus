"""
Generisk klient mot SSBs PxWebApi v2 (Statistikkbanken).

Designvalg: I stedet for å hardkode variabel-id-er som "InnkvarteringsType"
eller "Bostedsland" -- som kan skrives litt ulikt fra tabell til tabell --
leser klienten alltid metadata for tabellen først, og lar deg finne riktig
variabel med nøkkelord ("region", "tid", "bosted", ...). Det gjør koden
robust selv om vi ikke har kunnet verifisere hvert eneste feltnavn live.

Dokumentasjon: https://www.ssb.no/en/api/pxwebapiv2
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import pandas as pd
import requests

from config import SSB_API_BASE

TIMEOUT = 60


class SSBApiError(RuntimeError):
    pass


@lru_cache(maxsize=32)
def get_metadata(table_id: str, lang: str = "no") -> dict[str, Any]:
    """Hent metadata (variabler + koder) for en tabell. Cachet i prosessen."""
    url = f"{SSB_API_BASE}/{table_id}/metadata"
    resp = requests.get(url, params={"lang": lang}, timeout=TIMEOUT)
    if not resp.ok:
        raise SSBApiError(
            f"Klarte ikke hente metadata for tabell {table_id}: "
            f"{resp.status_code} {resp.text[:300]}"
        )
    return resp.json()


def find_variable(metadata: dict[str, Any], *keywords: str) -> dict[str, Any] | None:
    """
    Finn første variabel i metadata der id ELLER label matcher et av nøkkelordene
    (case-insensitive substring-match). Returnerer variabel-dict fra metadata,
    eller None hvis ingen treff.
    """
    for var in metadata.get("variables", []):
        haystack = f"{var.get('id', '')} {var.get('label', '')}".lower()
        if any(k.lower() in haystack for k in keywords):
            return var
    return None


def variable_ids(metadata: dict[str, Any]) -> list[str]:
    return [v["id"] for v in metadata.get("variables", [])]


def build_query_url(
    table_id: str,
    value_codes: dict[str, str],
    lang: str = "no",
    output_format: str = "json-stat2",
) -> str:
    """
    Bygg en fullstendig GET-URL mot PxWebApi v2.

    value_codes: {variabel_id: kode_uttrykk}, f.eks.
        {"Region": "32101,32102,32103", "Tid": "from(2024M01)", "ContentsCode": "*"}
    Kode-uttrykk følger PxWebApi-syntaks: "*", "top(3)", "from(2024M01)", "01,02".
    """
    parts = [f"lang={lang}", f"outputFormat={output_format}"]
    for var_id, codes in value_codes.items():
        parts.append(f"valueCodes[{var_id}]={codes}")
    return f"{SSB_API_BASE}/{table_id}/data?" + "&".join(parts)


def fetch_table(table_id: str, value_codes: dict[str, str], lang: str = "no") -> pd.DataFrame:
    """Hent data fra en SSB-tabell og returner som "lang" pandas DataFrame."""
    url = build_query_url(table_id, value_codes, lang=lang)
    resp = requests.get(url, timeout=TIMEOUT)
    if not resp.ok:
        raise SSBApiError(
            f"SSB-spørring feilet for tabell {table_id}:\n{url}\n"
            f"Status {resp.status_code}: {resp.text[:500]}"
        )
    return jsonstat_to_dataframe(resp.text)


def jsonstat_to_dataframe(jsonstat_text: str) -> pd.DataFrame:
    """Konverter JSON-stat2-respons til en pandas DataFrame med lesbare kolonner."""
    try:
        from pyjstat import pyjstat
    except ImportError as exc:  # pragma: no cover
        raise SSBApiError(
            "Mangler pakken 'pyjstat'. Kjør: pip install pyjstat"
        ) from exc

    data = json.loads(jsonstat_text)
    ds = pyjstat.Dataset.read(data)
    df = ds.write("dataframe")
    # pyjstat gir egne kolonnenavn per dimensjon-label og en "value"-kolonne.
    df.columns = [str(c).strip() for c in df.columns]
    return df


def fetch_all_wildcard(
    table_id: str,
    region_codes: list[str],
    year_from: int,
    region_var_hint: str = "region",
) -> pd.DataFrame:
    """
    Hent en tabell for gitte regionkoder og fra et gitt år, med alle andre
    dimensjoner (innkvarteringstype, bostedsland, ContentsCode, osv.) tatt med
    i sin helhet ("*"). Dette gir en "rå" lang tabell som appen selv pivoterer
    og filtrerer videre -- trygt valg når vi ikke kjenner alle dimensjonsnavn
    på forhånd.
    """
    meta = get_metadata(table_id)
    region_var = find_variable(meta, region_var_hint, "omrade", "område")
    tid_var = find_variable(meta, "tid", "time")

    if region_var is None or tid_var is None:
        raise SSBApiError(
            f"Fant ikke region- eller tidsvariabel i metadata for tabell "
            f"{table_id}. Variabler funnet: {variable_ids(meta)}"
        )

    value_codes = {
        region_var["id"]: ",".join(region_codes),
        tid_var["id"]: f"from({year_from}M01)",
    }
    for var in meta["variables"]:
        if var["id"] not in value_codes:
            value_codes[var["id"]] = "*"

    return fetch_table(table_id, value_codes)
