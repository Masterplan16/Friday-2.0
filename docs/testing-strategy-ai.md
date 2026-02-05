# Stratégie de Tests IA - Friday 2.0

**Date** : 2026-02-05
**Version** : 1.1.0
**Auteur** : Architecture Friday 2.0

---

## 1. Problématique : Tester des systèmes IA non-déterministes

Les agents IA de Friday 2.0 utilisent des LLM (Mistral) qui sont **non-déterministes** :
- Même prompt + même input ≠ même output (sauf temperature=0, et encore...)
- Les hallucinations sont possibles
- La qualité varie selon le contexte

**Objectif** : Valider que les agents IA fonctionnent correctement **sans appels LLM réels** en tests unitaires.

---

## 2. Pyramide de tests Friday 2.0

```
                    /\
                   /  \
                  / E2E \ (5% - Tests manuels)
                 /------\
                /  Intég \ (15% - Avec LLM réel + datasets)
               /----------\
              /  Unitaires \ (80% - Mocks uniquement)
             /--------------\
```

### Répartition cible

| Type | % | Quantité estimée | Durée exécution | LLM réel ? |
|------|---|------------------|-----------------|------------|
| **Tests unitaires** | 80% | ~400-500 tests | <2 min | ❌ Non (mocks) |
| **Tests intégration** | 15% | ~75-100 tests | ~10-15 min | ✅ Oui (datasets) |
| **Tests E2E** | 5% | ~25-30 tests | ~30-60 min | ✅ Oui (scénarios réels) |

---

## 3. Tests Unitaires (80%) - JAMAIS de LLM réel

### Principe : Mock TOUT ce qui touche à l'IA

**INTERDIT** :
```python
# ❌ JAMAIS FAIRE ÇA EN TEST UNITAIRE
async def test_email_classifier():
    result = await mistral_client.chat("Classe cet email...")  # Appel LLM réel = ❌
```

**CORRECT** :
```python
# ✅ TOUJOURS MOCKER
@patch("agents.tools.apis.mistral.MistralClient")
async def test_email_classifier(mock_mistral):
    # Simuler la réponse du LLM
    mock_mistral.return_value.chat.return_value = MistralResponse(
        choices=[Choice(message=Message(content='{"category": "medical", "confidence": 0.95}'))]
    )

    # Tester la logique de l'agent (pas le LLM)
    result = await classify_email(mock_email)

    assert result.category == "medical"
    assert result.confidence == 0.95
    # Vérifier que le prompt était correct
    mock_mistral.return_value.chat.assert_called_once()
    call_args = mock_mistral.return_value.chat.call_args
    assert "Classe cet email" in call_args[0][0]
```

### Librairies de mocking

| Outil | Usage |
|-------|-------|
| `unittest.mock` (standard Python) | Mock fonctions, classes, attributs |
| `pytest-mock` | Fixtures pytest pour mocking |
| `responses` | Mock requêtes HTTP (API externes) |
| `fakeredis` | Mock Redis en mémoire |

### Exemples par module

#### Module Email - Classification

