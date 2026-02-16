"""
Briefing Templates - Formatage messages briefings

Story 7.3: Multi-casquettes & Conflits (AC3)

Templates Markdown pour briefings avec:
- Groupement par casquette (émojis 🩺🎓🔬)
- Section conflits en haut si détectés
- Formatage heures français (09h00-12h00)
"""

from datetime import date, datetime
from typing import Optional

from agents.src.core.models import Casquette, CASQUETTE_EMOJI_MAPPING, CASQUETTE_LABEL_MAPPING


# ============================================================================
# Constants
# ============================================================================

# Labels journées semaine en français
WEEKDAY_LABELS = {
    0: "Lundi",
    1: "Mardi",
    2: "Mercredi",
    3: "Jeudi",
    4: "Vendredi",
    5: "Samedi",
    6: "Dimanche"
}

# Labels période journée par casquette (heuristique)
CASQUETTE_PERIOD_LABELS = {
    Casquette.MEDECIN: "Matin",
    Casquette.ENSEIGNANT: "Après-midi",
    Casquette.CHERCHEUR: "Soirée"
}


# ============================================================================
# Template Functions
# ============================================================================

def format_briefing_message(
    date: date,
    grouped_events: dict[Casquette, list[dict]],
    conflicts: list[dict]
) -> str:
    """
    Formate message briefing avec groupement par casquette (AC3).

    Args:
        date: Date du briefing
        grouped_events: Événements groupés par casquette
        conflicts: Liste conflits détectés

    Returns:
        Message Markdown formaté

    Example:
        ```
        📋 Briefing Lundi 17 février 2026

        ⚠️ CONFLIT DÉTECTÉ : 14h30 médecin ⚡ 14h00 enseignant

        🩺 MÉDECIN (Matin)
        • 09h00-12h00 : 3 consultations cardiologie

        🎓 ENSEIGNANT (Après-midi)
        • 14h00-16h00 : Cours L2 Anatomie
        ```
    """
    lines = []

    # Header
    weekday = WEEKDAY_LABELS[date.weekday()]
    date_formatted = date.strftime("%d %B %Y")
    lines.append(f"📋 **Briefing {weekday} {date_formatted}**")
    lines.append("")

    # Section conflits (en haut si détectés)
    if conflicts:
        lines.append("⚠️ **CONFLITS DÉTECTÉS**")
        for conflict in conflicts:
            conflict_line = _format_conflict_line(conflict)
            lines.append(conflict_line)
        lines.append("")

    # Sections par casquette
    if not grouped_events:
        lines.append("_Aucun événement prévu aujourd'hui_")
    else:
        for casquette, events in grouped_events.items():
            section = _format_casquette_section(casquette, events)
            lines.extend(section)
            lines.append("")

    return "\n".join(lines).strip()


def _format_casquette_section(casquette: Casquette, events: list[dict]) -> list[str]:
    """
    Formate section casquette avec liste événements (AC3).

    Args:
        casquette: Casquette (MEDECIN/ENSEIGNANT/CHERCHEUR)
        events: Liste événements de cette casquette

    Returns:
        Lignes section formatées

    Example:
        ```
        🩺 MÉDECIN (Matin)
        • 09h00-12h00 : 3 consultations cardiologie
        • 14h30-15h30 : Visite patient hospitalisé
        ```
    """
    lines = []

    # Header section
    emoji = CASQUETTE_EMOJI_MAPPING[casquette]
    label = CASQUETTE_LABEL_MAPPING[casquette].upper()
    period = CASQUETTE_PERIOD_LABELS.get(casquette, "")

    if period:
        lines.append(f"{emoji} **{label}** ({period})")
    else:
        lines.append(f"{emoji} **{label}**")

    # Liste événements
    for event in events:
        event_line = _format_event_line(event)
        lines.append(f"• {event_line}")

    return lines


def _format_event_line(event: dict) -> str:
    """
    Formate ligne événement avec horaires français.

    Args:
        event: Dict avec {title, start_datetime, end_datetime}

    Returns:
        Ligne formatée

    Example: "09h00-12h00 : 3 consultations cardiologie"
    """
    start_time = event["start_datetime"].strftime("%Hh%M")
    end_time = event["end_datetime"].strftime("%Hh%M")
    title = event["title"]

    return f"{start_time}-{end_time} : {title}"


def _format_conflict_line(conflict: dict) -> str:
    """
    Formate ligne conflit avec émojis casquettes.

    Args:
        conflict: Dict avec {event1, event2, overlap_minutes}

    Returns:
        Ligne formatée

    Example: "• 14h30 médecin ⚡ 14h00 enseignant (1h00 chevauchement)"
    """
    event1 = conflict["event1"]
    event2 = conflict["event2"]
    overlap_minutes = conflict["overlap_minutes"]

    # Heures
    time1 = event1["start_datetime"].strftime("%Hh%M")
    time2 = event2["start_datetime"].strftime("%Hh%M")

    # Casquettes
    casquette1_label = CASQUETTE_LABEL_MAPPING[event1["casquette"]].lower()
    casquette2_label = CASQUETTE_LABEL_MAPPING[event2["casquette"]].lower()

    # Durée chevauchement
    overlap_hours = overlap_minutes // 60
    overlap_mins = overlap_minutes % 60

    if overlap_hours > 0 and overlap_mins > 0:
        overlap_str = f"{overlap_hours}h{overlap_mins:02d}"
    elif overlap_hours > 0:
        overlap_str = f"{overlap_hours}h00"
    else:
        overlap_str = f"{overlap_mins}min"

    return f"• {time1} {casquette1_label} ⚡ {time2} {casquette2_label} ({overlap_str} chevauchement)"


def format_briefing_command_response(
    date: date,
    casquette_filter: Optional[Casquette],
    events_count: int
) -> str:
    """
    Formate réponse commande /briefing (Story 4.2 à venir).

    Args:
        date: Date du briefing
        casquette_filter: Filtre casquette appliqué (ou None)
        events_count: Nombre événements trouvés

    Returns:
        Message confirmation

    Example: "✅ Briefing généré (3 événements médecin)"
    """
    weekday = WEEKDAY_LABELS[date.weekday()]
    date_str = date.strftime("%d/%m/%Y")

    if casquette_filter:
        emoji = CASQUETTE_EMOJI_MAPPING[casquette_filter]
        label = CASQUETTE_LABEL_MAPPING[casquette_filter].lower()
        return f"✅ Briefing {emoji} **{label}** généré ({events_count} événements) - {weekday} {date_str}"
    else:
        return f"✅ Briefing généré ({events_count} événements) - {weekday} {date_str}"
