"""
Sentral konfigurasjon for Akershus reiselivsdashbord.

Alle geografi- og tabellkoder samles her, slik at resten av koden
aldri "gjetter" på koder inline.
"""

from datetime import date

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
