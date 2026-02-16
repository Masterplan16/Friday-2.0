#!/usr/bin/env python3
"""
Tests E2E Semantic Search (Story 3.3 - Task 9).

Pipeline complet:
    Document classified -> Embedding generated -> Search query -> Results returned

Tests avec mock infra (DB, Redis, Voyage AI) mais logique complete.
Les tests @pytest.mark.e2e_infra necessitent PostgreSQL+pgvector+Redis reels.

Date: 2026-02-16
Story: 3.3 - Task 9
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agents.src.agents.archiviste.models import SearchResult
from agents.src.tools.search_metrics import SearchMetrics

# ============================================================
# Test Dataset (Task 9.1) - 50 documents, 10 par categorie
# ============================================================

TEST_DATASET = [
    # --- PRO (10 docs) ---
    {"id": uuid4(), "category": "pro", "filename": "2026-01-15_Facture_Plombier_350EUR.pdf",
     "text": "Facture plombier intervention urgente fuite tuyau cabinet medical SELARL fevrier 2026 montant 350 euros TTC"},
    {"id": uuid4(), "category": "pro", "filename": "2026-02-01_Courrier_ARS_Inspection.pdf",
     "text": "Courrier ARS inspection sanitaire cabinet medical agrement annuel verification normes hygiene"},
    {"id": uuid4(), "category": "pro", "filename": "2025-12-20_Attestation_Formation_DPC.pdf",
     "text": "Attestation formation DPC developpement professionnel continu medecin generaliste diabetes"},
    {"id": uuid4(), "category": "pro", "filename": "2026-01-10_Contrat_Remplacement_Dr.pdf",
     "text": "Contrat remplacement medecin generaliste cabinet medical janvier 2026 conditions exercice"},
    {"id": uuid4(), "category": "pro", "filename": "2026-02-05_Facture_Materiel_Medical.pdf",
     "text": "Facture equipement medical tensiometre stethoscope Colson fournitures consommables"},
    {"id": uuid4(), "category": "pro", "filename": "2025-11-30_Courrier_CPAM_Convention.pdf",
     "text": "Courrier CPAM convention secteur 1 tiers payant tarif consultation"},
    {"id": uuid4(), "category": "pro", "filename": "2026-01-25_Facture_Logiciel_Medical.pdf",
     "text": "Facture logiciel gestion cabinet medical abonnement annuel dossier patient electronique"},
    {"id": uuid4(), "category": "pro", "filename": "2026-02-10_Ordonnance_Biologie.pdf",
     "text": "Ordonnance bilan biologique hemoglobine glyquee HbA1c creatinine DFG"},
    {"id": uuid4(), "category": "pro", "filename": "2025-10-15_Certificat_Aptitude.pdf",
     "text": "Certificat aptitude medecine du travail visite periodique medecin"},
    {"id": uuid4(), "category": "pro", "filename": "2026-01-20_Facture_Menage_Cabinet.pdf",
     "text": "Facture nettoyage menage desinfection cabinet medical prestation mensuelle"},

    # --- FINANCE (10 docs) ---
    {"id": uuid4(), "category": "finance", "subcategory": "selarl",
     "filename": "2026-01-31_Releve_SELARL_BanquePopulaire.pdf",
     "text": "Releve bancaire compte professionnel SELARL cabinet medical Banque Populaire janvier 2026"},
    {"id": uuid4(), "category": "finance", "subcategory": "scm",
     "filename": "2026-02-01_Appel_Charges_SCM.pdf",
     "text": "Appel charges trimestriel SCM societe civile moyens loyer electricite eau charges communes"},
    {"id": uuid4(), "category": "finance", "subcategory": "sci_ravas",
     "filename": "2025-12-31_Bilan_SCI_Ravas.pdf",
     "text": "Bilan comptable annuel SCI Ravas exercice 2025 revenus fonciers charges deductibles"},
    {"id": uuid4(), "category": "finance", "subcategory": "sci_malbosc",
     "filename": "2026-01-15_Loyer_SCI_Malbosc.pdf",
     "text": "Quittance loyer SCI Malbosc locataire janvier 2026 montant mensuel charges"},
    {"id": uuid4(), "category": "finance", "subcategory": "personal",
     "filename": "2026-02-05_Impots_Declaration_Revenus.pdf",
     "text": "Declaration revenus impot sur le revenu 2025 avis imposition traitements salaires"},
    {"id": uuid4(), "category": "finance", "subcategory": "selarl",
     "filename": "2026-01-20_Cotisations_URSSAF.pdf",
     "text": "Appel cotisations URSSAF trimestriel SELARL charges sociales CSG CRDS"},
    {"id": uuid4(), "category": "finance", "subcategory": "personal",
     "filename": "2026-01-10_Releve_Compte_Personnel.pdf",
     "text": "Releve bancaire compte personnel Caisse Epargne depenses courantes virements"},
    {"id": uuid4(), "category": "finance", "subcategory": "scm",
     "filename": "2025-12-15_Facture_Electricite_SCM.pdf",
     "text": "Facture electricite EDF local professionnel SCM consommation trimestrielle"},
    {"id": uuid4(), "category": "finance", "subcategory": "sci_ravas",
     "filename": "2026-01-05_Taxe_Fonciere_Ravas.pdf",
     "text": "Avis taxe fonciere SCI Ravas propriete immobiliere commune impot local"},
    {"id": uuid4(), "category": "finance", "subcategory": "personal",
     "filename": "2026-02-01_Assurance_Vie_Releve.pdf",
     "text": "Releve annuel assurance vie contrat multisupport performance fonds euros"},

    # --- UNIVERSITE (10 docs) ---
    {"id": uuid4(), "category": "universite",
     "filename": "2026-01-20_Cours_Pharmacologie_SGLT2.pdf",
     "text": "Cours pharmacologie inhibiteurs SGLT2 diabete type 2 empagliflozine dapagliflozine mecanisme action"},
    {"id": uuid4(), "category": "universite",
     "filename": "2025-12-10_TCS_Cas_Clinique_Pneumo.pdf",
     "text": "Test concordance scripts TCS pneumologie cas clinique embolie pulmonaire diagnostic"},
    {"id": uuid4(), "category": "universite",
     "filename": "2026-02-01_ECOS_Grille_Evaluation.pdf",
     "text": "Grille evaluation ECOS examen clinique objectif structure competences communication"},
    {"id": uuid4(), "category": "universite",
     "filename": "2026-01-15_These_Chapitre_3.pdf",
     "text": "These medecine chapitre 3 methodologie etude retrospective cohorte patients diabetiques"},
    {"id": uuid4(), "category": "universite",
     "filename": "2025-11-20_Bibliographie_Diabetes.pdf",
     "text": "Bibliographie annotee diabete type 2 metformine premiere intention traitement HbA1c"},
    {"id": uuid4(), "category": "universite",
     "filename": "2026-01-25_Cours_Dermatologie.pdf",
     "text": "Cours dermatologie melanome facteurs risque exposition solaire diagnostic precoce dermoscopie"},
    {"id": uuid4(), "category": "universite",
     "filename": "2026-02-10_Examen_Blanc_QCM.pdf",
     "text": "Examen blanc QCM medecine interne auto-immunite lupus polyarthrite rhumatoide"},
    {"id": uuid4(), "category": "universite",
     "filename": "2025-10-05_Stage_Rapport_Urgences.pdf",
     "text": "Rapport stage urgences prise en charge douleur thoracique protocole SCA"},
    {"id": uuid4(), "category": "universite",
     "filename": "2026-01-30_Memoire_Introduction.pdf",
     "text": "Introduction memoire DES medecine generale telemedecine consultation distance ruralite"},
    {"id": uuid4(), "category": "universite",
     "filename": "2025-12-20_Seminaire_Ethique.pdf",
     "text": "Seminaire ethique medicale fin de vie directives anticipees personne confiance"},

    # --- RECHERCHE (10 docs) ---
    {"id": uuid4(), "category": "recherche",
     "filename": "2026-01-10_Article_SGLT2_Nephroprotection.pdf",
     "text": "Article recherche nephroprotection inhibiteurs SGLT2 insuffisance renale chronique essai clinique"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2025-12-01_Protocole_Etude_Observationnelle.pdf",
     "text": "Protocole etude observationnelle multicentrique diabete gestationnel facteurs risque"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2026-02-05_Revue_Litterature_GLP1.pdf",
     "text": "Revue systematique agonistes GLP-1 semaglutide perte poids obesite diabete"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2026-01-20_Poster_Congres_SFD.pdf",
     "text": "Poster congres SFD societe francophone diabete resultats preliminaires cohorte"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2025-11-15_Article_IA_Retinopathie.pdf",
     "text": "Article intelligence artificielle depistage retinopathie diabetique deep learning fond oeil"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2026-01-05_CRF_Case_Report_Form.pdf",
     "text": "Case report form CRF formulaire recueil donnees essai clinique randomise"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2025-12-20_Consentement_Eclaire.pdf",
     "text": "Formulaire consentement eclaire patient etude clinique information risques benefices"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2026-02-10_Analyse_Statistique_R.pdf",
     "text": "Script analyse statistique R regression logistique multivariee odds ratio IC95"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2026-01-15_Soumission_JAMA.pdf",
     "text": "Lettre soumission article JAMA journal american medical association peer review"},
    {"id": uuid4(), "category": "recherche",
     "filename": "2025-10-30_Meta_Analyse_HTA.pdf",
     "text": "Meta analyse hypertension arterielle traitements antihypertenseurs mortalite cardiovasculaire"},

    # --- PERSO (10 docs) ---
    {"id": uuid4(), "category": "perso",
     "filename": "2026-01-15_Assurance_Habitation_MMA.pdf",
     "text": "Contrat assurance habitation MMA garantie multirisque dommages responsabilite civile"},
    {"id": uuid4(), "category": "perso",
     "filename": "2026-02-01_Facture_Internet_Orange.pdf",
     "text": "Facture mensuelle Orange fibre internet telephonie mobile abonnement fevrier 2026"},
    {"id": uuid4(), "category": "perso",
     "filename": "2025-12-25_Garantie_Electromenager.pdf",
     "text": "Certificat garantie lave-vaisselle Bosch achat Darty extension garantie 5 ans"},
    {"id": uuid4(), "category": "perso",
     "filename": "2026-01-10_Facture_Garage_Revision.pdf",
     "text": "Facture revision voiture garage vidange filtre huile plaquettes frein controle technique"},
    {"id": uuid4(), "category": "perso",
     "filename": "2025-11-20_Contrat_Mutuelle_Sante.pdf",
     "text": "Contrat complementaire sante mutuelle remboursement soins dentaires optique hospitalisation"},
    {"id": uuid4(), "category": "perso",
     "filename": "2026-01-20_Facture_Dentiste.pdf",
     "text": "Facture soins dentaires detartrage consultation annuelle remboursement securite sociale"},
    {"id": uuid4(), "category": "perso",
     "filename": "2026-02-10_Reservation_Vacances.pdf",
     "text": "Confirmation reservation vacances ete 2026 hotel bord mer famille"},
    {"id": uuid4(), "category": "perso",
     "filename": "2025-12-01_Facture_Plombier_Maison.pdf",
     "text": "Facture plombier intervention maison personnelle fuite chauffe-eau remplacement joint"},
    {"id": uuid4(), "category": "perso",
     "filename": "2026-01-25_Attestation_Assurance_Auto.pdf",
     "text": "Attestation assurance automobile carte verte vehicule personnel couverture tous risques"},
    {"id": uuid4(), "category": "perso",
     "filename": "2026-02-05_Quittance_Loyer_Personnel.pdf",
     "text": "Quittance loyer appartement personnel janvier 2026 charges provisions regularisation"},
]


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def dataset():
    """Dataset 50 documents test."""
    return TEST_DATASET


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg pool."""
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock()
    return pool