```python
# tests/unit/agents/test_email_agent.py
import pytest
from unittest.mock import patch, AsyncMock
from agents.src.agents.email.agent import EmailAgent, classify_email
from agents.src.models.email import Email

@pytest.fixture
def mock_email():
    return Email(
        message_id="123",
        sender="dr.martin@hospital.fr",
        subject="Résultats ECG patient Dupont",
        body_text="Bonjour, voici les résultats ECG...",
        category=None
    )

@pytest.mark.asyncio
@patch("agents.src.agents.email.agent.mistral_client")
async def test_classify_email_medical(mock_mistral, mock_email):
    """Test classification email médical"""
    # Mock réponse LLM
    mock_mistral.chat.return_value = AsyncMock(return_value={
        "category": "medical",
        "priority": "medium",
        "confidence": 0.92,
        "keywords": ["ECG", "patient", "résultats"]
    })

    # Exécution
    result = await classify_email(mock_email)

    # Assertions
    assert result.category == "medical"
    assert result.priority == "medium"
    assert result.confidence == 0.92
    assert "ECG" in result.keywords

    # Vérifier prompt
    call_args = mock_mistral.chat.call_args
    prompt = call_args[0][0]
    assert "Classe cet email" in prompt
    assert mock_email.subject in prompt

@pytest.mark.asyncio
@patch("agents.src.agents.email.agent.mistral_client")
async def test_classify_email_low_confidence_fallback(mock_mistral, mock_email):
    """Test fallback si confiance <70%"""
    # Mock réponse LLM avec faible confiance
    mock_mistral.chat.return_value = AsyncMock(return_value={
        "category": "unknown",
        "priority": "low",
        "confidence": 0.45,
        "keywords": []
    })

    result = await classify_email(mock_email)

    # Doit fallback sur catégorie "uncategorized"
    assert result.category == "uncategorized"
    assert result.priority == "low"
```

#### Module Archiviste - Renommage intelligent

```python
# tests/unit/agents/test_archiviste_agent.py
@pytest.mark.asyncio
@patch("agents.src.agents.archiviste.agent.mistral_client")
async def test_rename_document_invoice(mock_mistral):
    """Test renommage facture"""
    # Mock OCR extract
    ocr_text = "FACTURE\nPlomberie Dupont\nDate: 2026-02-01\nMontant: 250€"

    # Mock réponse LLM
    mock_mistral.chat.return_value = AsyncMock(return_value={
        "doc_type": "facture",
        "vendor": "Plomberie Dupont",
        "date": "2026-02-01",
        "amount": 250.00,
        "suggested_filename": "2026-02-01_Facture_Plomberie_Dupont_250e.pdf"
    })

    result = await rename_document(ocr_text, original_filename="scan001.pdf")

    assert result.new_filename == "2026-02-01_Facture_Plomberie_Dupont_250e.pdf"
    assert result.category == "facture"
```

---

## 4. Tests d'Intégration (15%) - Avec LLM réel + Datasets

### Principe : Valider la qualité réelle des agents IA

**Objectif** : Tester avec de **vrais appels LLM** pour valider :
- La qualité des prompts
- La robustesse face à des inputs variés
- Les edge cases réels

### Datasets de validation

Créer des datasets manuels pour chaque module :

#### Dataset Email Classification

**Fichier** : `tests/fixtures/email_classification_dataset.json`

```json
{
  "emails": [
    {
      "id": "email_medical_001",
      "subject": "Résultats ECG patient",
      "text": "Voici les résultats ECG du patient...",
      "expected_category": "medical",
      "expected_priority": "medium",
      "min_confidence": 0.80
    },
    {
      "id": "email_finance_001",
      "subject": "Facture URSSAF janvier 2026",
      "text": "Veuillez trouver ci-joint la facture...",
      "expected_category": "finance",
      "expected_priority": "high",
      "min_confidence": 0.85
    },
    {
      "id": "email_thesis_001",
      "subject": "Version 3 introduction thèse",
      "text": "Julie: Bonjour, voici la version 3...",
      "expected_category": "thesis",
      "expected_priority": "medium",
      "min_confidence": 0.75
    },
    {
      "id": "email_spam_001",
      "subject": "Gagnez 1000€ maintenant !!!",
      "text": "Cliquez ici pour gagner...",
      "expected_category": "spam",
      "expected_priority": "low",
      "min_confidence": 0.90
    },
    {
      "id": "email_ambiguous_001",
      "subject": "Réunion demain",
      "text": "On se voit demain ?",
      "expected_category": "personal",
      "expected_priority": "low",
      "min_confidence": 0.60,
      "allow_multiple_categories": ["personal", "professional"]
    }
  ]
}
```

#### Test avec dataset

