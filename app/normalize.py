"""Mise à plat des réponses API en lignes tabulaires homogènes."""
from __future__ import annotations

from typing import Any

from app.naf import format_naf_activity

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


def _format_date_fr(value: Any) -> str | None:
    s = _join_list(value)
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        yyyy, mm, dd = s.split("-")
        return f"{dd}/{mm}/{yyyy}"
    return s


def _format_creation_date_fr(value: Any) -> str | None:
    if _join_list(value) == "1900-01-01":
        return None
    return _format_date_fr(value)


def _etat_etablissement(etablissement: dict[str, Any]) -> str:
    etat = etablissement.get("etat_administratif")
    if etat == "A":
        return "en activité"
    fermeture = _format_date_fr(etablissement.get("date_fermeture"))
    if fermeture:
        return f"fermé le {fermeture}"
    if etat == "F":
        return "fermé"
    return _join_list(etat) or ""


def _first_present(*values: Any) -> str | None:
    for value in values:
        normalized = _join_list(value)
        if normalized:
            return normalized
    return None


def _current_insee_period(periods: list[dict[str, Any]] | None) -> dict[str, Any]:
    valid = [period for period in (periods or []) if isinstance(period, dict)]
    for period in valid:
        if not period.get("dateFinEtablissement"):
            return period
    return valid[0] if valid else {}


def _insee_company_name(unit: dict[str, Any]) -> str | None:
    return _first_present(
        unit.get("denominationUniteLegale"),
        unit.get("denominationUsuelle1UniteLegale"),
        " ".join(
            str(part)
            for part in [
                unit.get("prenom1UniteLegale"),
                unit.get("nomUniteLegale"),
            ]
            if part
        ),
    )


def _insee_establishment_name(period: dict[str, Any]) -> str | None:
    return _first_present(
        period.get("denominationUsuelleEtablissement"),
        period.get("enseigne1Etablissement"),
        period.get("enseigne2Etablissement"),
        period.get("enseigne3Etablissement"),
    )


def _insee_address(adr: dict[str, Any]) -> str | None:
    parts = [
        adr.get("complementAdresseEtablissement"),
        adr.get("numeroVoieEtablissement"),
        adr.get("indiceRepetitionEtablissement"),
        adr.get("typeVoieEtablissement"),
        adr.get("libelleVoieEtablissement"),
        adr.get("distributionSpecialeEtablissement"),
        adr.get("codePostalEtablissement"),
        adr.get("libelleCommuneEtablissement"),
        adr.get("libelleCommuneEtrangerEtablissement"),
        adr.get("libellePaysEtrangerEtablissement"),
    ]
    return " ".join(str(part).strip() for part in parts if part not in (None, "")) or None


def _department_from_postal_code(code_postal: Any) -> str | None:
    code = _join_list(code_postal)
    if not code:
        return None
    if code.startswith(("20", "2A", "2B")) and len(code) >= 2:
        return code[:2]
    if len(code) >= 2:
        return code[:2]
    return None


def _etat_insee_etablissement(period: dict[str, Any]) -> str:
    etat = period.get("etatAdministratifEtablissement")
    if etat == "A":
        return "en activité"
    fermeture = _format_date_fr(period.get("dateDebut"))
    if etat == "F" and fermeture:
        return f"fermé le {fermeture}"
    if etat == "F":
        return "fermé"
    return _join_list(etat) or ""


def _current_insee_unit_period(periods: list[dict[str, Any]] | None) -> dict[str, Any]:
    valid = [period for period in (periods or []) if isinstance(period, dict)]
    for period in valid:
        if not period.get("dateFinUniteLegale"):
            return period
    return valid[0] if valid else {}


def _etat_unite_legale(company: dict[str, Any]) -> str:
    etat = company.get("etat_administratif")
    if etat == "A":
        return "en activité"
    if etat == "C":
        fermeture = _format_date_fr(company.get("date_fermeture"))
        return f"cessée le {fermeture}" if fermeture else "cessée"

    unit = company.get("uniteLegale") or {}
    period = _current_insee_unit_period(unit.get("periodesUniteLegale"))
    etat = period.get("etatAdministratifUniteLegale")
    if etat == "A":
        return "en activité"
    if etat == "C":
        return "cessée"
    return _join_list(etat) or ""


