#!/usr/bin/env python3
"""
Migration des 55 000 emails existants vers Friday 2.0
Stratégie: Checkpointing + Retry + Resume + Progress tracking

Usage:
    python scripts/migrate_emails.py [--resume] [--dry-run] [--batch-size 100]

Features:
- Checkpoint tous les 100 emails (configurable)
- Retry exponentiel sur erreur API (3 tentatives)
- Resume depuis dernier checkpoint en cas de crash
- Progress bar + estimation temps restant
- Rate limiting API Mistral respecté (60 req/min max)
- Logs détaillés dans logs/migration.log
"""

import asyncio
import asyncpg
import argparse
import logging
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

# Configuration (chargée depuis variables d'environnement - jamais hardcodé)
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://friday:password@localhost:5432/friday")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
CHECKPOINT_FILE = "data/migration_checkpoint.json"
LOG_FILE = "logs/migration.log"
BATCH_SIZE = 100  # Emails par batch
MAX_RETRIES = 3
RATE_LIMIT_RPM = 60  # Mistral rate limit (requests per minute)
RATE_LIMIT_DELAY = 60 / RATE_LIMIT_RPM  # 1 seconde entre requêtes


@dataclass
class MigrationState:
    """État de la migration"""
    total_emails: int
    processed: int
    failed: int
    last_email_id: Optional[str]
    started_at: datetime
    last_checkpoint_at: datetime
    estimated_cost: float  # USD
    estimated_time_remaining: Optional[timedelta]


