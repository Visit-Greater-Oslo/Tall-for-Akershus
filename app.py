"""
Reiselivsdashbord for Akershus
================================
Kjør lokalt med:  streamlit run app.py

Datakilde: SSB Statistikkbanken (PxWebApi v2), tabellene 14172-14177 og
07459, samt Innovasjon Norges verdiskapingstall for reiselivet
(verdiskaping_akershus.csv). Se fanen "Om data og forbehold" i selve
appen for forbehold om datadekning.

NB: All kode ligger bevisst i denne ene filen (i stedet for flere moduler
i undermapper) for å unngå at enkeltfiler mistes ved opplasting til
GitHub via nettleseren.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Any

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(
    page_title="Reiseliv i Akershus",
    page_icon="🧭",
    layout="wide",
)

# =============================================================================
# KONFIGURASJON
# =============================================================================


# ---------------------------------------------------------------------------
# Geografi
# ---------------------------------------------------------------------------

FYLKE_NAVN = "Akershus"

# SSBs offisielle reiselivsregion-koder (brukes direkte mot tabell 14172-14177,
# som SSB publiserer PÅ reiselivsregion-nivå -- ingen aggregering nødvendig).
REISELIVSREGIONER: dict[str, str] = {
    "32101": "Asker/Bærum",
    "32102": "Follo",
    "32103": "Romerike/Hadeland",
}

# Kommuner per reiselivsregion (4-sifret SSB-kommunenummer, uten "K-"-prefiks).
# Brukes for tabeller som KUN finnes på kommunenivå (f.eks. befolkning 07459
# dersom fylkes-/regiontall ikke er tilgjengelig direkte).
KOMMUNER_PER_REGION: dict[str, list[str]] = {
    "32101": ["3201", "3203"],  # Bærum, Asker
    "32102": ["3207", "3212", "3214", "3216", "3218", "3220"],
    # Nordre Follo, Nesodden, Frogn, Vestby, Ås, Enebakk
    "32103": [
        "3205", "3209", "3222", "3224", "3226", "3228", "3230",
        "3232", "3234", "3236", "3238", "3240", "3242",
    ],
    # Lillestrøm, Ullensaker, Lørenskog, Rælingen, Aurskog-Høland, Nes,
    # Gjerdrum, Nittedal, Lunner, Jevnaker, Nannestad, Eidsvoll, Hurdal
}

ALLE_KOMMUNER: list[str] = [k for ks in KOMMUNER_PER_REGION.values() for k in ks]
ALLE_REGIONKODER: list[str] = list(REISELIVSREGIONER.keys())

# ---------------------------------------------------------------------------
# SSB-tabeller (PxWebApi v2, https://data.ssb.no/api/pxwebapi/v2/tables/<id>)
# ---------------------------------------------------------------------------

TABLES: dict[str, str] = {
    "overnattinger": "14172",          # Overnattinger per reiselivsregion
    "kapasitet_bedrifter": "14173",    # Åpne bedrifter/rom/hytter/senger
    "ankomne_gjester": "14174",        # Ankomne gjester
    "overnatting_formal": "14175",     # Overnatting etter formål (hotell)
    "omsetning_utnyttelse": "14176",   # Omsetning og kapasitetsutnyttelse (hotell)
    "nokkelindikatorer": "14177",      # Nøkkelindikatorer (hotell, bl.a. RevPAR)
    "befolkning": "07459",             # Befolkning
}

# NB: Korttidsutleie (Airbnb/Booking.com o.l.) er bevisst holdt utenfor
# omfanget til dette dashbordet (avklart med oppdragsgiver) og hentes derfor
# ikke inn i det hele tatt.

# ---------------------------------------------------------------------------
# Verdiskaping (Innovasjon Norge / Menon-tall, levert som Excel-uttrekk)
# ---------------------------------------------------------------------------

# Lokal kopi av "Aggregerte Data"-arket fra Innovasjon Norges verdiskapings-
# rapport, filtrert til Akershus sine 21 kommuner. Kolonner:
# Regnskapsår, Fylke, Kommune, Landsdel, Næring, Sektor, Verdiskaping,
# Ansatte, Årsverk, Foretak, Aktive Foretak.
VERDISKAPING_CSV = "verdiskaping_akershus.csv"
VERDISKAPING_MAX_YEAR = 2024  # nyeste år i kildefilen -- oppdater ved ny import

# ---------------------------------------------------------------------------
# Periode
# ---------------------------------------------------------------------------

START_YEAR = 2024
TODAY = date.today()
YEARS = list(range(START_YEAR, TODAY.year + 1))
MONTHS = [
    (1, "Januar"), (2, "Februar"), (3, "Mars"), (4, "April"),
    (5, "Mai"), (6, "Juni"), (7, "Juli"), (8, "August"),
    (9, "September"), (10, "Oktober"), (11, "November"), (12, "Desember"),
]

SSB_API_BASE = "https://data.ssb.no/api/pxwebapi/v2/tables"

# =============================================================================
# SSB PXWEBAPI V2 -- GENERISK KLIENT
# =============================================================================

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


def _dimension_items(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Returner (variabel_id, label) for hver dimensjon i tabellen, uansett
    hvilket av de to metadata-formatene SSB svarer med:

    - Nyere JSON-stat2-stil (nå standard i PxWebApi v2):
      {"id": ["Region", "Tid", ...], "dimension": {"Region": {"label": "region", ...}, ...}}
    - Eldre PxWebApi v1-stil:
      {"variables": [{"id": "Region", "label": "region"}, ...]}
    """
    if isinstance(metadata.get("dimension"), dict):
        order = metadata.get("id") or list(metadata["dimension"].keys())
        return [(var_id, metadata["dimension"].get(var_id, {}).get("label", "")) for var_id in order]
    return [(v.get("id", ""), v.get("label", "")) for v in metadata.get("variables", [])]


