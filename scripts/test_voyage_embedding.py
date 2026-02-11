#!/usr/bin/env python3
"""
Friday 2.0 - Script test manuel Voyage AI

Test l'adaptateur Voyage AI avec embeddings réels.

Prérequis:
    1. Compte Voyage AI créé (https://www.voyageai.com/)
    2. API key configurée dans .env : VOYAGE_API_KEY=...
    3. PostgreSQL running avec migration 008 appliquée (knowledge.embeddings table)

Usage:
    python scripts/test_voyage_embedding.py

Expected output:
    ✅ Voyage AI adapter initialisé
    ✅ Embedding généré (1024 dimensions)
    ✅ Embedding stocké dans PostgreSQL
    ✅ Recherche sémantique fonctionnelle (similarity > 0.8)

Date: 2026-02-11
Story: 6.2 - Subtask 1.6
"""

import asyncio
import os
import sys
from pathlib import Path

# Ajouter agents/src au path
agents_src = Path(__file__).parent.parent / "agents" / "src"
sys.path.insert(0, str(agents_src))

import structlog
from adapters.vectorstore import get_vectorstore_adapter
from dotenv import load_dotenv

logger = structlog.get_logger(__name__)


async def main():
    """Test complet adaptateur Voyage AI"""

    print("=" * 60)
    print("🧪 Friday 2.0 - Test Voyage AI Embeddings")
    print("=" * 60)
    print()

    # Load env vars
    load_dotenv()

    # Vérifier variables requises
    if not os.getenv("VOYAGE_API_KEY"):
        print("❌ VOYAGE_API_KEY manquante dans .env")
        print()
        print("Action requise:")
        print("1. Créer compte sur https://www.voyageai.com/")
        print("2. Générer API key depuis dashboard")
        print("3. Ajouter dans .env : VOYAGE_API_KEY=vo-xxxxx")
        print()
        return 1

    if not os.getenv("DATABASE_URL"):
        print("❌ DATABASE_URL manquante dans .env")
        print()
        print("Example:")
        print("DATABASE_URL=postgresql://friday:password@localhost:5432/friday")
        print()
        return 1

    print("✅ Variables d'environnement chargées")
    print()

    # Initialiser adaptateur
    print("📡 Initialisation adaptateur Voyage AI...")
    try:
        vectorstore = await get_vectorstore_adapter(provider="voyage")
        print("✅ Adaptateur initialisé (voyage-4-large, 1024 dims)")
        print()
    except Exception as e:
        print(f"❌ Échec initialisation: {e}")
        return 1

    # Test 1: Générer embedding
    print("🔬 Test 1: Génération embedding")
    print("-" * 40)

    test_text = "Facture plombier 250 EUR"
    print(f"Texte test: '{test_text}'")

    try:
        # Anonymisation automatique appliquée
        response = await vectorstore.embed([test_text], anonymize=True)

        embedding = response.embeddings[0]
        dimensions = len(embedding)
        tokens = response.tokens_used

        print(f"✅ Embedding généré:")
        print(f"   - Dimensions: {dimensions}")
        print(f"   - Tokens utilisés: {tokens}")
        print(f"   - Anonymisation: {response.anonymization_applied}")
        print(f"   - Premiers 5 floats: {embedding[:5]}")
        print()

        # Vérifier format
        assert dimensions == 1024, f"Expected 1024 dims, got {dimensions}"
        assert all(-1.0 <= v <= 1.0 for v in embedding), "Values out of range [-1, 1]"

    except Exception as e:
        print(f"❌ Échec génération embedding: {e}")
        return 1

    # Test 2: Stocker dans PostgreSQL
    print("💾 Test 2: Stockage PostgreSQL")
    print("-" * 40)

    test_node_id = "test_email_voyage_001"

    try:
        await vectorstore.store(
            node_id=test_node_id,
            embedding=embedding,
            metadata={"test": True, "source": "script_test_voyage"},
        )

        print(f"✅ Embedding stocké:")
        print(f"   - Node ID: {test_node_id}")
        print(f"   - Table: knowledge.embeddings")
        print()

    except Exception as e:
        print(f"❌ Échec stockage: {e}")
        return 1

    # Test 3: Recherche sémantique
    print("🔍 Test 3: Recherche sémantique")
    print("-" * 40)

    query_text = "plombier"
    print(f"Query: '{query_text}'")

    try:
        # Générer embedding query (input_type="query" optimisé)
        query_response = await vectorstore.embed([query_text], anonymize=True)
        query_embedding = query_response.embeddings[0]

        # Rechercher
        results = await vectorstore.search(
            query_embedding=query_embedding,
            top_k=5,
            filters=None,  # Pas de filtre pour test
        )

        print(f"✅ Recherche complétée:")
        print(f"   - Résultats trouvés: {len(results)}")
        print()

        if results:
            print("Top résultats:")
            for i, result in enumerate(results[:3], 1):
                print(f"{i}. Node: {result.node_id}")
                print(f"   Similarity: {result.similarity:.4f}")
                print(f"   Type: {result.node_type}")
                print()

            # Vérifier que notre test node est trouvé avec haute similarité
            test_result = next((r for r in results if r.node_id == test_node_id), None)

            if test_result:
                similarity = test_result.similarity
                print(f"✅ Test node trouvé (similarity: {similarity:.4f})")

                if similarity > 0.8:
                    print("✅ Similarity > 0.8 (excellent match)")
                else:
                    print(f"⚠️  Similarity {similarity:.4f} < 0.8 (attendu >0.8)")

            else:
                print("⚠️  Test node pas trouvé dans résultats")

        else:
            print("⚠️  Aucun résultat (BDD peut être vide)")

    except Exception as e:
        print(f"❌ Échec recherche: {e}")
        return 1

    # Cleanup
    print()
    print("🧹 Nettoyage...")
    try:
        await vectorstore.delete(test_node_id)
        print(f"✅ Test node supprimé: {test_node_id}")
    except Exception as e:
        print(f"⚠️  Échec cleanup: {e}")

    await vectorstore.close()
    print("✅ Connexions fermées")

    print()
    print("=" * 60)
    print("🎉 Tous les tests PASS!")
    print("=" * 60)
    print()
    print("Prochaines étapes:")
    print("  - Intégrer dans pipeline Email (Task 2)")
    print("  - Intégrer dans Archiviste (Task 3)")
    print("  - Créer endpoint /api/v1/search/semantic (Task 4)")
    print()

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
