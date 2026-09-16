"""
Høynivå-funksjoner for å hente ferdig strukturerte DataFrames til dashbordet.

Alle funksjoner er dekorert med st.cache_data slik at Streamlit ikke slår
mot SSB-API-et på hver eneste filterendring i grensesnittet.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ssb_client
from config import (
    ALLE_KOMMUNER,
    ALLE_REGIONKODER,
    KOMMUNER_PER_REGION,
    REISELIVSREGIONER,
    TABLES,
)

CACHE_TTL_SECONDS = 60 * 60 * 6  # 6 timer -- SSB oppdaterer typisk 1x/mnd


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter overnattingstall fra SSB …")
def load_overnattinger(year_from: int) -> pd.DataFrame:
    """
    Tabell 14172: Overnattinger per reiselivsregion, etter innkvarteringstype
    og gjestenes bostedsland. Rå, lang tabell -- appen pivoterer selv.
    """
    return ssb_client.fetch_all_wildcard(
        TABLES["overnattinger"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter kapasitetstall fra SSB …")
def load_kapasitet(year_from: int) -> pd.DataFrame:
    """Tabell 14173: Åpne bedrifter, rom/hytter/senger per reiselivsregion."""
    return ssb_client.fetch_all_wildcard(
        TABLES["kapasitet_bedrifter"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter gjestetall fra SSB …")
def load_ankomne_gjester(year_from: int) -> pd.DataFrame:
    """Tabell 14174: Ankomne gjester per reiselivsregion."""
    return ssb_client.fetch_all_wildcard(
        TABLES["ankomne_gjester"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter formålsdata (hotell) fra SSB …")
def load_overnatting_formal(year_from: int) -> pd.DataFrame:
    """Tabell 14175: Hotell -- overnattinger etter formål med oppholdet."""
    return ssb_client.fetch_all_wildcard(
        TABLES["overnatting_formal"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter omsetning/kapasitetsutnyttelse fra SSB …")
def load_omsetning_utnyttelse(year_from: int) -> pd.DataFrame:
    """Tabell 14176: Hotell -- omsetning og kapasitetsutnyttelse."""
    return ssb_client.fetch_all_wildcard(
        TABLES["omsetning_utnyttelse"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter nøkkelindikatorer (bl.a. RevPAR) fra SSB …")
def load_nokkelindikatorer(year_from: int) -> pd.DataFrame:
    """Tabell 14177: Hotell -- nøkkelindikatorer (bl.a. RevPAR, omsetning/gjest)."""
    return ssb_client.fetch_all_wildcard(
        TABLES["nokkelindikatorer"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter befolkningstall fra SSB …")
def load_befolkning(year_from: int) -> pd.DataFrame:
    """
    Tabell 07459: Befolkning. Denne publiseres normalt på KOMMUNE-nivå
    (ikke reiselivsregion), så vi henter per kommune og mapper til region
    selv -- se `map_kommune_to_region`.
    """
    df = ssb_client.fetch_all_wildcard(
        TABLES["befolkning"], ALLE_KOMMUNER, year_from, region_var_hint="region"
    )
    return map_kommune_to_region(df)


def map_kommune_to_region(df: pd.DataFrame) -> pd.DataFrame:
    """
    Legger til en kolonne 'Reiselivsregion' basert på kommunenummer funnet i
    en av kolonnene til df (SSB returnerer kommune som tekstlabel, f.eks.
    "3201 Bærum" -- vi matcher på kommunenummeret først i strengen).
    """
    kommune_to_region: dict[str, str] = {}
    for region_code, kommuner in KOMMUNER_PER_REGION.items():
        for k in kommuner:
            kommune_to_region[k] = REISELIVSREGIONER[region_code]

    region_col_candidates = [c for c in df.columns if "region" in c.lower() or "kommun" in c.lower()]
    geo_col = region_col_candidates[0] if region_col_candidates else df.columns[0]

    def _lookup(value: str) -> str | None:
        value = str(value)
        for kode, navn in kommune_to_region.items():
            if value.startswith(kode):
                return navn
        return None

    df = df.copy()
    df["Reiselivsregion"] = df[geo_col].map(_lookup)
    return df


def region_navn_til_kode(navn: str) -> str:
    for kode, n in REISELIVSREGIONER.items():
        if n == navn:
            return kode
    raise KeyError(navn)
