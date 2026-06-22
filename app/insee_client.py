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
        """Retourne (ok, message). Utilise un SIREN public connu (Peugeot)."""
        try:
            data = self._get("/siren/552100554")
            if data.get("uniteLegale"):
                return True, "Clé INSEE valide."
            return False, "Réponse inattendue."
        except InseeError as exc:
            return False, str(exc)

    def get_siren(self, siren: str) -> dict[str, Any]:
        return self._get(f"/siren/{siren}")

    def get_siret(self, siret: str) -> dict[str, Any]:
        return self._get(f"/siret/{siret}")

    def search_sirets(
        self,
        *,
        q: str,
        nombre: int = 1000,
        debut: int = 0,
        champs: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": q,
            "nombre": min(1000, max(1, int(nombre))),
            "debut": max(0, int(debut)),
        }
        if champs:
            params["champs"] = champs
        return self._get("/siret", params=params)

    def establishments_by_siren(
        self,
        siren: str,
        *,
        page_size: int = 1000,
        max_results: int | None = None,
        progress=None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Liste tous les établissements d'un SIREN via la recherche multicritère INSEE."""
        establishments: list[dict[str, Any]] = []
        total = 0
        debut = 0
        while True:
            data = self.search_sirets(
                q=f"siren:{siren}",
                nombre=page_size,
                debut=debut,
            )
            header = data.get("header") or {}
            total = int(header.get("total") or total or 0)
            page_items = [
                item for item in data.get("etablissements", []) if isinstance(item, dict)
            ]
            if not page_items:
                break

            remaining = None if max_results is None else max_results - len(establishments)
            if remaining is not None and remaining <= 0:
                break
            establishments.extend(page_items if remaining is None else page_items[:remaining])

            if progress is not None:
                progress(len(establishments), total or len(establishments), "Établissements INSEE")

            if len(establishments) >= total:
                break
            if max_results is not None and len(establishments) >= max_results:
                break
            debut += len(page_items)

        return establishments, total or len(establishments)
