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
- Rate limiting API Anthropic respecté (configurable req/min)
- Logs détaillés dans logs/migration.log
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import asyncpg

# Add agents/src to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "src"))

# Import Presidio anonymization (Story 6.4 Subtask 2.1)
from tools.anonymize import anonymize_text, AnonymizationResult

# Import Claude LLM adapter (Story 6.4 Subtask 2.2)
from adapters.llm import ClaudeAdapter, LLMResponse

# Configuration (chargée depuis variables d'environnement - jamais hardcodé)
# Pas de valeurs par défaut pour les secrets (age/SOPS pour secrets, voir architecture)
POSTGRES_DSN = os.getenv("POSTGRES_DSN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Validation
if not POSTGRES_DSN or not ANTHROPIC_API_KEY:
    raise EnvironmentError(
        "POSTGRES_DSN et ANTHROPIC_API_KEY doivent etre definis via variable d'environnement "
        "ou .env (utiliser age/SOPS pour les secrets, jamais de credentials en clair)"
    )

# Valider format POSTGRES_DSN

DSN_PATTERN = r"^postgresql://[^@]+@[^/]+/[^?]+(\?.*)?$"
if not re.match(DSN_PATTERN, POSTGRES_DSN):
    raise EnvironmentError(
        f"POSTGRES_DSN invalide: {POSTGRES_DSN}\n"
        f"Format attendu: postgresql://user:password@host:port/database"
    )
CHECKPOINT_FILE = "data/migration_checkpoint.json"
LOG_FILE = "logs/migration.log"
BATCH_SIZE = 100  # Emails par batch
MAX_RETRIES = 3
RATE_LIMIT_RPM = 50  # Anthropic rate limit (requests per minute) - tier 1
RATE_LIMIT_DELAY = 60 / RATE_LIMIT_RPM  # Délai entre requêtes


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
    def __init__(
        self,
        dry_run: bool = False,
        resume: bool = False,
        batch_size: int = BATCH_SIZE,
        rate_limit_rpm: int = RATE_LIMIT_RPM,
    ):
        self.dry_run = dry_run
        self.resume = resume
        self.batch_size = batch_size
        self.rate_limit_rpm = rate_limit_rpm
        self.rate_limit_delay = 60 / rate_limit_rpm
        self.db = None
        self.llm_client = None
        self.state: Optional[MigrationState] = None
        self.logger = self._setup_logging()

    def _setup_logging(self):
        """Configure logging"""
        Path("logs").mkdir(exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
        )
        return logging.getLogger(__name__)

    async def connect(self):
        """Connexion PostgreSQL + Claude Sonnet 4.5"""
        self.logger.info("Connexion à PostgreSQL...")
        self.db = await asyncpg.connect(POSTGRES_DSN)

        self.logger.info("Connexion à Claude Sonnet 4.5 (Anthropic API)...")
        # Story 6.4 Subtask 2.2: Initialiser ClaudeAdapter
        self.llm_client = ClaudeAdapter(
            api_key=ANTHROPIC_API_KEY,
            model="claude-sonnet-4-5-20250929",
            anonymize_by_default=False  # Déjà anonymisé par anonymize_for_classification()
        )

    async def load_checkpoint(self) -> Optional[MigrationState]:
        """Charge le checkpoint si existe"""
        checkpoint_path = Path(CHECKPOINT_FILE)
        if not checkpoint_path.exists():
            return None

        with open(checkpoint_path) as f:
            data = json.load(f)

        self.logger.info(
            "Checkpoint trouve: %d/%d emails traites", data["processed"], data["total_emails"]
        )
        return MigrationState(
            total_emails=data["total_emails"],
            processed=data["processed"],
            failed=data["failed"],
            last_email_id=data["last_email_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            last_checkpoint_at=datetime.fromisoformat(data["last_checkpoint_at"]),
            estimated_cost=data["estimated_cost"],
            estimated_time_remaining=None,
        )

    async def save_checkpoint(self) -> None:
        """Sauvegarde le checkpoint (atomic write pour eviter corruption)"""
        checkpoint_dir = Path(CHECKPOINT_FILE).parent
        checkpoint_dir.mkdir(exist_ok=True, parents=True)

        data = {
            "total_emails": self.state.total_emails,
            "processed": self.state.processed,
            "failed": self.state.failed,
            "last_email_id": self.state.last_email_id,
            "started_at": self.state.started_at.isoformat(),
            "last_checkpoint_at": datetime.now().isoformat(),
            "estimated_cost": self.state.estimated_cost,
        }

        # Atomic write: temp file + rename pour eviter corruption si crash mid-write
        fd, tmp_path = tempfile.mkstemp(dir=str(checkpoint_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            Path(tmp_path).replace(CHECKPOINT_FILE)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        self.logger.debug(
            "Checkpoint sauvegarde: %d/%d", self.state.processed, self.state.total_emails
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

        # RGPD: Anonymisation Presidio OBLIGATOIRE (Story 6.4 Subtask 2.1)
        try:
            result: AnonymizationResult = await anonymize_text(
                raw_text,
                context=f"migration_email_{email['message_id']}"
            )

            # Log anonymisation (structlog serait mieux mais logging suffit pour migration)
            self.logger.info(
                f"Email {email['message_id']}: {len(result.entities_found)} entités PII détectées "
                f"(confidence min: {result.confidence_min:.2f})"
            )

            # TODO: Stocker mapping dans Redis (TTL 24h) si besoin de dé-anonymisation
            # Pour migration batch, le mapping n'est pas utilisé après classification
            # donc on ne le stocke pas pour économiser RAM Redis

            return result.anonymized_text

        except Exception as e:
            self.logger.error(
                f"Erreur anonymisation Presidio pour email {email['message_id']}: {e}"
            )
            raise

    async def classify_email(self, email: dict, retry_count: int = 0) -> dict:
        """
        Classifie un email via Claude Sonnet 4.5 (Anthropic API)
        RGPD: Le texte est anonymisé via Presidio AVANT l'appel cloud.
        Retry exponentiel en cas d'erreur.
        """
        try:
            # Rate limiting
            await asyncio.sleep(self.rate_limit_delay)

            # RGPD: Anonymiser AVANT l'appel LLM cloud
            anonymized_content = await self.anonymize_for_classification(email)

            if self.dry_run:
                # Dry run: simuler classification
                return {
                    "category": "test",
                    "priority": "low",
                    "confidence": 0.95,
                    "keywords": ["test"],
                }

            # Appel Claude Sonnet 4.5 (texte déjà anonymisé → complete_raw)
            prompt = f"""Classifie cet email en JSON strict.

Email:
{anonymized_content}

Réponds UNIQUEMENT en JSON (pas de markdown, pas de texte supplémentaire):
{{
  "category": "medical|financial|administrative|professional|personal",
  "priority": "urgent|high|medium|low",
  "confidence": 0.0-1.0,
  "keywords": ["mot1", "mot2"]
}}"""

            response = await self.llm_client.complete_raw(
                prompt=prompt, max_tokens=512  # Classification courte
            )

            # Parser la réponse JSON
            classification = self._parse_classification(response.content)

            # Tracker usage API pour coûts réels
            self._track_api_usage(response.usage)

            return classification

        except Exception as e:
            if retry_count < MAX_RETRIES:
                # Retry exponentiel: 2^retry_count secondes
                wait_time = 2**retry_count
                self.logger.warning(
                    "Erreur classification (tentative %d/%d): %s", retry_count + 1, MAX_RETRIES, e
                )
                self.logger.info("Retry dans %ds...", wait_time)
                await asyncio.sleep(wait_time)
                return await self.classify_email(email, retry_count + 1)
            else:
                self.logger.error("Echec classification apres %d tentatives: %s", MAX_RETRIES, e)
                raise

    def _parse_classification(self, response_content: str) -> dict:
        """
        Parse la réponse JSON de Claude.

        Args:
            response_content: Réponse texte brute de Claude

        Returns:
            dict avec category, priority, confidence, keywords

        Raises:
            ValueError: Si parsing JSON échoue ou format invalide
        """
        try:
            # Nettoyer markdown potentiel (```json ... ```)
            content = response_content.strip()
            if content.startswith("```"):
                # Extraire JSON entre ```json et ```
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
                if match:
                    content = match.group(1)
                else:
                    # Fallback: enlever juste les balises
                    content = re.sub(r"```(?:json)?", "", content).strip()

            # Parser JSON
            data = json.loads(content)

            # Valider structure
            required_fields = {"category", "priority", "confidence", "keywords"}
            if not required_fields.issubset(data.keys()):
                missing = required_fields - data.keys()
                raise ValueError(f"Champs manquants dans la réponse: {missing}")

            # Valider types
            if not isinstance(data["confidence"], (int, float)):
                raise ValueError(f"confidence doit être numérique, reçu: {type(data['confidence'])}")
            if not isinstance(data["keywords"], list):
                raise ValueError(f"keywords doit être une liste, reçu: {type(data['keywords'])}")

            # Normaliser confidence (0.0-1.0)
            data["confidence"] = float(data["confidence"])
            if not 0.0 <= data["confidence"] <= 1.0:
                self.logger.warning(
                    "Confidence hors limites (%s), normalisée à [0,1]", data["confidence"]
                )
                data["confidence"] = max(0.0, min(1.0, data["confidence"]))

            return data

        except json.JSONDecodeError as e:
            self.logger.error("Erreur parsing JSON: %s\nContenu: %s", e, response_content[:200])
            raise ValueError(f"Réponse Claude invalide (pas JSON): {e}") from e
        except Exception as e:
            self.logger.error("Erreur validation classification: %s", e)
            raise

    def _track_api_usage(self, usage: dict) -> None:
        """
        Track l'usage API réel pour calcul coûts précis.

        Args:
            usage: dict avec input_tokens et output_tokens de LLMResponse

        Claude Sonnet 4.5 pricing (au 2026-02):
            - Input: $3.00 / 1M tokens
            - Output: $15.00 / 1M tokens
        """
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # Calcul coût réel (en USD)
        input_cost = (input_tokens / 1_000_000) * 3.00
        output_cost = (output_tokens / 1_000_000) * 15.00
        total_cost = input_cost + output_cost

        # Mise à jour état (remplace l'estimation fixe 0.003)
        self.state.estimated_cost += total_cost

        # Log tous les 1000 emails pour monitoring
        if self.state.processed % 1000 == 0:
            self.logger.info(
                "API usage: %d input tokens (%.4f$) + %d output tokens (%.4f$) = %.4f$ total",
                input_tokens,
                input_cost,
                output_tokens,
                output_cost,
                total_cost,
            )

    async def migrate_email(self, email: dict) -> None:
        """Migre un email (classification + insertion)"""
        try:
            # 1. Classification
            classification = await self.classify_email(email)

            # 2. Insertion dans ingestion.emails (nouveau schema)
            if not self.dry_run:
                await self.db.execute(
                    """
                    INSERT INTO ingestion.emails
                    (message_id, sender, subject, body_text, category, priority,
                     confidence, received_at, processed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                    email["message_id"],
                    email["sender"],
                    email["subject"],
                    email["body_text"],
                    classification["category"],
                    classification["priority"],
                    classification["confidence"],
                    email["received_at"],
                )

            # 3. Publier event Redis (pour pipeline downstream: extraction PJ, graphe, etc.)
            # TODO: redis.publish('email.migrated', {'email_id': email['message_id']})

            # 4. Le coût API est tracké automatiquement dans classify_email()
            # via _track_api_usage() avec les tokens réels

            self.state.processed += 1
            self.state.last_email_id = email["message_id"]

        except Exception as e:
            self.logger.error("Echec migration email %s: %s", email["message_id"], e)
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
                estimated_time_remaining=None,
            )
            self.logger.info("Demarrage migration: %d emails a traiter", total_count)
        else:
            self.logger.info(
                "Reprise migration: %d/%d deja traites",
                self.state.processed,
                self.state.total_emails,
            )

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
                    self.state.estimated_time_remaining = timedelta(
                        seconds=avg_time_per_email * remaining_emails
                    )

                if self.state.processed % 10 == 0:  # Log tous les 10 emails
                    self.logger.info(
                        "Progress: %d/%d (%.1f%%) - Failed: %d - ETA: %s - Cost: $%.4f",
                        self.state.processed,
                        self.state.total_emails,
                        progress_pct,
                        self.state.failed,
                        self.state.estimated_time_remaining,
                        self.state.estimated_cost,
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
    parser.add_argument("--resume", action="store_true", help="Reprendre depuis dernier checkpoint")
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulation sans modification réelle"
    )
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE, help=f"Taille batch (défaut: {BATCH_SIZE})"
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=RATE_LIMIT_RPM,
        help=(
            f"Rate limit Anthropic API en req/min (défaut: {RATE_LIMIT_RPM}). "
            "Ajuster selon tier Anthropic"
        ),
    )
    args = parser.parse_args()

    migrator = EmailMigrator(
        dry_run=args.dry_run,
        resume=args.resume,
        batch_size=args.batch_size,
        rate_limit_rpm=args.rate_limit,
    )
    await migrator.run(batch_size=args.batch_size)


if __name__ == "__main__":
    asyncio.run(main())
