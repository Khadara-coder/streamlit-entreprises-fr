"""Tests offline (aucun appel réseau) — identifiers + normalize."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import identifiers
from app.naf import format_naf_activity
from app.normalize import (
    from_company_summary,
    from_insee_etablissement,
    from_recherche_entreprises,
    from_recherche_etablissement,
    order_columns,
)


def test_normalize():
    assert identifiers.normalize(" 552 100 554 ") == "552100554"
    assert identifiers.normalize(None) == ""
    assert identifiers.normalize("44306184100047") == "44306184100047"


def test_kind():
    assert identifiers.kind("552100554") == "siren"
    assert identifiers.kind("44306184100047") == "siret"
    assert identifiers.kind("123") == "unknown"
    assert identifiers.kind("abc") == "unknown"


def test_luhn():
    assert identifiers.luhn_ok("552100554")  # Peugeot SA
    assert identifiers.luhn_ok("356000000")  # La Poste (exception)
    assert not identifiers.luhn_ok("123456789")
    assert not identifiers.luhn_ok("abc")


def test_parse_batch():
    raw = "552100554\n44306184100047, 542065479; 123abc"
    out = identifiers.parse_batch(raw)
    assert "552100554" in out
    assert "44306184100047" in out
    assert "542065479" in out
    assert "123abc" not in out
    # dédoublonnage
    assert identifiers.parse_batch("552100554\n552100554") == ["552100554"]


def test_split_valid_invalid():
    valid, invalid = identifiers.split_valid_invalid(["552100554", "123456789", "abc"])
    assert valid == ["552100554"]
    assert invalid == ["123456789", "abc"]


def test_from_recherche_entreprises():
    payload = {
        "siren": "552100554",
        "nom_complet": "PEUGEOT SA",
        "nom_raison_sociale": "PEUGEOT",
        "sigle": "PSA",
        "etat_administratif": "A",
        "date_creation": "1965-01-01",
        "activite_principale": "70.10Z",
        "section_activite_principale": "M",
        "nature_juridique": "5599",
        "tranche_effectif_salarie": "53",
        "categorie_entreprise": "GE",
        "nombre_etablissements": 12,
        "siege": {
            "siret": "55210055400067",
            "adresse": "7 RUE HENRI SAINTE CLAIRE DEVILLE 92500 RUEIL-MALMAISON",
            "code_postal": "92500",
            "libelle_commune": "RUEIL-MALMAISON",
            "departement": "92",
            "region": "11",
            "latitude": "48.876",
            "longitude": "2.181",
        },
        "dirigeants": [
            {"prenoms": "Jean", "nom": "Dupont", "qualite": "Président"},
        ],
        "complements": {"est_ess": False, "est_rge": False, "est_bio": False},
    }
    row = order_columns(from_recherche_entreprises(payload))
    assert row["denomination"] == "PEUGEOT SA"
    assert row["siren"] == "552100554"
    assert row["siret_siege"] == "55210055400067"
    assert row["code_postal"] == "92500"
    assert row["commune"] == "RUEIL-MALMAISON"
    assert "Jean" in row["dirigeants"]
    assert row["source"] == "recherche-entreprises"


def test_format_naf_activity():
    labels = {"46.74B": "Commerce de gros de fournitures pour plomberie et chauffage"}
    assert (
        format_naf_activity("46.74b", labels)
        == "Commerce de gros de fournitures pour plomberie et chauffage (46.74B)"
    )
    assert format_naf_activity("52.10B", labels) == "52.10B"
    assert format_naf_activity("", labels) is None


def test_from_recherche_etablissement():
    payload = {
        "siret": "68203389900092",
        "activite_principale": "46.74B",
        "adresse": "ZONE ACTIVITES ECONOMIQUE 11 RUE THEODULE VILLERET 95130 LE PLESSIS-BOUCHARD",
        "date_creation": "1999-10-01",
        "date_fermeture": None,
        "etat_administratif": "A",
        "est_siege": False,
        "liste_enseignes": ["FOURNITHERM"],
        "code_postal": "95130",
        "libelle_commune": "LE PLESSIS-BOUCHARD",
        "latitude": "49.002178151",
        "longitude": "2.2471480942",
    }
    row = from_recherche_etablissement(
        payload,
        company={"siren": "682033899", "nom_complet": "SCHMITT-NEY SFCP"},
        naf_labels={"46.74B": "Commerce de gros de fournitures pour plomberie et chauffage"},
    )
    assert row["SIREN"] == "682033899"
    assert row["SIRET"] == "68203389900092"
    assert row["Activité (NAF/APE)"].endswith("(46.74B)")
    assert "FOURNITHERM" in row["Détails (nom, enseigne, adresse)"]
    assert row["Création"] == "01/10/1999"
    assert row["État"] == "en activité"
    assert row["Siège social"] == "non"
    assert row["Ligne"] == "établissement"


def test_from_company_summary():
    row = from_company_summary(
        {
            "siren": "682033899",
            "nom_complet": "SCHMITT-NEY SFCP",
            "activite_principale": "46.74B",
            "date_creation": "1950-01-01",
            "etat_administratif": "A",
            "nombre_etablissements": 36,
            "nombre_etablissements_ouverts": 29,
            "_establishments_source": "recherche-entreprises",
        },
        naf_labels={"46.74B": "Commerce de gros de fournitures pour plomberie et chauffage"},
    )
    assert row["SIREN"] == "682033899"
    assert row["Ligne"] == "unité légale"
    assert row["SIRET"] is None
    assert row["État"] == "en activité"
    assert row["Total établissements annoncé"] == 36


def test_from_insee_etablissement_closed():
    payload = {
        "siren": "682033899",
        "siret": "68203389900076",
        "dateCreationEtablissement": "1992-04-13",
        "etablissementSiege": False,
        "adresseEtablissement": {
            "numeroVoieEtablissement": "48",
            "typeVoieEtablissement": "RUE",
            "libelleVoieEtablissement": "DELERUE",
            "codePostalEtablissement": "94100",
            "libelleCommuneEtablissement": "ST MAUR DES FOSSES",
        },
        "periodesEtablissement": [
            {
                "dateDebut": "2004-04-30",
                "dateFinEtablissement": None,
                "etatAdministratifEtablissement": "F",
                "activitePrincipaleEtablissement": "46.74B",
            }
        ],
        "uniteLegale": {"denominationUniteLegale": "SCHMITT-NEY SFCP"},
    }
    row = from_insee_etablissement(
        payload,
        naf_labels={"46.74B": "Commerce de gros de fournitures pour plomberie et chauffage"},
    )
    assert row["SIRET"] == "68203389900076"
    assert row["Entreprise"] == "SCHMITT-NEY SFCP"
    assert row["Création"] == "13/04/1992"
    assert row["État"] == "fermé le 30/04/2004"
    assert row["Date fermeture"] == "30/04/2004"
    assert row["Source"] == "INSEE Sirene"


def test_establishments_by_siren_service_orders_active_first():
    pytest.importorskip("pandas")
    from app.search_service import establishments_by_siren

    class FakeClient:
        def establishments_by_siren(self, siren: str, *, limit: int = 100):
            return (
                {"siren": siren, "nom_complet": "ACME", "nombre_etablissements": 2},
                [
                    {
                        "siret": f"{siren}00035",
                        "activite_principale": "46.74B",
                        "adresse": "1 RUE FERMEE 75001 PARIS",
                        "date_creation": "1992-04-13",
                        "date_fermeture": "2004-04-30",
                        "etat_administratif": "F",
                        "est_siege": False,
                    },
                    {
                        "siret": f"{siren}00019",
                        "activite_principale": "46.74B",
                        "adresse": "1 RUE ACTIVE 75001 PARIS",
                        "date_creation": "1900-01-01",
                        "date_fermeture": None,
                        "etat_administratif": "A",
                        "est_siege": True,
                    },
                ],
            )

    df, company = establishments_by_siren(FakeClient(), "682033899")
    assert company["nom_complet"] == "ACME"
    assert list(df["SIRET"]) == ["68203389900019", "68203389900035"]
    assert list(df["État"]) == ["en activité", "fermé le 30/04/2004"]


def test_establishments_by_sirens_includes_company_rows():
    pytest.importorskip("pandas")
    from app.search_service import establishments_by_sirens

    class FakeClient:
        def establishments_by_siren(self, siren: str, *, limit: int = 100):
            return (
                {
                    "siren": siren,
                    "nom_complet": f"ACME {siren}",
                    "etat_administratif": "A",
                    "nombre_etablissements": 1,
                },
                [
                    {
                        "siret": f"{siren}00019",
                        "activite_principale": "46.74B",
                        "adresse": "1 RUE ACTIVE 75001 PARIS",
                        "etat_administratif": "A",
                        "est_siege": True,
                    }
                ],
            )

    df, errors = establishments_by_sirens(FakeClient(), ["111111111", "222222222"])
    assert errors.empty
    assert list(df["SIREN"]) == ["111111111", "111111111", "222222222", "222222222"]
    assert list(df["Ligne"]) == [
        "unité légale",
        "établissement",
        "unité légale",
        "établissement",
    ]