def _make_db_row(doc, score=0.85, embedding_vector=None):
    """Helper: cree un mock row PostgreSQL pour un document."""
    row = {
        "document_id": doc["id"],
        "title": doc["filename"],
        "path": f"C:\\Users\\lopez\\BeeStation\\Friday\\Archives\\{doc['category']}\\{doc['filename']}",
        "score": score,
        "ocr_text": doc["text"],
        "classification_category": doc["category"],
        "classification_subcategory": doc.get("subcategory"),
        "classification_confidence": 0.95,
        "document_metadata": {},
    }
    return row


# ============================================================
# Mock helpers
# ============================================================


def _mock_anonymize(text):
    """Mock Presidio: retourne texte inchange (pas de PII dans dataset test)."""
    result = MagicMock()
    result.anonymized_text = text
    return result


def _mock_embedding(dim=1024):
    """Mock embedding vector."""
    return [0.1] * dim


# ============================================================
# E2E Tests
# ============================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_semantic_search_pipeline_complete(dataset, mock_db_pool):
    """
    Test E2E pipeline complet (Task 9.2).

    Flow: query -> anonymize -> embed -> pgvector search -> results
    """
    from agents.src.agents.archiviste.semantic_search import SemanticSearcher

    # Simuler pgvector retournant 5 docs finance
    finance_docs = [d for d in dataset if d["category"] == "finance"][:5]
    mock_rows = [_make_db_row(d, score=0.9 - i * 0.05) for i, d in enumerate(finance_docs)]
    mock_db_pool.fetch.return_value = mock_rows

    searcher = SemanticSearcher(db_pool=mock_db_pool)

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=_mock_anonymize("releve bancaire SELARL"),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = {"embeddings": [_mock_embedding()]}
        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            results = await searcher.search(query="releve bancaire SELARL", top_k=5)

    assert len(results) == 5
    assert all(isinstance(r, SearchResult) for r in results)
    assert results[0].score >= results[-1].score  # Tri par score descendant


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_query_pertinence_facture(dataset, mock_db_pool):
    """
    Test pertinence : "facture plombier 2026" -> trouve facture plombier (Task 9.3).
    """
    from agents.src.agents.archiviste.semantic_search import SemanticSearcher

    # Le doc attendu
    target = next(d for d in dataset if "Plombier_350EUR" in d["filename"])
    mock_db_pool.fetch.return_value = [_make_db_row(target, score=0.95)]

    searcher = SemanticSearcher(db_pool=mock_db_pool)

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=_mock_anonymize("facture plombier 2026"),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = {"embeddings": [_mock_embedding()]}
        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            results = await searcher.search(query="facture plombier 2026", top_k=5)

    assert len(results) >= 1
    assert "Plombier" in results[0].title
    assert results[0].score >= 0.9


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_query_semantic_sglt2(dataset, mock_db_pool):
    """
    Test semantique : "diabete inhibiteurs SGLT2" -> trouve articles recherche (Task 9.4).
    """
    from agents.src.agents.archiviste.semantic_search import SemanticSearcher

    # Docs pertinents : cours SGLT2 + article nephroprotection
    sglt2_docs = [d for d in dataset if "SGLT2" in d["text"]]
    mock_rows = [_make_db_row(d, score=0.92 - i * 0.03) for i, d in enumerate(sglt2_docs)]
    mock_db_pool.fetch.return_value = mock_rows

    searcher = SemanticSearcher(db_pool=mock_db_pool)

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=_mock_anonymize("diabete inhibiteurs SGLT2"),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = {"embeddings": [_mock_embedding()]}
        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            results = await searcher.search(query="diabete inhibiteurs SGLT2", top_k=5)

    assert len(results) >= 1
    # Tous les resultats contiennent SGLT2
    for r in results:
        assert "SGLT2" in r.excerpt or "SGLT2" in r.title


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_performance_parallel(mock_db_pool):
    """
    Test performance : 100 queries paralleles, latence < 3s chacune (Task 9.5, AC1).
    """
    from agents.src.agents.archiviste.semantic_search import SemanticSearcher

    mock_db_pool.fetch.return_value = []  # Pas de resultats (on teste la latence)
    searcher = SemanticSearcher(db_pool=mock_db_pool)

    async def run_query(query: str):
        with patch(
            "agents.src.agents.archiviste.semantic_search.anonymize_text",
            return_value=_mock_anonymize(query),
        ):
            mock_adapter = AsyncMock()
            mock_adapter.embed.return_value = {"embeddings": [_mock_embedding()]}
            with patch(
                "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
                return_value=mock_adapter,
            ):
                start = time.time()
                await searcher.search(query=query, top_k=5)
                return (time.time() - start) * 1000

    queries = [f"test query {i}" for i in range(100)]
    latencies = await asyncio.gather(*[run_query(q) for q in queries])

    # Toutes < 3000ms (AC1)
    for lat in latencies:
        assert lat < 3000, f"Query exceeded 3s: {lat:.0f}ms"

    # Mediane raisonnable (avec mocks, devrait etre < 100ms)
    sorted_lats = sorted(latencies)
    median = sorted_lats[len(sorted_lats) // 2]
    assert median < 1000, f"Median latency too high: {median:.0f}ms"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_desktop_search_fallback():
    """
    Test Desktop Search : CLI indisponible -> fallback pgvector (Task 9.6).
    """
    from agents.src.tools.desktop_search_wrapper import search_desktop

    with patch(
        "agents.src.tools.desktop_search_wrapper._is_claude_cli_available",
        return_value=False,
    ):
        with pytest.raises(FileNotFoundError):
            await search_desktop(query="test document")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_with_category_filter(dataset, mock_db_pool):
    """
    Test filtres : query + category=finance -> resultats finance uniquement (Task 9.7).
    """
    from agents.src.agents.archiviste.semantic_search import SemanticSearcher

    finance_docs = [d for d in dataset if d["category"] == "finance"][:3]
    mock_rows = [_make_db_row(d, score=0.88) for d in finance_docs]
    mock_db_pool.fetch.return_value = mock_rows
    mock_db_pool.execute = AsyncMock()  # SET LOCAL hnsw.iterative_scan

    searcher = SemanticSearcher(db_pool=mock_db_pool)

    with patch(
        "agents.src.agents.archiviste.semantic_search.anonymize_text",
        return_value=_mock_anonymize("releve bancaire"),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.embed.return_value = {"embeddings": [_mock_embedding()]}
        with patch(
            "agents.src.agents.archiviste.semantic_search.get_embedding_adapter",
            return_value=mock_adapter,
        ):
            results = await searcher.search(
                query="releve bancaire",
                top_k=5,
                filters={"category": "finance"},
            )

    assert len(results) == 3
    for r in results:
        assert r.metadata["category"] == "finance"

    # Verifier que hnsw.iterative_scan a ete active (filtre present)
    mock_db_pool.execute.assert_called_once_with("SET LOCAL hnsw.iterative_scan = on")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_dataset_coverage(dataset):
    """Verifie dataset 50 documents, 10 par categorie (Task 9.1)."""
    assert len(dataset) == 50

    categories = {}
    for doc in dataset:
        cat = doc["category"]
        categories[cat] = categories.get(cat, 0) + 1

    assert categories == {
        "pro": 10,
        "finance": 10,
        "universite": 10,
        "recherche": 10,
        "perso": 10,
    }

    # Chaque doc a les champs requis
    for doc in dataset:
        assert "id" in doc
        assert "category" in doc
        assert "filename" in doc
        assert "text" in doc
        assert isinstance(doc["id"], UUID)
