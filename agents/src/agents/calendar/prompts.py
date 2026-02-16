"""
Prompts Claude Sonnet 4.5 pour detection evenements

Story 7.1 AC7: Few-shot learning (5 exemples francais)
"""

from typing import Dict, Any, List


# ============================================================================
# EXEMPLES FEW-SHOT (AC7)
# ============================================================================

EVENT_DETECTION_EXAMPLES: List[Dict[str, Any]] = [
    # Exemple 1: Rendez-vous medical simple
    {
        "input": "RDV cardio Dr Leblanc jeudi 14h30",
        "current_date": "2026-02-10",
        "output": {
            "events_detected": [
                {
                    "title": "Consultation cardiologie Dr Leblanc",
                    "start_datetime": "2026-02-13T14:30:00",
                    "end_datetime": "2026-02-13T15:00:00",
                    "location": None,
                    "participants": ["Dr Leblanc"],
                    "event_type": "medical",
                    "casquette": "medecin",
                    "confidence": 0.95,
                    "context": "RDV cardio Dr Leblanc jeudi 14h30"
                }
            ],
            "confidence_overall": 0.95
        }
    },

    # Exemple 2: Reunion recurrente enseignement
    {
        "input": "Reunion pedagogique tous les mardis 10h salle B203",
        "current_date": "2026-02-10",
        "output": {
            "events_detected": [
                {
                    "title": "Reunion pedagogique",
                    "start_datetime": "2026-02-11T10:00:00",
                    "end_datetime": "2026-02-11T11:00:00",
                    "location": "Salle B203",
                    "participants": [],
                    "event_type": "meeting",
                    "casquette": "enseignant",
                    "confidence": 0.88,
                    "context": "Reunion pedagogique tous les mardis 10h salle B203"
                }
            ],
            "confidence_overall": 0.88
        }
    },

    # Exemple 3: Deadline recherche sans heure precise
    {
        "input": "Soumission article journal cardiologie avant le 28 fevrier",
        "current_date": "2026-02-10",
        "output": {
            "events_detected": [
                {
                    "title": "Deadline soumission article journal cardiologie",
                    "start_datetime": "2026-02-28T23:59:59",
                    "end_datetime": None,
                    "location": None,
                    "participants": [],
                    "event_type": "deadline",
                    "casquette": "chercheur",
                    "confidence": 0.92,
                    "context": "Soumission article journal cardiologie avant le 28 fevrier"
                }
            ],
            "confidence_overall": 0.92
        }
    },

    # Exemple 4: Conference multi-jours
    {
        "input": "Congres europeen cardiologie interventionnelle du 10 au 12 mars 2026 a Lyon",
        "current_date": "2026-02-10",
        "output": {
            "events_detected": [
                {
                    "title": "Congres europeen cardiologie interventionnelle",
                    "start_datetime": "2026-03-10T09:00:00",
                    "end_datetime": "2026-03-12T18:00:00",
                    "location": "Lyon",
                    "participants": [],
                    "event_type": "conference",
                    "casquette": "chercheur",
                    "confidence": 0.90,
                    "context": "Congres europeen cardiologie interventionnelle du 10 au 12 mars 2026 a Lyon"
                }
            ],
            "confidence_overall": 0.90
        }
    },

    # Exemple 5: Evenement personnel informel (date relative)
    {
        "input": "Diner chez Marie samedi soir 20h, elle invite aussi Jean et Sophie",
        "current_date": "2026-02-10",
        "output": {
            "events_detected": [
                {
                    "title": "Diner chez Marie",
                    "start_datetime": "2026-02-15T20:00:00",
                    "end_datetime": "2026-02-15T22:00:00",
                    "location": "Chez Marie",
                    "participants": ["Marie", "Jean", "Sophie"],
                    "event_type": "personal",
                    "casquette": "personnel",
                    "confidence": 0.75,
                    "context": "Diner chez Marie samedi soir 20h"
                }
            ],
            "confidence_overall": 0.75
        }
    }
]


# ============================================================================
# PROMPT SYSTEME (AC1, AC4, AC5, AC7)
# ============================================================================

