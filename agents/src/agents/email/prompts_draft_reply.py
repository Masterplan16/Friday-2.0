"""
Prompts LLM pour génération brouillons emails

Ce module construit les prompts system et user pour Claude Sonnet 4.5
lors de la génération de brouillons de réponse email.

Inclut :
- Few-shot learning (injection writing_examples)
- Correction rules (injection règles actives)
- User preferences (tone, tutoiement, verbosity)

Story: 2.5 Brouillon Réponse Email
"""

from typing import Optional

# ============================================================================
# Main Prompt Builder
# ============================================================================


def build_draft_reply_prompt(
    email_text: str,
    email_type: str,
    correction_rules: list[dict],
    writing_examples: list[dict],
    user_preferences: Optional[dict] = None,
) -> tuple[str, str]:
    """
    Build system + user prompts pour génération brouillon email

    Args:
        email_text: Texte email anonymisé (APRÈS Presidio)
        email_type: Type email (professional/personal/medical/academic)
        correction_rules: Règles correction actives (from core.correction_rules)
        writing_examples: Exemples style (from core.writing_examples)
        user_preferences: Préférences style rédactionnel (optionnel)
            Format: {"tone": "formal", "tutoiement": False, "verbosity": "concise"}

    Returns:
        Tuple (system_prompt, user_prompt)

    Example:
        >>> system, user = build_draft_reply_prompt(
        ...     email_text="Can I reschedule my appointment?",
        ...     email_type="professional",
        ...     correction_rules=[],
        ...     writing_examples=[],
        ...     user_preferences={"tone": "formal", "tutoiement": False, "verbosity": "concise"}
        ... )
        >>> 'Friday' in system
        True
        >>> 'reschedule' in user
        True
    """

    # Default preferences (AC2 - Day 1 fallback)
    if user_preferences is None:
        user_preferences = {"tone": "formal", "tutoiement": False, "verbosity": "concise"}

    # Format components
    preferences_text = _format_user_preferences(user_preferences)
    examples_text = _format_writing_examples(writing_examples)
    rules_text = _format_correction_rules(correction_rules)

    # Build system prompt (Subtask 3.2)
    system_prompt = f"""Tu es Friday, assistant personnel du Dr. Antonio Lopez.

CONTEXTE :
- Mainteneur : Médecin, enseignant, chercheur
- Ton rôle : Rédiger brouillons réponse email dans le style d'Antonio

STYLE RÉDACTIONNEL :
{preferences_text}

{examples_text if examples_text else "Pas d'exemples disponibles (Day 1). Utilise le style formel standard français."}

{rules_text if rules_text else "Aucune règle de correction spécifique."}

CONSIGNES :
1. Répondre de manière pertinente aux questions posées dans l'email original
2. Rester concis (max 300 mots sauf si contexte nécessite plus)
3. Respecter le style appris (formules de politesse, structure, ton)
4. Inclure signature standard : "Dr. Antonio Lopez"
5. Format : salutation, corps, formule de politesse, signature

IMPORTANT : Génère UNIQUEMENT le corps du brouillon (pas de métadonnées, pas de commentaires).
Le texte sera envoyé tel quel via email."""

    # Build user prompt (Subtask 3.3)
    user_prompt = f"""Email à répondre :

Type: {email_type}

Corps :
---
{email_text}
---

Rédige un brouillon de réponse dans le style du Mainteneur."""

    return (system_prompt, user_prompt)


# ============================================================================
# Formatters (helpers internes)
# ============================================================================


def _format_user_preferences(preferences: dict) -> str:
    """
    Formater user preferences pour injection dans system prompt

    Args:
        preferences: Dict avec clés tone, tutoiement, verbosity

    Returns:
        Texte formaté pour system prompt

    Example:
        >>> prefs = {"tone": "formal", "tutoiement": False, "verbosity": "concise"}
        >>> text = _format_user_preferences(prefs)
        >>> 'Ton : formel' in text
        True
    """

    tone = preferences.get("tone", "formal")
    tutoiement = preferences.get("tutoiement", False)
    verbosity = preferences.get("verbosity", "concise")

    # Traduction EN -> FR pour clarté
    tone_fr = "formel" if tone == "formal" else "informel"
    tutoiement_fr = "Oui" if tutoiement else "Non"
    verbosity_fr = "concis" if verbosity == "concise" else "détaillé"

    return f"""- Ton : {tone_fr}
- Tutoiement : {tutoiement_fr}
- Verbosité : {verbosity_fr}"""


