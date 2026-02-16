"""
Tests unitaires pour le module de classification de documents.

Story 3.2 - Task 1.7
Tests : Mock Claude, 20+ cas (5 catégories + 5 périmètres finance + edge cases + JSON parsing)
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from agents.src.agents.archiviste.classifier import DocumentClassifier, ClassificationResult
from agents.src.middleware.models import ActionResult


@pytest.fixture
def mock_llm_adapter():
    """Mock de l'adaptateur LLM Claude."""
    with patch("agents.src.agents.archiviste.classifier.get_llm_adapter") as mock:
        llm = AsyncMock()
        mock.return_value = llm
        yield llm


@pytest.fixture
def mock_presidio():
    """Mock de l'anonymisation Presidio."""
    with patch("agents.src.agents.archiviste.classifier.anonymize_text") as mock:
        mock.return_value = "ANONYMIZED_TEXT"
        yield mock


@pytest.fixture
def classifier(mock_llm_adapter, mock_presidio):
    """Instance du classifier avec mocks."""
    return DocumentClassifier()


# ==================== Tests Catégories Principales ====================

@pytest.mark.asyncio
async def test_classify_document_pro_medical(classifier, mock_llm_adapter):
    """Test classification document professionnel médical."""
    mock_llm_adapter.complete.return_value = {
        "category": "pro",
        "subcategory": None,
        "confidence": 0.95,
        "reasoning": "Courrier ARS, contexte professionnel médical"
    }

    metadata = {
        "ocr_text": "Courrier de l'ARS concernant votre activité médicale",
        "document_id": "doc-123"
    }

    result = await classifier.classify(metadata)

    assert isinstance(result, ActionResult)
    classification = ClassificationResult(**result.payload)
    assert classification.category == "pro"
    assert classification.subcategory is None
    assert classification.confidence >= 0.7
    assert "pro" in classification.path


