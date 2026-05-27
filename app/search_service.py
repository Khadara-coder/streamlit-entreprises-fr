"""Service de recherche unifié : appelle Recherche-Entreprises et, si dispo, INSEE."""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from app import identifiers
from app.insee_client import InseeClient, InseeError
from app.normalize import (
    from_insee_siren,
    from_insee_siret,
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