```python
# tests/integration/test_email_classification_quality.py
import pytest
import json
from agents.src.agents.email.agent import classify_email
from agents.src.models.email import Email

@pytest.fixture
def email_dataset():
    with open("tests/fixtures/email_classification_dataset.json") as f:
        return json.load(f)

@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_classification_accuracy(email_dataset):
    """Test accuracy sur dataset validation"""
    correct = 0
    total = len(email_dataset["emails"])

    for test_case in email_dataset["emails"]:
        email = Email(
            message_id=test_case["id"],
            subject=test_case["subject"],
            body_text=test_case["text"]
        )

        # VRAI appel LLM
        result = await classify_email(email)

        # Vérifier catégorie
        if "allow_multiple_categories" in test_case:
            category_ok = result.category in test_case["allow_multiple_categories"]
        else:
            category_ok = result.category == test_case["expected_category"]

        # Vérifier confiance minimale
        confidence_ok = result.confidence >= test_case["min_confidence"]

        if category_ok and confidence_ok:
            correct += 1
        else:
            print(f"❌ FAILED: {test_case['id']}")
            print(f"   Expected: {test_case['expected_category']} (conf >={test_case['min_confidence']})")
            print(f"   Got: {result.category} (conf={result.confidence})")

    accuracy = correct / total
    print(f"\n📊 Accuracy: {accuracy*100:.1f}% ({correct}/{total})")

    # Assertion : accuracy >= 85%
    assert accuracy >= 0.85, f"Accuracy trop faible: {accuracy*100:.1f}% (seuil: 85%)"
```

### Métriques de qualité par module

| Module | Métrique | Seuil minimum | Dataset size |
|--------|----------|---------------|--------------|
| **Email Classification** | Accuracy | 85% | 50 emails |
| **Archiviste Renommage** | Exact match filename | 80% | 30 documents |
| **Tuteur Thèse** | F1-score (détection erreurs) | 70% | 20 extraits thèses |
| **Veilleur Droit** | Recall clauses critiques | 95% | 10 contrats |
| **Finance Anomalies** | Precision (pas de faux positifs) | 90% | 100 transactions |

---

## 5. Tests End-to-End (5%) - Scénarios réels complets

### Principe : Valider des flux utilisateur complets

**Exemples de scénarios E2E** :

#### Scénario 1 : Email → Classification → Extraction PJ → Archivage

```python
# tests/e2e/test_email_to_archive_flow.py
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_email_with_invoice_attachment_full_flow():
    """Test flow complet : Email avec PJ facture → Archivage"""

    # 1. Simuler réception email via EmailEngine webhook
    email_payload = {
        "messageId": "test_123",
        "from": {"address": "plombier@example.com"},
        "subject": "Facture intervention 2026-02-01",
        "text": "Bonjour, voici la facture...",
        "attachments": [{
            "filename": "facture.pdf",
            "contentId": "att_001"
        }]
    }

    response = await client.post("/webhook/emailengine", json=email_payload)
    assert response.status_code == 200

    # 2. Attendre traitement async (Redis pub/sub)
    await asyncio.sleep(5)  # Laisser le temps au pipeline

    # 3. Vérifier email classifié dans PostgreSQL
    email_db = await db.fetchrow(
        "SELECT * FROM ingestion.emails WHERE message_id='test_123'"
    )
    assert email_db is not None
    assert email_db['category'] == 'finance'

    # 4. Vérifier document archivé
    doc_db = await db.fetchrow(
        "SELECT * FROM ingestion.documents "
        "WHERE source_email_id = $1", email_db['id']
    )
    assert doc_db is not None
    assert doc_db['doc_type'] == 'facture'
    assert '2026-02-01' in doc_db['filename']  # Renommé intelligemment

    # 5. Vérifier événements Redis envoyés
    redis_events = await redis.lrange("test:events", 0, -1)
    assert b'email.received' in redis_events
    assert b'document.processed' in redis_events
```

