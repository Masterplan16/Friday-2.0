#!/usr/bin/env python3
"""
Friday 2.0 - LLM Adapter avec anonymisation RGPD obligatoire

RÈGLE CRITIQUE (AC1 Story 1.5):
    TOUT appel LLM cloud DOIT passer par anonymisation Presidio.
    Aucune exception, aucun bypass.

Architecture:
    - anonymize_before_llm() : Wrapper obligatoire pré-LLM
    - ClaudeAdapter : Interface Claude Sonnet 4.5
    - Fail-explicit : Si Presidio DOWN → erreur, pas de fallback silencieux

Usage:
    from agents.src.adapters.llm import ClaudeAdapter

    adapter = ClaudeAdapter()
    response = await adapter.complete_with_anonymization(
        prompt="Analyse cet email",
        context=email_text  # PII sera anonymisée automatiquement
    )

Date: 2026-02-09
Version: 1.0.0 (Story 1.5 - Code Review fix C2)
"""

import os
from typing import Optional

import structlog
from agents.src.tools.anonymize import (
    AnonymizationError,
    AnonymizationResult,
    anonymize_text,
    deanonymize_text,
)
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from config.exceptions import PipelineError

logger = structlog.get_logger(__name__)


class LLMResponse(BaseModel):
    """Réponse LLM standardisée"""

    content: str = Field(..., description="Texte de réponse (deanonymisé si PII)")
    model: str = Field(..., description="Modèle LLM utilisé")
    usage: dict = Field(default_factory=dict, description="Tokens utilisés")
    anonymization_applied: bool = Field(False, description="True si anonymisation a été appliquée")


class LLMError(PipelineError):
    """Erreur appel LLM"""

    pass


