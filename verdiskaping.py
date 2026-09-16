"""
Verdiskaping per bransje og kommune for Akershus.

Kilde: Innovasjon Norges verdiskapingstall for reiselivet (Excel-uttrekk fra
Brønnøysundregistrene/Menon-metodikk, se verdiskaping_akershus.csv,
hentet fra arket "Aggregerte Data" i den originale rapporten).

Metodikk (fra kildefilens eget "Metodikk"-ark): Verdiskaping = driftsresultat
+ lønnskostnader + avskrivinger, aldri negativ. Tall er valuta- og
inflasjonsjustert til faste 2024-priser.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import KOMMUNER_PER_REGION, REISELIVSREGIONER, VERDISKAPING_CSV, VERDISKAPING_MAX_YEAR

_KOMMUNE_TIL_REGION: dict[str, str] = {
    # Kildefilen bruker kommunenavn, ikke kommunenummer -- egen navnenøkkel her.
    "Bærum": "Asker/Bærum",
    "Asker": "Asker/Bærum",
    "Nordre Follo": "Follo",
    "Nesodden": "Follo",
    "Frogn": "Follo",
    "Vestby": "Follo",
    "Ås": "Follo",
    "Enebakk": "Follo",
    "Lillestrøm": "Romerike/Hadeland",
    "Ullensaker": "Romerike/Hadeland",
    "Lørenskog": "Romerike/Hadeland",
    "Rælingen": "Romerike/Hadeland",
    "Aurskog-Høland": "Romerike/Hadeland",
    "Nes": "Romerike/Hadeland",
    "Gjerdrum": "Romerike/Hadeland",
    "Nittedal": "Romerike/Hadeland",
    "Lunner": "Romerike/Hadeland",
    "Jevnaker": "Romerike/Hadeland",
    "Nannestad": "Romerike/Hadeland",
    "Eidsvoll": "Romerike/Hadeland",
    "Hurdal": "Romerike/Hadeland",
}

@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_verdiskaping() -> pd.DataFrame:
    """Les den lokale verdiskapings-CSV-en og legg til reiselivsregion."""
    df = pd.read_csv(VERDISKAPING_CSV)
    df["Reiselivsregion"] = df["Kommune"].map(_KOMMUNE_TIL_REGION)
    return df


def resolve_year(requested_year: int) -> tuple[int, bool]:
    """
    Verdiskapingstallene finnes kun t.o.m. VERDISKAPING_MAX_YEAR (årlige tall,
    typisk 9-12 mnd etterslep). Returnerer (år_å_bruke, ble_justert).
    """
    if requested_year > VERDISKAPING_MAX_YEAR:
        return VERDISKAPING_MAX_YEAR, True
    return requested_year, False


def filter_verdiskaping(df: pd.DataFrame, year: int, regions: list[str]) -> pd.DataFrame:
    out = df[df["Regnskapsår"] == year]
    if regions:
        out = out[out["Reiselivsregion"].isin(regions)]
    return out


def per_bransje(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("Næring", as_index=False)["Verdiskaping"]
        .sum()
        .sort_values("Verdiskaping", ascending=False)
    )


def per_kommune(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("Kommune", as_index=False)["Verdiskaping"]
        .sum()
        .sort_values("Verdiskaping", ascending=False)
    )


def per_region_trend(df: pd.DataFrame, regions: list[str]) -> pd.DataFrame:
    """Total verdiskaping per år og region, for hele tidsserien (uavhengig av valgt år)."""
    out = df if not regions else df[df["Reiselivsregion"].isin(regions)]
    return (
        out.groupby(["Regnskapsår", "Reiselivsregion"], as_index=False)["Verdiskaping"]
        .sum()
    )


def total(df: pd.DataFrame) -> float:
    return float(df["Verdiskaping"].sum())
