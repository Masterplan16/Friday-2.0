# Heartbeat Engine - Spécification Technique Complète

**Story** : 4.1 - Heartbeat Engine Core
**Version** : 1.0.0
**Date** : 2026-02-16
**Auteur** : Claude Sonnet 4.5

---

## Table des Matières

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Flow Diagram](#flow-diagram)
4. [Composants Core](#composants-core)
5. [Check Registry Pattern](#check-registry-pattern)
6. [LLM Décideur](#llm-décideur)
7. [Quiet Hours & Silence Rate](#quiet-hours--silence-rate)
8. [Configuration & Deployment](#configuration--deployment)
9. [Checks Day 1](#checks-day-1)
10. [Notifications Telegram](#notifications-telegram)
11. [Metrics & Monitoring](#metrics--monitoring)
12. [Troubleshooting](#troubleshooting)
13. [Extension & Développement](#extension--développement)

---

## Vue d'ensemble

### Qu'est-ce que le Heartbeat Engine ?

Le **Heartbeat Engine** est le système d'intelligence proactive de Friday 2.0. Il exécute périodiquement des **checks** contextuels pour détecter des situations nécessitant l'attention du Mainteneur (emails urgents, échéances financières, relances thésards, etc.).

### Philosophie : Silence = Bon Comportement

**Règle d'or** : 80%+ des cycles doivent être **silencieux** (0 notification).

- ✅ **Silence** : Aucune situation urgente détectée → Mainteneur non dérangé
- ⚠️ **Notification** : Situation pertinente détectée → Notification ciblée Telegram

**Rationale** : Éviter la fatigue notificationnelle. Friday ne notifie que lorsque **vraiment nécessaire**.

### Caractéristiques Clés

- **Context-aware** : Sélection checks adaptée au contexte (casquette, heure, calendrier)
- **LLM-powered** : Claude Sonnet 4.5 décide quels checks exécuter selon contexte
- **Quiet Hours** : 22h-8h UTC → seuls checks CRITICAL exécutés
- **Circuit Breaker** : 3 échecs consécutifs → check disabled 1h + alerte System
- **Trust Layer** : Intégration `@friday_action` pour observability complète
- **Resilient** : 1 check crash n'arrête pas les autres (isolation)
- **Metrics** : Silence rate calculé sur 7j (target ≥80%)

---

## Architecture

### Stack Complet

```
┌─────────────────────────────────────────────────────────────────┐
│                      HeartbeatEngine                            │
│  (Orchestrateur principal - cycle toutes les 30 min)           │
└──────────────────┬──────────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
   ┌────▼────┐         ┌──────▼──────┐
   │ Context │         │  Check      │
   │Provider │         │  Executor   │
   └────┬────┘         └──────┬──────┘
        │                     │
        │              ┌──────▼──────┐
        │              │  Check      │
        │              │  Registry   │
        │              └──────┬──────┘
        │                     │
   ┌────▼────┐         ┌──────▼──────┐
   │   LLM   │         │  3 Checks   │
   │Décideur │         │   Day 1     │
   └─────────┘         └─────────────┘
        │
        │ (Claude Sonnet 4.5)
        ▼
   Selection checks
   context-aware
```

### Composants Principaux

| Composant | Rôle | Fichier |
|-----------|------|---------|
| **HeartbeatEngine** | Orchestrateur cycle complet | `agents/src/core/heartbeat_engine.py` |
| **ContextProvider** | Fournit contexte Mainteneur | `agents/src/core/context_provider.py` |
| **LLMDecider** | Sélection intelligente checks | `agents/src/core/llm_decider.py` |
| **CheckExecutor** | Exécution checks avec isolation | `agents/src/core/check_executor.py` |
| **CheckRegistry** | Registry singleton checks | `agents/src/core/check_registry.py` |
| **Checks Day 1** | 3 checks initiaux | `agents/src/core/checks/*.py` |

### Dépendances Externes

- **PostgreSQL** : Persistence metrics (`core.heartbeat_metrics`)
- **Redis** : Circuit breakers, cache context
- **Claude Sonnet 4.5** : Décision intelligente checks
- **Telegram Bot** : Notifications Topic Chat & Proactive, System

---

## Flow Diagram

### Cycle Heartbeat Complet

```
[START] HeartbeatEngine.run_heartbeat_cycle()
   │
   ├─► 1. ContextProvider.get_current_context()
   │      ├─ Current time, day of week, weekend
   │      ├─ Quiet hours (22h-8h)
   │      ├─ Casquette courante (médecin/enseignant/chercheur)
   │      ├─ Prochain événement calendrier
   │      └─ Dernière activité Mainteneur
   │
   ├─► 2. Check Quiet Hours
   │      │
   │      ├─[Quiet Hours = TRUE]─► Filtrer checks → Garder CRITICAL only
   │      │                         Skip LLM Décideur
   │      │                         │
   │      └─[Quiet Hours = FALSE]─► 3. LLMDecider.decide_checks()
   │                                   ├─ Prompt avec contexte complet
   │                                   ├─ Liste checks disponibles (priority, description)
   │                                   ├─ Règle 80% silence
   │                                   └─ Returns: {checks_to_run: [...], reasoning: "..."}
   │
   ├─► 4. CheckExecutor.execute_check() pour chaque check sélectionné
   │      │
   │      ├─ Check circuit breaker (disabled?)
   │      ├─ Execute check function (isolation try/except)
   │      ├─ Returns CheckResult {notify: bool, message: str, action: str}
   │      └─ Increment failures si error → Open circuit breaker si ≥3
   │
   ├─► 5. Pour chaque CheckResult avec notify=True
   │      │
   │      └─ _send_notification()
   │         ├─ Format message Heartbeat
   │         ├─ Create inline keyboard si action définie
   │         └─ Send to Topic Chat & Proactive
   │
   ├─► 6. _save_metrics()
   │      ├─ Insert into core.heartbeat_metrics
   │      ├─ cycle_timestamp, checks_selected, checks_executed, checks_notified
   │      ├─ llm_decision_reasoning, duration_ms, error
   │      └─ Calculate silence_rate sur 7j (SELECT core.calculate_silence_rate(7))
   │
   └─► [END] Return result {status, checks_executed, checks_notified, duration_ms}
```

### Quiet Hours Logic

```
is_quiet_hours = (current_hour >= 22 OR current_hour < 8)

IF is_quiet_hours:
    selected_checks = [check for check in all_checks if check.priority == CRITICAL]
    skip_llm = TRUE
ELSE:
    selected_checks = await llm_decider.decide_checks(context, all_checks)
    skip_llm = FALSE
```

**Rationale** : Mainteneur dort → notifications inutiles. Seules situations **critiques** justifient réveil (panne système, garantie expire demain, etc.).

---

## Composants Core

### HeartbeatEngine

**Fichier** : `agents/src/core/heartbeat_engine.py`

**Responsabilités** :
- Orchestrer cycle complet (Context → LLM → Checks → Notifications → Metrics)
- Gestion quiet hours
- Isolation erreurs (1 check crash n'arrête pas cycle)
- Sauvegarde metrics PostgreSQL
- Support 2 modes : `daemon` (boucle infinie) et `one-shot` (cron)

**API Principale** :

```python
class HeartbeatEngine:
    async def run_heartbeat_cycle(
        self,
        mode: str = "one-shot",  # "one-shot" | "daemon"
        interval_minutes: Optional[int] = None  # Pour mode daemon
    ) -> Dict[str, Any]:
        """
        Exécute cycle(s) Heartbeat.

        Returns:
            {
                "status": "success" | "error" | "partial_success",
                "checks_executed": int,
                "checks_notified": int,
                "duration_ms": int,
                "llm_reasoning": str,
                "selected_checks": List[str],
                "error": Optional[str]
            }
        """
```

**Modes** :
- **daemon** : Boucle infinie, cycle toutes les `interval_minutes` (default 30)
- **one-shot** : 1 cycle puis exit (utilisé par endpoint Gateway `/api/v1/heartbeat/trigger`)

### ContextProvider

**Fichier** : `agents/src/core/context_provider.py`

**Responsabilités** :
- Agréger contexte Mainteneur depuis ContextManager (Story 7.3)
- Détecter quiet hours
- Récupérer prochain événement calendrier
- Retourner `HeartbeatContext` standardisé

**API** :

```python
class ContextProvider:
    async def get_current_context(self) -> HeartbeatContext:
        """
        Génère contexte Heartbeat.

        Returns:
            HeartbeatContext {
                current_time: datetime,
                day_of_week: str,
                is_weekend: bool,
                is_quiet_hours: bool,
                current_casquette: Optional[str],  # medecin | enseignant | chercheur
                next_calendar_event: Optional[dict],
                last_activity_mainteneur: Optional[datetime]
            }
        """
```

**Intégration Story 7.3** : `ContextProvider` utilise `ContextManager` pour récupérer casquette courante depuis `core.user_context`.

### CheckExecutor

**Fichier** : `agents/src/core/check_executor.py`

**Responsabilités** :
- Exécuter checks avec **isolation** (try/except par check)
- Gérer **circuit breaker** (3 échecs → disable 1h)
- Envoyer alertes System si circuit breaker ouvert

**Circuit Breaker Logic** :

```python
CIRCUIT_BREAKER_THRESHOLD = 3  # 3 échecs consécutifs
CIRCUIT_BREAKER_TIMEOUT = 3600  # 1 heure

# Redis keys
check:failures:{check_id}  # Counter (TTL 5 min)
check:disabled:{check_id}  # Flag (TTL 1h)

# Workflow
1. Increment failures on error: INCR check:failures:{check_id}
2. If failures >= 3:
   - SETEX check:disabled:{check_id} 3600 "1"
   - Send alert System: "Check '{check_id}' disabled for 1h (3 failures)"
3. Reset failures on success: DEL check:failures:{check_id}
```

**API** :

```python
class CheckExecutor:
    async def execute_check(self, check_id: str) -> CheckResult:
        """
        Exécute check par ID avec isolation et circuit breaker.

        Returns:
            CheckResult {
                notify: bool,
                message: Optional[str],
                action: Optional[str],
                payload: Optional[dict],
                error: Optional[str]
            }
        """
```

---

## Check Registry Pattern

### Architecture Extensible

Le **CheckRegistry** est un **singleton** qui centralise tous les checks disponibles. Pattern extensible pour ajouter facilement nouveaux checks.

**Fichier** : `agents/src/core/check_registry.py`

### Modèle Check

```python
from dataclasses import dataclass
from enum import Enum

class CheckPriority(str, Enum):
    CRITICAL = "CRITICAL"  # Toujours exécuté (même quiet hours)
    HIGH = "HIGH"          # Contexte pertinent requis
    MEDIUM = "MEDIUM"      # Contexte très pertinent requis
    LOW = "LOW"            # Temps disponible + pertinent

@dataclass
class Check:
    check_id: str           # ID unique (ex: "check_urgent_emails")
    priority: CheckPriority
    description: str        # Description pour LLM prompt
    execute: Callable       # Fonction async check
```

### Enregistrer Check

```python
# agents/src/core/checks/__init__.py
from .urgent_emails import check_urgent_emails
from .financial_alerts import check_financial_alerts
from .thesis_reminders import check_thesis_reminders

def register_all_checks(registry: CheckRegistry):
    """Enregistre tous les checks disponibles."""

    # Check 1: Urgent Emails (HIGH)
    registry.register(
        check_id="check_urgent_emails",
        priority=CheckPriority.HIGH,
        description="Emails urgents non lus (cabinet médical, faculty)",
        execute_fn=check_urgent_emails
    )

    # Check 2: Financial Alerts (MEDIUM)
    registry.register(
        check_id="check_financial_alerts",
        priority=CheckPriority.MEDIUM,
        description="Échéances financières <7j (SELARL, SCM, SCI)",
        execute_fn=check_financial_alerts
    )

    # Check 3: Thesis Reminders (LOW)
    registry.register(
        check_id="check_thesis_reminders",
        priority=CheckPriority.LOW,
        description="Thésards sans contact depuis 14j",
        execute_fn=check_thesis_reminders
    )
```

### Ajouter Nouveau Check

**1. Créer fichier check** : `agents/src/core/checks/my_new_check.py`

```python
"""
Check My New Feature - Story X.Y Task Z

Description détaillée du check.
Requête SQL ou logique métier.
Trust level : auto/propose/blocked.
"""

import asyncpg
import structlog
from agents.src.middleware.trust import friday_action
from agents.src.core.heartbeat_models import CheckResult

logger = structlog.get_logger(__name__)

@friday_action(module="heartbeat", action="check_my_feature", trust_default="auto")
async def check_my_feature(db_pool: asyncpg.Pool) -> CheckResult:
    """
    Check my feature description.

    Priority: HIGH | MEDIUM | LOW | CRITICAL
    Trust: auto (notification seule)

    Returns:
        CheckResult avec notify=True si condition détectée
    """
    try:
        async with db_pool.acquire() as conn:
            # Query DB ou logique métier
            count = await conn.fetchval("SELECT COUNT(*) FROM ...")

        if count == 0:
            # Silence = bon comportement
            return CheckResult(notify=False)

        # Formater message
        message = f"🔔 {count} item(s) nécessitent attention"

        logger.info("my_feature_detected", count=count)

        return CheckResult(
            notify=True,
            message=message,
            action="view_my_feature",  # Action inline button
            payload={
                "check_id": "check_my_feature",
                "count": count
            }
        )

    except Exception as e:
        logger.error("check_my_feature failed", error=str(e))
        return CheckResult(
            notify=False,
            error=f"Failed to check my feature: {str(e)}"
        )
```

**2. Enregistrer dans registry** : `agents/src/core/checks/__init__.py`

```python
from .my_new_check import check_my_feature

def register_all_checks(registry: CheckRegistry):
    # ... existing checks ...

    # New check
    registry.register(
        check_id="check_my_feature",
        priority=CheckPriority.HIGH,  # Adapter selon besoin
        description="Description pour LLM prompt",
        execute_fn=check_my_feature
    )
```

**3. Redémarrer service** : `docker compose restart friday-heartbeat`

**C'est tout !** Le nouveau check sera automatiquement :
- Proposé au LLM décideur dans le prompt
- Exécuté si sélectionné par le LLM
- Protégé par circuit breaker
- Tracké dans metrics
- Intégré au Trust Layer

---

## LLM Décideur

### Rôle

Le **LLMDecider** utilise **Claude Sonnet 4.5** pour décider **intelligemment** quels checks exécuter selon le contexte Mainteneur.

**Fichier** : `agents/src/core/llm_decider.py`

### Configuration

```python
MODEL_ID = "claude-sonnet-4-5-20250929"
TEMPERATURE = 0.3  # Déterministe
TIMEOUT_SECONDS = 10
CIRCUIT_BREAKER_THRESHOLD = 3  # LLM décideur aussi a circuit breaker
```

### Prompt Strategy

Le prompt est **critique** pour respecter la philosophie 80% silence.

**Structure** :

```
=== CONTEXTE MAINTENEUR ===
- Heure actuelle : {current_time}
- Jour : {day_of_week} ({weekend/weekday})
- Casquette : {current_casquette}
- Prochain événement : {next_event}
- Dernière activité : {last_activity}

=== CHECKS DISPONIBLES ===
1. check_urgent_emails (HIGH) : Emails urgents non lus
2. check_financial_alerts (MEDIUM) : Échéances financières <7j
3. check_thesis_reminders (LOW) : Thésards sans contact 14j

=== RÈGLES SÉLECTION ===

**RÈGLE CRITIQUE:** 80%+ du temps, tu dois retourner checks_to_run = [] (silence).

Friday doit être **discret**. Ne notifier que si **vraiment pertinent** au contexte.

**Priorités** :
- CRITICAL : toujours exécuter (jamais skip, même en silence mode)
- HIGH : exécuter si pertinent (ex: urgent_emails si casquette médecin/enseignant)
- MEDIUM : exécuter si très pertinent (ex: financial_alerts si proche échéance probable)
- LOW : exécuter si temps disponible ET pertinent (ex: thesis_reminders si casquette enseignant + weekend)

**Contexte casquette** :
- medecin → urgent_emails pertinent (patients VIP)
- enseignant → urgent_emails + thesis_reminders pertinents
- chercheur → thesis_reminders pertinent
- null → checks génériques (financial_alerts)

**Exemples** :
- Lundi 14h30, casquette médecin, événement consultation 15h → urgent_emails
- Samedi 10h, casquette enseignant, pas d'événement → thesis_reminders (temps dispo)
- Mardi 20h, casquette null, pas d'événement → [] (silence)

=== FORMAT RÉPONSE ===

Retourne JSON strict :
{
  "checks_to_run": ["check_id1", "check_id2"],  // Liste IDs checks
  "reasoning": "Courte justification (1-2 phrases)"
}
```

### Fallback Mode

Si **LLM crash** ou **circuit breaker ouvert** (3 échecs) :

```python
# Fallback : Exécuter checks HIGH priority
fallback_checks = [
    check for check in all_checks
    if check.priority in [CheckPriority.CRITICAL, CheckPriority.HIGH]
]

return {
    "checks_to_run": [c.check_id for c in fallback_checks],
    "reasoning": "Fallback mode (LLM unavailable)"
}
```

### Circuit Breaker

Même logique que CheckExecutor :
- 3 échecs consécutifs → disable LLM décideur 1h
- Utilise fallback HIGH checks pendant 1h
- Reset après succès

**Redis keys** :
- `heartbeat:llm_failures` : Counter failures
- `heartbeat:llm_disabled` : Flag disabled (TTL 1h)

---

## Quiet Hours & Silence Rate

### Quiet Hours (22h-8h UTC)

**Philosophie** : Mainteneur dort → 0 notification sauf **CRITICAL**.

**Implémentation** :

```python
def is_quiet_hours(current_hour: int) -> bool:
    quiet_start = int(os.getenv("HEARTBEAT_QUIET_HOURS_START", "22"))
    quiet_end = int(os.getenv("HEARTBEAT_QUIET_HOURS_END", "8"))

    return current_hour >= quiet_start or current_hour < quiet_end
```

**Workflow** :
1. ContextProvider détecte quiet hours
2. HeartbeatEngine filtre checks → garde CRITICAL only
3. Skip LLM décideur (économie API call)
4. Exécute checks CRITICAL
5. Notifications envoyées uniquement si CRITICAL trouvé

**Exemples checks CRITICAL** :
- Service PostgreSQL down (panne critique)
- Garantie matériel expire demain (action urgente)
- RAM >95% VPS (risque crash)

### Silence Rate (AC4)

**Définition** : Pourcentage de cycles Heartbeat avec **0 notification** envoyée.

**Target** : ≥80%

**Calcul** :

```sql
-- Fonction PostgreSQL
CREATE FUNCTION core.calculate_silence_rate(days INT DEFAULT 7)
RETURNS NUMERIC AS $$
BEGIN
    RETURN (
        SELECT ROUND(
            (COUNT(*) FILTER (WHERE checks_notified = 0)::NUMERIC / NULLIF(COUNT(*), 0)) * 100,
            2
        )
        FROM core.heartbeat_metrics
        WHERE cycle_timestamp > NOW() - (days || ' days')::INTERVAL
    );
END;
$$ LANGUAGE plpgsql;

-- Usage
SELECT core.calculate_silence_rate(7);  -- Silence rate 7 derniers jours
-- Returns: 82.50 (82.5% cycles silencieux)
```

**Monitoring** :

```bash
# Endpoint Gateway
GET /api/v1/heartbeat/status

Response:
{
  "enabled": true,
  "mode": "daemon",
  "interval_minutes": 30,
  "last_cycle_timestamp": "2026-02-16T14:30:00Z",
  "silence_rate_7d": 82.5  # ✅ Target atteint
}
```

**Alerte** :

Si `silence_rate_7d < 50%` → Alerte Telegram Topic System (implémenté dans `services/metrics/nightly.py`).

**Rationale alerte** : Silence rate trop bas = trop de notifications = fatigue notificationnelle = besoin ajuster prompts LLM ou seuils checks.

---

## Configuration & Deployment

### Variables d'Environnement

**Fichier** : `.env` (voir `.env.example`)

```bash
# Heartbeat Engine (Story 4.1)
HEARTBEAT_ENABLED=true
HEARTBEAT_INTERVAL_MINUTES=30
HEARTBEAT_MODE=daemon  # daemon | cron
HEARTBEAT_QUIET_HOURS_START=22
HEARTBEAT_QUIET_HOURS_END=8

# LLM Provider (Claude Sonnet 4.5)
ANTHROPIC_API_KEY=your_api_key_here

# Database
DATABASE_URL=postgresql://user:pass@postgres:5432/friday

# Redis
REDIS_URL=redis://:password@redis:6379/0

# Telegram Bot (pour notifications)
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_SUPERGROUP_ID=-1001234567890
TOPIC_CHAT_PROACTIVE_ID=2
TOPIC_SYSTEM_ID=5
```

### Mode Daemon (Recommandé Production)

**Service Docker** : `docker-compose.services.yml`

```yaml
services:
  friday-heartbeat:
    build:
      context: ./agents
      dockerfile: Dockerfile
    container_name: friday-heartbeat
    command: python -m agents.src.core.heartbeat_daemon
    restart: unless-stopped
    env_file: .env
    environment:
      - HEARTBEAT_ENABLED=true
      - HEARTBEAT_MODE=daemon
      - HEARTBEAT_INTERVAL_MINUTES=30
    depends_on:
      - postgres
      - redis
    networks:
      friday-network:
        ipv4_address: 172.20.0.38
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M
```

**Démarrage** :

```bash
# 1. Configurer .env
HEARTBEAT_MODE=daemon
HEARTBEAT_INTERVAL_MINUTES=30

# 2. Démarrer service
docker compose -f docker-compose.yml -f docker-compose.services.yml up -d friday-heartbeat

# 3. Vérifier logs
docker logs -f friday-heartbeat

# Output attendu :
# {"event": "HeartbeatDaemon initialized", "enabled": true, "mode": "daemon", ...}
# {"event": "Connected to PostgreSQL"}
# {"event": "Connected to Redis"}
# {"event": "HeartbeatEngine initialized"}
# {"event": "Starting Heartbeat daemon mode", "interval_minutes": 30}
# {"event": "Heartbeat cycle completed", "status": "success", "checks_executed": 2, ...}
```

**Graceful Shutdown** :

```bash
# SIGTERM → graceful shutdown (close connections proprement)
docker stop friday-heartbeat

# Logs :
# {"event": "Signal received", "signal": "SIGTERM"}
# {"event": "Heartbeat daemon stopped"}
# {"event": "Redis connection closed"}
# {"event": "PostgreSQL pool closed"}
# {"event": "HeartbeatDaemon shutdown complete"}
```

### Mode Cron (via n8n)

**Avantage** : Flexibilité scheduling via UI n8n.

**1. Configurer .env** :

```bash
HEARTBEAT_MODE=cron
```

**2. Importer workflow n8n** :

- Dashboard n8n : http://n8n.friday.local
- Menu → Import from file
- Sélectionner `n8n-workflows/heartbeat-cron-trigger.json`
- Activer workflow (Toggle ON)

**3. Workflow structure** :

```
[Cron Trigger: */30 * * * *]
    ↓
[HTTP Request: POST /api/v1/heartbeat/trigger]
    ↓
[If Success?]
    ├─[YES]→ [Telegram: Success Notification (Topic Metrics)]
    └─[NO]→  [Telegram: Error Alert (Topic System)]
```

**4. Tester manuellement** :

```bash
# Via curl (avec Bearer token)
curl -X POST http://localhost:8000/api/v1/heartbeat/trigger \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json"

# Response:
{
  "status": "success",
  "checks_executed": 2,
  "checks_notified": 1,
  "duration_ms": 1250,
  "llm_reasoning": "Casquette médecin + heure travail → urgent_emails pertinent",
  "selected_checks": ["check_urgent_emails"]
}
```

### Comparaison Modes

| Critère | Daemon | Cron (n8n) |
|---------|--------|------------|
| **Resilience** | ✅ Haut (restart policy) | ⚠️ Dépend n8n uptime |
| **Flexibilité** | ⚠️ Redémarrer pour changer interval | ✅ UI n8n (pas de redémarrage) |
| **Monitoring** | ✅ Docker logs + healthcheck | ✅ n8n execution history |
| **Latence démarrage** | ⚠️ ~30s (init stack) | ✅ ~2s (endpoint déjà up) |
| **Recommandation** | **Production** | Development / Testing |

---

## Checks Day 1

### 1. check_urgent_emails (HIGH)

**Fichier** : `agents/src/core/checks/urgent_emails.py`

**Description** : Détecte emails urgents non lus (cabinet médical, faculty).

**Query** :
```sql
SELECT COUNT(*)
FROM ingestion.emails
WHERE priority = 'urgent'
  AND read = false
```

**Trigger** : ≥1 email urgent

**Message** :
```
📬 2 email(s) urgent(s) non lu(s)

• patient@example.com: Urgence consultation...
• dean@university.fr: Réunion faculté demain...
```

**Action inline button** : `view_urgent_emails` (ouvre liste emails)

**Trust** : `auto` (notification seule, pas d'action destructive)

### 2. check_financial_alerts (MEDIUM)

**Fichier** : `agents/src/core/checks/financial_alerts.py`

**Description** : Échéances financières <7 jours (SELARL, SCM, SCI).

**Query** :
```sql
SELECT entity_id, name, metadata->>'due_date', metadata->>'amount'
FROM knowledge.entities
WHERE entity_type = 'COTISATION'
  AND (metadata->>'due_date')::date < NOW() + INTERVAL '7 days'
  AND (metadata->>'due_date')::date >= NOW()
ORDER BY (metadata->>'due_date')::date ASC
```

**Trigger** : ≥1 cotisation échéance <7j

**Message** :
```
💰 3 échéance(s) financière(s) <7j

• URSSAF SELARL: 2500 € - échéance 2026-02-20
• Assurance SCM: 800 € - échéance 2026-02-22
• Taxe foncière SCI Ravas: 1200 € - échéance 2026-02-23
```

**Action** : `view_financial_alerts`

**Trust** : `auto`

### 3. check_thesis_reminders (LOW)

**Fichier** : `agents/src/core/checks/thesis_reminders.py`

**Description** : Thésards sans contact depuis 14 jours.

**Query** :
```sql
SELECT entity_id, name, metadata->>'last_contact', metadata->>'thesis_subject'
FROM knowledge.entities
WHERE entity_type = 'STUDENT'
  AND (metadata->>'last_contact')::date < NOW() - INTERVAL '14 days'
ORDER BY (metadata->>'last_contact')::date ASC
```

**Trigger** : ≥1 thésard sans contact 14j

**Message** :
```
🎓 2 thésard(s) à relancer (sans contact depuis 14j)

• Marie Dupont: Étude neuroplasticité... (dernier contact: 2026-01-28)
• Jean Martin: Modélisation Alzheimer... (dernier contact: 2026-01-30)
```

**Action** : `view_thesis_reminders`

**Trust** : `auto`

---

## Notifications Telegram

### Helper Module

**Fichier** : `agents/src/core/telegram_helper.py`

**Fonctions** :
- `get_telegram_bot()` : Singleton Bot Telegram
- `send_to_chat_proactive()` : Topic Chat & Proactive (notifications checks)
- `send_to_system_alerts()` : Topic System & Alerts (erreurs critiques)
- `format_heartbeat_message()` : Format standard `[Heartbeat] 🔔 <titre> : <message>`
- `create_action_keyboard()` : Inline keyboards actions

### Format Messages

**Standard** :
```
[Heartbeat] 🔔 Urgent Emails

📬 2 email(s) urgent(s) non lu(s)

• patient@example.com: Urgence consultation...
• dean@university.fr: Réunion faculté demain...

[📬 Voir emails urgents] ← Inline button
```

**HTML Tags** :
- `<b>Texte bold</b>`
- `<i>Texte italic</i>`
- HTML escape : `&`, `<`, `>`, `"`

### Topics Utilisés

| Type notification | Topic | Thread ID Env Var |
|-------------------|-------|-------------------|
| Checks notifications | Chat & Proactive (DEFAULT) | `TOPIC_CHAT_PROACTIVE_ID` |
| Erreurs Heartbeat | System & Alerts | `TOPIC_SYSTEM_ID` |
| Metrics cycles | Metrics & Logs | `TOPIC_METRICS_ID` |

---

## Metrics & Monitoring

### Table heartbeat_metrics

**Migration** : `database/migrations/039_heartbeat_metrics.sql`

**Schema** :
```sql
CREATE TABLE core.heartbeat_metrics (
    id UUID PRIMARY KEY,
    cycle_timestamp TIMESTAMPTZ NOT NULL,
    checks_selected TEXT[] NOT NULL,      -- IDs checks sélectionnés par LLM
    checks_executed INT NOT NULL,
    checks_notified INT NOT NULL,         -- Pour calcul silence_rate
    llm_decision_reasoning TEXT,
    duration_ms INT NOT NULL,
    error TEXT,                           -- NULL si succès
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_heartbeat_metrics_timestamp ON core.heartbeat_metrics(cycle_timestamp DESC);
CREATE INDEX idx_heartbeat_metrics_notified ON core.heartbeat_metrics(checks_notified) WHERE checks_notified > 0;
```

### Queries Monitoring

**Silence rate 7j** :
```sql
SELECT core.calculate_silence_rate(7);
-- Returns: 82.50
```

**Derniers cycles** :
```sql
SELECT
    cycle_timestamp,
    checks_executed,
    checks_notified,
    duration_ms,
    CASE WHEN checks_notified = 0 THEN '🟢 Silence' ELSE '🔔 Notified' END as status
FROM core.heartbeat_metrics
ORDER BY cycle_timestamp DESC
LIMIT 10;
```

**Cycles avec erreurs** :
```sql
SELECT
    cycle_timestamp,
    error,
    duration_ms
FROM core.heartbeat_metrics
WHERE error IS NOT NULL
ORDER BY cycle_timestamp DESC
LIMIT 20;
```

**Performance stats** :
```sql
SELECT
    AVG(duration_ms) as avg_duration_ms,
    MAX(duration_ms) as max_duration_ms,
    MIN(duration_ms) as min_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration_ms
FROM core.heartbeat_metrics
WHERE cycle_timestamp > NOW() - INTERVAL '7 days';
```

### Endpoint Status

**GET /api/v1/heartbeat/status** (authentifié)

```bash
curl -H "Authorization: Bearer TOKEN" http://localhost:8000/api/v1/heartbeat/status

Response:
{
  "enabled": true,
  "mode": "daemon",
  "interval_minutes": 30,
  "last_cycle_timestamp": "2026-02-16T14:30:00Z",
  "silence_rate_7d": 82.5
}
```

---

## Troubleshooting

### Service ne démarre pas

**Symptôme** : `docker logs friday-heartbeat` montre erreur au démarrage.

**Causes possibles** :

1. **DATABASE_URL invalide**
   ```
   Error: "DATABASE_URL environment variable not set"
   ```
   **Fix** : Vérifier `.env` contient `DATABASE_URL=postgresql://...`

2. **ANTHROPIC_API_KEY manquante**
   ```
   Error: "ANTHROPIC_API_KEY environment variable not set"
   ```
   **Fix** : Ajouter clé API dans `.env`

3. **PostgreSQL pas démarré**
   ```
   Error: "Connection refused (postgres:5432)"
   ```
   **Fix** : `docker compose up -d postgres` puis redémarrer heartbeat

4. **Redis pas démarré**
   ```
   Error: "Redis connection failed"
   ```
   **Fix** : `docker compose up -d redis` puis redémarrer heartbeat

### Cycles ne s'exécutent pas

**Symptôme** : Aucun log de cycle dans `docker logs friday-heartbeat`.

**Diagnostics** :

1. **HEARTBEAT_ENABLED=false**
   ```
   Log: "Heartbeat disabled (HEARTBEAT_ENABLED=false)"
   ```
   **Fix** : Changer `HEARTBEAT_ENABLED=true` dans `.env`, redémarrer

2. **Mode cron mais pas d'endpoint trigger**
   ```bash
   # Vérifier mode
   docker exec friday-heartbeat env | grep HEARTBEAT_MODE
   # Si mode=cron, vérifier n8n workflow actif
   ```

3. **Quiet hours toute la journée**
   ```
   # Vérifier config quiet hours
   docker exec friday-heartbeat env | grep QUIET_HOURS
   # HEARTBEAT_QUIET_HOURS_START=22
   # HEARTBEAT_QUIET_HOURS_END=8
   ```
   **Fix** : Ajuster heures si mauvaise timezone

### LLM décideur crash

**Symptôme** : Logs montrent "Fallback mode (LLM unavailable)".

**Causes** :

1. **Clé API invalide**
   ```
   Error: "AuthenticationError: Invalid API key"
   ```
   **Fix** : Vérifier `ANTHROPIC_API_KEY` valide

2. **Rate limit atteint**
   ```
   Error: "RateLimitError: Too many requests"
   ```
   **Fix** : Augmenter `HEARTBEAT_INTERVAL_MINUTES` (ex: 60 au lieu de 30)

3. **Timeout LLM**
   ```
   Error: "TimeoutError: LLM request timeout after 10s"
   ```
   **Fix** : Vérifier connexion réseau, augmenter timeout dans `llm_decider.py`

**Mode dégradé** : Si LLM crash >3 fois, circuit breaker ouvert 1h → fallback HIGH checks automatique.

### Check circuit breaker ouvert

**Symptôme** : Notification Telegram "Check 'check_urgent_emails' disabled for 1h (3 failures)".

**Diagnostics** :

1. **Vérifier logs check** :
   ```bash
   docker logs friday-heartbeat | grep "check_urgent_emails"
   # Chercher erreurs répétées
   ```

2. **Vérifier circuit breaker Redis** :
   ```bash
   docker exec redis redis-cli GET "check:disabled:check_urgent_emails"
   # Si retourne "1" → circuit ouvert
   ```

3. **Attendre 1h OU forcer réactivation** :
   ```bash
   # Forcer réactivation manuelle
   docker exec redis redis-cli DEL "check:disabled:check_urgent_emails"
   docker exec redis redis-cli DEL "check:failures:check_urgent_emails"
   ```

**Fix root cause** : Identifier pourquoi le check échoue (query SQL invalide, table manquante, etc.).

### Silence rate trop bas (<50%)

**Symptôme** : Alerte Telegram "Silence rate <50% sur 7j".

**Diagnostics** :

1. **Analyser cycles récents** :
   ```sql
   SELECT
       checks_selected,
       checks_notified,
       llm_decision_reasoning
   FROM core.heartbeat_metrics
   WHERE cycle_timestamp > NOW() - INTERVAL '7 days'
     AND checks_notified > 0
   ORDER BY cycle_timestamp DESC
   LIMIT 20;
   ```

2. **Identifier check(s) trop bavard(s)** :
   ```sql
   SELECT
       UNNEST(checks_selected) as check_id,
       COUNT(*) as executions,
       SUM(CASE WHEN checks_notified > 0 THEN 1 ELSE 0 END) as notifications
   FROM core.heartbeat_metrics
   WHERE cycle_timestamp > NOW() - INTERVAL '7 days'
   GROUP BY check_id
   ORDER BY notifications DESC;
   ```

**Fixes** :

- **Ajuster seuils checks** : Ex: `urgent_emails` notifie trop → augmenter seuil de 1 à 3 emails
- **Ajuster prompt LLM** : Renforcer règle 80% silence dans prompt
- **Revoir priority checks** : Check trop notifiant → downgrade MEDIUM → LOW

---

## Extension & Développement

### Ajouter Nouveau Check (Recap)

**Checklist** :
1. ✅ Créer fichier `agents/src/core/checks/my_check.py`
2. ✅ Implémenter fonction async avec `@friday_action` decorator
3. ✅ Retourner `CheckResult` avec `notify`, `message`, `action`, `payload`
4. ✅ Enregistrer dans `agents/src/core/checks/__init__.py` → `register_all_checks()`
5. ✅ Choisir priority : CRITICAL | HIGH | MEDIUM | LOW
6. ✅ Redémarrer service : `docker compose restart friday-heartbeat`

**Best practices** :
- **Silence = default** : Retourner `CheckResult(notify=False)` si rien détecté
- **Message concis** : Max 3 items dans notification (+ "... et X autres")
- **Action pertinente** : Inline button pour action Mainteneur (ouvrir liste, marquer vu, etc.)
- **Trust level adapté** : `auto` si notification seule, `propose` si action requise validation

### Tests

**Tests unitaires** : `tests/unit/core/test_check_executor.py`

```bash
pytest tests/unit/core/test_check_executor.py -v
```

**Tests intégration** : `tests/integration/test_heartbeat_pipeline_integration.py`

```bash
# Requiert PostgreSQL testcontainer
INTEGRATION_TESTS=1 pytest tests/integration/ -v
```

**Tests E2E** : `tests/e2e/test_heartbeat_e2e.py`

```bash
# Requiert DB réelle
pytest tests/e2e/test_heartbeat_e2e.py -v
```

### Debugging

**Logs structurés** (JSON) :

```bash
# Filtrer logs par événement
docker logs friday-heartbeat 2>&1 | jq 'select(.event == "Heartbeat cycle completed")'

# Filtrer logs par check_id
docker logs friday-heartbeat 2>&1 | jq 'select(.check_id == "check_urgent_emails")'

# Afficher derniers cycles
docker logs friday-heartbeat 2>&1 | jq 'select(.event == "Heartbeat cycle completed") | {time: .timestamp, status: .status, checks: .checks_executed, notified: .checks_notified}'
```

**Exec shell dans container** :

```bash
docker exec -it friday-heartbeat bash

# Dans container
python -c "
from agents.src.core.check_registry import CheckRegistry
from agents.src.core.checks import register_all_checks

registry = CheckRegistry()
register_all_checks(registry)

for check in registry.get_all_checks():
    print(f'{check.check_id}: {check.priority} - {check.description}')
"
```

---

## Références

- **Story 4.1** : `_bmad-output/implementation-artifacts/4-1-heartbeat-engine-core.md`
- **Architecture Friday** : `_docs/architecture-friday-2.0.md`
- **Trust Layer** : `docs/trust-layer-spec.md` (Story 1.6)
- **Multi-casquettes** : `docs/multi-casquettes-conflicts.md` (Story 7.3)
- **Telegram Topics** : `docs/telegram-topics-setup.md`

---

**Fin du document**
Version 1.0.0 - 2026-02-16
