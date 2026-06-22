"""Libellés NAF/APE pour enrichir l'affichage des activités."""
from __future__ import annotations

from typing import Any

import requests

NAF_LABELS_URL = "https://www.data.gouv.fr/api/1/datasets/r/680dbbb4-c808-44f2-b292-9b16ac2f0a3d"


def normalize_naf_code(code: object) -> str:
    if code is None:
        return ""
    return str(code).strip().upper()


def load_naf_labels(
    *,
    timeout: int = 10,
    session: requests.Session | None = None,
) -> dict[str, str]:
    """Charge les libellés NAF depuis data.gouv.fr.

    La fonction retourne un dictionnaire vide si la ressource est indisponible:
    l'app peut alors afficher simplement le code NAF.
    """
    http = session or requests.Session()
    try:
        response = http.get(NAF_LABELS_URL, timeout=timeout)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except (requests.RequestException, ValueError):
        return {}

    labels: dict[str, str] = {}
    for item in payload.get("values", []):
        if not isinstance(item, dict):
            continue
        code = normalize_naf_code(item.get("code"))
        label = str(item.get("libelle") or "").strip()
        if code and label:
            labels[code] = label
    return labels


def format_naf_activity(code: object, labels: dict[str, str] | None = None) -> str | None:
    normalized = normalize_naf_code(code)
    if not normalized:
        return None
    label = (labels or {}).get(normalized)
    if label:
        return f"{label} ({normalized})"
    return normalized
