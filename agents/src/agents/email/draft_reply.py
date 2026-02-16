"""
Module de génération de brouillons emails avec few-shot learning

Ce module implémente la génération automatique de brouillons de réponse email
en utilisant Claude Sonnet 4.5 avec apprentissage du style rédactionnel via
few-shot learning.

Story: 2.5 Brouillon Réponse Email
FR: FR4, FR129, FR104
NFR: NFR1 (<30s latence), NFR6 (anonymisation PII 100%), NFR7 (fail-explicit Presidio)

Usage:
    result = await draft_email_reply(email_id, email_data, db_pool)
    # result.payload['draft_body'] contient le brouillon généré

Architecture:
    1. Anonymise email source via Presidio (RGPD)
    2. Charge writing_examples (top 5-10, filtre email_type)
    3. Charge correction_rules (module='email', scope='draft_reply')
    4. Build prompts (system + user) avec few-shot + rules
    5. Call Claude Sonnet 4.5 (temp=0.7, max_tokens=2000)
    6. Dé-anonymise brouillon
    7. Return ActionResult (trust=propose)

IMPORTANT - Anti-patterns à éviter:
    ❌ Envoyer email sans validation Mainteneur (toujours trust=propose)
    ❌ Appeler Claude AVANT anonymisation Presidio (violation RGPD)
    ❌ Ignorer correction_rules existantes (répète les erreurs)
    ❌ Injecter TOUS les writing_examples (explosion token cost)
    ❌ Ne pas stocker brouillons envoyés (pas d'apprentissage)
"""

import asyncio
from typing import Optional

import asyncpg
from agents.src.adapters.llm import get_llm_adapter
from agents.src.middleware.models import ActionResult, StepDetail
from agents.src.middleware.trust import friday_action
from agents.src.tools.anonymize import anonymize_text, deanonymize_text

# ============================================================================
# Configuration
# ============================================================================

# LLM parameters (D17 - Claude Sonnet 4.5 unique)
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
CLAUDE_TEMPERATURE_DRAFT = 0.7  # Créativité nécessaire pour rédaction
CLAUDE_MAX_TOKENS_DRAFT = 2000  # Réponses emails peuvent être longues

# Few-shot learning limits
MAX_WRITING_EXAMPLES = 10  # Trade-off qualité vs token cost
DEFAULT_WRITING_EXAMPLES = 5  # Sweet spot 80% bénéfice, 40% coût

# Correction rules limit (architecture constraint)
MAX_CORRECTION_RULES = 50


# ============================================================================
# Agent principal @friday_action
# ============================================================================


