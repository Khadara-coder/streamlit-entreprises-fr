"""Streamlit-Entreprises-FR — recherche d'entreprises françaises (publiable sur Streamlit Cloud).

API principale : Recherche d'Entreprises (api.gouv.fr) — gratuite, sans clé.
API optionnelle : INSEE Sirene 3.11 — si l'utilisateur fournit sa clé en sidebar.
Aucune base de données, aucun secret obligatoire.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Permet `streamlit run streamlit_app.py` depuis la racine du repo
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import identifiers
from app.export import to_csv_bytes, to_excel_bytes
from app.insee_client import InseeClient, InseeError
from app.naf import load_naf_labels
from app.normalize import order_columns, from_recherche_entreprises
from app.recherche_entreprises_client import (
    RechercheEntreprisesClient,
    RechercheEntreprisesError,
)
from app.search_service import establishments_by_sirens, lookup_identifiers, search_by_text

st.set_page_config(
    page_title="Entreprises FR — Recherche publique",
    page_icon="🏢",
    layout="wide",
)


# ----------------------------------------------------------------------- helpers
@st.cache_resource(show_spinner=False)
def get_re_client() -> RechercheEntreprisesClient:
    return RechercheEntreprisesClient()


@st.cache_data(show_spinner=False, ttl=24 * 60 * 60)
def get_naf_labels() -> dict[str, str]:
    return load_naf_labels()


def get_optional_secret(name: str, default: str = "") -> str:
    env_value = os.environ.get(name)
    if env_value:
        return env_value
    try:
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


def render_downloads(df: pd.DataFrame, base_name: str, key: str) -> None:
    if df.empty:
        return
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Télécharger Excel",
            data=to_excel_bytes(df),
            file_name=f"{base_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key}_xlsx",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "⬇️ Télécharger CSV (;)",
            data=to_csv_bytes(df),
            file_name=f"{base_name}.csv",
            mime="text/csv",
            key=f"{key}_csv",
            use_container_width=True,
        )


def make_progress():
    bar = st.progress(0.0)
    txt = st.empty()

    def update(current: int, total: int, message: str = "") -> None:
        bar.progress(min(current / max(total, 1), 1.0))
        if message:
            txt.info(message)

    return update, bar, txt


# ------------------------------------------------------------------------ header
st.title("🏢 Entreprises FR — Recherche publique")
st.caption(
    "Recherchez des entreprises françaises à partir d'un SIREN/SIRET, "
    "d'une raison sociale, d'une adresse, ou enrichissez un fichier Excel/CSV en masse. "
    "Source principale : **API Recherche d'Entreprises** (api.gouv.fr — gratuite, sans clé)."
)


# ----------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    st.markdown(
        "**Source principale** : API publique gratuite *Recherche d'Entreprises*.\n\n"
        "Aucune clé requise — fonctionne tout de suite."
    )
    st.markdown("---")
    st.subheader("Clé INSEE Sirene (optionnel)")
    st.caption("Améliore l'enrichissement pour les SIREN/SIRET introuvables côté API publique.")
    insee_key = st.text_input(
        "Clé X-INSEE-Api-Key-Integration",
        type="password",
        value=get_optional_secret("INSEE_API_KEY"),
    )
    insee_client: InseeClient | None = None
    if insee_key:
        try:
            insee_client = InseeClient(api_key=insee_key)
        except InseeError as exc:
            st.error(str(exc))
            insee_client = None
        if insee_client and st.button("🔌 Tester la clé INSEE"):
            ok, msg = insee_client.test_key()
            (st.success if ok else st.error)(msg)
    st.markdown("---")
    st.markdown(
        "**Limites API publique** : 7 req/s, 10 000 résultats max par requête.\n\n"
        "**Documentation** : [recherche-entreprises.api.gouv.fr](https://recherche-entreprises.api.gouv.fr/docs/)"
    )


re_client = get_re_client()


# ------------------------------------------------------------------------- tabs
tab_id, tab_estabs, tab_name, tab_addr, tab_batch, tab_reliability, tab_help = st.tabs(
    [
        "🔢 Par SIREN / SIRET",
        "🏬 Établissements par SIREN",
        "🏷️ Par raison sociale / nom",
        "📍 Par adresse / géographie",
        "📂 Lot Excel / CSV",
        "🛡️ Fiabilité",
        "ℹ️ Aide",
    ]
)


# =========================================================== TAB 1 : par identifiant
with tab_id:
    st.subheader("Recherche par identifiants SIREN / SIRET")
    raw = st.text_area(
        "Un identifiant par ligne (ou séparés par , ;) — SIREN (9 chiffres) ou SIRET (14 chiffres)",
        value="552100554\n44306184100047\n542065479",
        height=130,
    )
    if st.button("🔎 Rechercher", type="primary", key="run_ids"):
        ids = identifiers.parse_batch(raw)
        if not ids:
            st.error("Aucun identifiant valide détecté.")
        else:
            update, _, _ = make_progress()
            with st.spinner("Recherche en cours…"):
                df, errors = lookup_identifiers(
                    re_client, ids, insee_client=insee_client, progress=update
                )
            st.success(f"{len(df)} résultat(s) trouvé(s) sur {len(ids)} identifiant(s).")
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
                render_downloads(df, "entreprises_par_identifiants", key="ids_dl")
            if not errors.empty:
                with st.expander(f"⚠️ {len(errors)} erreur(s) / non trouvés", expanded=False):
                    st.dataframe(errors, use_container_width=True, hide_index=True)


# =========================================================== TAB 2 : établissements par SIREN
with tab_estabs:
    st.subheader("Établissements d'une ou plusieurs entreprises")
    st.caption(
        "Colle un ou plusieurs SIREN/SIRET. Le résultat contient une ligne de synthèse "
        "par SIREN, puis les établissements rattachés."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        estabs_raw = st.text_area(
            "SIREN ou SIRET à traiter",
            value="682033899",
            height=130,
            help=(
                "Un identifiant par ligne, ou séparés par virgule/point-virgule. "
                "Si tu colles un SIRET, l'app utilise son SIREN de rattachement."
            ),
        )
    with col2:
        if insee_client is not None:
            fetch_all_estabs = st.checkbox(
                "Tout récupérer via INSEE",
                value=True,
                help="Utilise la pagination de l'API Sirene. Décoche pour limiter le volume.",
            )
            estabs_limit = None
            if not fetch_all_estabs:
                estabs_limit = st.number_input(
                    "Max établissements",
                    min_value=1,
                    max_value=200000,
                    value=1000,
                    step=100,
                )
        else:
            fetch_all_estabs = False
            estabs_limit = st.number_input(
                "Max établissements",
                min_value=1,
                max_value=100,
                value=100,
                step=5,
                help="Sans clé INSEE, l'API publique expose au maximum 100 établissements connexes.",
            )

    if insee_client is None:
        st.info(
            "Sans clé INSEE, l'application utilise l'API publique Recherche d'Entreprises "
            "et peut afficher jusqu'à 100 établissements. Pour récupérer toute la liste "
            "des grands réseaux, renseigne une clé API Sirene INSEE gratuite et personnelle "
            "dans la sidebar."
        )

    if st.button("🏬 Lister les établissements", type="primary", key="run_estabs"):
        raw_ids = identifiers.parse_batch(estabs_raw)
        valid_ids, invalid_ids = identifiers.split_valid_invalid(raw_ids)
        sirens: list[str] = []
        seen_sirens: set[str] = set()
        for ident in valid_ids:
            siren = ident[:9]
            if siren not in seen_sirens:
                seen_sirens.add(siren)
                sirens.append(siren)

        if not sirens:
            st.error("Aucun SIREN/SIRET valide détecté.")
        else:
            try:
                with st.spinner("Recherche des établissements…"):
                    progress_update, _, _ = make_progress()
                    naf_labels = get_naf_labels()
                    df_estabs, errors = establishments_by_sirens(
                        re_client,
                        sirens,
                        insee_client=insee_client,
                        naf_labels=naf_labels,
                        limit=None if fetch_all_estabs else int(estabs_limit),
                        progress=progress_update,
                    )
            except (RechercheEntreprisesError, InseeError) as exc:
                st.error(f"Erreur API : {exc}")
            else:
                if df_estabs.empty:
                    st.warning("Aucun établissement diffusible trouvé pour les SIREN fournis.")
                else:
                    summary_rows = df_estabs[df_estabs["Ligne"].eq("unité légale")]
                    establishment_rows = df_estabs[df_estabs["Ligne"].eq("établissement")]
                    st.success(
                        f"{len(establishment_rows)} établissement(s) récupéré(s) "
                        f"pour {len(summary_rows)} SIREN."
                    )
                    c1, c2, c3 = st.columns(3)
                    c1.metric("SIREN traités", len(summary_rows))
                    c2.metric("Établissements", len(establishment_rows))
                    c3.metric("Lignes exportées", len(df_estabs))

                    overview = summary_rows.copy()
                    overview["Établissements récupérés"] = pd.to_numeric(
                        overview.get("Établissements récupérés"),
                        errors="coerce",
                    ).fillna(0).astype(int)
                    overview["Lignes exportées"] = overview["Établissements récupérés"] + 1
                    overview_cols = [
                        "SIREN",
                        "Entreprise",
                        "État",
                        "Total établissements annoncé",
                        "Établissements ouverts annoncés",
                        "Établissements récupérés",
                        "Lignes exportées",
                        "Source",
                    ]
                    overview_cols = [c for c in overview_cols if c in overview.columns]
                    st.markdown("### Synthèse par SIREN traité")
                    st.dataframe(
                        overview[overview_cols],
                        use_container_width=True,
                        hide_index=True,
                    )

                    totals = pd.to_numeric(
                        summary_rows.get("Total établissements annoncé"),
                        errors="coerce",
                    )
                    fetched = pd.to_numeric(
                        summary_rows.get("Établissements récupérés"),
                        errors="coerce",
                    )
                    limited = summary_rows[totals.fillna(0) > fetched.fillna(0)]
                    if not limited.empty:
                        if insee_client is not None and not fetch_all_estabs:
                            st.warning(
                                "Certaines listes sont limitées par le maximum choisi dans l'interface."
                            )
                        elif insee_client is None:
                            st.warning(
                                "Certaines listes sont limitées par l'API publique à 100 établissements. "
                                "Ajoute une clé API Sirene INSEE gratuite et personnelle pour tout récupérer."
                            )
                        with st.expander("Voir les SIREN limités", expanded=False):
                            st.dataframe(
                                limited[
                                    [
                                        "SIREN",
                                        "Entreprise",
                                        "Total établissements annoncé",
                                        "Établissements récupérés",
                                    ]
                                ],
                                use_container_width=True,
                                hide_index=True,
                            )

                    if insee_client is not None:
                        st.caption("Source : API Sirene INSEE — liste complète paginée quand l'option est cochée.")
                    else:
                        st.caption("Source : INSEE via API Recherche d'Entreprises — limite publique de 100 établissements par SIREN.")

                    display_cols = [
                        "SIREN",
                        "Ligne",
                        "SIRET",
                        "Entreprise",
                        "Activité (NAF/APE)",
                        "Détails (nom, enseigne, adresse)",
                        "Création",
                        "État",
                        "Siège social",
                    ]
                    display_cols = [c for c in display_cols if c in df_estabs.columns]
                    st.dataframe(
                        df_estabs[display_cols],
                        use_container_width=True,
                        hide_index=True,
                    )

                    geo = df_estabs.dropna(subset=["Latitude", "Longitude"]).copy()
                    if not geo.empty:
                        geo["latitude"] = pd.to_numeric(geo["Latitude"], errors="coerce")
                        geo["longitude"] = pd.to_numeric(geo["Longitude"], errors="coerce")
                        geo = geo.dropna(subset=["latitude", "longitude"])
                        if not geo.empty:
                            with st.expander("📍 Carte des établissements", expanded=False):
                                st.map(geo[["latitude", "longitude"]])

                    render_downloads(df_estabs, "etablissements_par_siren", key="estabs_dl")

                if invalid_ids:
                    with st.expander(f"⚠️ {len(invalid_ids)} identifiant(s) invalide(s)", expanded=False):
                        st.dataframe(
                            pd.DataFrame(
                                {"identifiant": invalid_ids, "erreur": "format/Luhn invalide"}
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                if not errors.empty:
                    with st.expander(f"⚠️ {len(errors)} SIREN en erreur / non trouvé(s)", expanded=False):
                        st.dataframe(errors, use_container_width=True, hide_index=True)


# =========================================================== TAB 3 : par raison sociale
with tab_name:
    st.subheader("Recherche par raison sociale ou nom")
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Raison sociale, nom commercial, sigle, ou nom de dirigeant",
            value="PEUGEOT",
            help="L'API gère la tolérance aux typos, la pertinence multi-mots et les dirigeants.",
        )
    with col2:
        max_results = st.number_input("Max résultats", min_value=25, max_value=10000, value=200, step=25)

    with st.expander("🔍 Filtres avancés", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            nature_juridique = st.text_input("Catégorie juridique (code)", value="", help="Ex: 5710 (SAS), 5499 (SARL)")
            etat = st.selectbox("État administratif", ["", "A (actif)", "C (cessé)"])
            etat_code = etat.split(" ")[0] if etat else None
        with c2:
            activite = st.text_input("Code NAF/APE", value="", help="Ex: 62.01Z")
            section = st.text_input("Section NAF (lettre)", value="", help="Ex: J pour Information/Communication")
        with c3:
            cp_filter = st.text_input("Code postal", value="")
            dep_filter = st.text_input("Département (code)", value="", help="Ex: 75, 2A, 974")
            siege_only = st.checkbox("Sièges sociaux uniquement", value=False)

    if st.button("🔎 Rechercher", type="primary", key="run_name"):
        if not query and not (cp_filter or dep_filter or activite or section or nature_juridique):
            st.error("Saisis au moins une raison sociale ou un filtre.")
        else:
            update, _, _ = make_progress()
            try:
                with st.spinner("Recherche en cours…"):
                    df, total = search_by_text(
                        re_client,
                        query=query,
                        code_postal=cp_filter or None,
                        departement=dep_filter or None,
                        activite_principale=activite or None,
                        section=section or None,
                        nature_juridique=nature_juridique or None,
                        etat_administratif=etat_code or None,
                        est_siege=True if siege_only else None,
                        max_results=int(max_results),
                        progress=update,
                    )
            except RechercheEntreprisesError as exc:
                st.error(f"Erreur API : {exc}")
            else:
                st.success(f"{len(df)} résultat(s) affichés (total disponible côté API : {total}).")
                if not df.empty:
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    render_downloads(df, "entreprises_par_nom", key="name_dl")


# =========================================================== TAB 3 : par adresse
with tab_addr:
    st.subheader("Recherche par adresse / géographie")
    st.caption(
        "Combine une requête texte (raison sociale, voie, mots-clés) avec des filtres géographiques."
    )
    col1, col2 = st.columns(2)
    with col1:
        addr_query = st.text_input("Requête texte (nom, voie, mots-clés)", value="boulangerie")
        addr_cp = st.text_input("Code postal", value="75001")
    with col2:
        addr_dep = st.text_input("Département", value="")
        addr_max = st.number_input("Max résultats", 25, 10000, 100, 25, key="addr_max")

    if st.button("🔎 Rechercher", type="primary", key="run_addr"):
        update, _, _ = make_progress()
        try:
            with st.spinner("Recherche en cours…"):
                df, total = search_by_text(
                    re_client,
                    query=addr_query,
                    code_postal=addr_cp or None,
                    departement=addr_dep or None,
                    max_results=int(addr_max),
                    progress=update,
                )
        except RechercheEntreprisesError as exc:
            st.error(f"Erreur API : {exc}")
        else:
            st.success(f"{len(df)} résultat(s) affichés (total : {total}).")
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
                # Carte si lat/lon disponibles
                geo = df.dropna(subset=["latitude", "longitude"]).copy()
                if not geo.empty:
                    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
                    geo["longitude"] = pd.to_numeric(geo["longitude"], errors="coerce")
                    geo = geo.dropna(subset=["latitude", "longitude"])
                    if not geo.empty:
                        st.map(geo[["latitude", "longitude"]])
                render_downloads(df, "entreprises_par_adresse", key="addr_dl")


# =========================================================== TAB 4 : lot Excel/CSV
with tab_batch:
    st.subheader("Enrichissement en masse depuis Excel ou CSV")
    st.caption(
        "Charge un fichier contenant des SIREN, des SIRET ou des raisons sociales — "
        "le fichier d'origine est enrichi colonne par colonne, sans persistance serveur."
    )

    with st.expander("📘 **Mode d'emploi — format du fichier et colonnes**", expanded=True):
        st.markdown(
            """
