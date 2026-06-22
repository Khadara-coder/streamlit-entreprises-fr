"""Service de recherche unifié : appelle Recherche-Entreprises et, si dispo, INSEE."""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from app import identifiers
from app.insee_client import InseeClient, InseeError
from app.normalize import (
    from_company_summary,
    from_insee_etablissement,
    from_insee_siren,
    from_insee_siret,
    from_recherche_etablissement,
    from_recherche_entreprises,
    order_columns,
)
from app.recherche_entreprises_client import (
    RechercheEntreprisesClient,
    RechercheEntreprisesError,
)

ProgressFn = Callable[[int, int, str], None] | None


def search_by_text(
    re_client: RechercheEntreprisesClient,
    *,
    query: str,
    code_postal: str | None = None,
    departement: str | None = None,
    activite_principale: str | None = None,
    section: str | None = None,
    nature_juridique: str | None = None,
    etat_administratif: str | None = None,
    est_siege: bool | None = None,
    max_results: int = 100,
    progress: ProgressFn = None,
) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    total = 0
    page = 1
    while len(rows) < max_results:
        data = re_client.search(
            query=query,
            code_postal=code_postal,
            departement=departement,
            activite_principale=activite_principale,
            section_activite_principale=section,
            nature_juridique=nature_juridique,
            etat_administratif=etat_administratif,
            est_siege=est_siege,
            page=page,
            per_page=25,
        )
        total = data.get("total_results", total)
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            if len(rows) >= max_results:
                break
            rows.append(order_columns(from_recherche_entreprises(item)))
        if progress is not None:
            progress(len(rows), min(max_results, total), f"Page {page} — {len(rows)} résultat(s) cumulés")
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return pd.DataFrame(rows), total


def lookup_identifiers(
    re_client: RechercheEntreprisesClient,
    raw_ids: list[str],
    *,
    insee_client: InseeClient | None = None,
    progress: ProgressFn = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cherche en lot par SIREN/SIRET. Retourne (résultats, erreurs)."""
    valid, invalid = identifiers.split_valid_invalid(raw_ids)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = [
        {"identifiant": v, "erreur": "format/Luhn invalide"} for v in invalid
    ]
    total = len(valid)
    for idx, ident in enumerate(valid, 1):
        kind = identifiers.kind(ident)
        row: dict[str, Any] | None = None
        # Source primaire : Recherche-Entreprises (gratuite)
        try:
            if kind == "siren":
                hit = re_client.by_siren(ident)
            else:
                hit = re_client.by_siret(ident)
            if hit:
                row = order_columns(from_recherche_entreprises(hit))
        except RechercheEntreprisesError as exc:
            errors.append({"identifiant": ident, "erreur": f"recherche-entreprises: {exc}"})

        # Fallback / enrichissement INSEE si dispo
        if row is None and insee_client is not None:
            try:
                payload = insee_client.get_siren(ident) if kind == "siren" else insee_client.get_siret(ident)
                if payload:
                    row = order_columns(
                        from_insee_siren(payload) if kind == "siren" else from_insee_siret(payload)
                    )
            except InseeError as exc:
                errors.append({"identifiant": ident, "erreur": f"insee: {exc}"})

        if row is not None:
            row["input_identifier"] = ident
            row["input_identifier_type"] = kind
            rows.append(row)
        elif not any(e["identifiant"] == ident for e in errors):
            errors.append({"identifiant": ident, "erreur": "introuvable"})

        if progress is not None:
            progress(idx, total, f"Identifiants : {idx}/{total}")

    return pd.DataFrame(rows), pd.DataFrame(errors)


def establishments_by_siren(
    re_client: RechercheEntreprisesClient,
    siren: str,
    *,
    insee_client: InseeClient | None = None,
    naf_labels: dict[str, str] | None = None,
    limit: int | None = 100,
    progress: ProgressFn = None,
    include_company_row: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    """Liste les établissements diffusibles d'une entreprise à partir de son SIREN."""
    company: dict[str, Any] | None = None
    rows: list[dict[str, Any]]

    if insee_client is not None:
        try:
            company = re_client.by_siren(siren)
        except RechercheEntreprisesError:
            company = None
        if company is None:
            company = insee_client.get_siren(siren) or None

        establishments, total = insee_client.establishments_by_siren(
            siren,
            max_results=limit,
            progress=progress,
        )
        if company is None and not establishments:
            return pd.DataFrame(), None
        if company is None:
            company = {}
        company = dict(company)
        company.setdefault("siren", siren)
        company["nombre_etablissements"] = total
        company["_establishments_source"] = "insee-sirene"
        rows = [
            from_insee_etablissement(
                item,
                company=company,
                naf_labels=naf_labels,
            )
            for item in establishments
        ]
    else:
        company, establishments = re_client.establishments_by_siren(siren, limit=limit or 100)
        if company is not None:
            company = dict(company)
            company["_establishments_source"] = "recherche-entreprises"
        rows = [
            from_recherche_etablissement(
                item,
                company=company,
                naf_labels=naf_labels,
            )
            for item in establishments
        ]

    if not rows and not (include_company_row and company is not None):
        return pd.DataFrame(), company

    df = pd.DataFrame(rows)
    if not df.empty:
        if "Siège social" in df.columns:
            df["_siege_sort"] = df["Siège social"].eq("oui").astype(int)
        else:
            df["_siege_sort"] = 0
        if "État" in df.columns:
            df["_etat_sort"] = df["État"].eq("en activité").astype(int)
        else:
            df["_etat_sort"] = 0
        df = df.sort_values(
            by=["_etat_sort", "_siege_sort", "SIRET"],
            ascending=[False, False, True],
        ).drop(columns=["_etat_sort", "_siege_sort"])

    if include_company_row and company is not None:
        summary = from_company_summary(company, siren=siren, naf_labels=naf_labels)
        summary["Établissements récupérés"] = len(rows)
        df = pd.concat([pd.DataFrame([summary]), df], ignore_index=True)
    return df, company


def establishments_by_sirens(
    re_client: RechercheEntreprisesClient,
    sirens: list[str],
    *,
    insee_client: InseeClient | None = None,
    naf_labels: dict[str, str] | None = None,
    limit: int | None = 100,
    progress: ProgressFn = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Liste les établissements pour plusieurs SIREN en conservant l'ordre d'entrée."""
    frames: list[pd.DataFrame] = []
    errors: list[dict[str, Any]] = []
    total = len(sirens)

    for idx, siren in enumerate(sirens, 1):
        try:
            df, company = establishments_by_siren(
                re_client,
                siren,
                insee_client=insee_client,
                naf_labels=naf_labels,
                limit=limit,
                include_company_row=True,
            )
        except (RechercheEntreprisesError, InseeError) as exc:
            errors.append({"siren": siren, "erreur": str(exc)})
            df = pd.DataFrame()
            company = None

        if company is None:
            errors.append({"siren": siren, "erreur": "introuvable"})
        elif df.empty:
            errors.append({"siren": siren, "erreur": "aucun établissement diffusible"})
        else:
            frames.append(df)

        if progress is not None:
            progress(idx, total, f"SIREN traités : {idx}/{total}")

    if not frames:
        return pd.DataFrame(), pd.DataFrame(errors)
    return pd.concat(frames, ignore_index=True), pd.DataFrame(errors)
