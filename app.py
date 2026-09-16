"""
Reiselivsdashbord for Akershus
================================
Kjør lokalt med:  streamlit run app.py

Datakilde: SSB Statistikkbanken (PxWebApi v2), tabellene 14172-14177 og 07459.
Se README.md for forbehold om datadekning (korttidsutleie, verdiskaping).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src import data_loader as dl
from src import verdiskaping as vsk
from src.config import FYLKE_NAVN, MONTHS, REISELIVSREGIONER, START_YEAR, YEARS
from src.ssb_client import SSBApiError

st.set_page_config(
    page_title="Reiseliv i Akershus",
    page_icon="🧭",
    layout="wide",
)

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
    ["🛏️ Overnattinger", "💰 Nøkkeltall hotell", "📈 Verdiskaping", "ℹ️ Om data og forbehold"]
)

# ---------------------------------------------------------------------------
# TAB 1: Overnattinger
# ---------------------------------------------------------------------------

with tab_overnatting:
    try:
        raw = dl.load_overnattinger(START_YEAR)
    except SSBApiError as e:
        st.error(f"Klarte ikke hente overnattingsdata fra SSB.\n\n{e}")
        st.stop()

    df = region_filter(raw, valgte_regioner)
    df = filter_period(df, valgt_ar, valgte_maneder)

    innkvart_col = col(df, "innkvarteringstype", "innkvartering")
    bosted_col = col(df, "bostedsland", "bosted")
    v = value_col(df)

    total = sum_value(df)

    c1, c2, c3 = st.columns(3)
    c1.metric("Overnattinger totalt", f"{total:,.0f}".replace(",", " "))

    if bosted_col:
        norge_mask = df[bosted_col].astype(str).str.contains("norge", case=False, na=False)
        norsk = sum_value(df[norge_mask])
        internasjonalt = sum_value(df[~norge_mask])
        c2.metric("Norske overnattinger", f"{norsk:,.0f}".replace(",", " "))
        c3.metric("Internasjonale overnattinger", f"{internasjonalt:,.0f}".replace(",", " "))
    else:
        c2.metric("Norske overnattinger", "—")
        c3.metric("Internasjonale overnattinger", "—")

    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Overnattinger etter innkvarteringstype")
        if innkvart_col:
            fig = px.bar(
                df.groupby(innkvart_col, as_index=False)[v].sum(),
                x=innkvart_col, y=v, text_auto=".2s",
                labels={v: "Overnattinger", innkvart_col: "Type"},
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Fant ikke en egen 'innkvarteringstype'-kolonne i denne tabellen.")

    with col_b:
        st.subheader("Utvikling over tid")
        tid_col = col(df, "måned", "tid")
        if tid_col:
            trend = raw.copy()
            trend = region_filter(trend, valgte_regioner)
            trend = trend.groupby(tid_col, as_index=False)[value_col(trend)].sum()
            fig = px.line(trend, x=tid_col, y=value_col(trend), markers=True,
                          labels={value_col(trend): "Overnattinger", tid_col: "Måned"})
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Fordeling per reiselivsregion")
    region_col = col(df, "reiselivsregion", "region")
    if region_col:
        fig = px.bar(
            df.groupby(region_col, as_index=False)[v].sum().sort_values(v, ascending=False),
            x=region_col, y=v, text_auto=".2s",
            labels={v: "Overnattinger", region_col: "Reiselivsregion"},
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("Vis rådata"):
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
        omsetning_df = dl.load_omsetning_utnyttelse(START_YEAR)
        nokkel_df = dl.load_nokkelindikatorer(START_YEAR)
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

    vsk_df_all = vsk.load_verdiskaping()
    vsk_year, ble_justert = vsk.resolve_year(valgt_ar)
    if ble_justert:
        st.info(
            f"Verdiskapingstall finnes t.o.m. {vsk_year} (nyeste tilgjengelige "
            f"år i kildefilen). Viser {vsk_year} i stedet for {valgt_ar}."
        )

    vsk_df = vsk.filter_verdiskaping(vsk_df_all, vsk_year, valgte_regioner)

    try:
        befolkning_df = dl.load_befolkning(START_YEAR)
        befolkning_df = filter_period(befolkning_df, vsk_year, [])
        befolkning_df = region_filter(befolkning_df, valgte_regioner)
        befolkning_total = sum_value(befolkning_df)
    except SSBApiError:
        befolkning_total = None

    total_verdiskaping = vsk.total(vsk_df)

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
        bransje_df = vsk.per_bransje(vsk_df)
        fig = px.bar(
            bransje_df, x="Næring", y="Verdiskaping", text_auto=".2s",
            labels={"Verdiskaping": "Verdiskaping (kr)", "Næring": "Bransje"},
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Verdiskaping per kommune")
        kommune_df = vsk.per_kommune(vsk_df)
        fig = px.bar(
            kommune_df, x="Kommune", y="Verdiskaping", text_auto=".2s",
            labels={"Verdiskaping": "Verdiskaping (kr)"},
        )
        fig.update_xaxes(tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Utvikling over tid, per reiselivsregion")
    trend_df = vsk.per_region_trend(vsk_df_all, valgte_regioner)
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
  inn som `data/manual/verdiskaping_akershus.csv`. Dekker verdiskaping,
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

### Supplerende kilder å vurdere for v2
- [Visit Norway / Innovasjon Norge – statistikk og verktøy](https://reiseliv.innovasjonnorge.no/seksjon/statistikk-og-verktoy)
- [Eurostat – tourism database](https://ec.europa.eu/eurostat/data/database)
- [NHO Reiseliv – tall og fakta](https://www.nhoreiseliv.no/tall-og-fakta/tall-og-fakta-om-norsk-reiseliv/)

Ingen av disse har åpne, maskinlesbare API-er på linje med SSB, så de må
per i dag hentes inn manuelt (nedlastede filer / kopiert inn i egne
CSV-er under `data/manual/`) hvis du vil kombinere dem med SSB-tallene.
        """
    )