**1. Format accepté** : `.xlsx`, `.xls` ou `.csv` (séparateur auto-détecté `;` `,` ou tabulation).
La **première ligne doit contenir les en-têtes** de colonnes.

**2. Une seule colonne sert d'entrée** : tu la choisis dans le menu *Colonne source* après upload.
Cette colonne peut contenir **n'importe lequel** des éléments suivants :

| Type de valeur | Exemple | Détecté en mode *Auto* |
|---|---|---|
| **SIREN** (9 chiffres) | `552100554` | ✅ recherche directe |
| **SIRET** (14 chiffres) | `55210055400067` | ✅ recherche directe |
| **Raison sociale / nom** | `PEUGEOT SA` | ✅ recherche textuelle |
| **Nom + ville** | `BOULANGERIE DUPONT PARIS` | ✅ recherche textuelle |
| **Nom de dirigeant** | `Bernard Arnault` | ✅ recherche textuelle |

Les espaces, tirets et points dans les SIREN/SIRET sont ignorés (`552 100 554` ⇢ `552100554`).
La validation **Luhn** est appliquée automatiquement aux identifiants.

**3. Toutes les autres colonnes du fichier sont conservées telles quelles** et placées
**avant** les colonnes enrichies. Tu peux donc avoir un fichier client complet
(`Nom_Client`, `Code_Tier`, `Montant`, …) et seulement enrichir à partir de la
colonne `SIREN` ou `Raison_Sociale`.