def from_company_summary(
    company: dict[str, Any],
    *,
    siren: str | None = None,
    naf_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Crée la ligne de synthèse d'une unité légale pour les exports établissements."""
    unit = company.get("uniteLegale") or {}
    period = _current_insee_unit_period(unit.get("periodesUniteLegale"))
    resolved_siren = company.get("siren") or unit.get("siren") or siren
    company_name = (
        company.get("nom_complet")
        or company.get("nom_raison_sociale")
        or _insee_company_name(unit)
    )
    activity = company.get("activite_principale") or period.get("activitePrincipaleUniteLegale")
    total = company.get("nombre_etablissements") or company.get("nombrePeriodesUniteLegale")

    return {
        "SIREN": resolved_siren,
        "Ligne": "unité légale",
        "Entreprise": company_name,
        "SIRET": None,
        "Activité (NAF/APE)": format_naf_activity(activity, naf_labels),
        "Détails (nom, enseigne, adresse)": company_name,
        "Création": _format_creation_date_fr(
            company.get("date_creation") or unit.get("dateCreationUniteLegale")
        ),
        "État": _etat_unite_legale(company),
        "Siège social": None,
        "Enseigne": None,
        "Adresse": None,
        "Code postal": None,
        "Commune": None,
        "Département": None,
        "Région": None,
        "Latitude": None,
        "Longitude": None,
        "Date fermeture": _format_date_fr(company.get("date_fermeture")),
        "Total établissements annoncé": total,
        "Établissements ouverts annoncés": company.get("nombre_etablissements_ouverts"),
        "Établissements récupérés": None,
        "Source": company.get("_establishments_source") or company.get("source"),
    }


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


def from_recherche_etablissement(
    etablissement: dict[str, Any],
    *,
    company: dict[str, Any] | None = None,
    naf_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Aplatit un établissement lié à une unité légale."""
    enseignes = _join_list(etablissement.get("liste_enseignes"), sep=" / ")
    nom_commercial = _join_list(etablissement.get("nom_commercial"))
    nom_enseigne = enseignes or nom_commercial
    adresse = _join_list(etablissement.get("adresse"))
    details_parts = [part for part in (nom_enseigne, adresse) if part]

    return {
        "SIREN": (company or {}).get("siren"),
        "Ligne": "établissement",
        "Entreprise": (company or {}).get("nom_complet")
        or (company or {}).get("nom_raison_sociale"),
        "SIRET": etablissement.get("siret"),
        "Activité (NAF/APE)": format_naf_activity(
            etablissement.get("activite_principale"), naf_labels
        ),
        "Détails (nom, enseigne, adresse)": " - ".join(details_parts) or None,
        "Création": _format_creation_date_fr(etablissement.get("date_creation")),
        "État": _etat_etablissement(etablissement),
        "Siège social": "oui" if etablissement.get("est_siege") else "non",
        "Enseigne": nom_enseigne,
        "Adresse": adresse,
        "Code postal": etablissement.get("code_postal"),
        "Commune": etablissement.get("libelle_commune"),
        "Département": etablissement.get("departement"),
        "Région": etablissement.get("region"),
        "Latitude": etablissement.get("latitude"),
        "Longitude": etablissement.get("longitude"),
        "Date fermeture": _format_date_fr(etablissement.get("date_fermeture")),
        "Total établissements annoncé": None,
        "Établissements ouverts annoncés": None,
        "Établissements récupérés": None,
        "Source": "INSEE via recherche-entreprises",
    }


def from_insee_etablissement(
    etablissement: dict[str, Any],
    *,
    company: dict[str, Any] | None = None,
    naf_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Aplatit un établissement de l'API Sirene INSEE au format de la rubrique."""
    unit = etablissement.get("uniteLegale") or {}
    period = _current_insee_period(etablissement.get("periodesEtablissement"))
    adr = etablissement.get("adresseEtablissement") or {}
    nom_enseigne = _insee_establishment_name(period)
    adresse = _insee_address(adr)
    details_parts = [part for part in (nom_enseigne, adresse) if part]
    etat = _etat_insee_etablissement(period)
    fermeture = (
        _format_date_fr(period.get("dateDebut"))
        if period.get("etatAdministratifEtablissement") == "F"
        else None
    )
    company_unit = (company or {}).get("uniteLegale") or {}
    company_name = (
        (company or {}).get("nom_complet")
        or (company or {}).get("nom_raison_sociale")
        or _insee_company_name(company_unit)
        or _insee_company_name(unit)
    )

    return {
        "SIREN": etablissement.get("siren") or unit.get("siren"),
        "Ligne": "établissement",
        "Entreprise": company_name,
        "SIRET": etablissement.get("siret"),
        "Activité (NAF/APE)": format_naf_activity(
            period.get("activitePrincipaleEtablissement")
            or etablissement.get("activitePrincipaleEtablissement"),
            naf_labels,
        ),
        "Détails (nom, enseigne, adresse)": " - ".join(details_parts) or None,
        "Création": _format_creation_date_fr(etablissement.get("dateCreationEtablissement")),
        "État": etat,
        "Siège social": "oui" if etablissement.get("etablissementSiege") else "non",
        "Enseigne": nom_enseigne,
        "Adresse": adresse,
        "Code postal": adr.get("codePostalEtablissement"),
        "Commune": adr.get("libelleCommuneEtablissement"),
        "Département": _department_from_postal_code(adr.get("codePostalEtablissement")),
        "Région": None,
        "Latitude": None,
        "Longitude": None,
        "Date fermeture": fermeture,
        "Total établissements annoncé": None,
        "Établissements ouverts annoncés": None,
        "Établissements récupérés": None,
        "Source": "INSEE Sirene",
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
