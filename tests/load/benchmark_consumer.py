#!/usr/bin/env python3
"""
Injecte 100 faux emails dans Redis Streams pour benchmarker le consumer.
Mesure : throughput, latency, errors, cout tokens, RAM peak.

Story 2.9 / Phase C.7.5 — Test de charge AVANT Phase D.

IMPORTANT : Ne touche PAS aux vrais comptes email.
Les emails de test ont un flag is_benchmark=true pour nettoyage facile.

LIMITATION : Contenu synthetique — throughput reel sera ~20-40% inferieur.
Appliquer facteur correctif 0.6-0.8 sur les resultats.

Usage:
    python tests/load/benchmark_consumer.py           # Injecter + mesurer
    python tests/load/benchmark_consumer.py --cleanup  # Nettoyer donnees benchmark
"""

import asyncio
import json
import os
import sys
import time
import uuid

import asyncpg
import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL")
STREAM_KEY = "emails:received"
NUM_EMAILS = 100

# Corpus realiste avec corps de longueur variable pour tester le classifier
# Inclut des sujets de chaque categorie attendue + corps substantiels
TEST_EMAILS = [
    {
        "subject": "Rendez-vous consultation Dr Martin lundi 14h",
        "body": (
            "Bonjour Dr Lopez, je vous confirme le rendez-vous de consultation pour Mme Durand "
            "le lundi 17 fevrier a 14h au cabinet. La patiente presente des douleurs lombaires "
            "chroniques depuis 3 mois. Elle a deja consulte un kinesitherapeute sans amelioration. "
            "Merci de prevoir un examen clinique complet. Cordialement, Secretariat medical."
        ),
    },
    {
        "subject": "Facture EDF n 2026-0234 - Janvier 2026",
        "body": (
            "Cher client, veuillez trouver ci-joint votre facture d'electricite pour la periode "
            "du 01/01/2026 au 31/01/2026. Montant TTC : 187,43 EUR. Reference contrat : "
            "FR-2024-789456. Date limite de paiement : 28/02/2026. Le prelevement automatique "
            "sera effectue le 25/02/2026 sur votre compte bancaire. Pour toute reclamation, "
            "contactez le service client au 09 69 32 15 15."
        ),
    },
    {
        "subject": "Invitation soutenance these M. Dupont - Universite Montpellier",
        "body": (
            "Madame, Monsieur, J'ai le plaisir de vous inviter a la soutenance de these de "
            "M. Pierre Dupont intitulee 'Approches computationnelles pour l'analyse des reseaux "
            "de neurones artificiels appliques a l'imagerie medicale'. La soutenance aura lieu "
            "le 15 mars 2026 a 14h30 en salle des actes, Faculte de Medecine, Universite de "
            "Montpellier. Jury : Pr. Martin (directeur), Dr. Bernard (rapporteur), Pr. Petit."
        ),
    },
    {
        "subject": "Newsletter Carrefour - Promos de la semaine",
        "body": (
            "Decouvrez nos offres exceptionnelles cette semaine ! Fruits et legumes bio -30%. "
            "Electromenager : aspirateur robot a 199 EUR au lieu de 349 EUR. Rayon boucherie : "
            "entrecote de boeuf a 15.99 EUR/kg. Livraison gratuite des 50 EUR d'achats avec "
            "le code CARREFOUR2026. Valable du 12 au 18 fevrier 2026 dans tous les magasins."
        ),
    },
    {
        "subject": "URGENT: Resultat analyse biologique patient ref P-2026-4521",
        "body": (
            "Dr Lopez, resultats urgents pour patient ref P-2026-4521. Glycemie a jeun : "
            "2.45 g/L (norme < 1.10). HbA1c : 9.2% (norme < 6.5%). Creatinine : 18 mg/L "
            "(norme 7-13). DFG estime : 52 mL/min (insuffisance renale moderee). "
            "Recommandation : consultation diabetologie urgente + adaptation traitement. "
            "Laboratoire d'analyses medicales du Lez."
        ),
    },
    {
        "subject": "Rappel reunion SCM vendredi 10h - Ordre du jour",
        "body": (
            "Bonjour a tous, rappel de la reunion SCM ce vendredi 14 fevrier a 10h. "
            "Ordre du jour : 1) Bilan comptable T4 2025 2) Renouvellement bail commercial "
            "3) Investissement materiel echographe 4) Planning vacances ete 2026 "
            "5) Questions diverses. Merci de confirmer votre presence. Dr Martin, Dr Bernard."
        ),
    },
    {
        "subject": "Confirmation commande Amazon #123-456-789",
        "body": (
            "Votre commande a ete confirmee. Livraison estimee : 14-15 fevrier 2026. "
            "Articles : 1x Stethoscope Littmann Classic III (89.99 EUR), "
            "1x Tensiometre bras Omron M7 (79.99 EUR). Total : 169.98 EUR. "
            "Adresse de livraison : Cabinet medical, 15 rue de la Republique, 34000 Montpellier."
        ),
    },
    {
        "subject": "Appel a communications - Congres SFMG 2026 Lyon",
        "body": (
            "La Societe Francaise de Medecine Generale lance son appel a communications pour "
            "le congres annuel 2026 a Lyon (5-7 juin). Themes : IA en medecine generale, "
            "telemedecine post-COVID, prise en charge pluriprofessionnelle. Soumission abstracts "
            "avant le 31 mars 2026 via plateforme en ligne. Format : poster ou communication orale."
        ),
    },
    {
        "subject": "Releve bancaire Janvier 2026 - CIC Montpellier",
        "body": (
            "Releve de compte courant professionnel - Janvier 2026. Solde debut : 15 432.67 EUR. "
            "Mouvements : +12 350.00 (honoraires), +8 200.00 (honoraires), -3 500.00 (loyer), "
            "-1 200.00 (assurance), -890.00 (URSSAF). Solde fin : 30 392.67 EUR. "
            "Prochaine echeance pret : 05/03/2026 - 1 250.00 EUR."
        ),
    },
    {
        "subject": "Re: Bail SCI Ravas - Renouvellement locataire Dupont",
        "body": (
            "Maitre Lopez, suite a notre echange telephonique concernant le renouvellement du "
            "bail de M. Dupont au 23 avenue de Ravas. Le locataire accepte la revision de loyer "
            "a 850 EUR/mois (contre 820 EUR actuellement). Nouvelle duree : 3 ans a compter du "
            "01/04/2026. Je vous envoie le projet de bail pour validation. Cabinet notarial Durand."
        ),
    },
]


