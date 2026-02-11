"""
Prompt engineering pour classification d'emails (Story 2.2).

Construction des prompts système et utilisateur pour Claude Sonnet 4.5,
avec injection des correction_rules et contexte utilisateur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence  # H4 fix: Add Sequence for immutability

if TYPE_CHECKING:
    from agents.src.middleware.models import CorrectionRule


# M3 fix: Configuration centralisée (éviter magic numbers)
CLASSIFICATION_CONFIG = {
    "reasoning_min_length": 10,  # Minimum caractères pour reasoning
    "keywords_min": 3,  # Minimum mots-clés requis
    "keywords_max": 5,  # Maximum mots-clés acceptés
    "max_tokens": 300,  # Limite tokens réponse Claude
    "temperature": 0.1,  # Temperature classification (déterministe)
    "max_correction_rules": 50,  # Limite règles injectées dans prompt
}

# Catégories supportées avec descriptions détaillées
CATEGORY_DESCRIPTIONS = {
    "medical": "Emails du cabinet médical SELARL : patients, CPAM, URSSAF santé, planning consultations, admin médicale",
    "finance": "Comptabilité, banques, impôts, factures (5 périmètres : SELARL, SCM, SCI-1, SCI-2, personnel)",
    "faculty": "Enseignement universitaire : étudiants, plannings cours, examens, réunions faculté",
    "research": "Recherche académique : thèses encadrées, publications, colloques, revues scientifiques",
    "personnel": "Vie personnelle : amis, famille, loisirs, achats personnels, voyage",
    "urgent": "Emails nécessitant action immédiate : VIP, deadline <24h, urgence explicite",
    "spam": "Publicités commerciales, newsletters non sollicitées, emails promotionnels",
    "unknown": "Impossible à classifier avec confiance suffisante (fallback de sécurité)",
}


def build_classification_prompt(
    email_text: str,
    correction_rules: list[CorrectionRule] | None = None,
) -> tuple[str, str]:
    """
    Construit les prompts système et utilisateur pour classification email.

    Args:
        email_text: Texte de l'email anonymisé (corps + métadonnées)
        correction_rules: Règles de correction à injecter (triées par priority ASC)

    Returns:
        Tuple (system_prompt, user_prompt)

    Notes:
        - System prompt : contexte + catégories + règles correction + format output
        - User prompt : email à classifier
        - Température recommandée : 0.1 (classification déterministe)
        - Max tokens : 300 (catégorie + confidence + reasoning)
    """
    # ===== SYSTEM PROMPT =====

    system_prompt_parts = [
        # Contexte utilisateur
        "Tu es un assistant de classification d'emails pour un médecin français multi-casquettes :\n"
        "- Médecin libéral (SELARL)\n"
        "- Enseignant universitaire (faculté de médecine)\n"
        "- Directeur de thèses (doctorants)\n"
        "- Investisseur immobilier (SCIs)\n",
        # Injection règles de correction (PRIORITAIRES)
        _format_correction_rules(correction_rules or []),
        # Catégories disponibles
        "\n**CATÉGORIES DISPONIBLES** :\n",
        *[
            f"- `{cat}` : {desc}\n"
            for cat, desc in CATEGORY_DESCRIPTIONS.items()
        ],
        # Format output strict
        "\n**FORMAT DE SORTIE OBLIGATOIRE** :\n"
        "Tu DOIS retourner UNIQUEMENT un JSON valide, sans texte avant ou après.\n"
        "Pas de markdown (pas de ```json), pas d'explication, SEULEMENT le JSON.\n\n"
        "Format exact :\n"
        "```\n"
        "{\n"
        '  "category": "medical",  // UNE des catégories ci-dessus\n'
        '  "confidence": 0.92,      // Score 0.0-1.0\n'
        '  "reasoning": "Expéditeur @urssaf.fr, sujet cotisations SELARL",  // Explication claire\n'
        '  "keywords": ["SELARL", "cotisations", "URSSAF"],  // Mots-clés identifiés\n'
        '  "suggested_priority": "high"  // low/normal/high/urgent\n'
        "}\n"
        "```\n\n"
        "**RÈGLES STRICTES** :\n"
        "- Si tu as un doute → category='unknown' + confidence faible (<0.6)\n"
        f"- Reasoning doit expliquer ta décision (minimum {CLASSIFICATION_CONFIG['reasoning_min_length']} caractères)\n"  # M3 fix
        f"- Keywords : {CLASSIFICATION_CONFIG['keywords_min']}-{CLASSIFICATION_CONFIG['keywords_max']} mots-clés max qui ont influencé ta décision\n"  # M3 fix
        "- Confidence : sois réaliste (pas systématiquement >0.9)\n"
        "- JAMAIS de commentaires hors JSON\n",
    ]

    system_prompt = "".join(system_prompt_parts)

    # ===== USER PROMPT =====

    user_prompt = (
        "Classifie cet email dans l'une des catégories disponibles.\n\n"
        "**EMAIL À CLASSIFIER** :\n"
        f"{email_text}\n\n"
        "Retourne UNIQUEMENT le JSON de classification (sans markdown)."
    )

    return (system_prompt, user_prompt)


def _format_correction_rules(rules: Sequence[CorrectionRule]) -> str:  # H4 fix: Sequence for immutability
    """
    Formate les règles de correction pour injection dans le prompt.

    Args:
        rules: Liste triée par priority ASC (plus bas = plus prioritaire)

    Returns:
        Bloc texte formaté avec les règles

    Notes:
        - Maximum 50 règles (limite feedback loop Story 1.7)  # L2 fix: Correct AC reference
        - Si >50 règles actives, prendre les 50 plus prioritaires
    """
    if not rules:
        return ""

    # Limitation à 50 règles max
    rules_to_inject = rules[:50]

    parts = [
        "\n**RÈGLES DE CORRECTION PRIORITAIRES** :\n"
        "Applique ces règles AVANT toute décision (elles ont priorité absolue) :\n\n"
    ]

    for idx, rule in enumerate(rules_to_inject, start=1):
        # Utilise format_for_prompt() du modèle CorrectionRule
        parts.append(
            f"- Règle {idx}: {rule.format_for_prompt()}\n"
        )

    if len(rules) > 50:
        parts.append(
            f"\n⚠️ ATTENTION : {len(rules)} règles actives au total, "
            f"seules les 50 plus prioritaires sont affichées.\n"
        )

    parts.append("\n")  # Séparation avant les catégories

    return "".join(parts)


def validate_classification_response(json_str: str) -> bool:
    """
    Valide rapidement qu'une réponse ressemble à du JSON de classification.

    Args:
        json_str: Réponse brute de Claude

    Returns:
        True si ça ressemble à du JSON valide de classification

    Notes:
        - Validation basique (pas de parsing Pydantic complet)
        - Utilisé pour retry si format invalide
    """
    json_str = json_str.strip()

    # Vérifications basiques
    required_keys = ["category", "confidence", "reasoning"]

    return all(
        [
            json_str.startswith("{"),
            json_str.endswith("}"),
            *[key in json_str for key in required_keys],
        ]
    )
