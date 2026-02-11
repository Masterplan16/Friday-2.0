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
import redis.asyncio as redis

# Add agents/src to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "agents" / "src"))

# Import Presidio anonymization (Story 6.4 Subtask 2.1)
from tools.anonymize import anonymize_text, AnonymizationResult

# Import Claude LLM adapter (Story 6.4 Subtask 2.2)
from adapters.llm import ClaudeAdapter, LLMResponse

# Import MemoryStore pour Phase 2 graphe (Story 6.4 Task 3)
from adapters.memorystore_interface import MemoryStore, NodeType, RelationType

# Import VectorStore pour Phase 3 embeddings (Story 6.4 Task 4)
from adapters.vectorstore import VectorStoreAdapter

# Configuration (chargée depuis variables d'environnement - jamais hardcodé)
# Pas de valeurs par défaut pour les secrets (age/SOPS pour secrets, voir architecture)
POSTGRES_DSN = os.getenv("POSTGRES_DSN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

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


class EmailGraphPopulator:
    """
    Population du graphe de connaissances pour un email (Phase 2).

    Crée les nodes (Person, Email) et edges (SENT_BY, RECEIVED_BY) dans knowledge.*.
    """

    def __init__(self, memorystore: MemoryStore, dry_run: bool = False):
        """
        Args:
            memorystore: Adaptateur memorystore (PostgreSQL + pgvector Day 1)
            dry_run: Si True, simule les opérations sans modification BDD
        """
        self.memorystore = memorystore
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)

    async def populate_email(self, email: dict, classification: dict) -> dict:
        """
        Crée nodes + edges pour un email dans le graphe.

        Args:
            email: Email dict avec message_id, sender, recipients, subject, received_at
            classification: Classification dict avec category, priority, confidence

        Returns:
            dict avec {sender_node_id, email_node_id, edges_created, recipients_count}

        Raises:
            Exception: Si échec création nodes/edges
        """
        try:
            if self.dry_run:
                # Dry run: simuler sans modifier BDD
                return {
                    "sender_node_id": "dry-run-sender",
                    "email_node_id": "dry-run-email",
                    "edges_created": 1 + len(email.get("recipients", [])),
                    "recipients_count": len(email.get("recipients", [])),
                }

            # 1. Créer Person node pour sender (ou récupérer si existe)
            sender_node_id = await self.memorystore.get_or_create_node(
                node_type=NodeType.PERSON.value,
                name=email["sender"],
                metadata={"email": email["sender"]},
            )

            self.logger.debug("Sender node créé/récupéré: %s", sender_node_id)

            # 2. Créer Email node (toujours nouveau)
            email_node_id = await self.memorystore.create_node(
                node_type=NodeType.EMAIL.value,
                name=email["subject"] or "(Sans objet)",
                metadata={
                    "message_id": email["message_id"],
                    "subject": email["subject"],
                    "sender": email["sender"],
                    "category": classification["category"],
                    "priority": classification["priority"],
                    "confidence": classification["confidence"],
                    "received_at": email["received_at"].isoformat()
                    if isinstance(email["received_at"], datetime)
                    else str(email["received_at"]),
                },
            )

            self.logger.debug("Email node créé: %s", email_node_id)

            # 3. Créer edge SENT_BY (email → sender)
            await self.memorystore.create_edge(
                from_node_id=email_node_id,
                to_node_id=sender_node_id,
                relation_type=RelationType.SENT_BY.value,
                metadata={
                    "timestamp": email["received_at"].isoformat()
                    if isinstance(email["received_at"], datetime)
                    else str(email["received_at"])
                },
            )

            edges_created = 1  # SENT_BY edge

            # 4. Créer Person nodes pour recipients + edges RECEIVED_BY
            recipients = email.get("recipients", [])
            if recipients:
                for recipient in recipients:
                    recipient_node_id = await self.memorystore.get_or_create_node(
                        node_type=NodeType.PERSON.value,
                        name=recipient,
                        metadata={"email": recipient},
                    )

                    await self.memorystore.create_edge(
                        from_node_id=email_node_id,
                        to_node_id=recipient_node_id,
                        relation_type=RelationType.RECEIVED_BY.value,
                        metadata={
                            "timestamp": email["received_at"].isoformat()
                            if isinstance(email["received_at"], datetime)
                            else str(email["received_at"])
                        },
                    )

                    edges_created += 1

            self.logger.info(
                "Graphe populé pour email %s: 1 email node, %d person nodes, %d edges",
                email["message_id"],
                1 + len(recipients),  # sender + recipients
                edges_created,
            )

            return {
                "sender_node_id": sender_node_id,
                "email_node_id": email_node_id,
                "edges_created": edges_created,
                "recipients_count": len(recipients),
            }

        except Exception as e:
            self.logger.error("Echec population graphe pour email %s: %s", email["message_id"], e)
            raise