def find_variable(metadata: dict[str, Any], *keywords: str) -> dict[str, Any] | None:
    """
    Finn første variabel i metadata der id ELLER label matcher et av nøkkelordene
    (case-insensitive substring-match). Returnerer {"id": ..., "label": ...},
    eller None hvis ingen treff.
    """
    for var_id, label in _dimension_items(metadata):
        haystack = f"{var_id} {label}".lower()
        if any(k.lower() in haystack for k in keywords):
            return {"id": var_id, "label": label}
    return None


def variable_ids(metadata: dict[str, Any]) -> list[str]:
    return [var_id for var_id, _ in _dimension_items(metadata)]


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

    # Gir rå JSON-tekst rett til pyjstat i stedet for å forhåndsparse den selv:
    # pyjstat forventer enten en URL/JSON-streng (som den parser med sin egen
    # OrderedDict-hook) eller et allerede parset OrderedDict-objekt -- en vanlig
    # dict (det json.loads() gir som standard) blir feiltolket som noe som skal
    # leses fra fil/URL, og feiler med "AttributeError: 'dict' object has no
    # attribute 'read'".
    ds = pyjstat.Dataset.read(jsonstat_text)
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
    for var_id in variable_ids(meta):
        if var_id not in value_codes:
            value_codes[var_id] = "*"

    return fetch_table(table_id, value_codes)

# =============================================================================
# DATALASTING PER TABELL (cachet)
# =============================================================================