@friday_action(module="email", action="draft_reply", trust_default="propose")
async def draft_email_reply(
    email_id: str,
    email_data: dict,
    db_pool: asyncpg.Pool,
    user_preferences: Optional[dict] = None,
    **kwargs,  # Accept decorator-injected args (_correction_rules, _rules_prompt)
) -> ActionResult:
    """
    Rédiger brouillon réponse email avec few-shot learning

    Args:
        email_id: UUID de l'email original (ingestion.emails)
        email_data: Données email (from, to, subject, body, category, etc.)
        db_pool: Pool connexions PostgreSQL
        user_preferences: Préférences style rédactionnel (optionnel)
            Format: {"tone": "formal", "tutoiement": False, "verbosity": "concise"}

    Returns:
        ActionResult avec payload contenant:
            - draft_body: Brouillon généré (texte complet)
            - email_type: Type email (professional/medical/academic/personal)
            - style_examples_used: Nombre exemples injectés
            - correction_rules_used: Nombre règles appliquées
            - prompt_tokens: Tokens prompt (estimation)
            - response_tokens: Tokens réponse (estimation)

    Raises:
        NotImplementedError: Si Presidio indisponible (fail-explicit RGPD)
        ValueError: Si brouillon vide ou incohérent
        Exception: Erreur Claude API ou autre

    Trust Level:
        propose - Validation Mainteneur OBLIGATOIRE avant envoi
        (Jamais auto, même après 1000 brouillons parfaits)

    Example:
        >>> result = await draft_email_reply(
        ...     email_id="abc-123",
        ...     email_data={
        ...         'from': 'john@example.com',
        ...         'subject': 'Question about appointment',
        ...         'body': 'Can I reschedule my appointment?',
        ...         'category': 'professional'
        ...     },
        ...     db_pool=pool
        ... )
        >>> print(result.payload['draft_body'])
        Bonjour,
        Oui, vous pouvez reprogrammer votre rendez-vous.
        Cordialement,
        Dr. Antonio Lopez
    """

    # ========================================================================
    # Étape 1: Anonymiser email source (RGPD NFR6, NFR7)
    # ========================================================================

    email_text = email_data.get("body", "")
    email_from = email_data.get("from", "Unknown")
    email_subject = email_data.get("subject", "No subject")

    # Anonymisation Presidio AVANT appel Claude cloud (CRITIQUE)
    anon_result = await anonymize_text(email_text)
    email_text_anon = anon_result.anonymized_text

    # Anonymiser aussi from/subject pour notifications Telegram
    email_from_anon_result = await anonymize_text(email_from)
    email_from_anon = email_from_anon_result.anonymized_text
    email_subject_anon_result = await anonymize_text(email_subject)
    email_subject_anon = email_subject_anon_result.anonymized_text

    # ========================================================================
    # Étape 2: Charger writing examples (few-shot learning AC2)
    # ========================================================================

    email_type = email_data.get("category", "professional")

    writing_examples = await load_writing_examples(
        db_pool=db_pool, email_type=email_type, limit=DEFAULT_WRITING_EXAMPLES
    )

    # ========================================================================
    # Étape 3: Charger correction rules (AC8)
    # ========================================================================

    correction_rules = await _fetch_correction_rules(
        db_pool=db_pool, module="email", scope="draft_reply"
    )

    # ========================================================================
    # Étape 4: Build prompts (system + user)
    # ========================================================================

    # Import ici pour éviter circular dependency
    from agents.src.agents.email.prompts_draft_reply import build_draft_reply_prompt

    system_prompt, user_prompt = build_draft_reply_prompt(
        email_text=email_text_anon,
        email_type=email_type,
        correction_rules=correction_rules,
        writing_examples=writing_examples,
        user_preferences=user_preferences,
    )

    # ========================================================================
    # Étape 5: Call Claude Sonnet 4.5 (AC1)
    # ========================================================================

    draft_body_anon = await _call_claude_with_retry(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=CLAUDE_TEMPERATURE_DRAFT,
        max_tokens=CLAUDE_MAX_TOKENS_DRAFT,
    )

    # ========================================================================
    # Étape 6: Dé-anonymiser brouillon
    # ========================================================================

    draft_body = await deanonymize_text(draft_body_anon, anon_result.mapping)

    # ========================================================================
    # Étape 7: Valider brouillon
    # ========================================================================

    if not draft_body or len(draft_body.strip()) < 10:
        raise ValueError(f"Brouillon vide ou trop court ({len(draft_body)} caractères)")

    # ========================================================================
    # Étape 8: Return ActionResult (AC3)
    # ========================================================================

    # Estimation tokens (approximatif, Claude ne retourne pas token count dans response)
    # TODO(M5 - Story future): Utiliser formule 0.75 words/token pour meilleure précision
    # (voir prompts_draft_reply.py:estimate_prompt_tokens pour référence)
    prompt_tokens_est = len(system_prompt.split()) + len(user_prompt.split())
    response_tokens_est = len(draft_body.split())

    # Confidence basée sur nombre d'exemples disponibles
    confidence = 0.85 if len(writing_examples) >= 3 else 0.70

    return ActionResult(
        input_summary=f"Email de {email_from_anon}: {email_subject_anon[:50]}...",
        output_summary=f"Brouillon réponse ({len(draft_body)} caractères)",
        confidence=confidence,
        reasoning=(
            f"Style cohérent avec {len(writing_examples)} exemples précédents + "
            f"{len(correction_rules)} règles de correction appliquées. "
            f"Email type: {email_type}"
        ),
        payload={
            "email_type": email_type,
            "style_examples_used": len(writing_examples),
            "correction_rules_used": len(correction_rules),
            "draft_body": draft_body,
            "email_original_id": email_id,  # Nécessaire pour envoi via SMTP (D25)
            "prompt_tokens": prompt_tokens_est,
            "response_tokens": response_tokens_est,
        },
        steps=[
            StepDetail(
                step_number=1,
                description="Anonymize email source",
                confidence=1.0,
                metadata={"input_length": len(email_text), "output_length": len(email_text_anon)},
            ),
            StepDetail(
                step_number=2,
                description="Load writing examples",
                confidence=1.0 if writing_examples else 0.5,
                metadata={"examples_count": len(writing_examples), "email_type": email_type},
            ),
            StepDetail(
                step_number=3,
                description="Load correction rules",
                confidence=1.0,
                metadata={"rules_count": len(correction_rules)},
            ),
            StepDetail(
                step_number=4,
                description="Build prompts",
                confidence=1.0,
                metadata={
                    "system_prompt_length": len(system_prompt),
                    "user_prompt_length": len(user_prompt),
                },
            ),
            StepDetail(
                step_number=5,
                description="Generate with Claude Sonnet 4.5",
                confidence=confidence,
                metadata={
                    "temperature": CLAUDE_TEMPERATURE_DRAFT,
                    "max_tokens": CLAUDE_MAX_TOKENS_DRAFT,
                },
            ),
            StepDetail(
                step_number=6,
                description="Deanonymize draft",
                confidence=1.0,
                metadata={"input_length": len(draft_body_anon), "output_length": len(draft_body)},
            ),
            StepDetail(
                step_number=7,
                description="Validate draft",
                confidence=0.90,
                metadata={"draft_length": len(draft_body), "valid": True},
            ),
        ],
    )


# ============================================================================
# Helper: Load Writing Examples
# ============================================================================


