"""
Tests E2E accuracy classification email (Story 2.2, AC7).

Valide l'accuracy du modèle Claude Sonnet 4.5 sur dataset de 100 emails.

IMPORTANT: Ce test appelle Claude API réelle et consomme des tokens.
Exécuter manuellement avant release, PAS dans CI/CD quotidien.

Usage:
    pytest tests/e2e/email/test_classification_accuracy.py --run-e2e

Acceptance Criteria (AC7):
- Accuracy globale >= 85%
- Accuracy par catégorie >= 80%
"""

import json
import os
from collections import defaultdict
from pathlib import Path

import asyncpg
import pytest

# Markers pour skips conditionnels
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.getenv("RUN_E2E_TESTS"),
        reason="E2E tests require --run-e2e flag or RUN_E2E_TESTS=1 env",
    ),
]


@pytest.fixture
async def test_db_pool():
    """Pool PostgreSQL de test."""
    pool = await asyncpg.create_pool(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "friday_test"),
        user=os.getenv("POSTGRES_USER", "friday"),
        password=os.getenv("POSTGRES_PASSWORD", "friday_dev"),
    )
    yield pool
    await pool.close()


@pytest.fixture
def dataset_emails():
    """Charge le dataset de 100 emails."""
    dataset_path = (
        Path(__file__).parent.parent.parent / "fixtures" / "emails_classification_dataset.json"
    )
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_classification_accuracy_global(test_db_pool, dataset_emails):
    """
    Test accuracy globale >= 85% sur dataset complet (AC7).

    AVERTISSEMENT: Ce test consomme ~100 appels Claude API (~3000 tokens input + 300 output).
    Coût estimé : ~0.50 USD par run complet.
    """
    from agents.src.agents.email.classifier import classify_email

    correct_classifications = 0
    total_emails = len(dataset_emails)
    results = []

    # Classifier tous les emails
    for email_data in dataset_emails:
        # Construire texte email
        email_text = (
            f"From: {email_data['from']}\n"
            f"Subject: {email_data['subject']}\n\n"
            f"{email_data['body']}"
        )

        # Classifier
        try:
            result = await classify_email(
                email_id=email_data["id"],
                email_text=email_text,
                db_pool=test_db_pool,
            )

            predicted_category = result.payload.get("category")
            ground_truth = email_data["ground_truth"]
            confidence = result.confidence

            is_correct = predicted_category == ground_truth

            if is_correct:
                correct_classifications += 1

            results.append(
                {
                    "email_id": email_data["id"],
                    "predicted": predicted_category,
                    "ground_truth": ground_truth,
                    "confidence": confidence,
                    "correct": is_correct,
                }
            )

        except Exception as e:
            # Log error mais continuer
            results.append(
                {
                    "email_id": email_data["id"],
                    "predicted": "ERROR",
                    "ground_truth": email_data["ground_truth"],
                    "confidence": 0.0,
                    "correct": False,
                    "error": str(e),
                }
            )

    # Calculer accuracy globale
    accuracy_global = correct_classifications / total_emails

    # Générer rapport
    print("\n" + "=" * 80)
    print("RAPPORT ACCURACY CLASSIFICATION EMAIL")
    print("=" * 80)
    print(f"Total emails testés : {total_emails}")
    print(f"Classifications correctes : {correct_classifications}")
    print(f"Accuracy globale : {accuracy_global:.2%}")
    print("=" * 80)

    # Afficher erreurs si accuracy < 85%
    if accuracy_global < 0.85:
        print("\n⚠️  ERREURS DÉTAILLÉES (accuracy < 85%):")
        errors = [r for r in results if not r["correct"]]
        for err in errors[:10]:  # Afficher max 10 premières erreurs
            print(f"\n  Email: {err['email_id']}")
            print(f"  Ground truth: {err['ground_truth']}")
            print(f"  Predicted: {err['predicted']}")
            print(f"  Confidence: {err.get('confidence', 0):.2f}")
            if "error" in err:
                print(f"  Error: {err['error']}")

    # Sauvegarder résultats complets dans fichier JSON (debug)
    results_path = Path(__file__).parent / "accuracy_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "accuracy_global": accuracy_global,
                "correct": correct_classifications,
                "total": total_emails,
                "results": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nRésultats complets sauvegardés : {results_path}")

    # Assertion AC7 : Accuracy >= 85%
    assert accuracy_global >= 0.85, (
        f"Accuracy globale {accuracy_global:.2%} < 85% requis (AC7). "
        f"Voir {results_path} pour détails."
    )