def _format_writing_examples(examples: list[dict]) -> str:
    """
    Formater writing examples pour injection few-shot dans system prompt

    Args:
        examples: Liste exemples (from core.writing_examples)

    Returns:
        Texte formaté few-shot, ou "" si liste vide

    Example:
        >>> examples = [
        ...     {'subject': 'Re: Info', 'body': 'Bonjour,\\nVoici les infos.\\n\\nCordialement,\\nDr. Lopez'},
        ...     {'subject': 'Re: RDV', 'body': 'Bonjour,\\nJe confirme.\\n\\nCordialement,\\nDr. Lopez'}
        ... ]
        >>> text = _format_writing_examples(examples)
        >>> 'Exemples du style Mainteneur' in text
        True
        >>> 'Exemple 1' in text
        True
    """

    if not examples:
        return ""

    parts = ["Exemples du style Mainteneur :\n---"]

    for idx, ex in enumerate(examples, 1):
        subject = ex.get("subject", "No subject")
        body = ex.get("body", "No body")

        parts.append(
            f"""
Exemple {idx}:
Sujet: {subject}
Corps:
{body}
---"""
        )

    return "\n".join(parts)


def _format_correction_rules(rules: list[dict]) -> str:
    """
    Formater correction rules pour injection dans system prompt

    Args:
        rules: Liste règles (from core.correction_rules)

    Returns:
        Texte formaté règles, ou "" si liste vide

    Example:
        >>> rules = [
        ...     {'conditions': 'Remplacer "Bien à vous"', 'output': 'Utiliser "Cordialement"', 'priority': 1},
        ...     {'conditions': 'Signature complète', 'output': 'Dr. Antonio Lopez\\nMédecin', 'priority': 2}
        ... ]
        >>> text = _format_correction_rules(rules)
        >>> 'Règles de correction prioritaires' in text
        True
        >>> 'Remplacer' in text
        True
    """

    if not rules:
        return ""

    parts = ["Règles de correction prioritaires :"]

    for idx, rule in enumerate(rules, 1):
        conditions = rule.get("conditions", "N/A")
        output = rule.get("output", "N/A")

        parts.append(f"{idx}. {conditions} → {output}")

    return "\n".join(parts)


# ============================================================================
# Utilities (optionnel - pour tests/debug)
# ============================================================================


def estimate_prompt_tokens(system_prompt: str, user_prompt: str) -> int:
    """
    Estimer nombre de tokens dans les prompts (approximatif)

    Utilise règle simple : 1 token ≈ 0.75 mots (anglais/français mélangé)

    Args:
        system_prompt: Prompt système
        user_prompt: Prompt utilisateur

    Returns:
        Estimation nombre tokens total

    Example:
        >>> system = "Tu es Friday, assistant..."
        >>> user = "Email à répondre : ..."
        >>> tokens = estimate_prompt_tokens(system, user)
        >>> tokens > 0
        True
    """

    total_words = len(system_prompt.split()) + len(user_prompt.split())

    # Règle approximative : 1 token ≈ 0.75 mots
    # (Plus précis pour français que 4 chars/token)
    estimated_tokens = int(total_words / 0.75)

    return estimated_tokens


def validate_prompt_length(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> bool:
    """
    Valider que les prompts ne dépassent pas la limite raisonnable

    Args:
        system_prompt: Prompt système
        user_prompt: Prompt utilisateur
        max_tokens: Limite max tokens (défaut: 8000, safe pour Claude)

    Returns:
        True si OK, False si trop long

    Rationale:
        - Claude Sonnet 4.5 context: 200k tokens
        - Prompt budget raisonnable: <8k tokens (4% context)
        - Économie coût ($3/1M tokens input)

    Example:
        >>> system = "Short prompt"
        >>> user = "Short email"
        >>> validate_prompt_length(system, user)
        True
    """

    estimated = estimate_prompt_tokens(system_prompt, user_prompt)

    return estimated <= max_tokens
