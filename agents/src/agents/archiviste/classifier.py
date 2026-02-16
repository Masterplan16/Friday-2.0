"""
Module de classification de documents pour l'agent Archiviste.

Story 3.2 - Task 1 (1.1-1.7)
Classification automatique documents dans arborescence 5 catégories.

Architecture:
- Claude Sonnet 4.5 pour classification (temperature=0.3)
- Presidio anonymisation AVANT appel LLM
- Trust Layer avec @friday_action decorator
- Validation stricte périmètres finance (anti-contamination AC6)
"""

import json
from typing import Any, Dict, List, Optional

import structlog
from agents.src.adapters.llm import get_llm_adapter
from agents.src.agents.archiviste.models import ClassificationResult
from agents.src.config.arborescence_config import get_arborescence_config
from agents.src.middleware.models import ActionResult
from agents.src.middleware.trust import friday_action
from agents.src.tools.anonymize import anonymize_text

logger = structlog.get_logger(__name__)


class DocumentClassifier:
    """
    Classifie les documents dans l'arborescence Friday.

    Utilise Claude Sonnet 4.5 pour extraire category, subcategory (si finance),
    et génère le chemin relatif dans l'arborescence.

    Attributes:
        llm_adapter: Adaptateur LLM Claude Sonnet 4.5
        confidence_threshold: Seuil de confiance minimum (0.7)
    """

    def __init__(self):
        """Initialise le classifier avec l'adaptateur LLM."""
        self._llm_adapter = None
        self.confidence_threshold = 0.7

    @property
    def llm_adapter(self):
        """Lazy loading de l'adaptateur LLM."""
        if self._llm_adapter is None:
            self._llm_adapter = get_llm_adapter()
        return self._llm_adapter

    @friday_action(module="archiviste", action="classify", trust_default="propose")
    async def classify(self, metadata: Dict[str, Any], **kwargs) -> ActionResult:
        """
        Classifie un document dans l'arborescence Friday.

        Le classifier retourne le résultat avec la confidence telle que
        renvoyée par le LLM. Le seuil de confidence (0.7) est appliqué
        par le pipeline orchestrateur (ClassificationPipeline) qui décide
        si le document est déplacé ou mis en pending.

        Args:
            metadata: Dictionnaire contenant:
                - ocr_text: Texte OCR extrait du document
                - document_id: ID unique du document
            **kwargs: Decorator-injected arguments (e.g., _correction_rules)

        Returns:
            ActionResult avec:
                - input_summary: Résumé du document à classifier
                - output_summary: Catégorie et chemin calculé
                - confidence: Score de confiance Claude
                - reasoning: Explication de la classification
                - payload: ClassificationResult complet

        Raises:
            KeyError: Si ocr_text ou document_id manquant
            ValueError: Si périmètre finance invalide ou réponse LLM non-parseable
        """
        # Validation input
        if "ocr_text" not in metadata:
            raise KeyError("Missing required field: ocr_text")
        if "document_id" not in metadata:
            raise KeyError("Missing required field: document_id")

        ocr_text = metadata["ocr_text"]
        document_id = metadata["document_id"]

        logger.info("classification_started", document_id=document_id, text_length=len(ocr_text))

        # Anonymisation Presidio AVANT appel Claude (RGPD critique)
        anonymized_text = await anonymize_text(ocr_text)

        # Extraire correction_rules injectées par @friday_action
        correction_rules = kwargs.get("_correction_rules", [])

        # Prompt Claude Sonnet 4.5 pour extraction
        prompt = self._build_classification_prompt(anonymized_text, correction_rules)

        # Appel LLM
        response_raw = await self.llm_adapter.complete(
            prompt=prompt,
            temperature=0.3,  # Classification = déterministe
            max_tokens=200,  # Réponse courte structurée
        )

        # Parsing JSON de la réponse LLM
        response = self._parse_llm_response(response_raw)

        # Extraction réponse structurée
        category = response.get("category")
        subcategory = response.get("subcategory")
        confidence = response.get("confidence", 0.0)
        reasoning = response.get("reasoning", "")

        # Ensure reasoning meets minimum length requirement (20 chars)
        if len(reasoning) < 20:
            reasoning = f"Classification: {category}" + (f"/{subcategory}" if subcategory else "")

        logger.info(
            "classification_completed",
            document_id=document_id,
            category=category,
            subcategory=subcategory,
            confidence=confidence,
        )

        # Validation périmètre finance (AC6 - Anti-contamination)
        if category == "finance":
            if subcategory is None:
                raise ValueError("Finance category requires subcategory")

            valid_finance_perimeters = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}

            if subcategory not in valid_finance_perimeters:
                raise ValueError(
                    f"Invalid financial perimeter '{subcategory}'. "
                    f"Must be one of: {valid_finance_perimeters}"
                )

        # Calcul du chemin relatif via ArborescenceConfig
        path = self._compute_relative_path(category, subcategory)

        # Construction ClassificationResult
        classification = ClassificationResult(
            category=category,
            subcategory=subcategory,
            path=path,
            confidence=confidence,
            reasoning=reasoning,
        )

        # Construction ActionResult
        return ActionResult(
            input_summary=f"Document {document_id} ({len(ocr_text)} chars OCR)",
            output_summary=f"→ {category}"
            + (f"/{subcategory}" if subcategory else "")
            + f" ({path})",
            confidence=confidence,
            reasoning=reasoning,
            payload=classification.model_dump(),
        )

    def _parse_llm_response(self, response_raw) -> Dict[str, Any]:
        """
        Parse la réponse LLM en dict JSON.

        Gère les cas où la réponse est déjà un dict (mock tests)
        ou une string JSON (API réelle).

        Args:
            response_raw: Réponse brute de l'adaptateur LLM

        Returns:
            Dict avec category, subcategory, confidence, reasoning

        Raises:
            ValueError: Si la réponse ne peut pas être parsée en JSON
        """
        if isinstance(response_raw, dict):
            return response_raw

        if isinstance(response_raw, str):
            text = response_raw.strip()
            # Nettoyer markdown code blocks si présents
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines).strip()

            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                logger.error("llm_response_parse_error", response_preview=text[:200], error=str(e))
                raise ValueError(f"Failed to parse LLM response as JSON: {e}") from e

        raise ValueError(f"Unexpected LLM response type: {type(response_raw)}")

    def _build_classification_prompt(
        self, ocr_text: str, correction_rules: Optional[List] = None
    ) -> str:
        """
        Construit le prompt pour Claude Sonnet 4.5.

        Args:
            ocr_text: Texte OCR anonymisé du document
            correction_rules: Règles de correction injectées par @friday_action

        Returns:
            Prompt structuré pour extraction catégorie + subcategory
        """
        # Section correction rules si disponibles (feedback loop)
        rules_section = ""
        if correction_rules:
            rules_lines = []
            for rule in correction_rules:
                conditions = rule.get("conditions", "")
                output = rule.get("output", "")
                rules_lines.append(f"- Si {conditions} → {output}")
            rules_section = (
                "\n**Règles de correction prioritaires (applique-les EN PREMIER) :**\n"
                + "\n".join(rules_lines)
                + "\n"
            )

        # Tronquer OCR text pour économiser tokens
        truncated_text = ocr_text[:1000]

        prompt = f"""Tu es un assistant de classification de documents pour Friday, l'assistant personnel d'Antonio (médecin, enseignant universitaire, chercheur).

Analyse le texte OCR ci-dessous et classifie le document dans UNE des 5 catégories principales :

**Catégories principales :**
1. **pro** : Documents professionnels cabinet médical (courriers ARS, dossiers patients anonymisés, administratif cabinet)
2. **finance** : Documents financiers (factures, relevés, charges) — OBLIGATOIRE de préciser le périmètre
3. **universite** : Documents universitaires (encadrement thèses, cours, examens)
4. **recherche** : Documents recherche (publications, projets, communications scientifiques)
5. **perso** : Documents personnels (famille, voyages, divers)

**Périmètres finance (OBLIGATOIRE si category=finance) :**
- **selarl** : Cabinet médical SELARL
- **scm** : SCM (Société Civile de Moyens)
- **sci_ravas** : SCI Ravas (immobilier)
- **sci_malbosc** : SCI Malbosc (immobilier)
- **personal** : Finances personnelles
{rules_section}
**Texte OCR du document :**
```
{truncated_text}
```

**Instructions :**
1. Identifie la catégorie principale en analysant le contexte (émetteur, objet, contenu)
2. Si category=finance, tu DOIS extraire le périmètre exact (selarl, scm, sci_ravas, sci_malbosc, personal)
3. Attribue un score de confiance entre 0.0 et 1.0
4. Explique ta décision de classification

**Format de réponse (JSON strict) :**
{{
  "category": "finance",
  "subcategory": "selarl",
  "confidence": 0.94,
  "reasoning": "Facture Laboratoire Cerba adressée au cabinet médical SELARL"
}}

Réponds UNIQUEMENT avec le JSON, sans texte additionnel."""

        return prompt

    def _compute_relative_path(self, category: str, subcategory: str | None) -> str:
        """
        Calcule le chemin relatif via ArborescenceConfig.

        Utilise la configuration YAML au lieu de hardcoder les chemins.

        Args:
            category: Catégorie principale
            subcategory: Sous-catégorie (obligatoire pour finance)

        Returns:
            Chemin relatif (ex: "finance/selarl", "pro", "universite/theses")
        """
        try:
            config = get_arborescence_config()
            return config.get_category_path(category, subcategory)
        except (KeyError, FileNotFoundError):
            # Fallback si config indisponible
            if subcategory:
                return f"{category}/{subcategory}"
            return category
