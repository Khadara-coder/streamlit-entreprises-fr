"""Streamlit-Entreprises-FR — recherche d'entreprises françaises (publiable sur Streamlit Cloud).

API principale : Recherche d'Entreprises (api.gouv.fr) — gratuite, sans clé.
API optionnelle : INSEE Sirene 3.11 — si l'utilisateur fournit sa clé en sidebar.
Aucune base de données, aucun secret obligatoire.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Permet `streamlit run streamlit_app.py` depuis la racine du repo
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import identifiers
from app.export import to_csv_bytes, to_excel_bytes
from app.insee_client import InseeClient, InseeError
from app.normalize import order_columns, from_recherche_entreprises
from app.recherche_entreprises_client import (
    RechercheEntreprisesClient,
    RechercheEntreprisesError,
)
from app.search_service import lookup_identifiers, search_by_text

st.set_page_config(
    page_title="Entreprises FR — Recherche publique",
    page_icon="🏢",
    layout="wide",
)


# ----------------------------------------------------------------------- helpers
@st.cache_resource(show_spinner=False)
def get_re_client() -> RechercheEntreprisesClient:
    return RechercheEntreprisesClient()


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
        value=st.secrets.get("INSEE_API_KEY", "") if hasattr(st, "secrets") else "",
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
tab_id, tab_name, tab_addr, tab_batch, tab_help = st.tabs(
    [
        "🔢 Par SIREN / SIRET",
        "🏷️ Par raison sociale / nom",
        "📍 Par adresse / géographie",
        "📂 Lot Excel / CSV",
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


# =========================================================== TAB 2 : par raison sociale
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

            col1, col2 = st.columns(2)
            with col1:
                source_col = st.selectbox("Colonne source", options=list(df_in.columns))
            with col2:
                mode = st.radio(
                    "Type de recherche",
                    ["Auto (détecte SIREN/SIRET ou texte)", "Forcer SIREN/SIRET", "Forcer raison sociale"],
                    index=0,
                )

            limit_per_query = st.number_input(
                "Si recherche par nom : prendre seulement le N° 1 résultat ? "
                "(sinon limite max par ligne)",
                min_value=1,
                max_value=10,
                value=1,
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


# =========================================================== TAB 5 : aide
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