**4. Colonnes ajoutées par l'enrichissement** (préfixées en clair, source officielle) :
`denomination`, `siren`, `siret_siege`, `etat_administratif`, `date_creation`,
`activite_principale`, `section_activite`, `nature_juridique`, `tranche_effectifs`,
`categorie_entreprise`, `adresse`, `code_postal`, `commune`, `departement`,
`region`, `latitude`, `longitude`, `dirigeants`, `source`, et une colonne de
contrôle `_match_status` (`ok`, `ok-insee`, `aucun`, `introuvable`, `vide`,
`erreur: …`).

**5. Modes de recherche** :
- **Auto** *(recommandé)* : détecte SIREN/SIRET par leur format, sinon recherche textuelle.
- **Forcer SIREN/SIRET** : utile si ta colonne ne contient QUE des identifiants
  (rejette explicitement les valeurs invalides au lieu de tenter une recherche par nom).
- **Forcer raison sociale** : utile si tu as des numéros de téléphone, des codes
  internes, etc., qui ressembleraient à des SIREN/SIRET — mais que tu veux
  traiter comme du texte libre.

**6. Limite par ligne (mode texte uniquement)** : par défaut **1 résultat** (le plus
pertinent) est conservé. Tu peux remonter jusqu'à 10, mais chaque ligne
produit alors jusqu'à 10 lignes en sortie (utile pour vérifier les homonymes).

