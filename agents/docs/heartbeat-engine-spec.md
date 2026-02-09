# Heartbeat Engine - Spécification Technique

**Version** : 1.0.0
**Date** : 2026-02-05
**Story** : 2.5 (après Story 2)
**Effort estimé** : 10h dev + 2h tests

---

## 1. CONTEXTE & DÉCISION

### 1.1 Problématique

Friday 2.0 doit être **proactif**, pas seulement réactif. Antonio ne doit PAS avoir à demander "Y a-t-il des emails urgents ?" ou "Mes cotisations sont-elles à jour ?". Friday doit surveiller automatiquement et notifier UNIQUEMENT si important.

### 1.2 Alternatives considérées

| Approche | Coût | Avantages | Inconvénients | Décision |
|----------|------|-----------|---------------|----------|
| **Cron n8n manuel** | 0h (existant) | Simple, stable | Configuration fixe, pas d'intelligence décisionnelle | ❌ Rejeté |
| **OpenClaw complet** | 70h | Heartbeat + 50+ intégrations + 1715 skills | ROI -86%, risque supply chain 12%, redondances | ❌ Rejeté |
| **Heartbeat natif Friday** | 10h | Intelligence décisionnelle, intégration Trust Layer, contrôle total | Dev custom nécessaire | ✅ **Retenu** |

**Rationale** : Antonio a besoin du heartbeat proactif (critique Day 1) MAIS pas de multi-chat ni skills OpenClaw. Implémenter natif = 10h vs 70h OpenClaw complet.

### 1.3 Inspiration OpenClaw

Le Heartbeat Engine Friday s'inspire du [heartbeat OpenClaw](https://docs.openclaw.ai/automation/cron-vs-heartbeat) :
- Agent se réveille périodiquement (interval configurable)
- Décide dynamiquement quoi vérifier (contexte-aware)
- Notifie Antonio SEULEMENT si pertinent

**Mais avec différences clés** :
- ✅ Intégration native Trust Layer (`@friday_action`)
- ✅ Pas de dépendance externe (code maîtrisé)
- ✅ Checks enregistrés avec priorités (high/medium/low)
- ✅ Context-aware (heure, dernière activité, calendrier)

---

## 2. ARCHITECTURE

### 2.1 Vue d'ensemble

```
┌────────────────────────────────────────────────────────────┐
│                   HEARTBEAT ENGINE                          │
└────────────────────────────────────────────────────────────┘

asyncio.create_task(heartbeat.run_forever())
            ↓
   Sleep interval (default 30min)
            ↓
   Heartbeat tick déclenché
            ↓
   ┌──────────────────┐
   │ 1. Get Context   │ ← Heure, dernière activité, calendrier
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ 2. LLM Decision  │ ← "Quels checks exécuter maintenant ?"
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ 3. Execute Checks│ ← Checks sélectionnés (async parallèle)
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ 4. Filter Results│ ← Garder SEULEMENT si notify=True
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ 5. Notify Telegram│ ← Batch notifications (max 1 par tick)
   └──────────────────┘
```

### 2.2 Composants

| Composant | Fichier | Responsabilité |
|-----------|---------|----------------|
| **FridayHeartbeat** | `agents/src/core/heartbeat.py` | Orchestrateur principal, boucle async |
| **CheckRegistry** | `agents/src/core/heartbeat.py` | Enregistrement checks avec métadonnées |
| **ContextProvider** | `agents/src/core/context.py` | Fourniture contexte (heure, activité, calendrier) |
| **LLMDecider** | `agents/src/core/heartbeat.py` | LLM décide quels checks exécuter |
| **TelegramNotifier** | `agents/src/services/telegram/notifier.py` (existant) | Envoi notifications groupées |
| **Config** | `config/heartbeat.yaml` | Interval, checks actifs, quiet hours |

---

## 3. SPÉCIFICATION TECHNIQUE

### 3.1 Class FridayHeartbeat

