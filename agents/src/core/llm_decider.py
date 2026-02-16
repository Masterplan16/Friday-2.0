"""
LLM Décideur - Story 4.1 Task 4

LLM Décideur context-aware qui sélectionne intelligemment les checks
Heartbeat à exécuter selon le contexte actuel.

Philosophy "Silence = Bon" (AC4):
    - 80%+ du temps : retourne [] (aucun check)
    - Checks sélectionnés seulement si vraiment pertinents
    - CRITICAL : toujours (sauf si silence absolu)
    - HIGH : si pertinent contexte
    - MEDIUM : si très pertinent
    - LOW : si temps disponible ET pertinent

Usage:
    decider = LLMDecider(llm_client, redis_client)
    result = await decider.decide_checks(context, available_checks)

    # result = {"checks_to_run": ["check_id1"], "reasoning": "..."}
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import structlog
from agents.src.core.heartbeat_models import Check, CheckPriority, HeartbeatContext
from anthropic import AsyncAnthropic
from pydantic import BaseModel
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


# ============================================================================
# Models
# ============================================================================


class LLMDecisionResult(BaseModel):
    """
    Result model for LLM Decider decision.

    Attributes:
        checks_to_run: List of check IDs to execute
        reasoning: Justification for the decision
    """

    checks_to_run: List[str]
    reasoning: str


class LLMDecider:
    """
    LLM Décideur context-aware pour sélection checks Heartbeat (AC2, Task 4).

    Utilise Claude Sonnet 4.5 pour décider intelligemment quels checks
    exécuter selon contexte actuel (heure, casquette, événements, etc.).
    """

    # Circuit breaker config
    CIRCUIT_BREAKER_THRESHOLD = 3  # 3 échecs consécutifs
    CIRCUIT_BREAKER_TIMEOUT = 3600  # 1 heure

    # LLM config
    MODEL_ID = "claude-sonnet-4-5-20250929"
    TEMPERATURE = 0.3  # Décision déterministe mais flexible
    MAX_TOKENS = 500  # JSON response compact
    TIMEOUT_SECONDS = 10  # Timeout appel LLM

    def __init__(self, llm_client: AsyncAnthropic, redis_client: Redis):
        """
        Initialize LLM Décideur.

        Args:
            llm_client: Client Anthropic AsyncAnthropic
            redis_client: Redis client pour circuit breaker
        """
        self.llm_client = llm_client
        self.redis_client = redis_client

        logger.info("LLMDecider initialized", model=self.MODEL_ID)

    async def decide_checks(
        self, context: HeartbeatContext, available_checks: List[Check]
    ) -> Dict[str, Any]:
        """
        Décide quels checks exécuter selon contexte (Task 4.2).

        Args:
            context: HeartbeatContext actuel
            available_checks: Liste checks disponibles

        Returns:
            Dict avec "checks_to_run" (list[str]) et "reasoning" (str)
        """
        # Edge case : liste vide
        if not available_checks:
            return {"checks_to_run": [], "reasoning": "No checks available"}

        # Vérifier circuit breaker (Task 4.4)
        circuit_breaker_key = "heartbeat:llm_failures"
        failures = await self.redis_client.get(circuit_breaker_key)

        if failures and int(failures) >= self.CIRCUIT_BREAKER_THRESHOLD:
            logger.warning("LLM circuit breaker open, using fallback", failures=int(failures))
            return self._fallback_decision(available_checks, "Circuit breaker open")

        # Appeler LLM avec timeout
        try:
            result = await asyncio.wait_for(
                self._call_llm(context, available_checks), timeout=self.TIMEOUT_SECONDS
            )

            # Succès → reset circuit breaker
            await self.redis_client.delete(circuit_breaker_key)

            return result

        except asyncio.TimeoutError:
            logger.error("LLM decider timeout")
            await self._increment_failures(circuit_breaker_key)
            return self._fallback_decision(available_checks, "LLM timeout")

        except Exception as e:
            logger.error("LLM decider failed", error=str(e), error_type=type(e).__name__)
            await self._increment_failures(circuit_breaker_key)
            return self._fallback_decision(available_checks, f"LLM error: {str(e)}")

    async def _call_llm(
        self, context: HeartbeatContext, available_checks: List[Check]
    ) -> Dict[str, Any]:
        """
        Appelle LLM pour décision (Task 4.2).

        Args:
            context: HeartbeatContext
            available_checks: Checks disponibles

        Returns:
            Dict avec checks_to_run et reasoning

        Raises:
            Exception: Si erreur LLM ou parsing JSON
        """
        # Construire prompt (Task 4.2)
        prompt = self._build_prompt(context, available_checks)

        # Appeler Claude Sonnet 4.5
        response = await self.llm_client.messages.create(
            model=self.MODEL_ID,
            temperature=self.TEMPERATURE,
            max_tokens=self.MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parser réponse JSON
        response_text = response.content[0].text

        try:
            decision = json.loads(response_text)

            # Valider structure
            if not isinstance(decision.get("checks_to_run"), list):
                raise ValueError("checks_to_run must be a list")
            if not isinstance(decision.get("reasoning"), str):
                raise ValueError("reasoning must be a string")

            logger.info(
                "LLM decision",
                checks_count=len(decision["checks_to_run"]),
                checks=decision["checks_to_run"],
            )

            return decision

        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse LLM response", error=str(e), response=response_text)
            raise

    def _build_prompt(self, context: HeartbeatContext, available_checks: List[Check]) -> str:
        """
        Construit prompt LLM décideur (Task 4.2).

        Args:
            context: HeartbeatContext
            available_checks: Checks disponibles

        Returns:
            Prompt string
        """
        # Formater contexte actuel
        context_str = f"""**Contexte actuel:**
