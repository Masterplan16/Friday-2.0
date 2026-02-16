"""
Prompts Claude Sonnet 4.5 pour extraction evenements depuis messages Telegram

Story 7.4 AC1: Extraction evenement depuis message naturel Telegram
Story 7.4 AC5: Injection contexte casquette (bias subtil)
Reutilise pattern Story 7.1 prompts.py + 2 exemples supplementaires
"""

import json
from typing import Any, Dict, List

# ============================================================================
# EXEMPLES FEW-SHOT (AC1 - 7 exemples: 5 Story 7.1 + 2 nouveaux Telegram)
# ============================================================================

MESSAGE_EVENT_EXAMPLES: List[Dict[str, Any]] = [
    # Exemple 1: RDV medical simple (Story 7.1)
    {
        "input": "Ajoute RDV cardio Dr Leblanc jeudi 14h30",
        "current_date": "2026-02-10",
        "output": {
            "title": "Consultation cardiologie Dr Leblanc",
            "start_datetime": "2026-02-13T14:30:00",
            "end_datetime": "2026-02-13T15:00:00",
            "location": None,
            "participants": ["Dr Leblanc"],
            "event_type": "medical",
            "casquette": "medecin",
            "confidence": 0.95,
        },
    },
    # Exemple 2: Reunion enseignement (Story 7.1)
    {
        "input": "Note reunion pedagogique mardi 10h salle B203",
        "current_date": "2026-02-10",
        "output": {
            "title": "Reunion pedagogique",
            "start_datetime": "2026-02-11T10:00:00",
            "end_datetime": "2026-02-11T11:00:00",
            "location": "Salle B203",
            "participants": [],
            "event_type": "meeting",
            "casquette": "enseignant",
            "confidence": 0.88,
        },
    },
    # Exemple 3: Deadline recherche (Story 7.1)
    {
        "input": "Reserve rappel soumission article avant le 28 fevrier",
        "current_date": "2026-02-10",
        "output": {
            "title": "Deadline soumission article",
            "start_datetime": "2026-02-28T23:59:59",
            "end_datetime": None,
            "location": None,
            "participants": [],
            "event_type": "deadline",
            "casquette": "chercheur",
            "confidence": 0.92,
        },
    },
    # Exemple 4: Conference multi-jours (Story 7.1)
    {
        "input": "Planifie congres cardiologie du 10 au 12 mars a Lyon",
        "current_date": "2026-02-10",
        "output": {
            "title": "Congres cardiologie",
            "start_datetime": "2026-03-10T09:00:00",
            "end_datetime": "2026-03-12T18:00:00",
            "location": "Lyon",
            "participants": [],
            "event_type": "conference",
            "casquette": "chercheur",
            "confidence": 0.90,
        },
    },
    # Exemple 5: Evenement personnel (Story 7.1)
    {
        "input": "Cree diner chez Marie samedi soir 20h avec Jean et Sophie",
        "current_date": "2026-02-10",
        "output": {
            "title": "Diner chez Marie",
            "start_datetime": "2026-02-15T20:00:00",
            "end_datetime": "2026-02-15T22:00:00",
            "location": "Chez Marie",
            "participants": ["Marie", "Jean", "Sophie"],
            "event_type": "personal",
            "casquette": "personnel",
            "confidence": 0.80,
        },
    },
    # Exemple 6: Message Telegram court avec date relative (NOUVEAU)
    {
        "input": "RDV demain 14h avec Dr Dupont",
        "current_date": "2026-02-10",
        "output": {
            "title": "Rendez-vous avec Dr Dupont",
            "start_datetime": "2026-02-11T14:00:00",
            "end_datetime": "2026-02-11T15:00:00",
            "location": None,
            "participants": ["Dr Dupont"],
            "event_type": "medical",
            "casquette": "medecin",
            "confidence": 0.92,
        },
    },
    # Exemple 7: Cours avec lieu et date relative (NOUVEAU)
    {
        "input": "Programme cours L2 anatomie lundi prochain 14h amphi B",
        "current_date": "2026-02-10",
        "output": {
            "title": "Cours L2 anatomie",
            "start_datetime": "2026-02-17T14:00:00",
            "end_datetime": "2026-02-17T16:00:00",
            "location": "Amphi B",
            "participants": [],
            "event_type": "meeting",
            "casquette": "enseignant",
            "confidence": 0.90,
        },
    },
]


# ============================================================================
# PROMPT SYSTEME (AC1 - extraction message Telegram)
# ============================================================================