**7. Performance** : ~6 requêtes / seconde (limite API publique). Pour
**500 lignes**, compte ≈ 1,5 min. L'app n'écrit **rien** côté serveur, le
fichier enrichi est uniquement disponible via le bouton *Télécharger*.

**8. Aucun secret requis** — la clé INSEE (sidebar) sert uniquement de
*fallback* pour les SIREN/SIRET introuvables côté API publique.
            """
        )

    with st.expander("📥 Télécharger un modèle de fichier", expanded=False):
        sample = pd.DataFrame(
            {
                "id_interne": ["C001", "C002", "C003", "C004", "C005"],
                "valeur_a_chercher": [
                    "552100554",          # SIREN
                    "55210055400067",     # SIRET
                    "PEUGEOT SA",         # raison sociale
                    "DANONE 75009",       # nom + code postal
                    "Bernard Arnault",    # dirigeant
                ],
                "commentaire": [
                    "SIREN Peugeot",
                    "SIRET siège Peugeot",
                    "Raison sociale",
                    "Nom + code postal",
                    "Dirigeant",
                ],
            }
        )
        st.dataframe(sample, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "⬇️ Modèle Excel",
                data=to_excel_bytes(sample),
                file_name="modele_entreprises_fr.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="tpl_xlsx",
                use_container_width=True,
            )
        with c2:
            st.download_button(
                "⬇️ Modèle CSV",
                data=to_csv_bytes(sample),
                file_name="modele_entreprises_fr.csv",
                mime="text/csv",
                key="tpl_csv",
                use_container_width=True,
            )

    file = st.file_uploader("Fichier .xlsx ou .csv", type=["xlsx", "xls", "csv"])
    if file is not None:
        try:
            if file.name.lower().endswith(".csv"):
                df_in = pd.read_csv(file, sep=None, engine="python", dtype=str).fillna("")
            else:
                df_in = pd.read_excel(file, dtype=str).fillna("")
        except Exception as exc:
            st.error(f"Lecture impossible : {exc}")
            df_in = None

        if df_in is not None:
            st.write(f"**{len(df_in)} ligne(s)** — aperçu :")
            st.dataframe(df_in.head(20), use_container_width=True, hide_index=True)

            # Détection auto de la meilleure colonne candidate
            def _score_col(col: str) -> int:
                low = col.lower()
                if any(k in low for k in ("siret",)):
                    return 100
                if any(k in low for k in ("siren",)):
                    return 90
                if any(k in low for k in ("raison", "denomin", "nom_société", "nom_societe", "company")):
                    return 80
                if "nom" in low:
                    return 50
                return 0

            cols = list(df_in.columns)
            default_idx = max(range(len(cols)), key=lambda i: _score_col(cols[i])) if cols else 0

            col1, col2 = st.columns(2)
            with col1:
                source_col = st.selectbox(
                    "Colonne source (valeur à rechercher)",
                    options=cols,
                    index=default_idx,
                    help="Colonne contenant le SIREN, SIRET, raison sociale ou nom à chercher.",
                )
            with col2:
                mode = st.radio(
                    "Type de recherche",
                    ["Auto (détecte SIREN/SIRET ou texte)", "Forcer SIREN/SIRET", "Forcer raison sociale"],
                    index=0,
                    help=(
                        "Auto : recommandé — détecte le format ligne par ligne. "
                        "Force SIREN/SIRET : rejette les valeurs non numériques 9/14 chiffres. "
                        "Force raison sociale : traite tout en texte libre."
                    ),
                )

            limit_per_query = st.number_input(
                "Nombre de résultats par ligne (recherche textuelle uniquement)",
                min_value=1,
                max_value=10,
                value=1,
                help=(
                    "Pour les recherches par nom : 1 = top match seulement. "
                    "Augmente si tu veux voir les homonymes (le fichier de sortie aura "
                    "plusieurs lignes par ligne d'entrée)."
                ),
            )

            if st.button("🚀 Lancer l'enrichissement", type="primary", key="run_batch"):
                update, bar, txt = make_progress()
                enriched_rows: list[dict] = []
                errors: list[dict] = []
                total = len(df_in)

                for idx, (_, row) in enumerate(df_in.iterrows(), 1):
                    val = str(row[source_col]).strip()
                    if not val:
                        enriched_rows.append({**row.to_dict(), "_match_status": "vide"})
                        update(idx, total, f"{idx}/{total}")
                        continue

                    norm_val = identifiers.normalize(val)
                    k = identifiers.kind(norm_val)
                    treat_as_id = (
                        mode == "Forcer SIREN/SIRET"
                        or (mode.startswith("Auto") and k in {"siren", "siret"})
                    )

                    try:
                        if treat_as_id and k in {"siren", "siret"}:
                            hit = re_client.by_siren(norm_val) if k == "siren" else re_client.by_siret(norm_val)
                            if hit:
                                enriched = order_columns(from_recherche_entreprises(hit))
                                enriched_rows.append({**row.to_dict(), **enriched, "_match_status": "ok"})
                            elif insee_client is not None:
                                payload = (
                                    insee_client.get_siren(norm_val)
                                    if k == "siren"
                                    else insee_client.get_siret(norm_val)
                                )
                                if payload:
                                    from app.normalize import from_insee_siren, from_insee_siret

                                    enriched = order_columns(
                                        from_insee_siren(payload) if k == "siren" else from_insee_siret(payload)
                                    )
                                    enriched_rows.append({**row.to_dict(), **enriched, "_match_status": "ok-insee"})
                                else:
                                    enriched_rows.append({**row.to_dict(), "_match_status": "introuvable"})
                            else:
                                enriched_rows.append({**row.to_dict(), "_match_status": "introuvable"})
                        else:
                            data = re_client.search(query=val, per_page=int(limit_per_query))
                            results = data.get("results", [])
                            if not results:
                                enriched_rows.append({**row.to_dict(), "_match_status": "aucun"})
                            else:
                                top = order_columns(from_recherche_entreprises(results[0]))
                                top["_match_status"] = "ok"
                                top["_match_total_candidats"] = data.get("total_results", len(results))
                                enriched_rows.append({**row.to_dict(), **top})
                    except (RechercheEntreprisesError, InseeError) as exc:
                        enriched_rows.append({**row.to_dict(), "_match_status": f"erreur: {exc}"})
                        errors.append({"ligne": idx, "valeur": val, "erreur": str(exc)})

                    update(idx, total, f"{idx}/{total}")

                bar.progress(1.0)
                txt.success(f"Terminé : {total} ligne(s) traitée(s).")

                df_out = pd.DataFrame(enriched_rows)
                st.dataframe(df_out, use_container_width=True, hide_index=True)
                base = Path(file.name).stem + "_enrichi"
                render_downloads(df_out, base, key="batch_dl")
                if errors:
                    with st.expander(f"⚠️ {len(errors)} erreur(s)"):
                        st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)


# =========================================================== TAB 5 : fiabilité
with tab_reliability:
    st.subheader("🛡️ Fiabilité des informations renvoyées par l'application")

    st.success(
        "**TL;DR** — Les données viennent toutes de **sources publiques officielles** "
        "(INSEE, INPI/RNE, BAN, ADEME, etc.) via l'API gouvernementale "
        "*Recherche d'Entreprises*. L'application ne calcule rien, n'invente rien "
        "et n'enrichit rien par IA : c'est une mise à plat 1:1 du JSON officiel."
    )

    st.markdown("### ✅ Très fiable — données officielles")
    st.caption(
        "L'API [Recherche d'Entreprises](https://recherche-entreprises.api.gouv.fr/docs/) "
        "(api.gouv.fr) est un service public officiel opéré par la DINUM. Elle agrège :"
    )
    reliability_df = pd.DataFrame(
        [
            ["siren, siret_siege, denomination, sigle", "INSEE Sirene", "J+1"],
            ["etat_administratif (A/C), date_creation, date_derniere_maj", "INSEE Sirene", "J+1"],
            ["activite_principale (NAF/APE), section_activite", "INSEE Sirene", "J+1"],
            ["nature_juridique, categorie_entreprise", "INSEE Sirene", "J+1"],
            ["adresse, code_postal, commune, departement, region", "INSEE Sirene", "J+1"],
            ["latitude, longitude", "BAN (Base Adresse Nationale)", "J+1"],
            ["dirigeants", "INPI / RNE", "quelques jours"],
            ["est_rge, est_bio, est_ess, est_qualiopi, est_finess", "ADEME, Agence Bio, ESS France, France Compétences, FINESS", "J+7 à mensuel"],
            ["convention_collective (IDCC)", "DGT / Légifrance", "mensuel"],
            ["Bilans financiers (non exposés actuellement)", "INPI", "≈ J+30"],
        ],
        columns=["Donnée renvoyée", "Source primaire", "Fraîcheur"],
    )
    st.dataframe(reliability_df, use_container_width=True, hide_index=True)

    st.markdown("### ⚠️ Limites à connaître")
    st.markdown(
        """