```python
# agents/src/core/heartbeat.py

from datetime import datetime, timedelta, time
from typing import List, Callable, Dict, Any
import asyncio
import structlog

logger = structlog.get_logger(__name__)

class FridayHeartbeat:
    """
    Heartbeat proactif Friday 2.0

    Le Heartbeat se réveille périodiquement, analyse le contexte,
    décide intelligemment quoi vérifier, et notifie Antonio UNIQUEMENT
    si pertinent.

    Inspiration : OpenClaw heartbeat, mais intégration native Friday
    """

    def __init__(
        self,
        interval_minutes: int = 30,
        quiet_hours_start: time = time(22, 0),
        quiet_hours_end: time = time(8, 0),
    ):
        """
        Args:
            interval_minutes: Fréquence réveil (default 30min)
            quiet_hours_start: Début période silencieuse (default 22h00)
            quiet_hours_end: Fin période silencieuse (default 08h00)
        """
        self.interval = timedelta(minutes=interval_minutes)
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.checks: Dict[str, CheckDefinition] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def register_check(
        self,
        name: str,
        fn: Callable[[Dict[str, Any]], Awaitable[CheckResult]],
        priority: str,
        description: str = ""
    ):
        """
        Enregistre un check périodique

        Args:
            name: Identifiant unique check
            fn: Fonction async qui retourne CheckResult
            priority: 'high' (toujours) | 'medium' (si pertinent) | 'low' (si temps)
            description: Description lisible (pour LLM decision)

        Example:
            @heartbeat.register_check(
                name="check_urgent_emails",
                priority="high",
                description="Vérifie emails urgents non lus"
            )
            async def check_urgent_emails(context: Dict) -> CheckResult:
                urgent = await email_agent.get_urgent_unread()
                if urgent:
                    return CheckResult(
                        notify=True,
                        message=f"📧 {len(urgent)} emails urgents",
                        action="propose_summary"
                    )
                return CheckResult(notify=False)
        """
        if priority not in ('high', 'medium', 'low'):
            raise ValueError(f"Priority must be high/medium/low, got: {priority}")

        self.checks[name] = CheckDefinition(
            name=name,
            fn=fn,
            priority=priority,
            description=description,
            last_run=None,
            last_result=None
        )
        logger.info("registered_check", name=name, priority=priority)

    async def start(self):
        """Démarre la boucle heartbeat en arrière-plan"""
        if self._running:
            logger.warning("heartbeat_already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_forever())
        logger.info("heartbeat_started", interval_minutes=self.interval.total_seconds() / 60)

    async def stop(self):
        """Arrête proprement la boucle heartbeat"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("heartbeat_stopped")

    async def _run_forever(self):
        """Boucle principale heartbeat"""
        while self._running:
            try:
                await asyncio.sleep(self.interval.total_seconds())
                await self._heartbeat_tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("heartbeat_tick_error", error=str(e), exc_info=True)
                # Continue malgré l'erreur (resilience)

    async def _heartbeat_tick(self):
        """
        Un tick de heartbeat

        1. Vérifie quiet hours (skip si période silencieuse)
        2. Get context actuel
        3. LLM décide quels checks exécuter
        4. Exécute checks sélectionnés (parallèle)
        5. Filtre résultats (notify=True uniquement)
        6. Notifie Antonio (batch, max 1 notification par tick)
        """
        now = datetime.now()

        # 1. Vérifier quiet hours
        if self._is_quiet_hours(now.time()):
            logger.debug("heartbeat_skip_quiet_hours", time=now.time())
            return

        logger.info("heartbeat_tick_start", time=now)

        # 2. Get context
        context = await self._get_context()

        # 3. LLM décide quels checks exécuter
        selected_checks = await self._decide_checks(context)

        if not selected_checks:
            logger.debug("heartbeat_no_checks_selected")
            return

        # 4. Exécute checks (parallèle)
        results = await self._execute_checks(selected_checks, context)

        # 5. Filtre résultats notify=True
        notifications = [r for r in results if r.notify]

        if not notifications:
            logger.debug("heartbeat_no_notifications")
            return

        # 6. Notifie Antonio (batch)
        await self._notify_batch(notifications)

        logger.info("heartbeat_tick_complete", checks_run=len(selected_checks), notifications=len(notifications))

    def _is_quiet_hours(self, current_time: time) -> bool:
        """Vérifie si dans période silencieuse"""
        if self.quiet_hours_start < self.quiet_hours_end:
            # Ex: 22h00-08h00 (traverse minuit)
            return current_time >= self.quiet_hours_start or current_time < self.quiet_hours_end
        else:
            # Ex: 08h00-22h00 (pas de traversée minuit)
            return self.quiet_hours_start <= current_time < self.quiet_hours_end

    async def _get_context(self) -> Dict[str, Any]:
        """
        Récupère contexte actuel pour décision intelligente

        Returns:
            {
                'time': datetime,
                'hour': int,
                'is_weekend': bool,
                'last_active': datetime | None,
                'next_event': dict | None,
                'checks_last_run': dict,
            }
        """
        from agents.src.core.context import ContextProvider

        provider = ContextProvider()
        return await provider.get_context()

    async def _decide_checks(self, context: Dict[str, Any]) -> List[str]:
        """
        LLM décide quels checks exécuter (contexte-aware)

        Args:
            context: Contexte actuel

        Returns:
            Liste noms de checks à exécuter

        Logic:
            - high priority : TOUJOURS exécutés
            - medium priority : Si pertinent selon contexte
            - low priority : Si temps disponible (< 5 checks total)
        """
        from agents.src.adapters.llm import get_llm_adapter

        # Séparer checks par priorité
        high = [name for name, c in self.checks.items() if c.priority == 'high']
        medium = [name for name, c in self.checks.items() if c.priority == 'medium']
        low = [name for name, c in self.checks.items() if c.priority == 'low']

        # high : toujours
        selected = high.copy()

        # medium + low : LLM décide selon contexte
        if medium or low:
            llm = get_llm_adapter()

            prompt = f"""Tu es Friday, assistant IA proactif. Il est {context['time'].strftime('%H:%M')} ({context['day_name']}).

Contexte :
- Dernière activité Antonio : {context.get('last_active', 'inconnue')}
- Prochain événement : {context.get('next_event', 'aucun')}
- Checks déjà prévus (high) : {', '.join(high)}

Checks medium disponibles :
{self._format_checks_for_llm(medium)}

Checks low disponibles :
{self._format_checks_for_llm(low)}

Sélectionne les checks medium/low pertinents MAINTENANT (maximum 3).
Critères : urgence, contexte horaire, dernière exécution.

Retourne JSON : {{"selected": ["check1", "check2"]}}
"""

            response = await llm.chat(
                prompt=prompt,
                response_format={"type": "json_object"},
                model="claude-sonnet-4-5-20250929"  # D17: modèle unique
            )

            selected.extend(response['selected'])

        return selected

    def _format_checks_for_llm(self, check_names: List[str]) -> str:
        """Formate checks pour prompt LLM"""
        lines = []
        for name in check_names:
            check = self.checks[name]
            last_run = check.last_run.strftime('%H:%M') if check.last_run else 'jamais'
            lines.append(f"- {name} : {check.description} (dernière exec: {last_run})")
        return '\n'.join(lines)

    async def _execute_checks(
        self,
        check_names: List[str],
        context: Dict[str, Any]
    ) -> List[CheckResult]:
        """
        Exécute checks sélectionnés en parallèle

        Args:
            check_names: Noms des checks à exécuter
            context: Contexte à passer aux checks

        Returns:
            Liste CheckResult
        """
        tasks = []
        for name in check_names:
            if name not in self.checks:
                logger.warning("check_not_found", name=name)
                continue

            check = self.checks[name]
            tasks.append(self._execute_single_check(name, check, context))

        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_single_check(
        self,
        name: str,
        check: CheckDefinition,
        context: Dict[str, Any]
    ) -> CheckResult:
        """Exécute un check avec error handling"""
        try:
            result = await check.fn(context)
            check.last_run = datetime.now()
            check.last_result = result
            return result
        except Exception as e:
            logger.error("check_execution_error", name=name, error=str(e), exc_info=True)
            return CheckResult(
                notify=False,
                error=str(e)
            )

    async def _notify_batch(self, notifications: List[CheckResult]):
        """
        Envoie notifications groupées à Antonio via Telegram

        Format :
            🔔 HEARTBEAT (14:30)

            📧 3 emails urgents non lus
            [Voir résumé]

            💰 Alerte : cotisations URSSAF échéance 28/02
            [Créer tâche]

            📚 Deadline thèse Julie dans 7 jours
            [Voir détail]
        """
        from agents.src.services.telegram.notifier import send_notification

        now = datetime.now()

        message_parts = [
            f"🔔 **HEARTBEAT** ({now.strftime('%H:%M')})",
            ""
        ]

        for notif in notifications:
            message_parts.append(notif.message)
            message_parts.append("")

        message = '\n'.join(message_parts)

        await send_notification(
            message=message,
            priority="medium"
        )


# Models
from pydantic import BaseModel
from typing import Optional

class CheckResult(BaseModel):
    """Résultat d'un check heartbeat"""
    notify: bool
    message: str = ""
    action: Optional[str] = None
    payload: Dict[str, Any] = {}
    error: Optional[str] = None

class CheckDefinition(BaseModel):
    """Définition d'un check enregistré"""
    name: str
    fn: Callable
    priority: str
    description: str
    last_run: Optional[datetime] = None
    last_result: Optional[CheckResult] = None

    class Config:
        arbitrary_types_allowed = True
```