---

## 6. Tests critiques obligatoires (RGPD, RAM, Trust)

### Test Presidio Anonymization (RGPD)

**Fichier** : `tests/integration/test_anonymization_pipeline.py`
**Dataset** : `tests/fixtures/pii_samples.json`

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_presidio_anonymizes_all_pii(pii_samples):
    """Test anonymisation exhaustive PII (RGPD critique)"""
    for sample in pii_samples:
        # Anonymiser
        anonymized, tokens = await anonymize_text(sample["input"], "test_context")

        # Vérifier entités sensibles anonymisées
        for entity_type in sample["entities"]:
            # Doit contenir token anonymisé
            assert f"[{entity_type}_" in anonymized, \
                f"Entity {entity_type} pas anonymisée"

        # Vérifier pas de fuite PII
        for sensitive_value in sample["sensitive_values"]:
            assert sensitive_value not in anonymized, \
                f"PII '{sensitive_value}' pas anonymisée !"

        # Vérifier mapping stocké dans PostgreSQL
        for token in tokens:
            mapping = await db.fetchrow(
                "SELECT * FROM core.anonymization_mappings "
                "WHERE anonymized_token = $1", token
            )
            assert mapping is not None

        # Vérifier dés-anonymisation réversible
        deanonymized = await deanonymize_text(anonymized, tokens)
        assert deanonymized == sample["input"], \
            "Dés-anonymisation incorrecte"
```

**Dataset PII** : `tests/fixtures/pii_samples.json`

```json
{
  "samples": [
    {
      "input": "Le patient Jean Dupont, né le 15/03/1980, habite au 123 rue de la Paix 75001 Paris. Tél: 0612345678. Email: jean.dupont@example.com",
      "entities": ["PERSON", "DATE_TIME", "LOCATION", "PHONE_NUMBER", "EMAIL_ADDRESS"],
      "sensitive_values": ["Jean Dupont", "15/03/1980", "123 rue de la Paix", "0612345678", "jean.dupont@example.com"]
    },
    {
      "input": "Mme Marie Martin a effectué un virement de 5000€ depuis son compte IBAN FR76 1234 5678 9012 3456 7890 123",
      "entities": ["PERSON", "IBAN_CODE"],
      "sensitive_values": ["Marie Martin", "FR76 1234 5678 9012 3456 7890 123"]
    }
  ]
}
```

### Test Monitoring RAM (VPS-4 48 Go)

**Fichier** : `tests/unit/supervisor/test_orchestrator.py`

```python
@pytest.mark.asyncio
async def test_ram_monitor_alerts_on_threshold():
    """Test alerte RAM si >85%"""
    monitor = RAMMonitor(total_ram_gb=48, alert_threshold_pct=85)

    # Simuler charge élevée (42 Go utilisés)
    monitor.simulate_usage(used_gb=42)

    alerts = await monitor.check()
    assert len(alerts) > 0
    assert alerts[0].level == "warning"
    assert "85%" in alerts[0].message

@pytest.mark.asyncio
async def test_all_heavy_services_fit_in_ram():
    """Test tous services lourds résidents en simultané"""
    monitor = RAMMonitor(total_ram_gb=48, alert_threshold_pct=85)

    # Charger tous services lourds
    services = ["ollama-nemo", "faster-whisper", "kokoro-tts", "surya-ocr"]
    for svc in services:
        await monitor.register_service(svc, SERVICE_RAM_PROFILES[svc].ram_gb)

    # Vérifier sous le seuil d'alerte (85% de 48 Go = 40.8 Go)
    assert monitor.total_allocated_gb <= 40.8