1. **Tranche d'effectifs** (`tranche_effectifs`, `annee_effectifs`) — l'INSEE la publie avec
   **~18 mois de retard**, et seulement par tranche (1-2, 3-5, 6-9, …). Ce n'est **pas** un
   effectif exact.
2. **Catégorie entreprise** (`PME` / `ETI` / `GE`) — également **~18 mois de retard** côté INSEE.
3. **Dirigeants** — couvre seulement les **personnes morales immatriculées au RCS**. Les
   entreprises individuelles non commerçantes, professions libérales et associations
   sont souvent absentes.
4. **État administratif** — `A` signifie « existe juridiquement », **pas** « activité réelle »
   (une entreprise dormante reste `A`).
5. **Adresse** — c'est l'adresse **déclarée à l'INSEE**, pas nécessairement le lieu
   d'exploitation réel.
6. **Recherche par nom en mode batch top-1** — l'API renvoie le résultat le plus pertinent
   selon son scoring. Pour les noms ambigus (`DUPONT`, `BOULANGERIE PARIS`), **vérifie le
   SIREN**. Augmente la limite à 5-10 résultats pour contrôler les homonymes.
7. **Diffusion publique** — les entreprises ayant demandé leur **non-diffusion** n'apparaissent
   pas via Recherche d'Entreprises. L'API INSEE Sirene (clé optionnelle dans la sidebar) peut
   y donner accès sous conditions (article 21 du décret 2022-1014).
        """
    )

    st.markdown("### 🟢 Ce que l'application ne déforme pas")
    st.markdown(
        """