EVENT_DETECTION_SYSTEM_PROMPT = """Tu es un assistant specialise dans la detection d'evenements depuis des emails.

Ta mission est d'extraire TOUS les evenements mentionnes dans un email et de les structurer en JSON.

**Evenements a detecter:**
- Rendez-vous medicaux (consultations, gardes, formations medicales)
- Reunions (pedagogiques, service, equipe)
- Deadlines (soumissions articles, corrections, rapports)
- Conferences (congres, seminaires, colloques)
- Evenements personnels (diners, sorties, vacances)

**Classification multi-casquettes (OBLIGATOIRE):**
Tu DOIS classifier chaque evenement dans UNE des 4 casquettes suivantes:

1. **medecin**: Consultations patients, gardes hopital, reunions service medical, formations continues medicales
2. **enseignant**: Cours, TD, TP, reunions pedagogiques, examens, corrections, jurys
3. **chercheur**: Reunions laboratoire, conferences scientifiques, soumissions articles, seminaires recherche
4. **personnel**: Diners, sorties, vacances, rendez-vous personnels, famille, amis

**Regles d'extraction:**
- Si l'email mentionne plusieurs evenements distincts, extrais-les TOUS separement
- Convertis TOUTES les dates relatives en dates absolues ISO 8601 (utilise current_date fourni)
- Infere end_datetime si non mentionne (consultations: +30min, reunions: +1h, conferences: fin journee)
- Extrais participants mentionnes (noms de personnes)
- Extrais lieu si mentionne (adresse, salle, ville)
- Confidence >= 0.75 pour proposer l'evenement, sinon IGNORE
- Si aucun evenement detecte avec confidence >= 0.75, retourne events_detected = []

**Dates relatives a convertir (AC4):**
- "demain" → current_date + 1 jour
- "apres-demain" → current_date + 2 jours
- "lundi prochain" / "jeudi" → prochain jour de la semaine
- "dans 3 jours" → current_date + 3 jours
- "dans 2 semaines" → current_date + 14 jours
- "fin fevrier" → dernier jour du mois
- "debut mars" → premier jour du mois

**Anonymisation (AC1):**
Le texte email que tu recois a deja ete anonymise via Presidio (PII remplaces par placeholders PERSON_1, PERSON_2, etc.).
Utilise ces placeholders dans participants si presents.

**Format de sortie JSON:**
```json
{
  "events_detected": [
    {
      "title": "Titre evenement court et clair",
      "start_datetime": "2026-02-15T14:30:00",
      "end_datetime": "2026-02-15T15:00:00",
      "location": "Lieu si mentionne",
      "participants": ["Nom1", "Nom2"],
      "event_type": "medical|meeting|deadline|conference|personal",
      "casquette": "medecin|enseignant|chercheur|personnel",
      "confidence": 0.92,
      "context": "Snippet texte email source"
    }
  ],
  "confidence_overall": 0.92
}
```

**IMPORTANT:**
- Retourne UNIQUEMENT du JSON valide, AUCUN texte avant ou apres
- confidence_overall = min(events.confidence) de tous les evenements
- Si aucun evenement detecte: events_detected = [], confidence_overall = 0.0
"""


def build_event_detection_prompt(
    email_text: str,
    current_date: str,
    current_time: str = "12:00:00",
    timezone: str = "Europe/Paris",
    current_casquette = None
) -> str:
    """
    Construit le prompt complet pour detection evenements

    Args:
        email_text: Texte email (ANONYMISE via Presidio)
        current_date: Date actuelle ISO 8601 (ex: "2026-02-10")
        current_time: Heure actuelle (ex: "14:30:00")
        timezone: Fuseau horaire (ex: "Europe/Paris")
        current_casquette: Casquette actuelle du Mainteneur (Story 7.3 AC1)

    Returns:
        Prompt complet avec few-shot examples + user message

    Story 7.1 AC7: Injection 5 exemples few-shot
    Story 7.3 Task 9.2: Injection contexte casquette (bias subtil)
    """
    # Construire section exemples few-shot
    examples_text = "Voici 5 exemples d'extraction d'evenements :\n\n"

    for i, example in enumerate(EVENT_DETECTION_EXAMPLES, 1):
        examples_text += f"**Exemple {i}:**\n"
        examples_text += f"Date actuelle: {example['current_date']}\n"
        examples_text += f"Email: \"{example['input']}\"\n"
        examples_text += f"JSON:\n```json\n{_format_json_example(example['output'])}\n```\n\n"

    # Story 7.3 AC1: Hint contexte casquette actuel (bias subtil)
    context_hint = ""
    if current_casquette is not None:
        from agents.src.core.models import (
            Casquette,
            CASQUETTE_LABEL_MAPPING,
        )

        label = CASQUETTE_LABEL_MAPPING.get(current_casquette, current_casquette.value)

        context_hint = f"""
**CONTEXTE ACTUEL**: Le Mainteneur est actuellement en casquette {label} (selon son planning).
Si l'evenement semble lie a cette casquette, privilegie LEGEREMENT cette classification (mais reste objectif).

"""

    # Construire user message
    user_message = f"""Contexte temporel:
- Date actuelle: {current_date}
- Heure actuelle: {current_time}
- Fuseau horaire: {timezone}

{context_hint}Email a analyser:
\"\"\"
{email_text}
\"\"\"

Extrais TOUS les evenements mentionnes et retourne le JSON.
"""

    return examples_text + user_message


def _format_json_example(data: Dict[str, Any]) -> str:
    """
    Formate exemple JSON pour few-shot (sans import json pour eviter dependance)
    """
    import json
    return json.dumps(data, indent=2, ensure_ascii=False)


# ============================================================================
# PROMPT INJECTION PROTECTION
# ============================================================================

def sanitize_email_text(email_text: str) -> str:
    """
    Sanitize email text pour protection prompt injection

    Story 7.1 Task 7.1: Protection prompt injection (apostrophes, guillemets)

    Args:
        email_text: Texte email brut

    Returns:
        Texte sanitize (apostrophes/guillemets echappes)
    """
    # Echapper apostrophes et guillemets pour eviter casser le JSON
    sanitized = email_text.replace('"', '\\"').replace("'", "\\'")

    # Limiter longueur pour eviter token overflow (max 4000 chars)
    if len(sanitized) > 4000:
        sanitized = sanitized[:4000] + "... [tronque]"

    return sanitized