class EmailEmbeddingGenerator:
    """
    Génération embeddings pour emails (Phase 3).

    Génère embeddings via Voyage AI et stocke dans knowledge.embeddings (pgvector).
    """

    def __init__(self, vectorstore: VectorStoreAdapter, dry_run: bool = False):
        """
        Args:
            vectorstore: Adaptateur vectorstore (Voyage AI + pgvector)
            dry_run: Si True, simule les opérations sans appel API
        """
        self.vectorstore = vectorstore
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)

    async def generate_embedding(self, email: dict, email_node_id: str) -> str:
        """
        Génère embedding pour un email et le stocke dans pgvector.

        Args:
            email: Email dict avec message_id, subject, body_text
            email_node_id: ID du node Email dans knowledge.nodes (créé en Phase 2)

        Returns:
            email_node_id (même ID, car embedding lié au node)

        Raises:
            Exception: Si échec génération ou stockage embedding
        """
        try:
            if self.dry_run:
                # Dry run: simuler sans appel API
                return email_node_id

            # 1. Construire texte à embedder (sujet + corps limité à 2000 chars)
            subject = email.get("subject") or ""
            body_text = email.get("body_text") or ""
            text = f"{subject}\n{body_text[:2000]}"  # Limiter pour coût API

            if not text.strip():
                self.logger.warning("Email %s vide, skip embedding", email["message_id"])
                return email_node_id

            # 2. Anonymiser texte AVANT Voyage AI (RGPD)
            anonymized_result = await anonymize_text(
                text, context=f"embed_{email['message_id']}"
            )
            anonymized_text = anonymized_result.anonymized_text

            self.logger.debug(
                "Email %s anonymisé: %d entités PII (confidence min: %.2f)",
                email["message_id"],
                len(anonymized_result.entities_found),
                anonymized_result.confidence_min,
            )

            # 3. Générer embedding via Voyage AI (texte déjà anonymisé)
            embedding_response = await self.vectorstore.embed(
                [anonymized_text], anonymize=False  # Déjà anonymisé
            )
            embedding = embedding_response.embeddings[0]

            # 4. Stocker embedding dans knowledge.embeddings (pgvector)
            await self.vectorstore.store(
                node_id=email_node_id,
                embedding=embedding,
                metadata={
                    "source": "migration_emails",
                    "message_id": email["message_id"],
                    "anonymized": True,
                    "tokens_used": embedding_response.tokens_used,
                },
            )

            self.logger.info(
                "Embedding généré pour email %s (node %s): %d dims, %d tokens",
                email["message_id"],
                email_node_id,
                embedding_response.dimensions,
                embedding_response.tokens_used,
            )

            return email_node_id

        except Exception as e:
            self.logger.error(
                "Echec génération embedding pour email %s: %s", email["message_id"], e
            )
            raise