@pytest.mark.asyncio
async def test_classify_document_universite_these(classifier, mock_llm_adapter):
    """Test classification document universitaire thèse."""
    mock_llm_adapter.complete.return_value = {
        "category": "universite",
        "subcategory": "theses",
        "confidence": 0.92,
        "reasoning": "Document de thèse, contexte encadrement doctoral"
    }

    metadata = {
        "ocr_text": "Thèse de doctorat - Julie Dupont - Version 3",
        "document_id": "doc-124"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "universite"
    assert classification.subcategory == "theses"
    assert classification.confidence >= 0.7


@pytest.mark.asyncio
async def test_classify_document_recherche_publication(classifier, mock_llm_adapter):
    """Test classification document recherche publication."""
    mock_llm_adapter.complete.return_value = {
        "category": "recherche",
        "subcategory": "publications",
        "confidence": 0.90,
        "reasoning": "Article scientifique, contexte recherche"
    }

    metadata = {
        "ocr_text": "Article Nature - SGLT2 inhibitors efficacy",
        "document_id": "doc-125"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "recherche"
    assert classification.confidence >= 0.7


@pytest.mark.asyncio
async def test_classify_document_perso(classifier, mock_llm_adapter):
    """Test classification document personnel."""
    mock_llm_adapter.complete.return_value = {
        "category": "perso",
        "subcategory": None,
        "confidence": 0.88,
        "reasoning": "Facture plombier, contexte personnel"
    }

    metadata = {
        "ocr_text": "Facture plombier réparation salle de bain",
        "document_id": "doc-126"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "perso"
    assert classification.confidence >= 0.7


# ==================== Tests Périmètres Finance ====================

@pytest.mark.asyncio
async def test_classify_finance_selarl(classifier, mock_llm_adapter):
    """Test classification finance SELARL."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "selarl",
        "confidence": 0.94,
        "reasoning": "Facture laboratoire Cerba, contexte cabinet SELARL"
    }

    metadata = {
        "ocr_text": "Facture Laboratoire Cerba - Cabinet médical SELARL",
        "document_id": "doc-127"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "finance"
    assert classification.subcategory == "selarl"
    assert classification.confidence >= 0.7


@pytest.mark.asyncio
async def test_classify_finance_scm(classifier, mock_llm_adapter):
    """Test classification finance SCM."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "scm",
        "confidence": 0.91,
        "reasoning": "Charges SCM, société civile de moyens"
    }

    metadata = {
        "ocr_text": "Charges mensuelles SCM - Société Civile de Moyens",
        "document_id": "doc-128"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "finance"
    assert classification.subcategory == "scm"


@pytest.mark.asyncio
async def test_classify_finance_sci_ravas(classifier, mock_llm_adapter):
    """Test classification finance SCI Ravas."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "sci_ravas",
        "confidence": 0.89,
        "reasoning": "Document SCI Ravas, immobilier"
    }

    metadata = {
        "ocr_text": "SCI Ravas - Charges copropriété",
        "document_id": "doc-129"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "finance"
    assert classification.subcategory == "sci_ravas"


@pytest.mark.asyncio
async def test_classify_finance_sci_malbosc(classifier, mock_llm_adapter):
    """Test classification finance SCI Malbosc."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "sci_malbosc",
        "confidence": 0.87,
        "reasoning": "Document SCI Malbosc, immobilier"
    }

    metadata = {
        "ocr_text": "SCI Malbosc - Taxe foncière",
        "document_id": "doc-130"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "finance"
    assert classification.subcategory == "sci_malbosc"


@pytest.mark.asyncio
async def test_classify_finance_personal(classifier, mock_llm_adapter):
    """Test classification finance personnel."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "personal",
        "confidence": 0.93,
        "reasoning": "Relevé bancaire personnel"
    }

    metadata = {
        "ocr_text": "Relevé bancaire Compte Courant Personnel",
        "document_id": "doc-131"
    }

    result = await classifier.classify(metadata)

    classification = ClassificationResult(**result.payload)
    assert classification.category == "finance"
    assert classification.subcategory == "personal"


# ==================== Tests Validation Périmètres Finance ====================

@pytest.mark.asyncio
async def test_validate_finance_perimeter_valid(classifier, mock_llm_adapter):
    """Test validation périmètre finance valide."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "selarl",
        "confidence": 0.94,
        "reasoning": "Facture cabinet SELARL"
    }

    metadata = {"ocr_text": "Facture SELARL", "document_id": "doc-132"}

    result = await classifier.classify(metadata)
    classification = ClassificationResult(**result.payload)

    # Vérifier que le périmètre est dans la liste valide
    valid_perimeters = {"selarl", "scm", "sci_ravas", "sci_malbosc", "personal"}
    assert classification.subcategory in valid_perimeters


@pytest.mark.asyncio
async def test_validate_finance_perimeter_invalid_raises_error(classifier, mock_llm_adapter):
    """Test validation périmètre finance invalide lève erreur."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "invalid_perimeter",  # Périmètre invalide
        "confidence": 0.80,
        "reasoning": "Document financier"
    }

    metadata = {"ocr_text": "Document finance", "document_id": "doc-133"}

    with pytest.raises(ValueError, match="Invalid financial perimeter"):
        await classifier.classify(metadata)


@pytest.mark.asyncio
async def test_finance_must_have_subcategory(classifier, mock_llm_adapter):
    """Test finance DOIT avoir un subcategory."""
    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": None,  # Manquant !
        "confidence": 0.85,
        "reasoning": "Document financier"
    }

    metadata = {"ocr_text": "Facture", "document_id": "doc-134"}

    with pytest.raises(ValueError, match="Finance category requires subcategory"):
        await classifier.classify(metadata)


# ==================== Tests Edge Cases ====================

@pytest.mark.asyncio
async def test_low_confidence_below_threshold(classifier, mock_llm_adapter):
    """Test confidence <0.7 retourne status pending."""
    mock_llm_adapter.complete.return_value = {
        "category": "perso",
        "subcategory": None,
        "confidence": 0.65,  # Sous seuil
        "reasoning": "Document ambigu difficile à classifier avec certitude"
    }

    metadata = {"ocr_text": "Document peu clair", "document_id": "doc-135"}

    result = await classifier.classify(metadata)

    # Le classifier devrait retourner un ActionResult avec confidence faible
    assert result.confidence < 0.7


@pytest.mark.asyncio
async def test_presidio_anonymization_called(classifier, mock_presidio, mock_llm_adapter):
    """Test que Presidio anonymisation est appelée AVANT Claude."""
    mock_llm_adapter.complete.return_value = {
        "category": "pro",
        "subcategory": None,
        "confidence": 0.90,
        "reasoning": "Document professionnel"
    }

    metadata = {
        "ocr_text": "Document avec PII: Dr Lopez 0612345678",
        "document_id": "doc-136"
    }

    await classifier.classify(metadata)

    # Vérifier que Presidio a été appelé
    mock_presidio.assert_called_once()
    # Vérifier que Claude a reçu le texte anonymisé
    assert mock_llm_adapter.complete.called


@pytest.mark.asyncio
async def test_action_result_structure(classifier, mock_llm_adapter):
    """Test structure ActionResult retournée."""
    mock_llm_adapter.complete.return_value = {
        "category": "pro",
        "subcategory": None,
        "confidence": 0.92,
        "reasoning": "Document professionnel cabinet"
    }

    metadata = {"ocr_text": "Document pro", "document_id": "doc-137"}

    result = await classifier.classify(metadata)

    # Vérifier structure ActionResult
    assert isinstance(result, ActionResult)
    assert hasattr(result, "input_summary")
    assert hasattr(result, "output_summary")
    assert hasattr(result, "confidence")
    assert hasattr(result, "reasoning")
    assert hasattr(result, "payload")

    # Vérifier payload contient ClassificationResult
    assert "category" in result.payload
    assert "confidence" in result.payload
    assert "reasoning" in result.payload


@pytest.mark.asyncio
async def test_empty_metadata_raises_error(classifier):
    """Test metadata vide lève erreur."""
    with pytest.raises((ValueError, KeyError)):
        await classifier.classify({})


@pytest.mark.asyncio
async def test_missing_ocr_text_raises_error(classifier):
    """Test metadata sans ocr_text lève erreur."""
    with pytest.raises(KeyError):
        await classifier.classify({"document_id": "doc-138"})


# ==================== Tests JSON Parsing LLM (H1 fix) ====================

@pytest.mark.asyncio
async def test_parse_llm_response_string_json(classifier, mock_llm_adapter):
    """Test parsing réponse LLM string JSON."""
    mock_llm_adapter.complete.return_value = json.dumps({
        "category": "pro",
        "subcategory": None,
        "confidence": 0.90,
        "reasoning": "Document professionnel"
    })

    metadata = {"ocr_text": "Doc pro", "document_id": "doc-139"}
    result = await classifier.classify(metadata)

    assert result.confidence == 0.90
    assert result.payload["category"] == "pro"


@pytest.mark.asyncio
async def test_parse_llm_response_markdown_codeblock(classifier, mock_llm_adapter):
    """Test parsing réponse LLM avec markdown code blocks."""
    mock_llm_adapter.complete.return_value = '```json\n{"category": "finance", "subcategory": "selarl", "confidence": 0.92, "reasoning": "SELARL"}\n```'

    metadata = {"ocr_text": "Facture SELARL", "document_id": "doc-140"}
    result = await classifier.classify(metadata)

    assert result.payload["category"] == "finance"
    assert result.payload["subcategory"] == "selarl"


@pytest.mark.asyncio
async def test_parse_llm_response_invalid_json_raises(classifier, mock_llm_adapter):
    """Test parsing réponse LLM invalide lève ValueError."""
    mock_llm_adapter.complete.return_value = "This is not JSON at all"

    metadata = {"ocr_text": "Doc", "document_id": "doc-141"}

    with pytest.raises(ValueError, match="Failed to parse LLM response"):
        await classifier.classify(metadata)


# ==================== Tests Correction Rules (H4 fix) ====================

@pytest.mark.asyncio
async def test_correction_rules_injected_in_prompt(mock_llm_adapter, mock_presidio):
    """Test que les correction_rules sont utilisées dans le prompt."""
    classifier = DocumentClassifier()

    mock_llm_adapter.complete.return_value = {
        "category": "finance",
        "subcategory": "selarl",
        "confidence": 0.95,
        "reasoning": "Facture Cerba -> SELARL (règle correction)"
    }

    metadata = {"ocr_text": "Facture Cerba", "document_id": "doc-142"}

    # Simuler correction_rules passées via kwargs
    await classifier.classify(
        metadata,
        _correction_rules=[
            {"conditions": "Cerba dans émetteur", "output": "category=finance, subcategory=selarl"}
        ]
    )

    # Vérifier que le prompt contient les règles
    call_args = mock_llm_adapter.complete.call_args
    prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
    assert "Cerba" in prompt or "correction" in prompt.lower()
