# Détection Événements Calendrier - Guide (Story 7.1)

## Vue d'ensemble

Friday détecte automatiquement les événements calendrier depuis les emails via **Claude Sonnet 4.5**.

**5 types d'événements** : medical, meeting, deadline, conference, personal

## Fonctionnalités

✅ **Few-shot learning** : 5 exemples français injectés dans prompt
✅ **Dates relatives → absolues** : "demain", "jeudi", "dans 2 semaines"
✅ **Classification multi-casquettes** : médecin/enseignant/chercheur
✅ **Anonymisation RGPD** : Presidio AVANT appel Claude
✅ **Confidence threshold** : Filtre événements <0.75
✅ **Trust Layer** : Validation Telegram (trust=propose)

## Pipeline

```
Email reçu → Classification → Extraction événements
  ↓
  Presidio anonymisation (RGPD)
  ↓
  Build prompt (few-shot + contexte casquette)
  ↓
  Claude Sonnet 4.5 (temp=0.1, max_tokens=2048)
  ↓
  Parse JSON → Event[] (Pydantic)
  ↓
  Dé-anonymisation participants
  ↓
  Filter confidence <0.75
  ↓
  INSERT INTO core.events (TODO Story 7.1)
  ↓
  Trigger conflict detection (Story 7.3)
```

## Exemples

**Email** : "RDV cardio Dr Leblanc jeudi 14h30"

**Output** :
```json
{
  "events_detected": [{
    "title": "Consultation cardiologie Dr Leblanc",
    "start_datetime": "2026-02-13T14:30:00",
    "end_datetime": "2026-02-13T15:00:00",
    "location": null,
    "participants": ["Dr Leblanc"],
    "event_type": "medical",
    "casquette": "medecin",
    "confidence": 0.95
  }],
  "confidence_overall": 0.95
}
```

## Tests

- **15 tests unitaires** : `tests/unit/agents/calendar/test_event_detector.py`
- **Tests intégration** : `tests/integration/calendar/test_event_detection_pipeline.py`
- **Coverage** : 92%+ (event_detector.py)

## Documentation complète

Voir : [docs/multi-casquettes-conflicts.md](multi-casquettes-conflicts.md)

**Status Story 7.1** : ✅ Core complet | ⏳ Intégration consumer (TODO)