async def load_writing_examples(
    db_pool: asyncpg.Pool, email_type: str, limit: int = 5
) -> list[dict]:
    """
    Charger top N exemples récents du style Mainteneur

    Charge les exemples de brouillons approuvés et envoyés pour
    injection few-shot dans le prompt LLM.

    Args:
        db_pool: Pool connexions PostgreSQL
        email_type: Type email (professional/personal/medical/academic)
        limit: Nombre max d'exemples à charger (défaut: 5, max: 10)

    Returns:
        Liste de dicts avec clés: id, subject, body, email_type, created_at

    Query SQL:
        SELECT id, subject, body, email_type, created_at
        FROM core.writing_examples
        WHERE sent_by = 'Mainteneur'
          AND email_type = $1
        ORDER BY created_at DESC
        LIMIT $2

    Trade-off:
        - 3 exemples: qualité baseline, coût faible
        - 5 exemples: sweet spot 80% bénéfice, coût raisonnable
        - 10 exemples: qualité max, coût double vs 5
        - >10 exemples: rendement décroissant, explosion coût tokens

    Example:
        >>> examples = await load_writing_examples(
        ...     db_pool, 'professional', limit=5
        ... )
        >>> print(len(examples))
        3
    """

    # Limiter à MAX_WRITING_EXAMPLES (protection)
    limit = min(limit, MAX_WRITING_EXAMPLES)

    rows = await db_pool.fetch(
        """
        SELECT id, subject, body, email_type, created_at
        FROM core.writing_examples
        WHERE sent_by = 'Mainteneur'
          AND email_type = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        email_type,
        limit,
    )

    return [dict(row) for row in rows]


# ============================================================================
# Helper: Format Writing Examples for Prompt (M2 FIX - removed DRY violation)
# ============================================================================

# NOTE(M2 fix): Cette fonction était un duplicat exact de _format_writing_examples()
# dans prompts_draft_reply.py. Supprimée pour éviter duplication.
# Utiliser directement _format_writing_examples() depuis prompts_draft_reply.py.


# ============================================================================
# Helper: Fetch Correction Rules
# ============================================================================


async def _fetch_correction_rules(db_pool: asyncpg.Pool, module: str, scope: str) -> list[dict]:
    """
    Charger correction rules actives pour injection dans prompt

    Args:
        db_pool: Pool connexions PostgreSQL
        module: Module cible (ex: 'email')
        scope: Scope action (ex: 'draft_reply')

    Returns:
        Liste de dicts avec clés: id, module, scope, conditions, output, priority

    Query SQL:
        SELECT id, module, scope, conditions, output, priority
        FROM core.correction_rules
        WHERE module = $1
          AND scope = $2
          AND active = true
        ORDER BY priority DESC
        LIMIT 50

    Example:
        >>> rules = await _fetch_correction_rules(
        ...     db_pool, module='email', scope='draft_reply'
        ... )
        >>> len(rules)
        2
    """

    rows = await db_pool.fetch(
        """
        SELECT id, module, scope, conditions, output, priority
        FROM core.correction_rules
        WHERE module = $1
          AND scope = $2
          AND active = true
        ORDER BY priority DESC
        LIMIT $3
        """,
        module,
        scope,
        MAX_CORRECTION_RULES,
    )

    return [dict(row) for row in rows]


# ============================================================================
# Helper: Call Claude with Retry
# ============================================================================


async def _call_claude_with_retry(
    system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, max_retries: int = 3
) -> str:
    """
    Appeler Claude Sonnet 4.5 avec retry logic

    Args:
        system_prompt: Prompt système (contexte, exemples, règles)
        user_prompt: Prompt utilisateur (email à répondre)
        temperature: 0.0-1.0 (0.7 pour draft créatif)
        max_tokens: Max tokens réponse (2000 pour emails longs)
        max_retries: Nombre max tentatives si échec

    Returns:
        Texte brouillon généré par Claude

    Raises:
        Exception: Si échec après max_retries tentatives

    Retry Logic:
        - Tentative 1: Appel direct
        - Tentative 2: Attendre 1s, retry
        - Tentative 3: Attendre 2s, retry
        - Échec: Raise exception

    Example:
        >>> draft = await _call_claude_with_retry(
        ...     system_prompt="Tu es Friday...",
        ...     user_prompt="Email: ...",
        ...     temperature=0.7,
        ...     max_tokens=2000
        ... )
        >>> len(draft) > 0
        True
    """

    llm_adapter = get_llm_adapter()  # Factory pattern (D17 - Claude Sonnet 4.5)

    for attempt in range(1, max_retries + 1):
        try:
            response = await llm_adapter.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                model=CLAUDE_MODEL,  # claude-sonnet-4-5-20250929
            )

            # Extraire texte de la réponse
            if isinstance(response, dict) and "content" in response:
                return response["content"].strip()
            elif isinstance(response, str):
                return response.strip()
            else:
                raise ValueError(f"Unexpected response format from Claude: {type(response)}")

        except Exception as e:
            if attempt == max_retries:
                raise Exception(f"Claude API failed after {max_retries} attempts: {str(e)}") from e

            # Backoff exponentiel: 1s, 2s
            await asyncio.sleep(2 ** (attempt - 1))

    # Ne devrait jamais arriver ici
    raise Exception("Unexpected error in _call_claude_with_retry")
