"""Utilitaires pour SIREN / SIRET : normalisation, validation Luhn, parsing batch."""
from __future__ import annotations

import re
from typing import Iterable

_SPLIT_RE = re.compile(r"[\s,;]+")
_DIGITS_RE = re.compile(r"\D+")


def normalize(value: object) -> str:
    """Supprime espaces et caractères non numériques."""
    if value is None:
        return ""
    return _DIGITS_RE.sub("", str(value))


def luhn_ok(number: str) -> bool:
    """Validation Luhn (sauf cas spécial La Poste SIREN 356000000)."""
    if not number.isdigit():
        return False
    if number == "356000000":  # La Poste : exception officielle
        return True
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def kind(value: str) -> str:
    """Retourne 'siren', 'siret' ou 'unknown'."""
    v = normalize(value)
    if len(v) == 9 and v.isdigit():
        return "siren"
    if len(v) == 14 and v.isdigit():
        return "siret"
    return "unknown"


def parse_batch(raw: str) -> list[str]:
    """Découpe un texte multi-lignes / séparateurs en identifiants normalisés uniques."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for token in _SPLIT_RE.split(raw.strip()):
        n = normalize(token)
        if n and n not in seen and kind(n) in {"siren", "siret"}:
            seen.add(n)
            out.append(n)
    return out


def split_valid_invalid(values: Iterable[str]) -> tuple[list[str], list[str]]:
    valid, invalid = [], []
    for v in values:
        n = normalize(v)
        if kind(n) in {"siren", "siret"} and luhn_ok(n):
            valid.append(n)
        else:
            invalid.append(str(v))
    return valid, invalid
