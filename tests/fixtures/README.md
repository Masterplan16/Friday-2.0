# Tests Fixtures - Datasets de validation IA

**Objectif** : Créer des datasets manuels pour valider la qualité des agents IA de Friday 2.0.

**Stratégie** : Pyramide de tests — 80% unit (mocks), 15% integ (datasets), 5% E2E.

---

## 📊 **Datasets requis**

### **1. PII Samples (Anonymisation RGPD)** ✅ CRITIQUE

**Fichier** : `tests/fixtures/pii_samples.json`

**Objectif** : Valider que Presidio anonymise TOUTES les données sensibles avant LLM cloud.

**Contenu** : 20 exemples variés de PII (Personally Identifiable Information)

| Type d'entité | Exemples | Quantité min |
|---------------|----------|--------------|
| PERSON | "Jean Dupont", "Dr. Marie Martin" | 5 |
| DATE_TIME | "15/03/1980", "2026-02-05" | 3 |
| LOCATION | "123 rue de la Paix 75001 Paris" | 3 |
| PHONE_NUMBER | "0612345678", "+33 6 12 34 56 78" | 3 |
| EMAIL_ADDRESS | "jean.dupont@example.com" | 3 |
| IBAN_CODE | "FR76 1234 5678 9012 3456 7890 123" | 2 |
| MEDICAL_INFO | "Diabète type 2", "Traitement SGLT2" | 3 |

**Format JSON** :
```json
{
  "samples": [
    {
      "id": "pii_001",
      "input": "Le patient Jean Dupont, né le 15/03/1980...",
      "entities": ["PERSON", "DATE_TIME", "LOCATION", ...],
      "sensitive_values": ["Jean Dupont", "15/03/1980", ...]
    }
  ]
}
```

**Création** :
- **Responsable** : Mainteneur (fournit 20 exemples réels anonymisés)
- **Quand** : Avant Story 1.5 (Trust Layer dépend de Presidio)
- **Durée estimée** : 1-2h (collecte + formatting)

**Test associé** : `tests/integration/test_anonymization_pipeline.py`

---

### **2. Email Classification (Module Moteur Vie)** ✅ CRITIQUE

**Fichier** : `tests/fixtures/email_classification_dataset.json`

**Objectif** : Valider accuracy >85% de la classification emails.

**Contenu** : 50 emails représentatifs couvrant toutes les catégories

| Catégorie | Quantité min | Exemples sujets |
|-----------|--------------|-----------------|
| **medical** | 8 | "Résultats ECG patient", "Réunion staff médical" |
| **finance** | 8 | "Facture URSSAF", "Relevé bancaire SELARL" |
| **thesis** | 8 | "Version 3 introduction thèse Julie" |
| **legal** | 5 | "Bail cabinet échéance", "Contrat révision" |
| **personal** | 5 | "Invitation anniversaire", "Relance plombier" |
| **professional** | 8 | "Conférence SFMU 2026", "Demande expertise" |
| **spam** | 5 | "Gagnez 1000€", "Augmentez vos followers" |
| **ambiguous** | 3 | "Réunion demain" (flou) |

**Format JSON** :
```json
{
  "emails": [
    {
      "id": "email_001",
      "subject": "Résultats ECG patient Dupont",
      "text": "Bonjour, voici les résultats ECG...",
      "expected_category": "medical",
      "expected_priority": "medium",
      "min_confidence": 0.80
    }
  ]
}
```

**Création** :
- **Méthode** : Export 50 emails représentatifs depuis Thunderbird
- **Responsable** : Mainteneur (sélection + anonymisation)
- **Quand** : Avant Story 2 (module Email)
- **Durée estimée** : 2-3h (export + anonymisation + labelling)

**Test associé** : `tests/integration/test_email_classification_quality.py`

---

### **3. Document Archiviste (Renommage + Classification)** ✅ HAUTE

**Fichier** : `tests/fixtures/archiviste_dataset/`

**Objectif** : Valider renommage intelligent + classification documents.

**Contenu** : 30 documents PDF/images variés

| Type document | Quantité | Exemples |
|---------------|----------|----------|
| Factures | 10 | Plombier, électricité, matériel bureau |
| Contrats | 5 | Bail, assurance, prestation |
| Articles médicaux | 5 | PDF PubMed, HAS |
| Scans divers | 5 | Carte grise, permis, diplôme |
| Photos | 5 | Photos famille, vacances |

**Format** :
```
tests/fixtures/archiviste_dataset/
├── factures/
│   ├── scan_001.pdf (→ attendu: 2026-02-01_Facture_Plomberie_Dupont_250e.pdf)
│   └── ...
├── contrats/
│   └── ...
└── metadata.json (expected_filename, expected_category, expected_doc_type)
```

**Création** :
- **Méthode** : Collecter 30 documents existants + anonymiser
- **Responsable** : Antonio
- **Quand** : Avant Story 3 (module Archiviste)
- **Durée estimée** : 2-3h

**Test associé** : `tests/integration/test_archiviste_quality.py`