### 3.2 Context Provider

```python
# agents/src/core/context.py

from datetime import datetime
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger(__name__)

class ContextProvider:
    """Fournit contexte actuel pour décisions Heartbeat"""

    async def get_context(self) -> Dict[str, Any]:
        """
        Récupère contexte complet

        Returns:
            {
                'time': datetime.now(),
                'hour': int,
                'day_name': str,
                'is_weekend': bool,
                'last_active': datetime | None,
                'next_event': dict | None,
            }
        """
        now = datetime.now()

        return {
            'time': now,
            'hour': now.hour,
            'day_name': now.strftime('%A'),
            'is_weekend': now.weekday() >= 5,
            'last_active': await self._get_last_active(),
            'next_event': await self._get_next_event(),
        }

    async def _get_last_active(self) -> Optional[datetime]:
        """Dernière activité Antonio (dernière action receipts)"""
        from agents.src.database import get_db

        async with get_db() as db:
            result = await db.fetchrow(
                "SELECT MAX(created_at) as last_active FROM core.action_receipts"
            )
            return result['last_active'] if result else None

    async def _get_next_event(self) -> Optional[Dict[str, Any]]:
        """Prochain événement calendrier (si module agenda implémenté)"""
        # TODO: Implémenter quand Module 3 (Agenda) sera prêt
        return None
```