```

### Test Trust Layer

**Fichier** : `tests/unit/middleware/test_trust.py`

```python
@pytest.mark.asyncio
async def test_friday_action_auto_executes_and_logs(mock_db):
    """Test trust=auto : exécute + crée receipt"""

    @friday_action(module="email", action="classify", trust_default="auto")
    async def classify_test_email(email):
        return ActionResult(
            input_summary=f"Email: {email.subject}",
            output_summary="→ medical",
            confidence=0.92,
            reasoning="Keywords: ECG, patient"
        )

    result = await classify_test_email(mock_email)

    # Vérifier receipt créé
    receipt = await mock_db.fetchrow(
        "SELECT * FROM core.action_receipts ORDER BY created_at DESC LIMIT 1"
    )
    assert receipt is not None
    assert receipt['status'] == 'auto'
    assert receipt['confidence'] == 0.92

@pytest.mark.asyncio
async def test_friday_action_propose_waits_validation(mock_db, mock_telegram):
    """Test trust=propose : crée pending + envoie validation Telegram"""

    @friday_action(module="email", action="draft_reply", trust_default="propose")
    async def draft_reply_test(email):
        return ActionResult(
            input_summary=f"Email: {email.subject}",
            output_summary="Brouillon réponse généré",
            confidence=0.88,
            reasoning="Style formel adapté"
        )

    result = await draft_reply_test(mock_email)

    # Vérifier receipt pending
    receipt = await mock_db.fetchrow(
        "SELECT * FROM core.action_receipts ORDER BY created_at DESC LIMIT 1"
    )
    assert receipt['status'] == 'pending'
    assert receipt['trust_level'] == 'propose'

    # Vérifier message Telegram envoyé
    assert mock_telegram.send_message.called
    call_args = mock_telegram.send_message.call_args
    assert "inline_keyboard" in call_args[1]  # Boutons validation
```

---

## 7. Coverage & Métriques

### Coverage cible

| Composant | Coverage cible | Commande |
|-----------|----------------|----------|
| Agents IA | 70% | `pytest --cov=agents/src/agents --cov-report=html` |
| Middleware Trust | 90% | `pytest --cov=agents/src/middleware --cov-report=html` |
| Adapters | 80% | `pytest --cov=agents/src/adapters --cov-report=html` |
| Tools | 75% | `pytest --cov=agents/src/tools --cov-report=html` |
| Gateway API | 85% | `pytest --cov=services/gateway --cov-report=html` |

**Justification coverage IA < 100%** : Les agents IA ont des branches non-déterministes (gestion erreurs LLM, edge cases rares). Coverage 70-80% est réaliste.

### Métriques qualité CI

```bash
# Pre-commit hooks (automatique)
black agents/ --check
isort agents/ --check
flake8 agents/
mypy agents/ --strict

# Tests CI
pytest tests/unit -v --cov=agents --cov-report=term
pytest tests/integration -v -m "not slow"  # Tests intégration rapides
```

---

## 8. Stratégie d'exécution

### Local (développement)

```bash
# Tests unitaires uniquement (rapides, pas de LLM)
pytest tests/unit -v

# Tests intégration (avec LLM, plus lents)
pytest tests/integration -v

# Tests E2E (scénarios complets)
pytest tests/e2e -v
```

### CI/CD (GitHub Actions ou équivalent)

```yaml
# .github/workflows/tests.yml (si CI activé)
name: Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/unit --cov=agents --cov-report=xml
      - uses: codecov/codecov-action@v3  # Upload coverage

  integration-tests:
    runs-on: ubuntu-latest
    env:
      MISTRAL_API_KEY: ${{ secrets.MISTRAL_API_KEY }}
    steps:
      - uses: actions/checkout@v3
      - run: docker-compose up -d postgres redis qdrant
      - run: pytest tests/integration -v
```

---

## 9. Debugging tests IA

### Logs verbeux

```python
# Activer logs LLM en tests intégration
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("agents.tools.apis.mistral")
logger.setLevel(logging.DEBUG)

