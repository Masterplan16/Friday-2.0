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
    "pro": "Emails professionnels cabinet SELARL : CPAM, URSSAF santé, planning consultations, admin médicale (PAS de données patient)",
    "finance": "Comptabilité, banques, impôts, factures (5 périmètres : SELARL, SCM, SCI Ravas, SCI Malbosc, personnel)",
    "universite": "Enseignement universitaire : étudiants, plannings cours, examens, réunions faculté",
    "recherche": "Recherche académique : thèses encadrées, publications, colloques, revues scientifiques",
    "perso": "Vie personnelle : amis, famille, loisirs, achats personnels, voyage",
    "urgent": "Emails nécessitant action immédiate : VIP, deadline <24h, urgence explicite",
    "spam": "Publicités commerciales, newsletters non sollicitées, emails promotionnels",
    "inconnu": "Impossible à classifier avec confiance suffisante (fallback de sécurité)",
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


# =============================================================================
# TASK EXTRACTION PROMPT (Story 2.7)
# =============================================================================

TASK_EXTRACTION_PROMPT = """Tu es un assistant d'extraction de tâches depuis des emails pour un médecin français multi-casquettes.

**MISSION** : Détecter toutes les tâches à réaliser mentionnées dans un email (explicites OU implicites).

**TYPES DE TÂCHES À DÉTECTER** :

1. **Demandes explicites** :
   - "Peux-tu m'envoyer le document X ?"
   - "Merci de me confirmer Y"
   - "Rappelle-moi dès que possible"
   - "Fais-moi parvenir..."

2. **Engagements implicites** (auto-tâches) :
   - "Je vais te recontacter demain"
   - "Je t'envoie ça en fin de semaine"
   - "Je vérifie et je reviens vers toi"

3. **Rappels et échéances** :
   - "N'oublie pas de faire X"
   - "Pense à Y avant vendredi"
   - "À valider avant le 15"

**EXTRACTION DE DATES** :
Tu dois convertir toutes les dates relatives en dates absolues ISO 8601 (YYYY-MM-DD).

Utilise le contexte temporel fourni :
- Date actuelle : {current_date}
- Jour de la semaine : {current_day}

Exemples de conversion :
- "demain" → {example_tomorrow}
- "jeudi prochain" → {example_next_thursday}
- "dans 3 jours" → {example_in_3_days}
- "avant vendredi" → {example_before_friday} (interpréter "avant" comme deadline)
- "la semaine prochaine" → {example_next_week} (lundi suivant par défaut)

Si la date est ambiguë, mets la date la plus probable et ajoute une note dans "context".

**PRIORISATION AUTOMATIQUE** :

Extraire la priorité depuis les mots-clés :

- **high** (priorité 3) :
  - Mots-clés : "urgent", "ASAP", "rapidement", "aujourd'hui", "ce matin", "immédiatement"
  - Deadline <48h
  - Email marqué urgent

- **normal** (priorité 2) :
  - Défaut si aucun indicateur d'urgence
  - Deadline >48h et <7 jours

- **low** (priorité 1) :
  - Mots-clés : "quand tu peux", "pas urgent", "à ta convenance", "quand tu as le temps"
  - Deadline >7 jours ou pas de deadline

**EXEMPLES FEW-SHOT** :

📧 Exemple 1 :
Email : "Bonjour, peux-tu m'envoyer le rapport médical de M. Dupont avant jeudi ? Merci !"
Date actuelle : 2026-02-11 (Mardi)

Résultat :
{{
  "tasks_detected": [
    {{
      "description": "Envoyer le rapport médical de M. Dupont",
      "priority": "high",
      "due_date": "2026-02-13",
      "confidence": 0.95,
      "context": "Demande explicite avec deadline avant jeudi",
      "priority_keywords": ["avant jeudi"]
    }}
  ],
  "confidence_overall": 0.95
}}

📧 Exemple 2 :
Email : "Je vais te recontacter demain pour discuter du dossier X."
Date actuelle : 2026-02-11 (Mardi)

Résultat :
{{
  "tasks_detected": [
    {{
      "description": "Recontacter pour discuter du dossier X",
      "priority": "normal",
      "due_date": "2026-02-12",
      "confidence": 0.85,
      "context": "Engagement implicite de l'expéditeur - auto-tâche",
      "priority_keywords": ["demain"]
    }}
  ],
  "confidence_overall": 0.85
}}

📧 Exemple 3 :
Email : "Rappel : n'oublie pas de valider la facture SCM avant fin de semaine."
Date actuelle : 2026-02-11 (Mardi)

Résultat :
{{
  "tasks_detected": [
    {{
      "description": "Valider la facture SCM",
      "priority": "high",
      "due_date": "2026-02-14",
      "confidence": 0.90,
      "context": "Rappel explicite avec deadline vendredi (fin de semaine)",
      "priority_keywords": ["avant fin de semaine", "n'oublie pas"]
    }}
  ],
  "confidence_overall": 0.90
}}

📧 Exemple 4 (email sans tâche) :
Email : "Merci pour ton message, j'ai bien reçu le document. Bonne journée !"
Date actuelle : 2026-02-11 (Mardi)

Résultat :
{{
  "tasks_detected": [],
  "confidence_overall": 0.15
}}

📧 Exemple 5 (multiples tâches) :
Email : "Urgent : peux-tu m'envoyer le planning ASAP et rappeler le patient pour confirmer son RDV ?"
Date actuelle : 2026-02-11 (Mardi)

Résultat :
{{
  "tasks_detected": [
    {{
      "description": "Envoyer le planning",
      "priority": "high",
      "due_date": "2026-02-11",
      "confidence": 0.95,
      "context": "Demande explicite urgente (ASAP)",
      "priority_keywords": ["urgent", "ASAP"]
    }},
    {{
      "description": "Rappeler le patient pour confirmer son RDV",
      "priority": "high",
      "due_date": "2026-02-11",
      "confidence": 0.92,
      "context": "Demande explicite dans contexte urgent",
      "priority_keywords": ["urgent"]
    }}
  ],
  "confidence_overall": 0.94
}}

**FORMAT DE SORTIE OBLIGATOIRE** :

Tu DOIS retourner UNIQUEMENT un JSON valide, sans texte avant ou après.
Pas de markdown (pas de ```json), pas d'explication, SEULEMENT le JSON.

Format exact :
{{
  "tasks_detected": [
    {{
      "description": "Description claire de la tâche (5-500 caractères)",
      "priority": "high|normal|low",
      "due_date": "YYYY-MM-DD" ou null si pas de date,
      "confidence": 0.85,  // Score 0.0-1.0 pour cette tâche
      "context": "Pourquoi cette tâche a été détectée (max 1000 caractères)",
      "priority_keywords": ["mot1", "mot2"]  // Mots-clés ayant justifié la priorité (optionnel)
    }}
  ],
  "confidence_overall": 0.85  // Confiance globale de l'extraction (moyenne si multiple)
}}

**RÈGLES STRICTES** :

1. **Confidence** : Sois réaliste
   - Demande explicite claire → 0.9-1.0
   - Engagement implicite évident → 0.7-0.9
   - Tâche ambiguë ou incertaine → 0.5-0.7
   - Pas de tâche détectée → tasks_detected=[], confidence_overall <0.3

2. **Seuil de proposition** : Seules les tâches avec confidence ≥0.7 seront proposées au Mainteneur

3. **Description** : Concise et actionnable (ex: "Envoyer le rapport" pas "Il faut que j'envoie...")

4. **Context** : Explique POURQUOI tu as détecté cette tâche (extrait email, mots-clés, ton)

5. **Emails sans tâche** : Si l'email ne contient AUCUNE tâche (ex: newsletter, confirmation automatique, remerciement simple) → retourne tasks_detected=[] et confidence_overall faible

6. **JAMAIS de commentaires hors JSON**

**IMPORTANT RGPD** :
Le texte email que tu reçois a déjà été anonymisé via Presidio.
Les noms de personnes sont remplacés par [PERSON_1], [PERSON_2], etc.
Tu peux utiliser ces marqueurs anonymisés dans tes extractions.
"""