### 3.3 Configuration

```yaml
# config/heartbeat.yaml

interval_minutes: 30

quiet_hours:
  start: "22:00"
  end: "08:00"

checks:
  # Module 1 : Email
  - name: check_urgent_emails
    enabled: true
    priority: high
    description: "Vérifie emails urgents non lus"

  # Module 14 : Finance
  - name: check_financial_alerts
    enabled: true
    priority: medium
    description: "Vérifie alertes financières (seuils dépassés)"

  - name: check_upcoming_deadlines
    enabled: true
    priority: medium
    description: "Vérifie échéances proches (cotisations, contrats)"

  # Module 9 : Thèse
  - name: check_thesis_reminders
    enabled: true
    priority: low
    description: "Rappels deadlines thèses étudiants"

  # Module 18 : Entretien cyclique
  - name: check_maintenance_reminders
    enabled: false  # Day 1 disabled
    priority: low
    description: "Rappels entretiens périodiques"
```

---

## 4. EXEMPLES DE CHECKS

### 4.1 Check emails urgents

```python
# agents/src/agents/email/checks.py

from agents.src.core.heartbeat import CheckResult
from typing import Dict, Any

async def check_urgent_emails(context: Dict[str, Any]) -> CheckResult:
    """
    Vérifie emails urgents non lus

    Critère urgent : sender dans whitelist OU subject contient [URGENT]
    """
    from agents.src.agents.email.agent import EmailAgent

    agent = EmailAgent()
    urgent = await agent.get_urgent_unread()

    if not urgent:
        return CheckResult(notify=False)

    # Trier par date (plus récent d'abord)
    urgent = sorted(urgent, key=lambda e: e.received_at, reverse=True)

    # Limiter à 5 max dans notification
    to_show = urgent[:5]

    message_lines = [f"📧 **{len(urgent)} emails urgents non lus**", ""]

    for email in to_show:
        message_lines.append(
            f"• {email.sender} : {email.subject[:50]}"
        )

    if len(urgent) > 5:
        message_lines.append(f"... et {len(urgent) - 5} autres")

    return CheckResult(
        notify=True,
        message='\n'.join(message_lines),
        action="propose_summary",
        payload={"email_ids": [e.id for e in urgent]}
    )
```

