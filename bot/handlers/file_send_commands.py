"""
Handler Telegram pour envoi de fichiers via recherche sémantique (Story 3.6 Task 3).

Workflow :
1. Détection intention "envoyer fichier" via Claude Sonnet 4.5
2. Recherche sémantique pgvector + graphe de connaissances
3. Retrieve fichier depuis PC/VPS (Syncthing/Tailscale)
4. Envoi fichier Telegram (<20 Mo)
5. Notification confirmation topic "Email & Communications"

Exemples requêtes :
- "Envoie-moi la facture du plombier"
- "Je veux le contrat SELARL"
- "Donne-moi le dernier relevé bancaire SCI Ravas"
"""

import json
import os
from pathlib import Path
from typing import Optional

import asyncpg
import structlog
from agents.src.adapters.llm import ClaudeAdapter
from agents.src.adapters.vectorstore import get_vectorstore_adapter
from agents.src.tools.anonymize import presidio_anonymize
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import ContextTypes

logger = structlog.get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Telegram file size limit (20 MB)
MAX_FILE_SIZE_TELEGRAM = 20 * 1024 * 1024  # 20 Mo

# Storage paths (AC#3)
PC_ARCHIVES_ROOT = os.getenv("PC_ARCHIVES_ROOT", r"C:\Users\lopez\BeeStation\Friday\Archives")
VPS_ARCHIVES_MIRROR = os.getenv("VPS_ARCHIVES_MIRROR", "/var/friday/archives")

# Topics Telegram
TOPIC_EMAIL_COMMUNICATIONS = int(os.getenv("TOPIC_EMAIL_ID", "0"))

# Semantic search settings
SEARCH_TOP_K_DEFAULT = 3  # Top-3 résultats si exact match pas trouvé
SEARCH_SIMILARITY_THRESHOLD = 0.7  # Seuil similarité cosine (70%)

# Database URL (validé au chargement module, pas à chaque appel)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Connection pool (initialisé au premier appel)
_db_pool: Optional[asyncpg.Pool] = None


async def _get_db_pool() -> asyncpg.Pool:
    """Retourne un pool de connexions asyncpg (lazy init singleton)."""
    global _db_pool
    if _db_pool is None or _db_pool._closed:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL manquante")
        _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _db_pool


# ============================================================================
# Pydantic Models
# ============================================================================


class FileRequest(BaseModel):
    """Requête fichier détectée dans message utilisateur"""

    query: str = Field(..., description="Requête sémantique extraite")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiance intention")
    doc_type: Optional[str] = Field(
        None, description="Type document détecté (facture, contrat, etc.)"
    )
    keywords: list[str] = Field(default_factory=list, description="Mots-clés extraits")


class DocumentSearchResult(BaseModel):
    """Résultat recherche document"""

    document_id: str
    filename: str
    file_path: str
    doc_type: Optional[str]
    emitter: Optional[str]
    amount: float
    similarity: float
    category: Optional[str]
    subcategory: Optional[str]


# ============================================================================
# Intent Detection
# ============================================================================


