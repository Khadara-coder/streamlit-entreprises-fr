"""Client optionnel pour l'API INSEE Sirene 3.11 (nécessite une clé).

Utilisé uniquement comme source d'enrichissement quand l'utilisateur fournit sa clé
dans la sidebar. L'app fonctionne entièrement sans ce client.
"""
from __future__ import annotations

import time
from typing import Any

import requests

BASE_URL = "https://api.insee.fr/api-sirene/3.11"
RETRYABLE = {429, 500, 502, 503, 504}


class InseeError(RuntimeError):
    pass


class InseeClient:
    def __init__(self, api_key: str, timeout: int = 30):
        if not api_key:
            raise InseeError("Clé API INSEE manquante.")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = True
        self.session.headers.update({
            "X-INSEE-Api-Key-Integration": api_key,
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise InseeError(f"Erreur réseau INSEE: {exc}") from exc
                time.sleep(0.6 * (attempt + 1))
                continue
            if r.status_code in RETRYABLE and attempt < 2:
                time.sleep(0.8 * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                raise InseeError("Clé INSEE invalide ou non autorisée.")
            if r.status_code == 404:
                return {}
            if r.status_code >= 400:
                raise InseeError(f"HTTP {r.status_code} INSEE: {r.text[:200]}")
            return r.json()
        raise InseeError("Échec INSEE après plusieurs tentatives.")

    def test_key(self) -> tuple[bool, str]:
        """Retourne (ok, message). Utilise un SIREN public connu (Renault)."""
        try:
            data = self._get("/siren/441751111")
            if data.get("uniteLegale"):
                return True, "Clé INSEE valide."
            return False, "Réponse inattendue."
        except InseeError as exc:
            return False, str(exc)

    def get_siren(self, siren: str) -> dict[str, Any]:
        return self._get(f"/siren/{siren}")

    def get_siret(self, siret: str) -> dict[str, Any]:
        return self._get(f"/siret/{siret}")