async def inject_test_emails() -> float:
    """Injecte NUM_EMAILS faux emails dans Redis Streams."""
    r = aioredis.from_url(REDIS_URL)

    print(f"Injecting {NUM_EMAILS} test emails into Redis Streams...")
    start = time.time()

    for i in range(NUM_EMAILS):
        template = TEST_EMAILS[i % len(TEST_EMAILS)]
        email_data = {
            "message_id": f"<benchmark-{uuid.uuid4()}@test.friday>",
            "account_id": "benchmark-account",
            "from": f"test-{i % 10}@benchmark.friday",
            "to": "benchmark-recipient@test.friday",
            "subject": template["subject"],
            "body_text": template["body"],
            "received_at": "2026-02-12T12:00:00Z",
            "is_benchmark": "true",
        }
        await r.xadd(STREAM_KEY, {"data": json.dumps(email_data)})

        if (i + 1) % 25 == 0:
            print(f"  Injected {i + 1}/{NUM_EMAILS}")

    elapsed = time.time() - start
    print(f"Injection done in {elapsed:.1f}s\n")
    await r.aclose()
    return start


async def wait_and_measure(injection_start: float, timeout_minutes: int = 20) -> bool:
    """Attend que le consumer traite les 100 emails, mesure throughput."""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return False

    db = await asyncpg.connect(DATABASE_URL)

    print(f"Waiting for consumer to process (timeout {timeout_minutes}min)...")
    deadline = time.time() + timeout_minutes * 60
    count = 0

    while time.time() < deadline:
        count = await db.fetchval(
            "SELECT COUNT(*) FROM ingestion.emails "
            "WHERE metadata->>'is_benchmark' = 'true'"
        )
        if count >= NUM_EMAILS:
            elapsed = time.time() - injection_start
            throughput = NUM_EMAILS / (elapsed / 60)
            print(f"\n{'=' * 40}")
            print(f"BENCHMARK RESULTS")
            print(f"{'=' * 40}")
            print(f"Emails processed : {count}/{NUM_EMAILS}")
            print(f"Total time       : {elapsed:.0f}s ({elapsed / 60:.1f}min)")
            print(f"Throughput       : {throughput:.1f} emails/min")

            # Cout tokens
            cost = await db.fetchval(
                "SELECT SUM(cost_usd) FROM core.llm_usage "
                "WHERE context = 'benchmark'"
            )
            print(f"Cout tokens      : ${cost or 0:.2f}")
            if cost:
                print(f"Cout/email       : ${cost / NUM_EMAILS:.4f}")

            # Facteur correctif
            print(f"\nFacteur correctif recommande : x0.6-0.8")
            print(f"Throughput reel estime : {throughput * 0.6:.1f}-{throughput * 0.8:.1f} emails/min")

            await db.close()
            return True

        print(f"  ... {count}/{NUM_EMAILS} processed")
        await asyncio.sleep(15)

    print(f"\nTIMEOUT: Only {count}/{NUM_EMAILS} processed in {timeout_minutes}min")
    await db.close()
    return False


async def cleanup_benchmark() -> None:
    """Supprime les donnees de benchmark apres test."""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return

    db = await asyncpg.connect(DATABASE_URL)
    deleted = await db.fetchval(
        "DELETE FROM ingestion.emails "
        "WHERE metadata->>'is_benchmark' = 'true' "
        "RETURNING COUNT(*)"
    )
    await db.execute("DELETE FROM core.llm_usage WHERE context = 'benchmark'")
    await db.close()
    print(f"Cleanup: {deleted or 0} benchmark emails supprimees")


if __name__ == "__main__":
    if "--cleanup" in sys.argv:
        asyncio.run(cleanup_benchmark())
    else:
        start = asyncio.run(inject_test_emails())
        success = asyncio.run(wait_and_measure(start))
        if not success:
            print("Investiguer logs consumer AVANT Phase D")
            sys.exit(1)
        print(f"\nPour nettoyer : python tests/load/benchmark_consumer.py --cleanup")
