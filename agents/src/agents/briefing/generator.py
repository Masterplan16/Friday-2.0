"""
Briefing Generator - Génération briefings matinaux

Story 4.2: Briefing Matinal 8h00 (à venir)
Story 7.3: Multi-casquettes & Conflits (AC3)

Fonctionnalités AC3:
- Groupement événements par casquette (médecin/enseignant/chercheur)
- Section conflits en haut si détectés
- Filtrage optionnel par casquette (/briefing medecin)
"""

from datetime import date, datetime
from typing import Optional

import asyncpg
import structlog
from agents.src.agents.briefing.templates import format_briefing_message
from agents.src.core.models import Casquette

logger = structlog.get_logger(__name__)


# ============================================================================
# Briefing Generator
# ============================================================================


class BriefingGenerator:
    """
    Générateur de briefings quotidiens avec groupement par casquette (AC3).

    Story 4.2 (à venir): Briefing complet avec météo, emails, tâches, etc.
    Story 7.3 (AC3): Groupement événements par casquette + section conflits.
    """

    def __init__(self, db_pool: asyncpg.Pool):
        """
        Initialize Briefing Generator.

        Args:
            db_pool: Pool PostgreSQL
        """
        self.db_pool = db_pool

    async def generate_morning_briefing(
        self, target_date: Optional[date] = None, filter_casquette: Optional[Casquette] = None
    ) -> str:
        """
        Génère briefing matinal avec groupement par casquette (AC3).

        Args:
            target_date: Date du briefing (défaut: aujourd'hui)
            filter_casquette: Filtre optionnel par casquette (None = toutes)

        Returns:
            Message briefing formaté Markdown

        Example:
            ```
            📋 Briefing Lundi 17 février 2026

            🩺 MÉDECIN (Matin)
            • 09h00-12h00 : 3 consultations cardiologie
            • 14h30-15h30 : Visite patient hospitalisé

            🎓 ENSEIGNANT (Après-midi)
            • 14h00-16h00 : Cours L2 Anatomie

            ⚠️ CONFLIT DÉTECTÉ : 14h30 médecin ⚡ 14h00 enseignant
            ```
        """
        if not target_date:
            target_date = datetime.now().date()

        logger.info(
            "generating_morning_briefing",
            date=str(target_date),
            filter_casquette=filter_casquette.value if filter_casquette else None,
        )

        # Récupérer événements du jour
        events = await self._get_events_for_day(target_date, filter_casquette)

        # Grouper par casquette
        grouped_events = self._group_events_by_casquette(events)

        # Récupérer conflits du jour (Story 7.3 Task 5)
        conflicts = await self._get_conflicts_for_day(target_date)

        # Formater message
        message = format_briefing_message(
            date=target_date, grouped_events=grouped_events, conflicts=conflicts
        )

        logger.info(
            "morning_briefing_generated",
            date=str(target_date),
            events_count=len(events),
            conflicts_count=len(conflicts),
        )

        return message

    # ========================================================================
    # Private Helpers
    # ========================================================================

    async def _get_events_for_day(
        self, target_date: date, filter_casquette: Optional[Casquette] = None
    ) -> list[dict]:
        """
        Récupère événements pour une journée donnée.

        Args:
            target_date: Date cible
            filter_casquette: Filtre optionnel par casquette

        Returns:
            Liste événements avec {id, title, casquette, start_datetime, end_datetime}
        """
        async with self.db_pool.acquire() as conn:
            # Query de base
            query = """
                SELECT
                    id,
                    properties->>'title' AS title,
                    properties->>'casquette' AS casquette,
                    (properties->>'start_datetime')::timestamptz AS start_datetime,
                    (properties->>'end_datetime')::timestamptz AS end_datetime
                FROM knowledge.entities
                WHERE entity_type = 'EVENT'
                  AND (properties->>'status') = 'confirmed'
                  AND DATE((properties->>'start_datetime')::timestamptz) = $1
                  AND properties->>'casquette' IS NOT NULL
            """

            params = [target_date]

            # Filtre optionnel par casquette
            if filter_casquette:
                query += " AND properties->>'casquette' = $2"
                params.append(filter_casquette.value)

            query += " ORDER BY (properties->>'start_datetime')::timestamptz ASC"

            rows = await conn.fetch(query, *params)

        events = []
        for row in rows:
            try:
                casquette = Casquette(row["casquette"])
            except ValueError:
                # Casquette invalide → skip
                continue

            events.append(
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "casquette": casquette,
                    "start_datetime": row["start_datetime"],
                    "end_datetime": row["end_datetime"],
                }
            )

        return events

    def _group_events_by_casquette(self, events: list[dict]) -> dict[Casquette, list[dict]]:
        """
        Groupe événements par casquette (AC3).

        Args:
            events: Liste événements

        Returns:
            Dict {Casquette: [événements]} trié par casquette
        """
        grouped = {Casquette.MEDECIN: [], Casquette.ENSEIGNANT: [], Casquette.CHERCHEUR: []}

        for event in events:
            casquette = event["casquette"]
            if casquette in grouped:
                grouped[casquette].append(event)

        # Tri chronologique dans chaque section (fallback si mock/DB ne trie pas)
        for casquette in grouped:
            grouped[casquette].sort(key=lambda e: e["start_datetime"])

        # Retirer casquettes vides
        return {k: v for k, v in grouped.items() if v}

    async def _get_conflicts_for_day(self, target_date: date) -> list[dict]:
        """
        Récupère conflits calendrier pour une journée (AC3).

        Note: Story 7.3 Task 5 (conflict_detector) pas encore implémenté.
        Cette méthode sera complétée lors de Task 5.

        Args:
            target_date: Date cible

        Returns:
            Liste conflits avec {event1, event2, overlap_minutes}
        """
        # TODO: Implémenter lors de Task 5 (conflict_detector)
        # from agents.src.agents.calendar.conflict_detector import detect_calendar_conflicts
        # return await detect_calendar_conflicts(target_date)

        return []  # Stub pour l'instant
