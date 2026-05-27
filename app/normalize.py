"""Mise à plat des réponses API en lignes tabulaires homogènes."""
from __future__ import annotations

from typing import Any

# Colonnes affichées en priorité, dans cet ordre
PREFERRED_COLUMNS = [
    "denomination",
    "siren",
    "siret_siege",
    "etat_administratif",
    "date_creation",
    "activite_principale",
    "section_activite",
    "nature_juridique",
    "tranche_effectifs",
    "annee_effectifs",
    "categorie_entreprise",
    "adresse",
    "code_postal",
    "commune",
    "departement",
    "region",
    "latitude",
    "longitude",
    "dirigeants",
    "site_web",
    "email",
    "telephone",
    "source",
]


def _join_list(value: Any, sep: str = ", ") -> str | None:
    """Concatène une liste/valeur de l'API en string sécurisée (None si vide)."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [str(v) for v in value if v not in (None, "")]
        return sep.join(parts) or None
    if isinstance(value, bool):
        return "oui" if value else "non"
    s = str(value).strip()
    return s or None


def from_recherche_entreprises(item: dict[str, Any]) -> dict[str, Any]:
    """Aplatit un résultat de l'API Recherche d'Entreprises."""
    siege = item.get("siege") or {}
    matched = item.get("_matched_etablissement") or siege

    dirigeants_raw = item.get("dirigeants") or []
    dirigeants_parts: list[str] = []
    for d in dirigeants_raw[:5]:
        if not isinstance(d, dict):
            continue
        # personne morale
        if d.get("denomination") or d.get("siren"):
            label = d.get("denomination") or d.get("siren")
        else:
            label = " ".join(
                str(x) for x in [d.get("prenoms"), d.get("nom")] if x
            ).strip()
        qualite = d.get("qualite")
        if label and qualite:
            dirigeants_parts.append(f"{label} ({qualite})")
        elif label:
            dirigeants_parts.append(label)
    dirigeants = "; ".join(dirigeants_parts) or None

    complements = item.get("complements") or {}
    return {
        "denomination": item.get("nom_complet") or item.get("nom_raison_sociale"),
        "sigle": item.get("sigle"),
        "siren": item.get("siren"),
        "siret_siege": siege.get("siret") or item.get("siret"),
        "siret_matched": matched.get("siret") if matched is not siege else None,
        "etat_administratif": item.get("etat_administratif"),
        "date_creation": item.get("date_creation"),
        "date_derniere_maj": item.get("date_mise_a_jour"),
        "activite_principale": item.get("activite_principale"),
        "section_activite": item.get("section_activite_principale"),
        "nature_juridique": item.get("nature_juridique"),
        "tranche_effectifs": item.get("tranche_effectif_salarie"),
        "annee_effectifs": item.get("annee_tranche_effectif_salarie"),
        "categorie_entreprise": item.get("categorie_entreprise"),
        "annee_categorie": item.get("annee_categorie_entreprise"),
        "adresse": matched.get("adresse") or siege.get("adresse"),
        "code_postal": matched.get("code_postal") or siege.get("code_postal"),
        "commune": matched.get("libelle_commune") or siege.get("libelle_commune"),
        "departement": matched.get("departement") or siege.get("departement"),
        "region": matched.get("region") or siege.get("region"),
        "latitude": matched.get("latitude") or siege.get("latitude"),
        "longitude": matched.get("longitude") or siege.get("longitude"),
        "nombre_etablissements": item.get("nombre_etablissements"),
        "nombre_etablissements_ouverts": item.get("nombre_etablissements_ouverts"),
        "dirigeants": dirigeants or None,
        "convention_collective": _join_list(complements.get("liste_idcc")),
        "est_ess": complements.get("est_ess"),
        "est_rge": complements.get("est_rge"),
        "est_bio": complements.get("est_bio"),
        "est_qualiopi": complements.get("est_qualiopi"),
        "est_finess": complements.get("est_finess"),
        "source": "recherche-entreprises",
    }


def from_insee_siren(payload: dict[str, Any]) -> dict[str, Any]:
    """Aplatit /siren/{siren} de l'API INSEE Sirene 3.11."""
    unit = payload.get("uniteLegale") or {}
    period = (unit.get("periodesUniteLegale") or [{}])[0]
    siege = (payload.get("etablissementSiege") or {}).get("etablissement") or payload.get("etablissementSiege") or {}
    siege_period = (siege.get("periodesEtablissement") or [{}])[0] if siege else {}
    adr = siege.get("adresseEtablissement") or {}
    adresse = " ".join(
        filter(
            None,
            [
                adr.get("numeroVoieEtablissement"),
                adr.get("typeVoieEtablissement"),
                adr.get("libelleVoieEtablissement"),
            ],
        )
    ) or None
    return {
        "denomination": period.get("denominationUniteLegale")
        or period.get("denominationUsuelle1UniteLegale")
        or " ".join(filter(None, [period.get("prenom1UniteLegale"), unit.get("nomUniteLegale")])),
        "siren": unit.get("siren"),
        "siret_siege": (siege.get("siret") if siege else None) or (unit.get("siren") and period.get("nicSiegeUniteLegale") and f"{unit['siren']}{period['nicSiegeUniteLegale']}"),
        "etat_administratif": period.get("etatAdministratifUniteLegale"),
        "date_creation": unit.get("dateCreationUniteLegale"),
        "activite_principale": period.get("activitePrincipaleUniteLegale"),
        "nature_juridique": period.get("categorieJuridiqueUniteLegale"),
        "tranche_effectifs": unit.get("trancheEffectifsUniteLegale"),
        "annee_effectifs": unit.get("anneeEffectifsUniteLegale"),
        "categorie_entreprise": unit.get("categorieEntreprise"),
        "annee_categorie": unit.get("anneeCategorieEntreprise"),
        "adresse": adresse,
        "code_postal": adr.get("codePostalEtablissement"),
        "commune": adr.get("libelleCommuneEtablissement"),
        "source": "insee-sirene",
    }