async def detect_file_request_intent(text: str) -> Optional[FileRequest]:
    """
    Détecte si message utilisateur demande un fichier.

    Utilise Claude Sonnet 4.5 avec few-shot examples pour identifier
    les intentions "envoyer document".

    Args:
        text: Message utilisateur

    Returns:
        FileRequest si intention détectée, None sinon

    Raises:
        LLMError: Si appel Claude échoue
    """
    llm = ClaudeAdapter()

    # Prompt few-shot pour intent detection
    system_prompt = """Tu es un assistant spécialisé dans la détection d'intentions de demande de fichiers.

Analyse le message utilisateur et détermine s'il demande un fichier/document.

Exemples de requêtes positives :
- "Envoie-moi la facture du plombier" → INTENTION: envoyer fichier, QUERY: "facture plombier", TYPE: facture
- "Je veux le contrat SELARL" → INTENTION: envoyer fichier, QUERY: "contrat SELARL", TYPE: contrat
- "Donne-moi le dernier relevé bancaire SCI Ravas" → INTENTION: envoyer fichier, QUERY: "relevé bancaire SCI Ravas", TYPE: relevé
- "Où est mon certificat d'assurance" → INTENTION: envoyer fichier, QUERY: "certificat assurance", TYPE: certificat
- "Peux-tu me retrouver la garantie du frigo" → INTENTION: envoyer fichier, QUERY: "garantie frigo", TYPE: garantie

Exemples de requêtes négatives (pas de demande de fichier) :
- "Bonjour" → PAS D'INTENTION
- "Comment vas-tu ?" → PAS D'INTENTION
- "Combien j'ai payé le plombier ?" → PAS D'INTENTION (question info, pas demande fichier)
- "Résume-moi le contrat SELARL" → PAS D'INTENTION (demande résumé, pas fichier)

Réponds en JSON avec ce format :
{
    "has_intent": true/false,
    "query": "requête sémantique extraite" (si has_intent=true),
    "doc_type": "type document" (si détecté),
    "keywords": ["mot1", "mot2"],
    "confidence": 0.0-1.0
}"""

    prompt = f'Message utilisateur : "{text}"\n\nAnalyse l\'intention :'

    try:
        # Anonymiser texte utilisateur avant appel LLM cloud (RGPD CLAUDE.md)
        anonymized_prompt = await presidio_anonymize(prompt)

        response = await llm.complete_raw(
            prompt=anonymized_prompt,
            system=system_prompt,
            max_tokens=512,
        )

        result = json.loads(response.content)

        if not result.get("has_intent", False):
            logger.debug("no_file_intent_detected", text=text[:50])
            return None

        # Créer FileRequest
        file_request = FileRequest(
            query=result["query"],
            confidence=result["confidence"],
            doc_type=result.get("doc_type"),
            keywords=result.get("keywords", []),
        )

        logger.info(
            "file_intent_detected",
            query=file_request.query,
            confidence=file_request.confidence,
            doc_type=file_request.doc_type,
        )

        return file_request

    except json.JSONDecodeError as e:
        logger.error(
            "intent_json_parse_failed", error=str(e), response_content=response.content[:200]
        )
        return None

    except Exception as e:
        logger.error("intent_detection_failed", error=str(e), error_type=type(e).__name__)
        return None


# ============================================================================
# Semantic Search
# ============================================================================


async def search_documents_semantic(
    query: str,
    top_k: int = SEARCH_TOP_K_DEFAULT,
    doc_type: Optional[str] = None,
) -> list[DocumentSearchResult]:
    """
    Recherche sémantique documents via pgvector.

    Args:
        query: Requête sémantique utilisateur
        top_k: Nombre résultats (default 3)
        doc_type: Filtrer par type document (optionnel)

    Returns:
        Liste DocumentSearchResult triés par similarité DESC

    Raises:
        VectorStoreError: Si échec recherche
    """
    try:
        # 1. Générer embedding query via factory pattern (CLAUDE.md adaptateur obligatoire)
        vectorstore = await get_vectorstore_adapter()

        query_embedding = await vectorstore.embed_query(query)

        logger.info("query_embedding_generated", query=query[:50], dimensions=len(query_embedding))

        # 2. Rechercher dans pgvector
        filters = {}
        if doc_type:
            filters["doc_type"] = doc_type

        vector_results = await vectorstore.search(
            query_embedding=query_embedding,
            top_k=top_k * 2,  # Doubler pour filtrer après JOIN
            filters=filters,
        )

        logger.info("vector_search_completed", results_count=len(vector_results))

        # 3. JOIN avec ingestion.document_metadata pour récupérer file_path
        pool = await _get_db_pool()

        async with pool.acquire() as conn:
            results = []

            for vec_result in vector_results:
                row = await conn.fetchrow(
                    """
                    SELECT
                        dm.id,
                        dm.filename,
                        dm.file_path,
                        dm.doc_type,
                        dm.emitter,
                        dm.amount,
                        dm.classification_category,
                        dm.classification_subcategory
                    FROM ingestion.document_metadata dm
                    JOIN knowledge.embeddings e ON e.document_id = dm.id
                    WHERE e.node_id = $1
                    """,
                    vec_result.node_id,
                )

                if row:
                    results.append(
                        DocumentSearchResult(
                            document_id=str(row["id"]),
                            filename=row["filename"],
                            file_path=row["file_path"] or "",
                            doc_type=row["doc_type"],
                            emitter=row["emitter"],
                            amount=float(row["amount"]) if row["amount"] else 0.0,
                            similarity=vec_result.similarity,
                            category=row["classification_category"],
                            subcategory=row["classification_subcategory"],
                        )
                    )

                if len(results) >= top_k:
                    break

        await vectorstore.close()

        logger.info("document_search_completed", results_count=len(results))

        return results

    except Exception as e:
        logger.error("document_search_failed", error=str(e), error_type=type(e).__name__)
        raise


