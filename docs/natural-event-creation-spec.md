# Natural Event Creation - Specification Technique

> Story 7.4 - Creation Evenements via Message Naturel Telegram

## Architecture

```
Message Telegram
    |
    v
[Intent Detection] ---- Regex patterns (verbes + temps + contexte)
    |
    v  (si intention detectee)
[Presidio Anonymisation] ---- RGPD obligatoire AVANT LLM
    |
    v
[Claude Sonnet 4.5] ---- Extraction JSON structuree (7 few-shot examples)
    |
    v
[Pydantic Validation] ---- Event model + confidence check >= 0.70
    |
    v
[Deanonymisation] ---- Restauration PII participants via mapping
    |
    v
[PostgreSQL] ---- INSERT knowledge.entities (status='proposed')
    |
    v
[Notification Telegram] ---- Inline buttons: [Creer] [Modifier] [Annuler]
    |
    v (si [Creer])
[Google Calendar Sync] ---- Story 7.2 reuse
    |
    v
[Conflict Detection] ---- Story 7.3 Allen's interval algebra
```

## Messages Naturels Supportes

| Message | Casquette Detectee | Type |
|---------|-------------------|------|
| "Ajoute RDV demain 14h" | medecin | medical |
| "Cours L2 anatomie lundi 10h amphi B" | enseignant | meeting |
| "Seminaire dans 2 semaines" | chercheur | conference |
| "Reunion jeudi 16h" | auto-detect | meeting |
| "Diner samedi soir 20h" | personnel | personal |
| "Deadline soumission article 28 fevrier" | chercheur | deadline |
| "Note consultation Dr Martin demain 9h" | medecin | medical |
| "Planifie garde week-end prochain" | medecin | medical |
| "Reserve salle TP vendredi 14h-16h" | enseignant | meeting |
| "Bloque creneaux these mercredi 8h-12h" | chercheur | other |

## Patterns Declencheurs

### Verbes
`ajoute, cree, planifie, reserve, note, programme, prevois, mets, inscris, fixe, cale, bloque`

### Indicateurs Temporels
`demain, apres-demain, lundi-dimanche, prochain(e), dans X jours/semaines/mois, HH:MM, HHh, JJ/MM(/AAAA), JJ mois`

### Contexte Evenement
`reunion, rendez-vous, rdv, consultation, cours, seminaire, conference, colloque, congres, examen, soutenance, garde, formation, atelier, workshop, diner, dejeuner, entretien, visite, permanence`

### Regle de Detection
Intention = (verbe + temps) OU (contexte + temps) OU (verbe + contexte)

## Commande /creer_event

Dialogue guide en 6 etapes avec state machine Redis (TTL 10 min):

1. **Titre** : Texte libre (2-200 chars)
2. **Date** : JJ/MM/AAAA ou JJ/MM (annee courante)
3. **Heure debut** : HH:MM ou HHhMM
4. **Heure fin** : HH:MM ou '.' pour passer
5. **Lieu** : Texte libre ou '.' pour passer
6. **Participants** : Separes par virgule ou '.' pour passer

Resume affiche avec inline buttons: [Creer] [Recommencer] [Annuler]

## Modification Evenement

Menu inline buttons: [Titre] [Date] [Heure] [Lieu] [Participants] [Valider] [Annuler]

Chaque modification stockee dans state Redis. [Valider] applique en PostgreSQL.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| CONFIDENCE_THRESHOLD | Seuil extraction | 0.70 |
| LLM_MODEL | Model Claude | claude-sonnet-4-5-20250929 |
| LLM_TEMPERATURE | Temperature extraction | 0.1 |
| LLM_MAX_TOKENS | Max tokens output | 1024 |
| MAX_RETRIES | Retries Claude API | 3 |
| STATE_TTL | TTL state Redis (sec) | 600 |

## Trust Layer

- Action `calendar.create_event_from_message` : trust = `propose`
- ActionResult obligatoire : input_summary, output_summary, confidence, reasoning
- Inline button [Creer] = approbation implicite -> trust='auto' pour confirmation

## Troubleshooting

| Symptome | Cause | Solution |
|----------|-------|----------|
| Confidence <0.70 | Message ambigu | Message Topic Chat "Je n'ai pas bien compris" |
| Circuit breaker ouvert | 3+ echecs Claude API | Attendre reset automatique |
| Google Calendar sync echec | Credentials expirees | Voir docs/google-calendar-sync.md |
| State Redis expire | >10 min sans reponse | Relancer /creer_event |
| Conflit detecte | Chevauchement horaire | Alerte Topic System automatique |

## Dependances

- Story 7.1 : Event Detection (models, prompts, patterns)
- Story 7.2 : Google Calendar Sync (write_event_to_google)
- Story 7.3 : Multi-casquettes & Conflits (ContextManager, conflict_detector)
- Story 1.5 : Presidio Anonymisation (anonymize_text)
- Story 1.6 : Trust Layer (@friday_action, ActionResult)