def from_insee_siret(payload: dict[str, Any]) -> dict[str, Any]:
    et = payload.get("etablissement") or {}
    unit = et.get("uniteLegale") or {}
    adr = et.get("adresseEtablissement") or {}
    period = (et.get("periodesEtablissement") or [{}])[0]
    adresse = " ".join(
        filter(
            None,
            [
                adr.get("numeroVoieEtablissement"),
                adr.get("typeVoieEtablissement"),
                adr.get("libelleVoieEtablissement"),
            ],
        )
    ) or None
    return {
        "denomination": unit.get("denominationUniteLegale")
        or unit.get("denominationUsuelle1UniteLegale")
        or " ".join(filter(None, [unit.get("prenom1UniteLegale"), unit.get("nomUniteLegale")])),
        "siren": et.get("siren"),
        "siret_siege": et.get("siret") if period.get("etablissementSiege") else None,
        "siret_matched": et.get("siret"),
        "etat_administratif": period.get("etatAdministratifEtablissement"),
        "date_creation": et.get("dateCreationEtablissement"),
        "activite_principale": period.get("activitePrincipaleEtablissement"),
        "tranche_effectifs": et.get("trancheEffectifsEtablissement"),
        "annee_effectifs": et.get("anneeEffectifsEtablissement"),
        "adresse": adresse,
        "code_postal": adr.get("codePostalEtablissement"),
        "commune": adr.get("libelleCommuneEtablissement"),
        "source": "insee-sirene",
    }


def order_columns(row: dict[str, Any]) -> dict[str, Any]:
    preferred = {k: row.get(k) for k in PREFERRED_COLUMNS if k in row}
    extras = {k: v for k, v in row.items() if k not in preferred}
    return {**preferred, **extras}