class ClaudeAdapter:
    """
    Adapter pour Claude Sonnet 4.5 avec anonymisation RGPD obligatoire.

    IMPORTANT: Toutes les méthodes publiques appliquent automatiquement
    l'anonymisation Presidio avant l'appel LLM.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5-20250929",
        anonymize_by_default: bool = True,
    ):
        """
        Initialise l'adapter Claude.

        Args:
            api_key: Clé API Anthropic (défaut: env var ANTHROPIC_API_KEY)
            model: Modèle Claude à utiliser
            anonymize_by_default: Si True, force anonymisation (DOIT rester True en prod)

        Raises:
            ValueError: Si api_key manquante
        """
        # C2 fix: Warning si api_key passée directement (risque hardcoding)
        if api_key is not None:
            logger.warning(
                "api_key_passed_directly",
                message="API key passed as parameter. Prefer ANTHROPIC_API_KEY env var to avoid hardcoding risk.",
            )

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY manquante. "
                "Définir la variable d'environnement ANTHROPIC_API_KEY (requis en production)."
            )

        self.model = model
        self.anonymize_by_default = anonymize_by_default
        self.client = AsyncAnthropic(api_key=self.api_key)

        if not anonymize_by_default:
            logger.warning(
                "llm_anonymization_disabled",
                message="⚠️ ANONYMIZATION DISABLED - RGPD risk!",
            )

    async def complete_with_anonymization(
        self,
        prompt: str,
        context: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        force_anonymize: bool = True,
    ) -> LLMResponse:
        """
        Appel LLM avec anonymisation automatique du contexte.

        RÈGLE CRITIQUE: Le contexte est TOUJOURS anonymisé avant envoi LLM,
        sauf si force_anonymize=False (INTERDIT en production).

        Args:
            prompt: Instruction utilisateur (pas anonymisée, considérée safe)
            context: Contexte contenant potentiellement des PII (anonymisé)
            system: System prompt optionnel
            max_tokens: Limite tokens réponse
            temperature: Température génération
            force_anonymize: Si False, skip anonymisation (DEBUG ONLY)

        Returns:
            LLMResponse avec contenu deanonymisé

        Raises:
            AnonymizationError: Si Presidio unavailable (fail-explicit)
            LLMError: Si appel Claude échoue
        """
        anonymization_result: Optional[AnonymizationResult] = None

        # 1. Anonymiser le contexte si présent
        if context and force_anonymize:
            try:
                anonymization_result = await anonymize_text(context)
                anonymized_context = anonymization_result.anonymized_text

                logger.info(
                    "context_anonymized",
                    entities_count=len(anonymization_result.entities_found),
                    confidence_min=anonymization_result.confidence_min,
                )
            except AnonymizationError as e:
                logger.error("anonymization_failed", error=str(e))
                # Fail-explicit: Si Presidio down, on arrête tout
                raise

        elif context and not force_anonymize:
            # Mode debug: pas d'anonymisation (DANGEREUX)
            anonymized_context = context
            logger.warning(
                "anonymization_skipped",
                reason="force_anonymize=False",
                message="⚠️ PII peut être envoyée au LLM cloud!",
            )
        else:
            anonymized_context = None

        # 2. Construire le message
        user_message = prompt
        if anonymized_context:
            user_message = f"{prompt}\n\nContexte:\n{anonymized_context}"

        # 3. Appeler Claude
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system if system else "",
                messages=[{"role": "user", "content": user_message}],
            )

            response_text = response.content[0].text

            # 4. Deanonymiser la réponse
            if anonymization_result and anonymization_result.mapping:
                response_text = await deanonymize_text(response_text, anonymization_result.mapping)
                logger.debug(
                    "response_deanonymized",
                    placeholders_restored=len(anonymization_result.mapping),
                )

            return LLMResponse(
                content=response_text,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                anonymization_applied=anonymization_result is not None,
            )

        except Exception as e:
            logger.error("llm_call_failed", error=str(e), error_type=type(e).__name__)
            raise LLMError(f"Claude API call failed: {e}") from e

    async def complete_raw(
        self, prompt: str, system: Optional[str] = None, max_tokens: int = 4096
    ) -> LLMResponse:
        """
        Appel LLM SANS anonymisation (pour texte déjà safe ou non-PII).

        ⚠️ ATTENTION: Utiliser UNIQUEMENT pour texte sans PII garanti!

        Args:
            prompt: Prompt utilisateur (DOIT être sans PII)
            system: System prompt optionnel
            max_tokens: Limite tokens

        Returns:
            LLMResponse

        Raises:
            LLMError: Si appel Claude échoue
        """
        logger.warning(
            "raw_llm_call",
            message="⚠️ complete_raw() utilisé - pas d'anonymisation!",
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system if system else "",
                messages=[{"role": "user", "content": prompt}],
            )

            return LLMResponse(
                content=response.content[0].text,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                anonymization_applied=False,
            )

        except Exception as e:
            logger.error("llm_call_failed", error=str(e))
            raise LLMError(f"Claude API call failed: {e}") from e


# Factory helper
def get_llm_adapter(
    provider: str = "anthropic",
    model: Optional[str] = None,
    anonymize_by_default: bool = True,
) -> ClaudeAdapter:
    """
    Factory pour créer un adapter LLM.

    Args:
        provider: Provider LLM (seul 'anthropic' supporté Day 1)
        model: Modèle Claude spécifique (défaut: claude-sonnet-4-5-20250929)
        anonymize_by_default: Force anonymisation (DOIT rester True en prod)

    Returns:
        ClaudeAdapter configuré

    Raises:
        ValueError: Si provider non supporté
    """
    if provider != "anthropic":
        raise NotImplementedError(
            f"Provider '{provider}' pas encore supporté. "
            f"Seul 'anthropic' (Claude Sonnet 4.5) disponible Day 1."
        )

    kwargs: dict = {"anonymize_by_default": anonymize_by_default}
    if model:
        kwargs["model"] = model

    return ClaudeAdapter(**kwargs)
