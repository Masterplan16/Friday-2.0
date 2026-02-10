# Décision architecturale : Stockage mapping Presidio

**Date** : 2026-02-05
**Status** : ACCEPTÉE
**Décideurs** : Mainteneur Lopez, Claude Code

---

## Contexte

Friday 2.0 utilise Presidio pour anonymiser les données PII avant tout appel LLM cloud (RGPD).
Le mapping `{token_anonymisé} → valeur_originale` doit être stocké pour désanonymisation ultérieure.

**Question** : Où stocker ce mapping ? Redis éphémère (TTL court) ou PostgreSQL persistant ?

---

## Décision

**Mapping éphémère Redis avec TTL court (1 heure)**

---

## Justification

### Sécurité RGPD
- Le mapping contient des données PII sensibles (noms, emails, numéros)
- Persister ce mapping = augmenter la surface d'attaque
- TTL court = fenêtre d'exposition minimale

### Use case Friday 2.0
**Workflow typique** :
1. Email reçu → Anonymisation Presidio → Appel LLM cloud (classification)
2. Réponse LLM → Désanonymisation immédiate → Stockage PostgreSQL local
3. **Durée totale** : <30 secondes en moyenne

**Observation** : Le mapping n'est utilisé que dans la **même session de traitement**.

### Analyse besoins recherche historique
**Question** : Besoin de rechercher sur emails de >1h avec tokens anonymisés ?

**Réponse** : NON
- Une fois email traité, il est stocké **en clair** dans PostgreSQL local (pas de sortie cloud)
- Recherches futures = Requêtes directes PostgreSQL (données non anonymisées)
- Pas besoin de "re-désanonymiser" des données de >1h

---

## Implémentation

### Structure Redis
```python
# Key pattern
key = f"presidio:mapping:{anonymized_token}"
# Exemple : "presidio:mapping:[EMAIL_a3f9b2]"

# Value
value = "mainteneur.lopez@example.com"

# TTL
ttl = 3600  # 1 heure
```

### Code type
```python
# Anonymisation
async def anonymize_text(text: str) -> tuple[str, dict]:
    """Retourne (texte_anonymisé, mapping)"""
    anonymized, mapping = presidio_engine.anonymize(text)

    # Stocker mapping dans Redis avec TTL
    for token, original in mapping.items():
        await redis.setex(
            f"presidio:mapping:{token}",
            3600,  # 1h TTL
            original
        )

    return anonymized, mapping

# Désanonymisation
async def deanonymize_text(text: str) -> str:
    """Remplace tokens par valeurs originales"""
    tokens = extract_presidio_tokens(text)

    for token in tokens:
        original = await redis.get(f"presidio:mapping:{token}")
        if original:
            text = text.replace(token, original)
        else:
            logger.warning(f"Mapping expiré pour {token}")

    return text
```

---

## Trade-offs acceptés

### Limitation
- Après 1h, mapping perdu
- Impossible de "re-désanonymiser" des données de >1h via tokens

### Pourquoi c'est acceptable
1. **Données déjà traitées** : Après 1h, email déjà classé + stocké en clair dans PostgreSQL
2. **Recherche directe possible** : Requêter PostgreSQL local (pas besoin de passer par mapping)
3. **Sécurité prioritaire** : Pas de mapping PII persistant = réduction risque RGPD

### Cas limite (rare)
**Scénario** : LLM cloud met >1h à répondre (timeout, panne réseau)

**Solution** :
- Retry avec timeout court (30s max)
- Si échec après retries → Log erreur + notification Mainteneur
- Re-traiter email depuis source (PostgreSQL) si besoin

---

## Alternatives rejetées

### Alternative 1 : Stockage PostgreSQL persistant
**Problème** :
- Mapping PII persiste indéfiniment
- Surface d'attaque élargie (backup, exports, logs SQL)
- Violation principe "durée minimale de conservation" RGPD

### Alternative 2 : TTL 24h
**Problème** :
- Pas de justification métier (emails traités en <30s)
- Augmente inutilement la fenêtre d'exposition

### Alternative 3 : Aucun stockage (mapping en mémoire uniquement)
**Problème** :
- Si process crash entre anonymisation et désanonymisation → perte données
- Pas de retry possible

---

## Monitoring

### Métriques à surveiller
```python
# agents/src/middleware/presidio_metrics.py
{
    "presidio.mapping.ttl_expired": 0,  # Alerter si >10/jour
    "presidio.anonymize.duration_ms": [12, 15, 18],  # p50, p95, p99
    "presidio.deanonymize.duration_ms": [5, 8, 10]
}
```

### Alertes
- Si `ttl_expired > 10/jour` → Investiguer (LLM cloud lent ? Timeout trop court ?)
- Si `anonymize.duration_ms.p99 > 500ms` → Optimiser Presidio (batch processing ?)

---

## Tests requis

### Test nominal
```python
@pytest.mark.asyncio
async def test_presidio_mapping_roundtrip():
    """Anonymisation → Désanonymisation dans TTL"""
    text = "Appeler Mainteneur Lopez à mainteneur@example.com"

    # Anonymiser
    anonymized, mapping = await anonymize_text(text)
    assert "Mainteneur Lopez" not in anonymized
    assert "[PERSON_" in anonymized

    # Désanonymiser immédiatement
    original = await deanonymize_text(anonymized)
    assert original == text
```

### Test expiration
```python
@pytest.mark.asyncio
async def test_presidio_mapping_ttl_expired():
    """Mapping expiré après TTL"""
    text = "Email: test@example.com"

    # Anonymiser
    anonymized, _ = await anonymize_text(text)

    # Simuler expiration (avancer temps Redis)
    await redis.expire("presidio:mapping:*", -1)

    # Désanonymiser
    result = await deanonymize_text(anonymized)

    # Token non remplacé (mapping expiré)
    assert "[EMAIL_" in result
    assert "test@example.com" not in result
```

---

## Révision

Cette décision sera révisée si :
- Taux `ttl_expired` > 10/jour pendant 1 semaine
- Besoin métier de "re-désanonymiser" des données de >1h émerge
- Audit RGPD recommande approche différente

**Prochaine révision** : Story 2 (Email Agent) après 1 mois de production

---

## Références

- Architecture Friday 2.0 : `_docs/architecture-friday-2.0.md` (section 3.1 Sécurité RGPD)
- Addendum technique : `_docs/architecture-addendum-20260205.md` (section 9.1)
- Code review adversarial v2 : Finding #23