# ============================================================================
# File Retrieval
# ============================================================================


def resolve_file_path_vps(pc_path: str) -> Optional[Path]:
    """
    Résout chemin PC → chemin VPS via miroir Syncthing.

    Args:
        pc_path: Chemin PC (C:\\Users\\lopez\\BeeStation\\Friday\\Archives\\...)

    Returns:
        Path VPS si fichier existe, None sinon

    Note:
        TODO (Story 3.6 Task 3.4) : Implémenter mécanisme récupération
        fichier depuis PC via Tailscale/rsync si pas de miroir local.
    """
    if not pc_path.startswith(PC_ARCHIVES_ROOT):
        logger.warning("invalid_pc_path", path=pc_path)
        return None

    # Convertir chemin PC → chemin VPS
    # Ex: C:\\Users\\lopez\\BeeStation\\Friday\\Archives\\finance\\facture.pdf
    #  → /var/friday/archives/finance/facture.pdf
    relative_path = pc_path[len(PC_ARCHIVES_ROOT) :].lstrip("\\").replace("\\", "/")
    vps_path = Path(VPS_ARCHIVES_MIRROR) / relative_path

    if vps_path.exists():
        logger.info("file_found_on_vps", vps_path=str(vps_path))
        return vps_path

    logger.warning("file_not_found_on_vps", pc_path=pc_path, vps_path=str(vps_path))
    return None


# ============================================================================
# Main Handler
# ============================================================================


