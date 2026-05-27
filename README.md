# Streamlit-Entreprises-FR

Application **Streamlit** publique pour rechercher les informations officielles des
entreprises françaises (Sirene, INPI/RNE, dirigeants, finances) — **sans clé API**,
**sans base de données**, prête à publier gratuitement sur **Streamlit Community Cloud**.

## Fonctionnalités

| Onglet | Cas d'usage |
|---|---|
| 🔢 **Par SIREN / SIRET** | Lookup direct multi-identifiants, validation Luhn, fallback INSEE |
| 🏷️ **Par raison sociale / nom** | Recherche textuelle + filtres NAF, code postal, département, nature juridique, état administratif, sièges uniquement |
| 📍 **Par adresse / géographie** | Filtrage CP/département + carte interactive |
| 📂 **Lot Excel / CSV** | Enrichissement en masse d'un fichier (SIREN/SIRET ou raison sociale), téléchargement Excel/CSV |

## Sources de données

- **Principale** : [API Recherche d'Entreprises](https://recherche-entreprises.api.gouv.fr/docs/) (api.gouv.fr)
  - Gratuite, sans clé d'API
  - Données : Sirene (INSEE) + INPI/RNE + RNA + données dirigeants + bilans financiers
  - Mise à jour quotidienne
  - Limite : 7 req/s par IP, 10 000 résultats max par requête
- **Enrichissement optionnel** : [API INSEE Sirene 3.11](https://portail-api.insee.fr/) — clé à coller dans la sidebar

## Lancement local

```bash
cd streamlit-entreprises-fr
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Application disponible sur <http://localhost:8501>.

## Publication sur Streamlit Cloud

1. Pousser ce dossier sur un dépôt GitHub public.
2. Sur <https://share.streamlit.io>, créer une nouvelle app pointant sur `streamlit_app.py`.
3. (Optionnel) Settings → Secrets :

   ```toml
   INSEE_API_KEY = "votre_cle_optionnelle"
   ```

## Architecture

```
streamlit-entreprises-fr/
├── streamlit_app.py              # UI Streamlit multi-onglets
├── requirements.txt              # Dépendances minimales
├── .streamlit/config.toml        # Thème & options serveur
└── app/
    ├── recherche_entreprises_client.py  # Client API publique (sans clé)
    ├── insee_client.py                  # Client INSEE optionnel
    ├── identifiers.py                   # SIREN/SIRET : Luhn, parsing, normalisation
    ├── normalize.py                     # Mise à plat des réponses → lignes tabulaires
    ├── search_service.py                # Orchestration recherche unifiée
    └── export.py                        # Exports Excel/CSV
```

## Pas de base de données ?

Volontairement. Streamlit Community Cloud impose un système de fichiers **éphémère** :
toute persistance serait perdue à chaque redémarrage. Tous les résultats sont :

- Affichés dans des `st.dataframe`
- Téléchargeables instantanément en Excel / CSV via `st.download_button`

Si vous voulez de la persistance, branchez ultérieurement Supabase / Postgres /
Google Sheets via `st.secrets`.