CACHE_TTL_SECONDS = 60 * 60 * 6  # 6 timer -- SSB oppdaterer typisk 1x/mnd


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter overnattingstall fra SSB …")
def load_overnattinger(year_from: int) -> pd.DataFrame:
    """
    Tabell 14172: Overnattinger per reiselivsregion, etter innkvarteringstype
    og gjestenes bostedsland. Rå, lang tabell -- appen pivoterer selv.
    """
    return fetch_all_wildcard(
        TABLES["overnattinger"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter kapasitetstall fra SSB …")
def load_kapasitet(year_from: int) -> pd.DataFrame:
    """Tabell 14173: Åpne bedrifter, rom/hytter/senger per reiselivsregion."""
    return fetch_all_wildcard(
        TABLES["kapasitet_bedrifter"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter gjestetall fra SSB …")
def load_ankomne_gjester(year_from: int) -> pd.DataFrame:
    """Tabell 14174: Ankomne gjester per reiselivsregion."""
    return fetch_all_wildcard(
        TABLES["ankomne_gjester"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter formålsdata (hotell) fra SSB …")
def load_overnatting_formal(year_from: int) -> pd.DataFrame:
    """Tabell 14175: Hotell -- overnattinger etter formål med oppholdet."""
    return fetch_all_wildcard(
        TABLES["overnatting_formal"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter omsetning/kapasitetsutnyttelse fra SSB …")
def load_omsetning_utnyttelse(year_from: int) -> pd.DataFrame:
    """Tabell 14176: Hotell -- omsetning og kapasitetsutnyttelse."""
    return fetch_all_wildcard(
        TABLES["omsetning_utnyttelse"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter nøkkelindikatorer (bl.a. RevPAR) fra SSB …")
def load_nokkelindikatorer(year_from: int) -> pd.DataFrame:
    """Tabell 14177: Hotell -- nøkkelindikatorer (bl.a. RevPAR, omsetning/gjest)."""
    return fetch_all_wildcard(
        TABLES["nokkelindikatorer"], ALLE_REGIONKODER, year_from
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Henter befolkningstall fra SSB …")
def load_befolkning(year_from: int) -> pd.DataFrame:
    """
    Tabell 07459: Befolkning. Denne publiseres normalt på KOMMUNE-nivå
    (ikke reiselivsregion), så vi henter per kommune og mapper til region
    selv -- se `map_kommune_to_region`.
    """
    df = fetch_all_wildcard(
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

# =============================================================================
# VERDISKAPING (Innovasjon Norge-tall)
# =============================================================================

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


def verdiskaping_total(df: pd.DataFrame) -> float:
    return float(df["Verdiskaping"].sum())

# =============================================================================
# STREAMLIT-APP
# =============================================================================

# ---------------------------------------------------------------------------
# Hjelpefunksjoner for å finne riktig kolonne i SSB-tabeller uten å hardkode
# eksakte kolonnenavn (som varierer litt fra tabell til tabell).
# ---------------------------------------------------------------------------

def col(df: pd.DataFrame, *keywords: str) -> str | None:
    for c in df.columns:
        if any(k.lower() in c.lower() for k in keywords):
            return c
    return None


def filter_period(df: pd.DataFrame, year: int, months: list[int]) -> pd.DataFrame:
    tid_col = col(df, "måned", "tid", "time")
    if tid_col is None:
        return df
    df = df.copy()
    # SSB-tidskoder ser typisk ut som "2024M01" eller tekstlabel "2024M01 Januar"
    df["_year"] = df[tid_col].astype(str).str.extract(r"(\d{4})").astype(float)
    df["_month"] = df[tid_col].astype(str).str.extract(r"M(\d{2})").astype(float)
    mask = df["_year"] == year
    if months:
        mask &= df["_month"].isin(months)
    return df.loc[mask].drop(columns=["_year", "_month"])


def region_filter(df: pd.DataFrame, regions: list[str]) -> pd.DataFrame:
    region_col = col(df, "reiselivsregion", "region")
    if region_col is None or not regions:
        return df
    return df[df[region_col].isin(regions)]


def value_col(df: pd.DataFrame) -> str:
    return col(df, "value") or df.columns[-1]


def sum_value(df: pd.DataFrame) -> float:
    v = value_col(df)
    return pd.to_numeric(df[v], errors="coerce").sum()


def filter_to_matching_label(df: pd.DataFrame, colname: str | None, *keywords: str) -> pd.DataFrame:
    """Behold kun rader der colname inneholder ett av søkeordene (case-insensitive)."""
    if colname is None:
        return df
    labels_lower = df[colname].astype(str).str.lower()
    mask = labels_lower.apply(lambda s: any(k.lower() in s for k in keywords))
    return df[mask]


# Kandidat-etiketter SSB typisk bruker for totalkategorien innenfor en
# dimensjon (f.eks. bostedsland). Vi matcher EKSAKT (ikke "inneholder"),
# fordi f.eks. "Utlandet i alt" inneholder delstrengen "i alt" og ville blitt
# feilaktig plukket opp av en substreng-sjekk mot totalraden "I alt".
TOTAL_LABEL_CANDIDATES = ["i alt", "alle", "totalt"]
NORGE_LABEL_CANDIDATES = ["norge"]
UTLAND_LABEL_CANDIDATES = ["utlandet i alt", "i alt utlandet", "utlandet"]


def pick_exact_label(
    df: pd.DataFrame, colname: str | None, candidates: list[str]
) -> tuple[pd.DataFrame | None, str | None]:
    """
    Finn radene som EKSAKT matcher en av kandidat-etikettene (case-insensitive,
    trimmet). Brukes for å plukke ut en éntydig total-/landsgruppe-rad fra en
    dimensjon som også inneholder enkeltland eller andre undergrupper --
    summering av HELE kolonnen ville dobbelttelle (total + landsgrupper +
    enkeltland oppå hverandre).
    """
    if colname is None:
        return None, None
    labels_lower = df[colname].astype(str).str.strip().str.lower()
    for cand in candidates:
        mask = labels_lower == cand
        if mask.any():
            return df[mask], cand
    return None, None


# ---------------------------------------------------------------------------
# Sidepanel -- filtre
# ---------------------------------------------------------------------------

st.sidebar.title("🧭 Filtre")

geo_level = st.sidebar.radio("Geografisk nivå", ["Hele fylket (Akershus)", "Velg reiselivsregion(er)"])
if geo_level == "Hele fylket (Akershus)":
    valgte_regioner = list(REISELIVSREGIONER.values())
else:
    valgte_regioner = st.sidebar.multiselect(
        "Reiselivsregion",
        options=list(REISELIVSREGIONER.values()),
        default=list(REISELIVSREGIONER.values()),
    )

valgt_ar = st.sidebar.selectbox("År", options=YEARS, index=len(YEARS) - 1)
valgte_maneder = st.sidebar.multiselect(
    "Måned (tom = alle måneder)",
    options=[m for m, _ in MONTHS],
    format_func=lambda m: dict(MONTHS)[m],
    default=[],
)

st.sidebar.caption(
    "Kilde: SSB Statistikkbanken (PxWebApi v2), tabell 14172-14177 og 07459. "
    "Data hentes live og caches i 6 timer."
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title(f"Reiseliv i {FYLKE_NAVN}")
st.caption(
    f"Viser data for {', '.join(valgte_regioner) if len(valgte_regioner) < 3 else 'hele Akershus'} "
    f"— {valgt_ar}"
    + (f", måned(er): {', '.join(dict(MONTHS)[m] for m in valgte_maneder)}" if valgte_maneder else " (alle måneder)")
)

tab_overnatting, tab_nokkeltall, tab_verdiskaping, tab_om = st.tabs(
    ["🛏️ Hotellovernattinger", "💰 Nøkkeltall hotell", "📈 Verdiskaping", "ℹ️ Om data og forbehold"]
)

# ---------------------------------------------------------------------------
# TAB 1: Overnattinger
# ---------------------------------------------------------------------------

with tab_overnatting:
    try:
        raw = load_overnattinger(START_YEAR)
    except SSBApiError as e:
        st.error(f"Klarte ikke hente overnattingsdata fra SSB.\n\n{e}")
        st.stop()

    innkvart_col = col(raw, "innkvarteringstype", "innkvartering")
    # NB: SSB bruker nynorsk-stavemåten "bustadland" i denne tabellen
    # (bekreftet i tabellens offisielle tittel), ikke "bostedsland" -- derfor
    # må vi lete etter begge stavemåtene, ellers finner vi ikke kolonnen.
    bosted_col = col(raw, "bostedsland", "bosted", "bustadland", "bustad")

    # Denne fanen viser KUN hotellovernattinger (avklart med oppdragsgiver) --
    # camping, hyttegrend m.m. filtreres bort med en gang, før noe annet
    # regnes ut, slik at ALT under (KPI-er, trend, regionfordeling) er
    # hotell-tall.
    if innkvart_col:
        raw_hotell = filter_to_matching_label(raw, innkvart_col, "hotell")
        if raw_hotell.empty:
            st.warning(
                "Fant ingen rader merket 'hotell' i innkvarteringstype-kolonnen "
                "for tabell 14172 -- SSB kan ha endret kategorinavnet. Viser "
                "alle innkvarteringstyper i stedet (se rådata under)."
            )
            raw_hotell = raw
    else:
        raw_hotell = raw

    st.caption("Viser kun hotellovernattinger (camping, hyttegrend m.m. er utelatt).")

    df = region_filter(raw_hotell, valgte_regioner)
    df = filter_period(df, valgt_ar, valgte_maneder)

    # Bostedsland-dimensjonen inneholder normalt en totalrad ("I alt"), én
    # rad for "Norge", én for "Utlandet i alt" OG enkeltland -- summering av
    # HELE kolonnen ville lagt alt dette oppå hverandre. Vi plukker derfor ut
    # de tre eksakte radene vi trenger i stedet for å summere alt.
    total_df, _ = pick_exact_label(df, bosted_col, TOTAL_LABEL_CANDIDATES)
    norge_df, _ = pick_exact_label(df, bosted_col, NORGE_LABEL_CANDIDATES)
    utland_df, _ = pick_exact_label(df, bosted_col, UTLAND_LABEL_CANDIDATES)

    c1, c2, c3 = st.columns(3)

    total = sum_value(total_df) if total_df is not None else None
    c1.metric("Hotellovernattinger totalt", f"{total:,.0f}".replace(",", " ") if total is not None else "—")

    norsk = sum_value(norge_df) if norge_df is not None else None
    internasjonalt = sum_value(utland_df) if utland_df is not None else None
    c2.metric("Norske overnattinger", f"{norsk:,.0f}".replace(",", " ") if norsk is not None else "—")
    c3.metric(
        "Internasjonale overnattinger",
        f"{internasjonalt:,.0f}".replace(",", " ") if internasjonalt is not None else "—",
    )

    if bosted_col is None:
        st.warning(
            "Fant ikke en 'bostedsland/bustadland'-kolonne i tabell 14172 i "
            "det hele tatt -- se listen over faktiske kolonnenavn i "
            "rådata-panelet nederst, så kan søkeordene i koden (`col(raw, "
            "\"bostedsland\", \"bosted\", \"bustadland\", \"bustad\")`) rettes opp."
        )
    elif total_df is None or norge_df is None or utland_df is None:
        faktiske_kategorier = sorted(df[bosted_col].dropna().unique().tolist())
        st.info(
            "Fant ikke entydige rader for 'I alt', 'Norge' og/eller "
            f"'Utlandet i alt' i bostedsland-kolonnen ('{bosted_col}') for "
            f"det valgte utvalget. Faktiske kategorier funnet: {faktiske_kategorier}"
        )
    elif total is not None and norsk is not None and internasjonalt is not None:
        avvik = total - (norsk + internasjonalt)
        if abs(avvik) > max(1.0, total * 0.01):
            st.caption(
                f"⚠️ Merk: totalt ({total:,.0f}) stemmer ikke helt med "
                f"norsk + internasjonalt ({norsk + internasjonalt:,.0f}) -- "
                f"avvik på {avvik:,.0f}. Kan skyldes uoppgitt bostedsland "
                f"i kildedataene.".replace(",", " ")
            )

    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Norske vs. internasjonale overnattinger")
        if norsk is not None and internasjonalt is not None:
            fordeling = pd.DataFrame(
                {"Type": ["Norske", "Internasjonale"], "Overnattinger": [norsk, internasjonalt]}
            )
            fig = px.bar(fordeling, x="Type", y="Overnattinger", text_auto=".2s")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Se merknad over.")

    with col_b:
        st.subheader("Utvikling over tid")
        tid_col = col(df, "måned", "tid")
        if tid_col:
            trend_source, _ = pick_exact_label(
                region_filter(raw_hotell, valgte_regioner), bosted_col, TOTAL_LABEL_CANDIDATES
            )
            if trend_source is not None:
                trend = trend_source.groupby(tid_col, as_index=False)[value_col(trend_source)].sum()
                fig = px.line(
                    trend, x=tid_col, y=value_col(trend), markers=True,
                    labels={value_col(trend): "Hotellovernattinger", tid_col: "Måned"},
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Fant ikke totalrad for bostedsland -- kan ikke vise trend trygt.")

    st.subheader("Fordeling per reiselivsregion")
    region_col = col(df, "reiselivsregion", "region")
    if region_col and total_df is not None:
        v_total = value_col(total_df)
        fig = px.bar(
            total_df.groupby(region_col, as_index=False)[v_total].sum().sort_values(v_total, ascending=False),
            x=region_col, y=v_total, text_auto=".2s",
            labels={v_total: "Hotellovernattinger", region_col: "Reiselivsregion"},
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("Vis rådata (kun hotell, valgt periode)"):
        st.dataframe(df, use_container_width=True)

# ---------------------------------------------------------------------------
# TAB 2: Nøkkeltall hotell
# ---------------------------------------------------------------------------

with tab_nokkeltall:
    st.caption(
        "Basert på tabell 14176 (omsetning og kapasitetsutnyttelse) og "
        "14177 (nøkkelindikatorer). Velg selv hvilken indikator-rad som "
        "skal vises — SSBs eksakte indikatornavn kan variere litt mellom "
        "tabellene."
    )
    try:
        omsetning_df = load_omsetning_utnyttelse(START_YEAR)
        nokkel_df = load_nokkelindikatorer(START_YEAR)
    except SSBApiError as e:
        st.error(f"Klarte ikke hente nøkkeltall fra SSB.\n\n{e}")
        st.stop()

    # --- RevPAR = Losjiomsetning per tilgjengelig rom -----------------------
    # Beregnes selv i stedet for å stole på at SSB har en ferdig "RevPAR"-rad,
    # siden vi ikke kan bekrefte det eksakte indikatornavnet live. Hvis vi
    # ikke finner begge nødvendige rader, vises panelet rett og slett ikke.
    st.subheader("RevPAR — Losjiomsetning per tilgjengelig rom")
    revpar_df = region_filter(omsetning_df, valgte_regioner)
    revpar_df = filter_period(revpar_df, valgt_ar, valgte_maneder)
    indikator_col = col(revpar_df, "statistikkvariabel", "contentscode", "indikator")
    tid_col = col(revpar_df, "måned", "tid")
    region_col = col(revpar_df, "reiselivsregion", "region")
    v = value_col(revpar_df)

    revpar_computed = False
    if indikator_col and tid_col and region_col:
        labels = revpar_df[indikator_col].dropna().unique().tolist()
        losji_label = next((l for l in labels if "losji" in str(l).lower()), None)
        rom_label = next(
            (l for l in labels if ("tilgjengelig" in str(l).lower() or "disponibl" in str(l).lower())
             and "rom" in str(l).lower()),
            None,
        )
        if losji_label and rom_label:
            losji = revpar_df[revpar_df[indikator_col] == losji_label][[tid_col, region_col, v]]
            rom = revpar_df[revpar_df[indikator_col] == rom_label][[tid_col, region_col, v]]
            merged = losji.merge(rom, on=[tid_col, region_col], suffixes=("_losji", "_rom"))
            merged = merged[merged[f"{v}_rom"].astype(float) > 0]
            if not merged.empty:
                merged["RevPAR"] = pd.to_numeric(merged[f"{v}_losji"], errors="coerce") / pd.to_numeric(
                    merged[f"{v}_rom"], errors="coerce"
                )
                fig = px.line(
                    merged.sort_values(tid_col), x=tid_col, y="RevPAR", color=region_col,
                    markers=True, labels={tid_col: "Måned", "RevPAR": "RevPAR (kr)"},
                )
                st.plotly_chart(fig, use_container_width=True)
                revpar_computed = True

    if not revpar_computed:
        st.info(
            "Fant ikke rader for både 'losjiomsetning' og 'tilgjengelige "
            "rom' i tabell 14176 for det valgte utvalget, så RevPAR kan "
            "ikke beregnes akkurat nå. Sjekk indikatornavnene i "
            "rådata-panelet under for å se om oppslaget i "
            "`app.py` (funksjonen som finner disse to radene) bør justeres."
        )

    st.divider()

    for label, source_df in [
        ("Omsetning og kapasitetsutnyttelse (tabell 14176)", omsetning_df),
        ("Nøkkelindikatorer, inkl. RevPAR (tabell 14177)", nokkel_df),
    ]:
        st.subheader(label)
        df = region_filter(source_df, valgte_regioner)
        df = filter_period(df, valgt_ar, valgte_maneder)

        indikator_col = col(df, "statistikkvariabel", "contentscode", "indikator")
        v = value_col(df)

        if indikator_col:
            indikatorer = sorted(df[indikator_col].dropna().unique().tolist())
            valgt_indikator = st.selectbox(
                "Velg indikator", indikatorer, key=f"indikator_{label}"
            )
            plot_df = df[df[indikator_col] == valgt_indikator]
            tid_col = col(plot_df, "måned", "tid")
            region_col = col(plot_df, "reiselivsregion", "region")
            if tid_col and region_col:
                fig = px.line(
                    plot_df.sort_values(tid_col), x=tid_col, y=v, color=region_col,
                    markers=True, labels={v: valgt_indikator, tid_col: "Måned"},
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Fant ikke en indikator-kolonne i denne tabellen -- se rådata under.")

        with st.expander(f"Vis rådata — {label}"):
            st.dataframe(df, use_container_width=True)

# ---------------------------------------------------------------------------
# TAB 3: Verdiskaping
# ---------------------------------------------------------------------------

with tab_verdiskaping:
    st.caption(
        "Kilde: Innovasjon Norges verdiskapingstall for reiselivet "
        "(regnskapsbasert, faste 2024-priser). Årlige tall — måned-filteret "
        "påvirker ikke denne fanen."
    )

    vsk_df_all = load_verdiskaping()
    vsk_year, ble_justert = resolve_year(valgt_ar)
    if ble_justert:
        st.info(
            f"Verdiskapingstall finnes t.o.m. {vsk_year} (nyeste tilgjengelige "
            f"år i kildefilen). Viser {vsk_year} i stedet for {valgt_ar}."
        )

    vsk_df = filter_verdiskaping(vsk_df_all, vsk_year, valgte_regioner)

    try:
        befolkning_df = load_befolkning(START_YEAR)
        befolkning_df = filter_period(befolkning_df, vsk_year, [])
        befolkning_df = region_filter(befolkning_df, valgte_regioner)
        befolkning_total = sum_value(befolkning_df)
    except SSBApiError:
        befolkning_total = None

    total_verdiskaping = verdiskaping_total(vsk_df)

    c1, c2 = st.columns(2)
    c1.metric(f"Verdiskaping totalt ({vsk_year})", f"{total_verdiskaping / 1e6:,.0f} mill. kr".replace(",", " "))
    if befolkning_total:
        per_innbygger = total_verdiskaping / befolkning_total
        c2.metric("Verdiskaping per innbygger", f"{per_innbygger:,.0f} kr".replace(",", " "))
    else:
        c2.metric("Verdiskaping per innbygger", "—", help="Klarte ikke hente befolkningstall fra SSB akkurat nå.")

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Verdiskaping per reiselivsbransje")
        bransje_df = per_bransje(vsk_df)
        fig = px.bar(
            bransje_df, x="Næring", y="Verdiskaping", text_auto=".2s",
            labels={"Verdiskaping": "Verdiskaping (kr)", "Næring": "Bransje"},
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Verdiskaping per kommune")
        kommune_df = per_kommune(vsk_df)
        fig = px.bar(
            kommune_df, x="Kommune", y="Verdiskaping", text_auto=".2s",
            labels={"Verdiskaping": "Verdiskaping (kr)"},
        )
        fig.update_xaxes(tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Utvikling over tid, per reiselivsregion")
    trend_df = per_region_trend(vsk_df_all, valgte_regioner)
    fig = px.line(
        trend_df, x="Regnskapsår", y="Verdiskaping", color="Reiselivsregion",
        markers=True, labels={"Verdiskaping": "Verdiskaping (kr)"},
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Vis rådata — verdiskaping"):
        st.dataframe(vsk_df, use_container_width=True)

# ---------------------------------------------------------------------------
# TAB 4: Om data og forbehold
# ---------------------------------------------------------------------------

with tab_om:
    st.markdown(
        """
### Kilder brukt i denne versjonen
- **SSB Statistikkbanken** (PxWebApi v2), tabellene:
  - 14172 – Overnattinger per reiselivsregion
  - 14173 – Åpne bedrifter/rom/hytter/senger
  - 14174 – Ankomne gjester
  - 14175 – Overnatting etter formål (hotell)
  - 14176 – Omsetning og kapasitetsutnyttelse (hotell) — grunnlag for RevPAR
  - 14177 – Nøkkelindikatorer (hotell)
  - 07459 – Befolkning
- **Innovasjon Norges verdiskapingstall for reiselivet** (regnskapsbasert,
  Brønnøysundregistrene/Menon-metodikk), levert som Excel-uttrekk og lagt
  inn som `verdiskaping_akershus.csv`. Dekker verdiskaping,
  ansatte, årsverk og antall foretak per kommune, bransje og år
  (2015–2024).

### Avklarte forhold (oppdatert etter tilbakemelding)
1. **Korttidsutleie (Airbnb/Booking.com) er bevisst tatt ut av omfanget**
   og hentes ikke inn i denne versjonen.
2. **RevPAR er definert som losjiomsetning per tilgjengelig rom**, og
   beregnes i appen ved å dele "losjiomsetning"-raden på
   "tilgjengelige/disponible rom"-raden i tabell 14176 for samme
   region/måned — i stedet for å stole på at SSB har en egen ferdig
   RevPAR-rad et sted vi ikke har kunnet bekrefte navnet på. Hvis appen
   ikke finner begge radene for et gitt utvalg, vises panelet rett og
   slett ikke (i stedet for et feilaktig tall).
3. **Verdiskaping per bransje og kommune er nå dekket** via Innovasjon
   Norge-filen, inkludert et forsøk på verdiskaping per innbygger (delt
   på SSBs befolkningstall for samme område). Tallene er årlige og går
   t.o.m. 2024 — nyere år vises ikke før kildefilen oppdateres.
4. **Overnattingsfanen viser kun hotell** — camping, hyttegrend og andre
   innkvarteringstyper i tabell 14172 filtreres bort. Norsk/internasjonalt-
   fordelingen beregnes ved å plukke ut de eksakte radene "I alt" og
   "Norge" fra bostedsland-kolonnen (internasjonalt = totalt − norsk),
   i stedet for å summere hele kolonnen — bostedsland inneholder nemlig
   både en totalsum, landsgrupper og enkeltland samtidig, og en ren
   summering ville telt alt dette flere ganger oppå hverandre.

### Supplerende kilder å vurdere for v2
- [Visit Norway / Innovasjon Norge – statistikk og verktøy](https://reiseliv.innovasjonnorge.no/seksjon/statistikk-og-verktoy)
- [Eurostat – tourism database](https://ec.europa.eu/eurostat/data/database)
- [NHO Reiseliv – tall og fakta](https://www.nhoreiseliv.no/tall-og-fakta/tall-og-fakta-om-norsk-reiseliv/)

Ingen av disse har åpne, maskinlesbare API-er på linje med SSB, så de må
per i dag hentes inn manuelt (nedlastede filer / kopiert inn i egne
CSV-er under `(rotmappen, ikke undermappe)/`) hvis du vil kombinere dem med SSB-tallene.
        """
    )