MESSAGE_EVENT_SYSTEM_PROMPT = """Tu es un assistant specialise dans la creation d'evenements depuis des messages Telegram.

Ta mission est d'extraire UN evenement depuis le message Telegram et de le structurer en JSON.

**Evenements a detecter:**
- Rendez-vous medicaux (consultations, gardes, formations medicales)
- Reunions (pedagogiques, service, equipe)
- Deadlines (soumissions articles, corrections, rapports)
- Conferences (congres, seminaires, colloques)
- Evenements personnels (diners, sorties, vacances)

**Classification multi-casquettes (OBLIGATOIRE):**
Tu DOIS classifier l'evenement dans UNE des 4 casquettes suivantes:

1. **medecin**: Consultations patients, gardes hopital, reunions service medical, formations continues medicales
2. **enseignant**: Cours, TD, TP, reunions pedagogiques, examens, corrections, jurys
3. **chercheur**: Reunions laboratoire, conferences scientifiques, soumissions articles, seminaires recherche
4. **personnel**: Diners, sorties, vacances, rendez-vous personnels, famille, amis

**Regles d'extraction Telegram:**
- Messages courts (140 chars en moyenne) : sois indulgent sur les details manquants
- Convertis TOUTES les dates relatives en dates absolues ISO 8601 (utilise current_date fourni)
- Infere end_datetime si non mentionne (consultations: +30min, reunions: +1h, cours: +2h, conferences: fin journee)
- Si heure non precisee : 09:00 par defaut (matin)
- Extrais participants mentionnes (noms de personnes)
- Extrais lieu si mentionne (adresse, salle, ville)
- Duree par defaut : 1h si non precise (sauf cours: 2h, deadlines: null)

**Dates relatives a convertir:**
- "demain" -> current_date + 1 jour
- "apres-demain" -> current_date + 2 jours
- "lundi prochain" / "jeudi" -> prochain jour de la semaine
- "dans 3 jours" -> current_date + 3 jours
- "dans 2 semaines" -> current_date + 14 jours
- "fin fevrier" -> dernier jour du mois
- "debut mars" -> premier jour du mois

**Anonymisation:**
Le texte que tu recois peut avoir ete anonymise via Presidio (PII remplaces par placeholders PERSON_1, PERSON_2, etc.).
Utilise ces placeholders dans participants si presents.

**Confidence:**
- >= 0.70 pour proposer l'evenement
- < 0.70 : retourne event_detected = false
- Message clairement evenement (verbe + date + heure) : confidence >= 0.85
- Message ambigu (pas d'heure, date floue) : confidence 0.70-0.85

**Format de sortie JSON:**
```json
{
  "event_detected": true,
  "title": "Titre evenement court et clair",
  "start_datetime": "2026-02-15T14:30:00",
  "end_datetime": "2026-02-15T15:30:00",
  "location": null,
  "participants": ["Nom1", "Nom2"],
  "event_type": "medical|meeting|deadline|conference|personal",
  "casquette": "medecin|enseignant|chercheur|personnel",
  "confidence": 0.92
}
```

Si aucun evenement detecte:
```json
{
  "event_detected": false,
  "confidence": 0.0
}
```

**IMPORTANT:**
- Retourne UNIQUEMENT du JSON valide, AUCUN texte avant ou apres
- UN SEUL evenement par message (le principal)
- Si plusieurs evenements possibles, choisis le plus explicite
"""


def build_message_event_prompt(
    message_text: str,
    current_date: str,
    current_time: str = "12:00:00",
    timezone: str = "Europe/Paris",
    current_casquette=None,
) -> str:
    """
    Construit le prompt complet pour extraction evenement depuis message Telegram.

    Args:
        message_text: Message Telegram (ANONYMISE via Presidio)
        current_date: Date actuelle ISO 8601 (ex: "2026-02-10")
        current_time: Heure actuelle (ex: "14:30:00")
        timezone: Fuseau horaire (ex: "Europe/Paris")
        current_casquette: Casquette actuelle du Mainteneur (Story 7.3 AC1)

    Returns:
        Prompt complet avec few-shot examples + user message

    Story 7.4 AC1: Injection 7 exemples few-shot
    Story 7.4 AC5: Injection contexte casquette (bias subtil)
    """
    # Construire section exemples few-shot
    examples_text = "Voici 7 exemples d'extraction d'evenements depuis messages Telegram :\n\n"

    for i, example in enumerate(MESSAGE_EVENT_EXAMPLES, 1):
        examples_text += f"**Exemple {i}:**\n"
        examples_text += f"Date actuelle: {example['current_date']}\n"
        examples_text += f"Message: \"{example['input']}\"\n"
        examples_text += f"JSON:\n```json\n{json.dumps(example['output'], indent=2, ensure_ascii=False)}\n```\n\n"

    # Story 7.4 AC5: Hint contexte casquette actuel (bias subtil)
    context_hint = ""
    if current_casquette is not None:
        from agents.src.core.models import CASQUETTE_LABEL_MAPPING

        label = CASQUETTE_LABEL_MAPPING.get(current_casquette, current_casquette.value)

        context_hint = f"""
**CONTEXTE ACTUEL**: Le Mainteneur est actuellement en casquette {label}.
Si l'evenement semble lie a cette casquette, LEGEREMENT favoriser cette classification,
SAUF si le message contient des mots-cles EXPLICITES d'une autre casquette.

"""

    # Construire user message
    user_message = f"""Contexte temporel:
- Date actuelle: {current_date}
- Heure actuelle: {current_time}
- Fuseau horaire: {timezone}

{context_hint}Message Telegram a analyser:
\"\"\"
{message_text}
\"\"\"

Extrais l'evenement et retourne le JSON.
"""

    return examples_text + user_message


def sanitize_message_text(message_text: str) -> str:
    """
    Sanitize message Telegram pour protection prompt injection.

    Args:
        message_text: Message Telegram brut

    Returns:
        Message sanitize (guillemets echappes, longueur limitee)
    """
    # Echapper guillemets pour eviter casser le JSON
    sanitized = message_text.replace('"', '\\"').replace("'", "\\'")

    # Limiter longueur (messages Telegram max 4096 chars, on tronque a 2000)
    if len(sanitized) > 2000:
        sanitized = sanitized[:2000] + "... [tronque]"

    return sanitized