- Heure: {context.current_time.strftime('%H:%M')} UTC ({context.day_of_week})
- Weekend: {"Oui" if context.is_weekend else "Non"}
- Casquette active: {context.current_casquette or "Aucune"}
- Prochain événement: {self._format_next_event(context.next_calendar_event)}
- Dernière activité: {self._format_last_activity(context.last_activity_mainteneur)}"""

        # Formater checks disponibles
        checks_str = "\n".join(
            [
                f"- **{check.check_id}** (priorité: {check.priority}): {check.description}"
                for check in available_checks
            ]
        )

        # Prompt complet avec règles
        prompt = f"""Tu es l'assistant de décision du Heartbeat Engine de Friday.

{context_str}

**Checks disponibles:**
{checks_str}

**Question:** Quels checks dois-je exécuter maintenant?

**RÈGLE CRITIQUE:** 80%+ du temps, tu dois retourner checks_to_run = [] (silence).
Seuls les checks vraiment pertinents dans le contexte actuel doivent être exécutés.

**Règles de sélection:**
- CRITICAL : toujours exécuter (garanties <7j, pannes critiques)
- HIGH : exécuter si pertinent (ex: urgent_emails si casquette médecin/enseignant)
- MEDIUM : exécuter si très pertinent (ex: calendar_conflicts si événement dans 24h)
- LOW : exécuter si temps disponible ET pertinent (ex: thesis_reminders si casquette enseignant)

**Exemples:**
- 03:00 (nuit, pas d'événement proche) → [] (silence)
- 08:30 (matin, casquette médecin, événement consultation 09:00) → ["check_urgent_emails", "check_calendar_conflicts"]
- 14:00 (après-midi, casquette enseignant, pas d'email urgent récent) → [] (silence)
- 18:00 (soir, échéance cotisation dans 3j) → ["check_financial_alerts"]

**Format de réponse (JSON obligatoire) :**
{{"checks_to_run": ["check_id1", "check_id2"], "reasoning": "Justification concise de ta décision"}}

**IMPORTANT:** Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

        return prompt

    def _format_next_event(self, event: Dict[str, Any] | None) -> str:
        """Formate prochain événement pour prompt."""
        if not event:
            return "Aucun dans les 24h"

        title = event.get("title", "Unknown")
        start_time = event.get("start_time", "")

        # Parse ISO time si disponible
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
        except (ValueError, AttributeError):
            time_str = "?"

        return f"{title} à {time_str}"

    def _format_last_activity(self, activity: datetime | None) -> str:
        """Formate dernière activité pour prompt."""
        if not activity:
            return "Inconnue"

        now = datetime.now(timezone.utc)
        delta = now - activity

        if delta.total_seconds() < 3600:
            minutes = int(delta.total_seconds() / 60)
            return f"Il y a {minutes} min"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"Il y a {hours}h"
        else:
            days = int(delta.total_seconds() / 86400)
            return f"Il y a {days}j"

    def _fallback_decision(self, available_checks: List[Check], reason: str) -> Dict[str, Any]:
        """
        Décision fallback si LLM indisponible (Task 4.3).

        Fallback : HIGH + CRITICAL checks seulement

        Args:
            available_checks: Checks disponibles
            reason: Raison du fallback

        Returns:
            Dict avec checks_to_run et reasoning
        """
        fallback_checks = [
            check.check_id
            for check in available_checks
            if check.priority in [CheckPriority.CRITICAL, CheckPriority.HIGH]
        ]

        logger.warning(
            "Using fallback decision", reason=reason, fallback_checks_count=len(fallback_checks)
        )

        return {
            "checks_to_run": fallback_checks,
            "reasoning": f"Fallback mode ({reason}): HIGH + CRITICAL checks only",
        }

    async def _increment_failures(self, key: str) -> None:
        """
        Incrémente compteur échecs circuit breaker (Task 4.4).

        Args:
            key: Clé Redis pour compteur
        """
        failures = await self.redis_client.incr(key)

        if failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            # Ouvrir circuit breaker pour 1h
            await self.redis_client.expire(key, self.CIRCUIT_BREAKER_TIMEOUT)

            logger.error(
                "LLM circuit breaker opened",
                failures=failures,
                timeout_seconds=self.CIRCUIT_BREAKER_TIMEOUT,
            )
        else:
            # Expiration courte pour reset si succès
            await self.redis_client.expire(key, 300)  # 5 min