class EmailMigrator:
    def __init__(
        self,
        dry_run: bool = False,
        resume: bool = False,
        batch_size: int = BATCH_SIZE,
        rate_limit_rpm: int = RATE_LIMIT_RPM,
        limit: Optional[int] = None,
    ):
        self.dry_run = dry_run
        self.resume = resume
        self.batch_size = batch_size
        self.rate_limit_rpm = rate_limit_rpm
        self.rate_limit_delay = 60 / rate_limit_rpm
        self.limit = limit  # Limiter à N emails (pour tests)
        self.db = None
        self.llm_client = None
        self.redis_client = None  # Redis pour mapping Presidio (AC3)
        self.memorystore = None  # Phase 2: graphe
        self.graph_populator = None  # Phase 2: EmailGraphPopulator
        self.vectorstore = None  # Phase 3: embeddings
        self.embedding_generator = None  # Phase 3: EmailEmbeddingGenerator
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
        """Connexion PostgreSQL + Claude Sonnet 4.5 + Redis + MemoryStore"""
        self.logger.info("Connexion à PostgreSQL...")
        self.db = await asyncpg.connect(POSTGRES_DSN)

        self.logger.info("Connexion à Redis (mapping Presidio)...")
        self.redis_client = await redis.from_url(REDIS_URL, decode_responses=True)

        self.logger.info("Connexion à Claude Sonnet 4.5 (Anthropic API)...")
        # Story 6.4 Subtask 2.2: Initialiser ClaudeAdapter
        self.llm_client = ClaudeAdapter(
            api_key=ANTHROPIC_API_KEY,
            model="claude-sonnet-4-5-20250929",
            anonymize_by_default=False  # Déjà anonymisé par anonymize_for_classification()
        )

        # Story 6.4 Task 3: Initialiser MemoryStore pour Phase 2 (graphe)
        self.logger.info("Initialisation MemoryStore (PostgreSQL + pgvector)...")
        # Créer pool pour memorystore (min 2 connexions, max 10)
        db_pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=2, max_size=10)

        from adapters.memorystore import PostgreSQLMemorystore

        self.memorystore = PostgreSQLMemorystore(db_pool)
        await self.memorystore.init_pgvector()  # Vérifier extension pgvector

        # Initialiser EmailGraphPopulator
        self.graph_populator = EmailGraphPopulator(self.memorystore, dry_run=self.dry_run)
        self.logger.info("EmailGraphPopulator initialisé")

        # Story 6.4 Task 4: Initialiser VectorStore pour Phase 3 (embeddings)
        self.logger.info("Initialisation VectorStore (Voyage AI + pgvector)...")

        from adapters.vectorstore import get_vectorstore_adapter

        self.vectorstore = await get_vectorstore_adapter()

        # Initialiser EmailEmbeddingGenerator
        self.embedding_generator = EmailEmbeddingGenerator(
            self.vectorstore, dry_run=self.dry_run
        )
        self.logger.info("EmailEmbeddingGenerator initialisé")

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
                SELECT message_id, sender, recipients, subject, body_text, received_at
                FROM ingestion.emails_legacy
                WHERE message_id > $1
                ORDER BY message_id
                LIMIT $2
            """
            return await self.db.fetch(query, self.state.last_email_id, batch_size)
        else:
            # Démarrage from scratch
            query = """
                SELECT message_id, sender, recipients, subject, body_text, received_at
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

            # FIX M1: Logging standard OK pour migration one-shot (Architecture préfère structlog,
            # mais acceptable ici : migration batch temporaire, pas service permanent)
            self.logger.info(
                f"Email {email['message_id']}: {len(result.entities_found)} entités PII détectées "
                f"(confidence min: {result.confidence_min:.2f})"
            )

            # FIX C3: Stocker mapping dans Redis (TTL 24h) pour conformité AC3
            if result.mapping:
                redis_key = f"presidio:mapping:migration:{email['message_id']}"
                await self.redis_client.setex(
                    redis_key,
                    86400,  # 24h TTL (AC3 requirement)
                    json.dumps(result.mapping)
                )
                self.logger.debug(
                    f"Mapping Presidio stocké dans Redis: {redis_key} (TTL 24h)"
                )

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

            # Tracker usage API pour coûts réels (async now pour DB insert)
            await self._track_api_usage(response.usage)

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

    async def _track_api_usage(self, usage: dict) -> None:
        """
        Track l'usage API réel pour calcul coûts précis + stockage BDD (AC2).

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

        # FIX H1: Stocker dans core.api_usage (AC2 requirement)
        if not self.dry_run:
            try:
                await self.db.execute(
                    """
                    INSERT INTO core.api_usage
                    (provider, service, model, tokens_input, tokens_output, cost_usd, context)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    "anthropic",
                    "classification",
                    "claude-sonnet-4-5-20250929",
                    input_tokens,
                    output_tokens,
                    total_cost,
                    "migration_emails"
                )
            except Exception as e:
                self.logger.warning("Erreur stockage api_usage: %s (non-bloquant)", e)

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

            # 3. Population graphe (Phase 2) - Story 6.4 Task 3
            graph_result = await self.graph_populator.populate_email(email, classification)
            self.logger.debug(
                "Graphe populé: email_node=%s, edges=%d, recipients=%d",
                graph_result["email_node_id"],
                graph_result["edges_created"],
                graph_result["recipients_count"],
            )

            # 4. Génération embedding (Phase 3) - Story 6.4 Task 4
            embedding_node_id = await self.embedding_generator.generate_embedding(
                email, email_node_id=graph_result["email_node_id"]
            )
            self.logger.debug("Embedding généré pour node %s", embedding_node_id)

            # 5. FIX H4: Publier event Redis (pour pipeline downstream: extraction PJ, archiviste, etc.)
            if not self.dry_run:
                try:
                    event_data = {
                        "message_id": email["message_id"],
                        "sender": email["sender"],
                        "category": classification["category"],
                        "priority": classification["priority"],
                        "email_node_id": graph_result["email_node_id"],
                        "migrated_at": datetime.now().isoformat()
                    }
                    # Utiliser Redis Streams (événement critique, pas Pub/Sub)
                    await self.redis_client.xadd(
                        "stream:email.migrated",
                        {"data": json.dumps(event_data)}
                    )
                    self.logger.debug("Event email.migrated publié: %s", email["message_id"])
                except Exception as e:
                    self.logger.warning("Erreur publish event Redis (non-bloquant): %s", e)

            # 6. Le coût API est tracké automatiquement dans classify_email()
            # via _track_api_usage() avec les tokens réels

            self.state.processed += 1
            self.state.last_email_id = email["message_id"]

        except Exception as e:
            self.logger.error("Echec migration email %s: %s", email["message_id"], e)
            self.state.failed += 1

            # FIX H3: Stocker email échoué dans DLQ (AC5 requirement)
            if not self.dry_run:
                try:
                    await self.db.execute(
                        """
                        INSERT INTO core.migration_failed
                        (message_id, error_message, retry_count, failed_at, context)
                        VALUES ($1, $2, $3, NOW(), $4)
                        ON CONFLICT (message_id) DO UPDATE SET
                            retry_count = core.migration_failed.retry_count + 1,
                            error_message = $2,
                            failed_at = NOW()
                        """,
                        email["message_id"],
                        str(e)[:500],  # Limiter longueur erreur
                        1,  # Premier échec (ou incrémenté si existe)
                        "migration_emails"
                    )
                except Exception as db_error:
                    self.logger.warning("Erreur DLQ (non-bloquant): %s", db_error)

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

            # Limiter si --limit spécifié
            if self.limit and self.limit < total_count:
                total_count = self.limit
                self.logger.info("LIMIT: Migration limitée à %d emails (--limit)", total_count)

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

        # FIX H2: Notification début migration (AC4 - topic Metrics)
        # TODO: Implémenter Telegram notification quand Story 1.9 sera déployée
        self.logger.info(
            "🚀 MIGRATION DÉMARRÉE - %d emails à traiter (budget estimé: $%.2f)",
            self.state.total_emails,
            self.state.total_emails * 0.003  # Estimation initiale
        )

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

        # 5. Résumé + notification finale (AC4)
        elapsed_total = time.time() - start_time
        success_rate = ((self.state.processed - self.state.failed) / self.state.processed * 100) if self.state.processed > 0 else 0

        self.logger.info("=" * 60)
        self.logger.info("✅ MIGRATION TERMINEE")
        self.logger.info("Total traite: %d/%d", self.state.processed, self.state.total_emails)
        self.logger.info("Echecs: %d (%.1f%%)", self.state.failed, 100 - success_rate)
        self.logger.info("Duree: %s", timedelta(seconds=elapsed_total))
        self.logger.info("Cout reel: $%.2f", self.state.estimated_cost)
        self.logger.info("=" * 60)

        # FIX H2: Notification fin migration (AC4 - topic Metrics ou System si échec >1%)
        # TODO: Implémenter Telegram notification quand Story 1.9 sera déployée
        if self.state.failed / self.state.processed > 0.01:
            self.logger.warning(
                "⚠️ ALERTE: Taux d'échec >1%% (%d/%d) - Vérifier logs et DLQ",
                self.state.failed,
                self.state.processed
            )

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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limiter à N emails (pour tests). Par défaut: tous les emails",
    )
    args = parser.parse_args()

    migrator = EmailMigrator(
        dry_run=args.dry_run,
        resume=args.resume,
        batch_size=args.batch_size,
        rate_limit_rpm=args.rate_limit,
        limit=args.limit,
    )
    await migrator.run(batch_size=args.batch_size)


if __name__ == "__main__":
    asyncio.run(main())
