"""
Graph populator pour le pipeline Email (Epic 2).

Ce module peuple le graphe de connaissances après classification d'un email :
- Créer Email node
- Extraire Person nodes (sender/recipients)
- Créer relations SENT_BY + RECEIVED_BY
- Extraire Entity nodes via NER
- Créer relations MENTIONS
- Si PJ détectées → créer relations ATTACHED_TO vers Document nodes

Dépendances :
- memorystore.py (adaptateur graphe)
- Presidio (anonymisation PII avant LLM)
- Claude Sonnet 4.5 (NER extraction)

Usage:
    email_data = {
        "message_id": "<abc@example.com>",
        "subject": "RE: Projet",
        "sender": "john@example.com",
        "recipients": ["alice@example.com", "bob@example.com"],
        "body": "Bonjour, ...",
        "date": "2026-02-11T14:30:00Z",
        "category": "admin",
        "priority": "normal"
    }

    await populate_email_graph(email_data, memorystore_adapter)
"""

import structlog
from datetime import datetime
from typing import Any, Optional

from agents.src.adapters.memorystore_interface import MemoryStore, NodeType, RelationType
from agents.src.adapters.vectorstore import get_vectorstore_adapter
from agents.src.tools.anonymize import anonymize_text

logger = structlog.get_logger(__name__)


