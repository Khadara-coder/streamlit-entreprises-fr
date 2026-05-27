"""Client pour l'API publique gratuite Recherche d'Entreprises (api.gouv.fr).

Documentation : https://recherche-entreprises.api.gouv.fr/docs/
Aucune clé d'API requise. Limite : 7 req/s par IP.
Couvre Sirene, INPI/RNE, RNA, données dirigeants, bilans financiers, etc.
"""
from __future__ import annotations

import time
from typing import Any

import requests

BASE_URL = "https://recherche-entreprises.api.gouv.fr"
DEFAULT_TIMEOUT = 20
MAX_PER_PAGE = 25  # plafond imposé par l'API
RATE_LIMIT_SLEEP = 0.16  # ~6 req/s, marge sous la limite de 7 req/s


class RechercheEntreprisesError(RuntimeError):
    pass


class RechercheEntreprisesClient:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        # respecte la config proxy du système si présente
        self.session.trust_env = True
        self._last_call = 0.0

    # ------------------------------------------------------------------ internal
    def _throttle(self) -> None:
        delta = time.monotonic() - self._last_call
        if delta < RATE_LIMIT_SLEEP:
            time.sleep(RATE_LIMIT_SLEEP - delta)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._throttle()
        url = f"{BASE_URL}{path}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise RechercheEntreprisesError(f"Erreur réseau: {exc}") from exc
                time.sleep(0.6 * (attempt + 1))
                continue
            if r.status_code == 429 and attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            if r.status_code == 404:
                return {"results": [], "total_results": 0}
            if r.status_code >= 400:
                raise RechercheEntreprisesError(
                    f"HTTP {r.status_code} sur {path} : {r.text[:200]}"
                )
            try:
                return r.json()
            except ValueError as exc:
                raise RechercheEntreprisesError("Réponse JSON invalide.") from exc
        raise RechercheEntreprisesError("Échec après plusieurs tentatives.")

    # ------------------------------------------------------------------ public
    def search(
        self,
        query: str = "",
        *,
        code_postal: str | None = None,
        departement: str | None = None,
        activite_principale: str | None = None,
        section_activite_principale: str | None = None,
        nature_juridique: str | None = None,
        etat_administratif: str | None = None,  # 'A' actif, 'C' cessé
        est_siege: bool | None = None,
        page: int = 1,
        per_page: int = MAX_PER_PAGE,
    ) -> dict[str, Any]:
        """Recherche textuelle multi-critères. Query vide autorisée si autres filtres."""
        params: dict[str, Any] = {
            "page": max(1, int(page)),
            "per_page": min(MAX_PER_PAGE, max(1, int(per_page))),
        }
        if query:
            params["q"] = query
        if code_postal:
            params["code_postal"] = code_postal
        if departement:
            params["departement"] = departement
        if activite_principale:
            params["activite_principale"] = activite_principale
        if section_activite_principale:
            params["section_activite_principale"] = section_activite_principale
        if nature_juridique:
            params["nature_juridique"] = nature_juridique
        if etat_administratif:
            params["etat_administratif"] = etat_administratif
        if est_siege is not None:
            params["est_siege"] = "true" if est_siege else "false"
        return self._get("/search", params=params)

    def by_siren(self, siren: str) -> dict[str, Any] | None:
        data = self._get("/search", params={"q": siren, "per_page": 1})
        for result in data.get("results", []):
            if str(result.get("siren")) == siren:
                return result
        return None

    def by_siret(self, siret: str) -> dict[str, Any] | None:
        siren = siret[:9]
        result = self.by_siren(siren)
        if not result:
            return None
        # Cherche l'établissement correspondant au SIRET
        match = next(
            (e for e in result.get("matching_etablissements", []) if e.get("siret") == siret),
            None,
        )
        if match:
            result = dict(result)
            result["_matched_etablissement"] = match
        return result

    def near_address(self, query: str, latitude: float, longitude: float, radius_km: float = 5) -> dict[str, Any]:
        params = {
            "q": query or "*",
            "lat": latitude,
            "long": longitude,
            "radius": radius_km,
            "per_page": MAX_PER_PAGE,
        }
        return self._get("/near_point", params=params)

    def iter_all(
        self,
        query: str = "",
        *,
        max_results: int = 1000,
        progress=None,
        **filters: Any,
    ):
        """Itère sur les résultats jusqu'à max_results (API limite ~10 000)."""
        per_page = MAX_PER_PAGE
        page = 1
        collected = 0
        while collected < max_results:
            data = self.search(query=query, page=page, per_page=per_page, **filters)
            results = data.get("results", [])
            if not results:
                break
            for item in results:
                if collected >= max_results:
                    return
                yield item
                collected += 1
            if progress is not None:
                progress(collected, min(max_results, data.get("total_results", collected)))
            total_pages = data.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