### 4.2 Check alertes financières

```python
# agents/src/agents/finance/checks.py

async def check_financial_alerts(context: Dict[str, Any]) -> CheckResult:
    """
    Vérifie alertes financières

    Alertes :
    - Seuil compte bancaire bas (<5000€)
    - Échéance cotisations proches (<7j)
    - Transactions suspectes (montant anormal)
    """
    from agents.src.agents.finance.agent import FinanceAgent

    agent = FinanceAgent()
    alerts = await agent.check_thresholds()

    if not alerts:
        return CheckResult(notify=False)

    # Grouper par type
    critical = [a for a in alerts if a.severity == 'critical']
    warning = [a for a in alerts if a.severity == 'warning']

    if not critical and not warning:
        return CheckResult(notify=False)

    message_lines = ["💰 **Alertes financières**", ""]

    if critical:
        message_lines.append("🚨 **Critiques** :")
        for alert in critical:
            message_lines.append(f"• {alert.description}")
        message_lines.append("")

    if warning:
        message_lines.append("⚠️ **Warnings** :")
        for alert in warning:
            message_lines.append(f"• {alert.description}")

    return CheckResult(
        notify=True,
        message='\n'.join(message_lines),
        action="propose_analysis",
        payload={"alerts": [a.dict() for a in alerts]}
    )
```

---

## 5. INTÉGRATION TRUST LAYER

### 5.1 Heartbeat checks passent par Trust Layer

Chaque check retourne un `CheckResult`, mais si le check déclenche une **action** (pas juste une notification), il DOIT passer par `@friday_action` :

```python
# Example : Check qui propose de créer une tâche

@friday_action(module="finance", action="create_task_from_alert", trust_default="propose")
async def create_task_from_alert(alert: FinancialAlert) -> ActionResult:
    """
    Crée une tâche à partir d'une alerte financière
    (déclenché si Antonio clique sur bouton Telegram)
    """
    task = await db.fetchrow(
        """
        INSERT INTO core.tasks (title, due_date, priority, module)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        alert.description,
        alert.deadline,
        'high',
        'finance'
    )

    return ActionResult(
        input_summary=f"Alerte : {alert.description}",
        output_summary=f"Tâche créée : {alert.description}",
        confidence=1.0,
        reasoning="Création automatique depuis alerte heartbeat"
    )
```

**Principe** : Heartbeat notifie → Antonio clique inline button → Action exécutée via Trust Layer.

---

## 6. TESTS

### 6.1 Tests unitaires

```python
# tests/unit/core/test_heartbeat.py

import pytest
from datetime import datetime, time
from agents.src.core.heartbeat import FridayHeartbeat, CheckResult

@pytest.mark.asyncio
async def test_heartbeat_registers_check():
    """Test enregistrement check"""
    heartbeat = FridayHeartbeat()

    async def dummy_check(context):
        return CheckResult(notify=False)

    heartbeat.register_check(
        name="test_check",
        fn=dummy_check,
        priority="high",
        description="Test check"
    )

    assert "test_check" in heartbeat.checks
    assert heartbeat.checks["test_check"].priority == "high"

@pytest.mark.asyncio
async def test_heartbeat_skips_quiet_hours():
    """Test skip pendant quiet hours"""
    heartbeat = FridayHeartbeat(
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(8, 0)
    )

    # 23h00 = dans quiet hours
    assert heartbeat._is_quiet_hours(time(23, 0)) is True

    # 10h00 = hors quiet hours
    assert heartbeat._is_quiet_hours(time(10, 0)) is False

@pytest.mark.asyncio
async def test_heartbeat_executes_high_priority_always():
    """Test high priority checks toujours exécutés"""
    heartbeat = FridayHeartbeat()

    high_executed = False

    async def high_check(context):
        nonlocal high_executed
        high_executed = True
        return CheckResult(notify=False)

    heartbeat.register_check(
        name="high_check",
        fn=high_check,
        priority="high",
        description="Always run"
    )

    context = await heartbeat._get_context()
    selected = await heartbeat._decide_checks(context)

    assert "high_check" in selected

    await heartbeat._execute_checks(selected, context)
    assert high_executed is True
```