# Afficher prompts envoyés
@pytest.fixture(autouse=True)
def log_llm_calls(caplog):
    caplog.set_level(logging.DEBUG, logger="agents")
```

### Sauvegarder outputs LLM

```python
# tests/integration/test_email_classification_quality.py
@pytest.mark.integration
async def test_email_classification_with_output_dump(email_dataset, tmp_path):
    """Test avec dump des réponses LLM pour analyse"""
    outputs = []

    for test_case in email_dataset["emails"]:
        result = await classify_email(...)
        outputs.append({
            "input": test_case,
            "output": result.dict(),
            "prompt": result._prompt_used  # Si disponible
        })

    # Sauvegarder pour analyse manuelle
    output_file = tmp_path / "llm_outputs.json"
    with open(output_file, "w") as f:
        json.dump(outputs, f, indent=2)

    print(f"✅ LLM outputs saved to: {output_file}")
```

---

## 10. Maintenance & Amélioration continue

### Enrichir les datasets

Quand Friday fait une erreur en production :
1. Antonio corrige via Trust Layer
2. Ajouter le cas dans le dataset de tests intégration
3. Re-run tests → vérifier que le problème est résolu
4. Commit dataset enrichi

### Ajuster les seuils de qualité

Si accuracy < seuil sur dataset :
1. Analyser les erreurs (quels types ?)
2. Améliorer les prompts (plus de contexte, exemples, contraintes)
3. Re-tester
4. Si toujours insuffisant → augmenter le dataset ou changer de modèle LLM

---

## 11. Tests manquants identifies (review adversariale 2026-02-05)

La review adversariale du 2026-02-05 a identifie les tests suivants comme manquants dans la couverture actuelle. Ils devront etre implementes dans leurs stories respectives.

| Test | Categorie | Story | Priorite |
|------|-----------|-------|----------|
| Presidio partial anonymization failure | Integration | 1.5 | CRITIQUE |
| Mistral API rate limit handling | Integration | 2 | HAUTE |
| Ollama fallback si indisponible | Integration | 2 | HAUTE |
| Redis Streams delivery guarantee | Integration | 1 | HAUTE |
| Trust retrogradation edge cases (sample size <10) | Unit | 1.5 | MOYENNE |
| Checkpoint JSON corruption recovery | Unit | 2 | MOYENNE |
| EmailEngine token expiration detection | Integration | 2 | MOYENNE |

**Details** :

- **Presidio partial anonymization failure** : Tester le comportement quand Presidio n'anonymise que partiellement un texte (ex: detecte le nom mais pas le numero de telephone). Le pipeline doit rejeter le texte si des PII connues subsistent.
- **Mistral API rate limit handling** : Verifier que le retry exponentiel fonctionne correctement quand Mistral renvoie un 429 (rate limit). Inclure le test du backoff et du nombre maximal de retries.
- **Ollama fallback si indisponible** : Quand Ollama (LLM local) est down, verifier que le systeme bascule correctement sur Mistral cloud (avec anonymisation Presidio prealable).
- **Redis Streams delivery guarantee** : Verifier qu'un message publie dans un Stream est bien consomme meme si le consumer redemarre entre-temps (consumer groups + ACK).
- **Trust retrogradation edge cases** : Que se passe-t-il si un module n'a que 3 actions sur la semaine ? Le seuil de 90% sur 3 actions (= 1 erreur = retrogradation) est-il trop sensible ? Definir un sample size minimum.
- **Checkpoint JSON corruption recovery** : Tester la recuperation quand le fichier JSON de checkpoint de migration est corrompu (ecriture interrompue). Le script doit detecter la corruption et reprendre depuis le dernier checkpoint valide.
- **EmailEngine token expiration detection** : Verifier que le systeme detecte quand le token OAuth/IMAP d'EmailEngine expire et envoie une alerte Telegram au lieu de silencieusement echouer.

---

**Version** : 1.1.0
**Dernière mise à jour** : 2026-02-05