---

### **4. Finance Anomalies** ✅ HAUTE

**Fichier** : `tests/fixtures/finance_anomalies.csv`

**Objectif** : Valider détection anomalies financières (precision >90%).

**Contenu** : 100 transactions (90 normales, 10 anormales)

| Type anomalie | Quantité | Exemples |
|---------------|----------|----------|
| Facture en double | 3 | Même montant, même vendeur, dates proches |
| Dépense inhabituelle | 3 | Montant 3× supérieur à moyenne catégorie |
| Seuil trésorerie | 2 | Compte <500€ (alerte) |
| Abonnement non utilisé | 2 | Dernière utilisation >6 mois |

**Format CSV** :
```csv
date,amount,vendor,category,account,is_anomaly,anomaly_type
2026-01-15,250.50,"Plomberie Dupont",maintenance,SELARL,false,
2026-01-16,250.50,"Plomberie Dupont",maintenance,SELARL,true,duplicate
...
```

**Création** :
- **Méthode** : Export CSV bancaires SELARL + ajout anomalies synthétiques
- **Responsable** : Mainteneur (fournit CSV réel + indique anomalies connues)
- **Quand** : Avant Story 6 (module Suivi Financier)
- **Durée estimée** : 1h

**Test associé** : `tests/integration/test_finance_anomalies_quality.py`

---

### **5. Tuteur Thèse (Détection erreurs méthodologiques)** ✅ MOYENNE

**Fichier** : `tests/fixtures/thesis_extracts/`

**Objectif** : Valider détection erreurs méthodologiques (F1-score >70%).

**Contenu** : 20 extraits de thèses (500-1000 mots) avec erreurs annotées

| Type erreur | Quantité | Exemples |
|-------------|----------|----------|
| Structure IMRAD | 5 | Méthode avant introduction, etc. |
| Méthodologie | 5 | Échantillon non représentatif, biais sélection |
| Statistiques | 5 | Test inapproprié, p-value mal interprétée |
| Rédaction | 5 | Phrases passives, jargon non défini |

**Format** :
```
tests/fixtures/thesis_extracts/
├── extract_001_structure_error.md
│   (annotations: <!-- ERREUR: Introduction manquante -->)
├── extract_002_methodology_error.md
└── metadata.json (expected_errors: ["structure", "methodology", ...])
```

**Création** :
- **Méthode** : Extraits anonymisés de thèses réelles
- **Responsable** : Mainteneur (fournit 20 extraits + annote erreurs)
- **Quand** : Avant Story 7 (module Tuteur Thèse)
- **Durée estimée** : 3-4h

**Test associé** : `tests/integration/test_thesis_tutor_quality.py`

---

## 📅 **Planning de création**

| Dataset | Priorité | Deadline | Effort | Responsable |
|---------|----------|----------|--------|-------------|
| **PII Samples** | P0 | Avant Story 1.5 | 1-2h | Antonio |
| **Email Classification** | P0 | Avant Story 2 | 2-3h | Antonio |
| **Document Archiviste** | P1 | Avant Story 3 | 2-3h | Antonio |
| **Finance Anomalies** | P1 | Avant Story 6 | 1h | Antonio |
| **Tuteur Thèse** | P2 | Avant Story 7 | 3-4h | Antonio |

**Total effort estimé** : 9-13h de travail Mainteneur (collecte + anonymisation + labelling)

---

## 🛠️ **Outils de création**

### **Export emails Thunderbird**

```bash
# 1. Sélectionner 50 emails représentatifs dans Thunderbird
# 2. Clic droit → "Sauvegarder comme" → Format EML
# 3. Script Python pour convertir EML → JSON

python scripts/convert_eml_to_dataset.py \
  --input emails_export/*.eml \
  --output tests/fixtures/email_classification_dataset.json
```

### **Anonymisation batch**

```python
# scripts/anonymize_dataset.py
# Utilise Presidio pour anonymiser batch de documents/emails

python scripts/anonymize_dataset.py \
  --input tests/fixtures/raw/ \
  --output tests/fixtures/email_classification_dataset.json
```

---

## ✅ **Validation des datasets**

Chaque dataset doit passer ces checks avant commit :

1. **Format valide** : JSON parsable, schéma Pydantic respecté
2. **PII nettoyées** : Aucune donnée sensible réelle (vérif manuelle)
3. **Quantité suffisante** : Minimum requis atteint
4. **Diversité** : Toutes les catégories/cas représentés
5. **Labelling cohérent** : expected_* fields corrects

**Script de validation** :

```bash
python scripts/validate_datasets.py
# Vérifie tous les datasets dans tests/fixtures/
```

---

## 📝 **Notes**

- **Datasets = fichiers gitignored** si contiennent des données sensibles (même anonymisées)
- **Alternative** : Datasets synthétiques générés par LLM (qualité inférieure mais rapide)
- **Maintenance** : Enrichir datasets quand Friday fait une erreur en prod (feedback loop)

---

**Créé le** : 2026-02-05
**Version** : 1.0.0