### 6.2 Tests intégration

```python
# tests/integration/test_heartbeat_integration.py

@pytest.mark.asyncio
async def test_heartbeat_full_cycle():
    """Test cycle complet heartbeat"""
    heartbeat = FridayHeartbeat(interval_minutes=1)

    notified = False

    async def urgent_check(context):
        nonlocal notified
        notified = True
        return CheckResult(
            notify=True,
            message="Test urgent notification"
        )

    heartbeat.register_check(
        name="urgent_check",
        fn=urgent_check,
        priority="high",
        description="Test"
    )

    # Démarrer heartbeat
    await heartbeat.start()

    # Attendre 1 tick (>1min)
    await asyncio.sleep(65)

    # Vérifier exécution
    assert notified is True

    # Arrêter proprement
    await heartbeat.stop()
```

---

## 7. DÉPLOIEMENT

### 7.1 Intégration main

```python
# agents/src/main.py

async def main():
    """Point d'entrée principal Friday 2.0"""
    logger.info("friday_starting")

    # ... init database, redis, etc.

    # Démarrer Heartbeat Engine
    from agents.src.core.heartbeat import FridayHeartbeat
    from agents.src.agents.email.checks import check_urgent_emails
    from agents.src.agents.finance.checks import check_financial_alerts

    heartbeat = FridayHeartbeat(interval_minutes=30)

    # Enregistrer checks
    heartbeat.register_check(
        name="check_urgent_emails",
        fn=check_urgent_emails,
        priority="high",
        description="Emails urgents"
    )

    heartbeat.register_check(
        name="check_financial_alerts",
        fn=check_financial_alerts,
        priority="medium",
        description="Alertes financières"
    )

    # Démarrer (non-bloquant, background task)
    await heartbeat.start()

    logger.info("heartbeat_started")

    # ... reste de l'application

    try:
        # Keep alive
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("friday_shutting_down")
        await heartbeat.stop()
```

### 7.2 Monitoring

```python
# Endpoint FastAPI pour monitoring

@app.get("/api/v1/heartbeat/status")
async def get_heartbeat_status():
    """Status Heartbeat Engine"""
    from agents.src.core.heartbeat import heartbeat_instance

    return {
        "running": heartbeat_instance._running,
        "interval_minutes": heartbeat_instance.interval.total_seconds() / 60,
        "checks_registered": len(heartbeat_instance.checks),
        "checks": [
            {
                "name": name,
                "priority": check.priority,
                "last_run": check.last_run.isoformat() if check.last_run else None,
                "last_notify": check.last_result.notify if check.last_result else None
            }
            for name, check in heartbeat_instance.checks.items()
        ]
    }
```

---

## 8. ROADMAP

### Phase 1 : Core Heartbeat (Story 2.5, ~10h)

- [x] Class `FridayHeartbeat`
- [x] `ContextProvider`
- [x] LLM decision layer
- [x] Check registration
- [x] Telegram notification batch
- [x] Tests unitaires + intégration
- [x] Documentation

### Phase 2 : Checks Day 1 (Story 3-4)

- [ ] `check_urgent_emails` (Module 1)
- [ ] `check_financial_alerts` (Module 14)
- [ ] `check_upcoming_deadlines` (Module 14)
- [ ] `check_thesis_reminders` (Module 9)

### Phase 3 : Checks additionnels (Story 5+)

- [ ] `check_maintenance_reminders` (Module 18)
- [ ] `check_calendar_conflicts` (Module 3)
- [ ] `check_patient_followups` (Module 7)
- [ ] `check_contract_renewals` (Module 8)

---

## 9. RÉFÉRENCES

- **Décision architecturale** : [docs/DECISION_LOG.md](../../docs/DECISION_LOG.md) (2026-02-05)
- **Analyse comparative OpenClaw** : Session Party Mode 2026-02-05
- **OpenClaw Heartbeat docs** : https://docs.openclaw.ai/automation/cron-vs-heartbeat
- **Trust Layer** : [CLAUDE.md](../../CLAUDE.md) section Observability

---

**Version** : 1.0.0
**Dernière mise à jour** : 2026-02-05
**Status** : ✅ Prêt pour implémentation Story 2.5