@pytest.mark.asyncio
async def test_classification_accuracy_per_category(test_db_pool, dataset_emails):
    """
    Test accuracy par catégorie >= 80% (AC7).

    Breakdown par catégorie :
    - medical (13 emails)
    - finance (13 emails)
    - faculty (13 emails)
    - research (13 emails)
    - personnel (13 emails)
    - urgent (7 emails)
    - spam (7 emails)
    - unknown (5 emails)
    """
    from agents.src.agents.email.classifier import classify_email

    # Grouper résultats par catégorie
    category_stats = defaultdict(lambda: {"correct": 0, "total": 0})

    # Classifier tous les emails
    for email_data in dataset_emails:
        ground_truth = email_data["ground_truth"]
        category_stats[ground_truth]["total"] += 1

        # Construire texte email
        email_text = (
            f"From: {email_data['from']}\n"
            f"Subject: {email_data['subject']}\n\n"
            f"{email_data['body']}"
        )

        # Classifier
        try:
            result = await classify_email(
                email_id=email_data["id"],
                email_text=email_text,
                db_pool=test_db_pool,
            )

            predicted_category = result.payload.get("category")

            if predicted_category == ground_truth:
                category_stats[ground_truth]["correct"] += 1

        except Exception:
            # Erreur = classification incorrecte
            pass

    # Calculer accuracy par catégorie
    category_accuracies = {}
    for category, stats in category_stats.items():
        accuracy = stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0
        category_accuracies[category] = accuracy

    # Afficher breakdown
    print("\n" + "=" * 80)
    print("ACCURACY PAR CATÉGORIE")
    print("=" * 80)
    for category in sorted(category_accuracies.keys()):
        accuracy = category_accuracies[category]
        stats = category_stats[category]
        status = "✓" if accuracy >= 0.80 else "✗"
        print(f"{status}  {category:12} : {accuracy:.2%}  ({stats['correct']}/{stats['total']})")
    print("=" * 80)

    # Assertion AC7 : Toutes catégories >= 80%
    failed_categories = [(cat, acc) for cat, acc in category_accuracies.items() if acc < 0.80]

    if failed_categories:
        failed_details = ", ".join([f"{cat}={acc:.2%}" for cat, acc in failed_categories])
        pytest.fail(f"Certaines catégories < 80% accuracy requis (AC7): {failed_details}")


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_classification_smoke_subset_20(test_db_pool):
    """
    Test smoke : subset 20 emails pour CI/CD (AC7).

    Sélectionne 20 emails variés (2-3 par catégorie) pour validation rapide.
    Utilisable dans CI/CD car coût réduit (~0.10 USD).

    Acceptance : >= 80% accuracy sur subset (tolérance réduite car sample petit).
    """
    from agents.src.agents.email.classifier import classify_email

    # Subset 20 emails (IDs hardcodés pour reproducibilité)
    smoke_email_ids = [
        "email-001",
        "email-002",
        "email-003",
        "email-004",
        "email-005",  # 1 par catégorie principale
        "email-006",
        "email-007",
        "email-008",  # urgent, spam, unknown
        "email-009",
        "email-017",
        "email-025",  # medical, finance, personnel (variantes)
        "email-032",
        "email-039",
        "email-044",  # research (variantes)
        "email-048",
        "email-056",
        "email-064",  # unknown, urgent, spam (variantes)
        "email-071",
        "email-083",  # medical (edge cases)
    ]

    # Charger dataset complet
    dataset_path = (
        Path(__file__).parent.parent.parent / "fixtures" / "emails_classification_dataset.json"
    )
    with open(dataset_path, "r", encoding="utf-8") as f:
        all_emails = json.load(f)

    # Filtrer subset
    subset_emails = [e for e in all_emails if e["id"] in smoke_email_ids]

    correct = 0
    total = len(subset_emails)

    # Classifier subset
    for email_data in subset_emails:
        email_text = (
            f"From: {email_data['from']}\n"
            f"Subject: {email_data['subject']}\n\n"
            f"{email_data['body']}"
        )

        try:
            result = await classify_email(
                email_id=email_data["id"],
                email_text=email_text,
                db_pool=test_db_pool,
            )

            if result.payload.get("category") == email_data["ground_truth"]:
                correct += 1

        except Exception:
            pass  # Erreur = incorrect

    accuracy = correct / total

    print(f"\n[SMOKE TEST] Accuracy subset 20 emails : {accuracy:.2%} ({correct}/{total})")

    # Assertion : >= 80% sur subset (tolérance car petit sample)
    assert accuracy >= 0.80, f"Smoke test accuracy {accuracy:.2%} < 80% requis"
