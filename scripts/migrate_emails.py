#!/usr/bin/env python3
"""
Migration des 110 000 emails existants vers Friday 2.0
Stratégie: Checkpointing + Retry + Resume + Progress tracking

Usage:
    python scripts/migrate_emails.py [--resume] [--dry-run] [--batch-size 100]

Prérequis:
- Table `ingestion.emails_legacy` doit exister (migration dédiée à créer avant exécution).
  Cette table contient les 110k emails importés depuis les 4 comptes via EmailEngine bulk export.
  Migration suggérée: `012_ingestion_emails_legacy.sql` (à créer dans Story 2).
- Répertoire `data/` doit exister (créé automatiquement si absent):
  - data/checkpoints/ : fichiers checkpoint JSON
  - data/logs/ : logs migration

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
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

# Configuration (chargée depuis variables d'environnement - jamais hardcodé)
# Pas de valeurs par défaut pour les secrets (age/SOPS pour secrets, voir architecture)
POSTGRES_DSN = os.getenv("POSTGRES_DSN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
if not POSTGRES_DSN or not MISTRAL_API_KEY:
    raise EnvironmentError(
        "POSTGRES_DSN et MISTRAL_API_KEY doivent etre definis via variable d'environnement ou .env "
        "(utiliser age/SOPS pour les secrets, jamais de credentials en clair)"
    )
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
    def __init__(self, dry_run: bool = False, resume: bool = False, batch_size: int = BATCH_SIZE, rate_limit_rpm: int = RATE_LIMIT_RPM):
        self.dry_run = dry_run
        self.resume = resume
        self.batch_size = batch_size
        self.rate_limit_rpm = rate_limit_rpm
        self.rate_limit_delay = 60 / rate_limit_rpm
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

        with open(checkpoint_path) as f:
            data = json.load(f)

        self.logger.info("Checkpoint trouve: %d/%d emails traites", data['processed'], data['total_emails'])
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

    async def save_checkpoint(self) -> None:
        """Sauvegarde le checkpoint (atomic write pour eviter corruption)"""
        checkpoint_dir = Path(CHECKPOINT_FILE).parent
        checkpoint_dir.mkdir(exist_ok=True, parents=True)

        data = {
            'total_emails': self.state.total_emails,
            'processed': self.state.processed,
            'failed': self.state.failed,
            'last_email_id': self.state.last_email_id,
            'started_at': self.state.started_at.isoformat(),
            'last_checkpoint_at': datetime.now().isoformat(),
            'estimated_cost': self.state.estimated_cost
        }

        # Atomic write: temp file + rename pour eviter corruption si crash mid-write
        fd, tmp_path = tempfile.mkstemp(dir=str(checkpoint_dir), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
            Path(tmp_path).replace(CHECKPOINT_FILE)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        self.logger.debug(
            "Checkpoint sauvegarde: %d/%d",
            self.state.processed, self.state.total_emails
        )

    async def get_emails_to_migrate(self, batch_size: int = BATCH_SIZE) -> list[dict]:
        """Recupere les emails a migrer (avec resume si checkpoint existe)"""
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

        IMPORTANT: Cette fonction DOIT anonymiser les PII avant tout appel LLM cloud.
        En dry-run, retourne le texte brut (pas d'appel cloud).
        En mode reel, REFUSE d'envoyer du PII non-anonymise.
        """
        raw_text = f"Sujet: {email['subject']}\nDe: {email['sender']}\n{email['body_text'][:500]}"

        if self.dry_run:
            return raw_text

        # TODO(Story 1.5): Brancher sur agents/src/tools/anonymize.py
        # from agents.src.tools.anonymize import anonymize_text
        # anonymized, mapping = await anonymize_text(raw_text, context=f"migration_{email['message_id']}")
        # return anonymized

        # RGPD: JAMAIS envoyer de PII au cloud sans anonymisation
        raise NotImplementedError(
            "Presidio anonymization non implementee. "
            "RGPD interdit l'envoi de PII au LLM cloud sans anonymisation. "
            "Implementer agents/src/tools/anonymize.py (Story 1.5) avant d'utiliser ce script en mode reel."
        )

    async def classify_email(self, email: dict, retry_count: int = 0) -> dict:
        """
        Classifie un email via Mistral API
        RGPD: Le texte est anonymisé via Presidio AVANT l'appel cloud.
        Retry exponentiel en cas d'erreur.
        """
        try:
            # Rate limiting
            await asyncio.sleep(self.rate_limit_delay)

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
                self.logger.warning("Erreur classification (tentative %d/%d): %s", retry_count + 1, MAX_RETRIES, e)
                self.logger.info("Retry dans %ds...", wait_time)
                await asyncio.sleep(wait_time)
                return await self.classify_email(email, retry_count + 1)
            else:
                self.logger.error("Echec classification apres %d tentatives: %s", MAX_RETRIES, e)
                raise

    async def migrate_email(self, email: dict) -> None:
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
            # ~550 Mo texte / 110k emails = ~5 Ko/email = ~12.5 tokens/email input
            # $0.30/1M tokens → ~$0.0000003/email (Mistral Nemo input+output)
            self.state.estimated_cost += 0.0000003

            self.state.processed += 1
            self.state.last_email_id = email['message_id']

        except Exception as e:
            self.logger.error("Echec migration email %s: %s", email['message_id'], e)
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
            self.logger.info("Demarrage migration: %d emails a traiter", total_count)
        else:
            self.logger.info("Reprise migration: %d/%d deja traites", self.state.processed, self.state.total_emails)

        if self.dry_run:
            self.logger.warning("MODE DRY-RUN: Aucune modification reelle")

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

                # Progress bar (guard division par zero si table legacy vide)
                elapsed = time.time() - start_time
                if self.state.total_emails > 0:
                    progress_pct = (self.state.processed / self.state.total_emails) * 100
                else:
                    progress_pct = 100.0

                if self.state.processed > 0:
                    avg_time_per_email = elapsed / self.state.processed
                    remaining_emails = self.state.total_emails - self.state.processed
                    self.state.estimated_time_remaining = timedelta(seconds=avg_time_per_email * remaining_emails)

                if self.state.processed % 10 == 0:  # Log tous les 10 emails
                    self.logger.info(
                        "Progress: %d/%d (%.1f%%) - Failed: %d - ETA: %s - Cost: $%.4f",
                        self.state.processed, self.state.total_emails,
                        progress_pct, self.state.failed,
                        self.state.estimated_time_remaining, self.state.estimated_cost
                    )

            # Checkpoint tous les batch_size emails
            checkpoint_counter += len(batch)
            if checkpoint_counter >= self.batch_size:
                await self.save_checkpoint()
                checkpoint_counter = 0

        # 4. Final checkpoint
        await self.save_checkpoint()

        # 5. Résumé
        elapsed_total = time.time() - start_time
        self.logger.info("=" * 60)
        self.logger.info("MIGRATION TERMINEE")
        self.logger.info("Total traite: %d/%d", self.state.processed, self.state.total_emails)
        self.logger.info("Echecs: %d", self.state.failed)
        self.logger.info("Duree: %s", timedelta(seconds=elapsed_total))
        self.logger.info("Cout estime: $%.2f", self.state.estimated_cost)
        self.logger.info("=" * 60)

        # 6. Cleanup checkpoint file si succes complet
        if self.state.failed == 0 and self.state.processed == self.state.total_emails:
            Path(CHECKPOINT_FILE).unlink(missing_ok=True)
            self.logger.info("Checkpoint file supprime (migration complete)")


async def main():
    parser = argparse.ArgumentParser(description="Migration emails Friday 2.0")
    parser.add_argument('--resume', action='store_true', help="Reprendre depuis dernier checkpoint")
    parser.add_argument('--dry-run', action='store_true', help="Simulation sans modification réelle")
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help=f"Taille batch (défaut: {BATCH_SIZE})")
    parser.add_argument('--rate-limit', type=int, default=RATE_LIMIT_RPM, help=f"Rate limit Mistral API en req/min (défaut: {RATE_LIMIT_RPM}). Varie selon tier: gratuit=20, pay-as-you-go=60, enterprise=custom")
    args = parser.parse_args()

    migrator = EmailMigrator(
        dry_run=args.dry_run,
        resume=args.resume,
        batch_size=args.batch_size,
        rate_limit_rpm=args.rate_limit
    )
    await migrator.run(batch_size=args.batch_size)


if __name__ == "__main__":
    asyncio.run(main())