async def populate_email_graph(
    email_data: dict[str, Any],
    memorystore: MemoryStore,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    Peuple le graphe de connaissances à partir d'un email classifié.

    Args:
        email_data: Données email (message_id, subject, sender, recipients,
                    body, date, category, priority)
        memorystore: Adaptateur memorystore
        attachments: Liste optionnelle de PJ [{doc_id, filename, mime_type}, ...]

    Returns:
        email_node_id: UUID du nœud Email créé

    Raises:
        ValueError: Si données email invalides
    """
    # Validation données requises
    required_fields = ["message_id", "subject", "sender", "date"]
    for field in required_fields:
        if field not in email_data:
            raise ValueError(f"Missing required field: {field}")

    logger.info("Populating graph for email: %s", email_data["subject"])

    # Task 9.1 : Créer Email node
    email_node_id = await memorystore.create_node(
        node_type=NodeType.EMAIL.value,
        name=email_data["subject"],
        metadata={
            "message_id": email_data["message_id"],
            "subject": email_data["subject"],
            "sender": email_data["sender"],
            "recipients": email_data.get("recipients", []),
            "date": email_data["date"],
            "category": email_data.get("category", "inconnu"),
            "priority": email_data.get("priority", "normal"),
            "thread_id": email_data.get("thread_id"),
        },
        source="email",
    )

    logger.info("Created Email node: %s", email_node_id)

    # Task 6.2 Subtask 2.1 : Générer embedding pour Email (subject + body anonymisé)
    try:
        # 1. Préparer texte : subject + body
        subject = email_data["subject"]
        body = email_data.get("body", "")
        text_to_embed = f"{subject} {body}".strip()

        # 2. Anonymiser texte AVANT envoi à Voyage AI (RGPD obligatoire)
        anonymized_result = await anonymize_text(text_to_embed)
        anonymized_text = anonymized_result.anonymized_text

        # 3. Générer embedding via Voyage AI
        vectorstore = await get_vectorstore_adapter()
        embedding_response = await vectorstore.embed([anonymized_text], anonymize=False)  # Déjà anonymisé

        # 4. Stocker embedding dans knowledge.embeddings
        embedding = embedding_response.embeddings[0]
        await vectorstore.store(
            node_id=email_node_id,
            embedding=embedding,
            metadata={"source": "email", "anonymized": True},
        )

        logger.info(
            "Embedding generated and stored for email %s (anonymized: %s PII entities)",
            email_node_id,
            len(anonymized_result.entities),
        )

    except Exception as e:
        # Erreur Voyage AI → Email créé quand même, embedding manquant
        logger.error(
            "Failed to generate embedding for email %s: %s. Email node created without embedding.",
            email_node_id,
            str(e),
        )
        # TODO (Story 6.2 Subtask 2.3): Envoyer alerte Telegram + créer receipt status=failed
        # Job nightly retentera génération embedding pour nœuds sans embedding

    # Task 9.2 : Extraire sender → Créer Person node (get_or_create pour déduplication)
    sender_email = email_data["sender"]
    sender_name = email_data.get("sender_name", sender_email.split("@")[0])

    sender_node_id = await memorystore.get_or_create_node(
        node_type=NodeType.PERSON.value,
        name=sender_name,
        metadata={"email": sender_email},
        source="email",
    )

    # Task 9.3 : Créer edge SENT_BY (Email → Person)
    await memorystore.create_edge(
        from_node_id=email_node_id,
        to_node_id=sender_node_id,
        relation_type=RelationType.SENT_BY.value,
        metadata={"confidence": 1.0},
    )

    logger.info("Linked Email SENT_BY Person: %s", sender_node_id)

    # Extraire recipients → Créer Person nodes + edges RECEIVED_BY
    recipients = email_data.get("recipients", [])
    for recipient_email in recipients:
        recipient_name = recipient_email.split("@")[0]

        recipient_node_id = await memorystore.get_or_create_node(
            node_type=NodeType.PERSON.value,
            name=recipient_name,
            metadata={"email": recipient_email},
            source="email",
        )

        await memorystore.create_edge(
            from_node_id=email_node_id,
            to_node_id=recipient_node_id,
            relation_type=RelationType.RECEIVED_BY.value,
            metadata={"confidence": 1.0},
        )

    logger.info("Linked %d recipients via RECEIVED_BY", len(recipients))

    # Task 9.4 : Si PJ détectées → Créer edges ATTACHED_TO vers Document nodes
    if attachments:
        for attachment in attachments:
            doc_id = attachment.get("doc_id")
            if doc_id:
                await memorystore.create_edge(
                    from_node_id=doc_id,
                    to_node_id=email_node_id,
                    relation_type=RelationType.ATTACHED_TO.value,
                    metadata={
                        "filename": attachment.get("filename"),
                        "mime_type": attachment.get("mime_type"),
                    },
                )

        logger.info("Linked %d attachments via ATTACHED_TO", len(attachments))

    # Task 9.5 : NER sur email.body → Créer Entity nodes + edges MENTIONS
    # Note: Pour MVP, implémentation simplifiée - NER complet dans Story 2.2+
    body = email_data.get("body", "")
    if body:
        entities = await extract_entities_ner(body)

        for entity in entities:
            entity_node_id = await memorystore.get_or_create_node(
                node_type=NodeType.ENTITY.value,
                name=entity["name"],
                metadata={
                    "entity_type": entity["type"],
                    "confidence": entity.get("confidence", 0.8),
                },
                source="email",
            )

            await memorystore.create_edge(
                from_node_id=email_node_id,
                to_node_id=entity_node_id,
                relation_type=RelationType.MENTIONS.value,
                metadata={"context": entity.get("context", "")},
            )

        logger.info("Extracted %d entities via NER", len(entities))

    return email_node_id


async def extract_entities_ner(text: str) -> list[dict[str, Any]]:
    """
    Extrait entités via NER (Named Entity Recognition).

    Args:
        text: Texte email body

    Returns:
        Liste d'entités [{name, type, confidence, context}, ...]

    Note:
        Implémentation simplifiée pour Story 6.1.
        NER complet sera implémenté dans Story 2.2 (Classification Email LLM).
        Pour MVP, retourne liste vide (pas de NER).
    """
    # TODO (Story 2.2): Implémenter NER via Claude Sonnet 4.5
    # - Anonymisation Presidio AVANT appel LLM
    # - Prompt NER : extraire PERSON, ORG, LOC, DRUG, DISEASE, CONCEPT
    # - Parser résultat LLM → liste entités
    # - Retourner avec confidence scores

    logger.debug("NER extraction not implemented yet (Story 2.2) - returning empty list")
    return []


async def link_email_to_task(
    email_node_id: str, task_node_id: str, memorystore: MemoryStore
) -> str:
    """
    Crée relation CREATED_FROM entre Task et Email.

    Args:
        email_node_id: UUID du nœud Email
        task_node_id: UUID du nœud Task
        memorystore: Adaptateur memorystore

    Returns:
        edge_id: UUID de la relation créée

    Usage:
        Après extraction tâche depuis email (Story 2.7 + 4.6),
        lier la Task au Email source pour traçabilité.
    """
    edge_id = await memorystore.create_edge(
        from_node_id=task_node_id,
        to_node_id=email_node_id,
        relation_type=RelationType.CREATED_FROM.value,
        metadata={"extraction_date": datetime.utcnow().isoformat()},
    )

    logger.info("Linked Task %s CREATED_FROM Email %s", task_node_id[:8], email_node_id[:8])

    return edge_id


async def link_email_to_event(
    email_node_id: str, event_node_id: str, memorystore: MemoryStore
) -> str:
    """
    Crée relation CREATED_FROM entre Event et Email.

    Args:
        email_node_id: UUID du nœud Email
        event_node_id: UUID du nœud Event
        memorystore: Adaptateur memorystore

    Returns:
        edge_id: UUID de la relation créée

    Usage:
        Après détection événement dans email (Story 7.1),
        lier Event au Email source.
    """
    edge_id = await memorystore.create_edge(
        from_node_id=event_node_id,
        to_node_id=email_node_id,
        relation_type=RelationType.CREATED_FROM.value,
        metadata={"detection_date": datetime.utcnow().isoformat()},
    )

    logger.info("Linked Event %s CREATED_FROM Email %s", event_node_id[:8], email_node_id[:8])

    return edge_id
