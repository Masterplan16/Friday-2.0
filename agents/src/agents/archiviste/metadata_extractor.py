"""
Extraction de métadonnées depuis texte OCR via Claude Sonnet 4.5 (Story 3.1 - Task 2).

Pipeline RGPD strict (AC6) :
1. Anonymiser texte OCR via Presidio
2. Extraire métadonnées via Claude (texte anonymisé)
3. Déanonymiser émetteur si nécessaire
4. Retourner ActionResult avec confidence

Trust Layer: @friday_action avec trust=propose (Day 1).
"""

import json
from datetime import datetime
from typing import Optional

import structlog

from agents.src.agents.archiviste.models import MetadataExtraction, OCRResult
from agents.src.middleware.trust import friday_action
from agents.src.middleware.models import ActionResult
from agents.src.adapters.llm import get_llm_adapter
from agents.src.tools.anonymize import anonymize_text, deanonymize_text

logger = structlog.get_logger(__name__)


class MetadataExtractor:
    """
    Extracteur de métadonnées depuis texte OCR (AC3).

    Utilise Claude Sonnet 4.5 pour extraire :
    - Date du document
    - Type (Facture, Courrier, Garantie, etc.)
    - Émetteur/Expéditeur
    - Montant (EUR)

    RGPD strict : Texte OCR anonymisé via Presidio AVANT appel Claude.
    """

    # Prompt Claude pour extraction métadonnées (Task 2.4)
    EXTRACTION_PROMPT_TEMPLATE = """
Tu es un assistant spécialisé dans l'extraction de métadonnées depuis des documents OCR.

Analyse le texte OCR suivant et extrait les métadonnées au format JSON :

```
{ocr_text}
```

Nom du fichier original : {filename}

Extraction requise (format JSON strict) :
{{
    "date": "YYYY-MM-DD",  // Date du document (si absente, utilise la date du jour)
    "doc_type": "Type",    // Type: Facture, Courrier, Garantie, Contrat, Releve, Attestation, Inconnu
    "emitter": "Émetteur", // Nom de l'émetteur/expéditeur (sanitisé si caractères spéciaux)
    "amount": 0.0,         // Montant en EUR (0.0 si absent)
    "confidence": 0.0,     // Score de confiance 0.0-1.0
    "reasoning": "..."     // Explication brève de ta décision
}}

Règles :
- La date DOIT être au format ISO 8601 (YYYY-MM-DD)
- Si la date est absente ou illisible, utilise la date du jour : {today_date}
- Le type DOIT être l'un des suivants : Facture, Courrier, Garantie, Contrat, Releve, Attestation, Inconnu
- L'émetteur DOIT être un nom court (max 50 caractères)
- Le montant DOIT être un nombre (0.0 si absent)
- La confidence DOIT refléter la qualité de l'OCR et la clarté des informations
- Le reasoning DOIT expliquer ta décision en 1-2 phrases

Réponds UNIQUEMENT avec le JSON, sans texte avant ou après.
"""

    @friday_action(module="archiviste", action="extract_metadata", trust_default="propose")
    async def extract_metadata(self, ocr_result: OCRResult, filename: str, **kwargs) -> ActionResult:
        """
        Extraire métadonnées depuis résultat OCR (AC3, AC6).

        Pipeline RGPD strict :
        1. Anonymiser texte OCR via Presidio (NFR6, NFR7)
        2. Appeler Claude Sonnet 4.5 pour extraction
        3. Déanonymiser émetteur
        4. Valider et retourner ActionResult

        Args:
            ocr_result: Résultat OCR Surya
            filename: Nom du fichier original

        Returns:
            ActionResult avec MetadataExtraction dans payload

        Raises:
            NotImplementedError: Si Presidio ou Claude crash (fail-explicit AC7)
        """
        logger.info(
            "extract_metadata.start",
            filename=filename,
            ocr_confidence=ocr_result.confidence,
            ocr_length=len(ocr_result.text),
        )

        try:
            # 1. Anonymiser texte OCR via Presidio (AC6, NFR6)
            try:
                anonymized_text, mapping = await anonymize_text(ocr_result.text)
                logger.debug(
                    "extract_metadata.anonymized",
                    entities_count=len(mapping),
                    entities_types=list(set(k.split("_")[0] for k in mapping.keys())),
                )
            except Exception as e:
                # Fail-explicit (AC7) : Si Presidio crash
                logger.error("extract_metadata.presidio_failure", error=str(e))
                raise NotImplementedError(f"Presidio anonymization unavailable: {str(e)}") from e

            # 2. Préparer prompt Claude avec texte anonymisé
            today_date = datetime.now().strftime("%Y-%m-%d")
            prompt = self.EXTRACTION_PROMPT_TEMPLATE.format(
                ocr_text=anonymized_text, filename=filename, today_date=today_date
            )

            # 3. Appeler Claude Sonnet 4.5 (AC3, Decision D17)
            try:
                llm = get_llm_adapter()
                response = await llm.complete(
                    prompt=prompt,
                    temperature=0.1,  # Extraction = déterministe
                    max_tokens=300,  # Métadonnées courtes
                    model="claude-sonnet-4-5-20250929",
                )

                logger.debug(
                    "extract_metadata.claude_response",
                    input_tokens=response.usage.input_tokens if hasattr(response, "usage") else 0,
                    output_tokens=response.usage.output_tokens if hasattr(response, "usage") else 0,
                )

            except Exception as e:
                # Fail-explicit (AC7) : Si Claude crash
                logger.error("extract_metadata.claude_failure", error=str(e))
                raise NotImplementedError(f"Claude API unavailable: {str(e)}") from e

            # 4. Parser réponse JSON Claude (Task 2.5)
            try:
                # Extraire JSON de la réponse (Claude peut ajouter du texte autour)
                content = response.content.strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                metadata_dict = json.loads(content)

                # Parser date
                date = datetime.fromisoformat(metadata_dict["date"])

                # Déanonymiser émetteur si nécessaire (Task 2.3)
                emitter = metadata_dict["emitter"]
                if any(placeholder in emitter for placeholder in mapping.keys()):
                    emitter = await deanonymize_text(emitter, mapping)

                # Créer MetadataExtraction (Task 2.5)
                metadata = MetadataExtraction(
                    date=date,
                    doc_type=metadata_dict["doc_type"],
                    emitter=emitter,
                    amount=float(metadata_dict.get("amount", 0.0)),
                    confidence=float(metadata_dict["confidence"]),
                    reasoning=metadata_dict["reasoning"],
                )

                # 5. Calculer confidence globale (AC5)
                # Confidence = min(OCR confidence, Claude confidence)
                global_confidence = min(ocr_result.confidence, metadata.confidence)

                # 6. Construire ActionResult (Task 2.6)
                action_result = ActionResult(
                    input_summary=f"OCR de {filename} ({ocr_result.page_count} pages, conf={ocr_result.confidence:.2f})",
                    output_summary=f"Métadonnées: {metadata.doc_type} de {metadata.emitter}, {metadata.amount}EUR, date={metadata.date.strftime('%Y-%m-%d')}",
                    confidence=global_confidence,
                    reasoning=metadata.reasoning,
                    payload={
                        "metadata": metadata.model_dump(mode='json') if hasattr(metadata, 'model_dump') else metadata.dict(),
                        "ocr_result": ocr_result.model_dump(mode='json') if hasattr(ocr_result, 'model_dump') else ocr_result.dict(),
                        "filename": filename,
                        "anonymized_text": anonymized_text,
                    },
                )

                logger.info(
                    "extract_metadata.success",
                    filename=filename,
                    doc_type=metadata.doc_type,
                    emitter=metadata.emitter,
                    amount=metadata.amount,
                    confidence=global_confidence,
                )

                return action_result

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(
                    "extract_metadata.parse_failure", error=str(e), claude_response=content[:200]
                )
                raise NotImplementedError(f"Failed to parse Claude response: {str(e)}") from e

        except NotImplementedError:
            # Re-raise NotImplementedError (fail-explicit)
            raise

        except Exception as e:
            # Autre erreur inattendue
            logger.error("extract_metadata.unexpected_error", error=str(e))
            raise NotImplementedError(f"Metadata extraction failed: {str(e)}") from e