async def handle_file_send_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler principal pour requêtes envoi fichier.

    Workflow :
    1. Détection intention via Claude
    2. Recherche sémantique pgvector
    3. Retrieve fichier PC/VPS
    4. Envoi Telegram (<20 Mo)
    5. Notification confirmation

    Args:
        update: Update Telegram
        context: Context Telegram

    Note:
        Ce handler est appelé pour TOUS les messages texte.
        Il détecte l'intention et ne traite que les requêtes fichier.
    """
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # 1. Détection intention
    file_request = await detect_file_request_intent(text)

    if not file_request:
        # Pas d'intention détectée → pas de traitement
        return

    # 2. Notification traitement
    await update.message.reply_text(
        f"🔍 Recherche : {file_request.query}...", message_thread_id=TOPIC_EMAIL_COMMUNICATIONS
    )

    # 3. Recherche sémantique
    try:
        results = await search_documents_semantic(
            query=file_request.query, top_k=SEARCH_TOP_K_DEFAULT, doc_type=file_request.doc_type
        )

        if not results:
            # Aucun résultat trouvé
            await update.message.reply_text(
                f'❌ Aucun fichier trouvé pour : "{file_request.query}"\n\n'
                "Essayez avec d'autres mots-clés ou vérifiez si le document a été archivé.",
                message_thread_id=TOPIC_EMAIL_COMMUNICATIONS,
            )
            logger.warning("no_documents_found", query=file_request.query)
            return

        # 4. Vérifier si meilleur match a bonne similarité
        best_match = results[0]

        if best_match.similarity < SEARCH_SIMILARITY_THRESHOLD:
            # Similarité faible → proposer alternatives
            alternatives = "\n".join(
                [
                    f"• {r.filename} ({r.doc_type or 'document'}) - {r.similarity*100:.0f}%"
                    for r in results[:3]
                ]
            )

            await update.message.reply_text(
                f'🤔 Aucun résultat exact trouvé pour : "{file_request.query}"\n\n'
                f"Suggestions (similarité <{SEARCH_SIMILARITY_THRESHOLD*100:.0f}%) :\n{alternatives}",
                message_thread_id=TOPIC_EMAIL_COMMUNICATIONS,
            )
            logger.info(
                "low_similarity_results",
                query=file_request.query,
                best_similarity=best_match.similarity,
            )
            return

        # 5. Retrieve fichier
        vps_file_path = resolve_file_path_vps(best_match.file_path)

        if not vps_file_path:
            # Fichier pas accessible sur VPS
            await update.message.reply_text(
                f"✅ Fichier trouvé : {best_match.filename}\n"
                f"📁 Emplacement PC : {best_match.file_path}\n\n"
                f"⚠️ Le fichier n'est pas encore synchronisé sur le VPS.\n"
                f"Accédez-y directement depuis votre PC.",
                message_thread_id=TOPIC_EMAIL_COMMUNICATIONS,
            )
            logger.info(
                "file_found_but_not_synced",
                filename=best_match.filename,
                pc_path=best_match.file_path,
            )
            return

        # 6. Vérifier taille fichier
        file_size = vps_file_path.stat().st_size

        if file_size > MAX_FILE_SIZE_TELEGRAM:
            # Fichier trop gros pour Telegram
            await update.message.reply_text(
                f"✅ Fichier trouvé : {best_match.filename}\n"
                f"📁 Emplacement : {best_match.file_path}\n\n"
                f"❌ Fichier trop volumineux pour Telegram : {file_size / 1024 / 1024:.1f} Mo\n"
                f"Limite : {MAX_FILE_SIZE_TELEGRAM / 1024 / 1024:.0f} Mo\n\n"
                f"Accédez-y directement depuis votre PC.",
                message_thread_id=TOPIC_EMAIL_COMMUNICATIONS,
            )
            logger.info(
                "file_too_large_for_telegram",
                filename=best_match.filename,
                size_mb=file_size / 1024 / 1024,
            )
            return

        # 7. Envoi fichier Telegram
        with open(vps_file_path, "rb") as f:
            caption = f"📄 {best_match.filename}\n"
            if best_match.doc_type:
                caption += f"Type : {best_match.doc_type}\n"
            if best_match.emitter:
                caption += f"Émetteur : {best_match.emitter}\n"
            if best_match.amount > 0:
                caption += f"Montant : {best_match.amount:.2f} EUR\n"

            await update.message.reply_document(
                document=f,
                filename=best_match.filename,
                caption=caption,
                message_thread_id=TOPIC_EMAIL_COMMUNICATIONS,
            )

        logger.info(
            "file_sent_to_user",
            filename=best_match.filename,
            size_bytes=file_size,
            similarity=best_match.similarity,
        )

    except Exception as e:
        logger.error("file_send_handler_failed", error=str(e), error_type=type(e).__name__)

        await update.message.reply_text(
            "❌ Erreur lors de la recherche/envoi du fichier.\n\n"
            "Veuillez réessayer plus tard ou contacter l'administrateur.",
            message_thread_id=TOPIC_EMAIL_COMMUNICATIONS,
        )