Le code source ne fait **aucun** des traitements suivants :

- ❌ Pas de calcul, pas d'agrégation, pas d'enrichissement par IA
- ❌ Pas de complétion automatique de champs manquants
- ❌ Pas de stockage serveur, pas de cache persistant entre sessions

Il fait uniquement :

- ✅ Appel HTTP → JSON officiel
- ✅ Mise à plat 1:1 des champs dans des colonnes lisibles
- ✅ Validation **Luhn** des SIREN/SIRET avant requête
- ✅ Trace de la source dans la colonne `source`
        """
    )

    st.markdown("### 🔗 Vérifier une information par toi-même")
    st.markdown(
        """
- **Annuaire des entreprises** (officiel, DINUM) :
  <https://annuaire-entreprises.data.gouv.fr/>
- **INSEE — fiche Sirene** :
  `https://www.insee.fr/fr/statistiques/serie/{SIREN}`
- **INPI — Registre National des Entreprises** :
  <https://data.inpi.fr/>
- **Légifrance — convention collective IDCC** :
  <https://www.legifrance.gouv.fr/conv_coll/>
        """
    )

    st.markdown("### 📌 Recommandations pratiques")
    st.info(
        """
Pour les usages **critiques** (KYC, due diligence, juridique) :

- Utilise le **SIREN/SIRET comme clé** (mode *Forcer SIREN/SIRET*) plutôt que la recherche par nom.
- Garde la colonne `source` du résultat pour la traçabilité.
- Pour une preuve à **valeur légale**, seul l'extrait **Kbis** (infogreffe.fr) fait foi.
        """
    )


# =========================================================== TAB 6 : aide
with tab_help:
    st.markdown(
        """