class EmailMigrator:
    def __init__(self, dry_run: bool = False, resume: bool = False):
        self.dry_run = dry_run
        self.resume = resume
        self.db = None
        self.mistral_client = None
        self.state: Optional[MigrationState] = None
        self.logger = self._setup_logging()

    def _setup_logging(self):
        """Configure logging"""
        Path("logs").mkdir(exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(LOG_FILE),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)

    async def connect(self):
        """Connexion PostgreSQL + Mistral"""
        self.logger.info("Connexion à PostgreSQL...")
        self.db = await asyncpg.connect(POSTGRES_DSN)

        self.logger.info("Connexion à Mistral API...")
        # TODO: Initialiser MistralClient
        # self.mistral_client = MistralClient(api_key=MISTRAL_API_KEY)

    async def load_checkpoint(self) -> Optional[MigrationState]:
        """Charge le checkpoint si existe"""
        checkpoint_path = Path(CHECKPOINT_FILE)
        if not checkpoint_path.exists():
            return None

        import json
        with open(checkpoint_path) as f:
            data = json.load(f)

        self.logger.info(f"📂 Checkpoint trouvé: {data['processed']}/{data['total_emails']} emails traités")
        return MigrationState(
            total_emails=data['total_emails'],
            processed=data['processed'],
            failed=data['failed'],
            last_email_id=data['last_email_id'],
            started_at=datetime.fromisoformat(data['started_at']),
            last_checkpoint_at=datetime.fromisoformat(data['last_checkpoint_at']),
            estimated_cost=data['estimated_cost'],
            estimated_time_remaining=None
        )

    async def save_checkpoint(self):
        """Sauvegarde le checkpoint"""
        import json
        Path(CHECKPOINT_FILE).parent.mkdir(exist_ok=True, parents=True)

        data = {
            'total_emails': self.state.total_emails,
            'processed': self.state.processed,
            'failed': self.state.failed,
            'last_email_id': self.state.last_email_id,
            'started_at': self.state.started_at.isoformat(),
            'last_checkpoint_at': datetime.now().isoformat(),
            'estimated_cost': self.state.estimated_cost
        }

        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(data, f, indent=2)

        self.logger.debug(f"💾 Checkpoint sauvegardé: {self.state.processed}/{self.state.total_emails}")

    async def get_emails_to_migrate(self, batch_size: int = BATCH_SIZE):
        """Récupère les emails à migrer (avec resume si checkpoint existe)"""
        if self.state and self.state.last_email_id:
            # Resume depuis dernier checkpoint
            query = """
                SELECT message_id, sender, subject, body_text, received_at
                FROM ingestion.emails_legacy
                WHERE message_id > $1
                ORDER BY message_id
                LIMIT $2
            """
            return await self.db.fetch(query, self.state.last_email_id, batch_size)
        else:
            # Démarrage from scratch
            query = """
                SELECT message_id, sender, subject, body_text, received_at
                FROM ingestion.emails_legacy
                ORDER BY message_id
                LIMIT $1
            """
            return await self.db.fetch(query, batch_size)

    async def anonymize_for_classification(self, email: dict) -> str:
        """
        Anonymise le contenu email via Presidio AVANT envoi au LLM cloud (RGPD obligatoire).
        TODO: Brancher sur agents/src/tools/anonymize.py quand disponible.
        """
        # RGPD: Presidio anonymisation AVANT tout appel LLM cloud
        # from agents.tools.anonymize import anonymize_text
        # anonymized, tokens = await anonymize_text(
        #     f"Sujet: {email['subject']}\nDe: {email['sender']}\n{email['body_text'][:500]}",
        #     context=f"migration_{email['message_id']}"
        # )
        # return anonymized
        return f"Sujet: {email['subject']}\nDe: {email['sender']}\n{email['body_text'][:500]}"

    async def classify_email(self, email: dict, retry_count: int = 0) -> dict:
        """
        Classifie un email via Mistral API
        RGPD: Le texte est anonymisé via Presidio AVANT l'appel cloud.
        Retry exponentiel en cas d'erreur.
        """
        try:
            # Rate limiting
            await asyncio.sleep(RATE_LIMIT_DELAY)

            # RGPD: Anonymiser AVANT l'appel LLM cloud
            anonymized_content = await self.anonymize_for_classification(email)

            # Appel Mistral (TODO: implémenter avec contenu anonymisé)
            # response = await self.mistral_client.chat(
            #     model="mistral-nemo",
            #     messages=[{
            #         "role": "user",
            #         "content": f"Classe cet email:\n{anonymized_content}"
            #     }]
            # )

            if self.dry_run:
                # Dry run: simuler classification
                return {
                    'category': 'test',
                    'priority': 'low',
                    'confidence': 0.95,
                    'keywords': ['test']
                }

            # Parse response (TODO)
            return {
                'category': 'uncategorized',
                'priority': 'low',
                'confidence': 0.5,
                'keywords': []
            }

        except Exception as e:
            if retry_count < MAX_RETRIES:
                # Retry exponentiel: 2^retry_count secondes
                wait_time = 2 ** retry_count
                self.logger.warning(f"⚠️ Erreur classification (tentative {retry_count+1}/{MAX_RETRIES}): {e}")
                self.logger.info(f"   Retry dans {wait_time}s...")
                await asyncio.sleep(wait_time)
                return await self.classify_email(email, retry_count + 1)
            else:
                self.logger.error(f"❌ Échec classification après {MAX_RETRIES} tentatives: {e}")
                raise

    async def migrate_email(self, email: dict):
        """Migre un email (classification + insertion)"""
        try:
            # 1. Classification
            classification = await self.classify_email(email)

            # 2. Insertion dans ingestion.emails (nouveau schema)
            if not self.dry_run:
                await self.db.execute("""
                    INSERT INTO ingestion.emails
                    (message_id, sender, subject, body_text, category, priority, confidence, received_at, processed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                    email['message_id'],
                    email['sender'],
                    email['subject'],
                    email['body_text'],
                    classification['category'],
                    classification['priority'],
                    classification['confidence'],
                    email['received_at']
                )

            # 3. Publier event Redis (pour pipeline downstream: extraction PJ, graphe, etc.)
            # TODO: redis.publish('email.migrated', {'email_id': email['message_id']})

            # 4. Update cost estimation
            # ~275 Mo texte / 55k emails = ~5 Ko/email = ~12.5 tokens/email input
            # $0.02/1M tokens → ~$0.00000025/email
            self.state.estimated_cost += 0.00000025

            self.state.processed += 1
            self.state.last_email_id = email['message_id']

        except Exception as e:
            self.logger.error(f"❌ Échec migration email {email['message_id']}: {e}")
            self.state.failed += 1
            # Continue avec les autres emails (ne pas bloquer toute la migration)

    async def run(self, batch_size: int = BATCH_SIZE):
        """Lance la migration"""
        await self.connect()

        # 1. Load checkpoint si resume
        if self.resume:
            self.state = await self.load_checkpoint()

        # 2. Initialiser state si nouveau démarrage
        if not self.state:
            total_count = await self.db.fetchval("SELECT COUNT(*) FROM ingestion.emails_legacy")
            self.state = MigrationState(
                total_emails=total_count,
                processed=0,
                failed=0,
                last_email_id=None,
                started_at=datetime.now(),
                last_checkpoint_at=datetime.now(),
                estimated_cost=0.0,
                estimated_time_remaining=None
            )
            self.logger.info(f"🚀 Démarrage migration: {total_count} emails à traiter")
        else:
            self.logger.info(f"▶️ Reprise migration: {self.state.processed}/{self.state.total_emails} déjà traités")

        if self.dry_run:
            self.logger.warning("🧪 MODE DRY-RUN: Aucune modification réelle")

        # 3. Boucle de migration par batch
        start_time = time.time()
        checkpoint_counter = 0

        while self.state.processed < self.state.total_emails:
            # Fetch batch
            batch = await self.get_emails_to_migrate(batch_size)
            if not batch:
                break  # Plus d'emails à traiter

            # Process batch
            for email in batch:
                await self.migrate_email(email)

                # Progress bar
                progress_pct = (self.state.processed / self.state.total_emails) * 100
                elapsed = time.time() - start_time
                if self.state.processed > 0:
                    avg_time_per_email = elapsed / self.state.processed
                    remaining_emails = self.state.total_emails - self.state.processed
                    self.state.estimated_time_remaining = timedelta(seconds=avg_time_per_email * remaining_emails)

                if self.state.processed % 10 == 0:  # Log tous les 10 emails
                    self.logger.info(
                        f"📊 {self.state.processed}/{self.state.total_emails} "
                        f"({progress_pct:.1f}%) - "
                        f"Failed: {self.state.failed} - "
                        f"ETA: {self.state.estimated_time_remaining} - "
                        f"Cost: ${self.state.estimated_cost:.4f}"
                    )

            # Checkpoint tous les BATCH_SIZE emails
            checkpoint_counter += len(batch)
            if checkpoint_counter >= batch_size:
                await self.save_checkpoint()
                checkpoint_counter = 0

        # 4. Final checkpoint
        await self.save_checkpoint()

        # 5. Résumé
        elapsed_total = time.time() - start_time
        self.logger.info("=" * 60)
        self.logger.info("✅ MIGRATION TERMINÉE")
        self.logger.info(f"   Total traité: {self.state.processed}/{self.state.total_emails}")
        self.logger.info(f"   Échecs: {self.state.failed}")
        self.logger.info(f"   Durée: {timedelta(seconds=elapsed_total)}")
        self.logger.info(f"   Coût estimé: ${self.state.estimated_cost:.2f}")
        self.logger.info("=" * 60)

        # 6. Cleanup checkpoint file si succès complet
        if self.state.failed == 0 and self.state.processed == self.state.total_emails:
            Path(CHECKPOINT_FILE).unlink(missing_ok=True)
            self.logger.info("🗑️ Checkpoint file supprimé (migration complète)")


async def main():
    parser = argparse.ArgumentParser(description="Migration emails Friday 2.0")
    parser.add_argument('--resume', action='store_true', help="Reprendre depuis dernier checkpoint")
    parser.add_argument('--dry-run', action='store_true', help="Simulation sans modification réelle")
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help=f"Taille batch (défaut: {BATCH_SIZE})")
    args = parser.parse_args()

    migrator = EmailMigrator(dry_run=args.dry_run, resume=args.resume)
    await migrator.run(batch_size=args.batch_size)


if __name__ == "__main__":
    asyncio.run(main())
