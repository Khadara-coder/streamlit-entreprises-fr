"""Tests offline (aucun appel réseau) — identifiers + normalize."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import identifiers
from app.normalize import from_recherche_entreprises, order_columns


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