### À propos

Application 100 % publique pour interroger les données des entreprises françaises.

- **Source principale** : [API Recherche d'Entreprises](https://recherche-entreprises.api.gouv.fr/docs/)
  (api.gouv.fr) — gratuite, sans clé, couvre Sirene + INPI + RNE + données dirigeants.
- **Source d'enrichissement optionnelle** : [API INSEE Sirene 3.11](https://portail-api.insee.fr/)
  (clé personnelle à fournir dans la sidebar).

### Fonctionnalités

1. **Recherche par SIREN / SIRET** — un ou plusieurs, validation Luhn automatique.
2. **Recherche par raison sociale / nom / dirigeant** — multi-critères : NAF, code postal,
   département, nature juridique, état administratif, sièges uniquement.
3. **Recherche par adresse** — code postal, département + carte si géolocalisation dispo.
4. **Enrichissement en masse** — upload Excel/CSV, choix de la colonne source,
   téléchargement du fichier enrichi (aucune donnée stockée serveur).

### Limites API publique

- 7 requêtes / seconde / IP (l'app respecte ~6 req/s).
- 10 000 résultats max par requête de recherche.
- Données mises à jour quotidiennement par l'INSEE.

### Publication sur Streamlit Cloud

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Aucun secret obligatoire. La clé INSEE optionnelle peut être renseignée dans
`Streamlit Cloud → Settings → Secrets` :

```toml
INSEE_API_KEY = "votre_cle"
```
        """
    )
