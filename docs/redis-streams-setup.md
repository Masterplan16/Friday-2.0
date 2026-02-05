# Redis Streams - Setup & Configuration

**Date** : 2026-02-05
**Version** : 1.0.0
**Objectif** : Configuration complète Redis Streams pour événements critiques Friday 2.0

---

## 🎯 Principe

Friday 2.0 utilise **Redis Streams** (pas Pub/Sub) pour les événements critiques afin de garantir :
- ✅ Delivery garanti (même si consumer temporairement down)
- ✅ Persistence des événements
- ✅ Replay possible en cas d'erreur
- ✅ Consumer groups pour load balancing

**Événements critiques** (via Redis Streams) :
- `email.received`
- `document.processed`
- `pipeline.error`
- `service.down`
- `trust.level.changed`
- `action.corrected`
- `action.validated`

**Événements informatifs** (via Redis Pub/Sub) :
- `agent.completed`
- `file.uploaded`

---

## 📚 Concepts Redis Streams

### **Stream = Log d'événements**

Chaque événement a un **ID unique** (timestamp + séquence) :
```
1517574547834-0  → timestamp-sequence
```

### **Consumer Group = Groupe de workers**

Plusieurs consumers peuvent lire le même stream en parallèle sans dupliquer le travail.

### **Pending Entries List (PEL)**

Événements "en cours de traitement" par un consumer. Permet retry si consumer crash.

---

## 🛠️ Setup initial

### **1. Créer les streams et consumer groups**

```bash
# Script: scripts/setup-redis-streams.sh

#!/bin/bash

REDIS_HOST=${REDIS_HOST:-localhost}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_PASSWORD=${REDIS_PASSWORD:-}

# Helper function
create_stream_group() {
    local stream=$1
    local group=$2

    echo "📝 Creating consumer group: $stream → $group"

    if [ -n "$REDIS_PASSWORD" ]; then
        redis-cli -h $REDIS_HOST -p $REDIS_PORT -a "$REDIS_PASSWORD" --no-auth-warning \
            XGROUP CREATE $stream $group $ MKSTREAM
    else
        redis-cli -h $REDIS_HOST -p $REDIS_PORT \
            XGROUP CREATE $stream $group $ MKSTREAM
    fi
}

echo "🚀 Setup Redis Streams for Friday 2.0"
echo "========================================"

# Créer consumer groups pour chaque stream critique
create_stream_group "email.received" "email-processor"
create_stream_group "document.processed" "document-indexer"
create_stream_group "pipeline.error" "error-handler"
create_stream_group "service.down" "monitoring"
create_stream_group "trust.level.changed" "trust-manager"
create_stream_group "action.corrected" "feedback-loop"
create_stream_group "action.validated" "trust-manager"

echo ""
echo "✅ Redis Streams setup complete!"
echo ""
echo "Verify with:"
echo "  redis-cli XINFO GROUPS email.received"
```

**Exécuter** :
```bash
chmod +x scripts/setup-redis-streams.sh
./scripts/setup-redis-streams.sh
```

### **2. Vérifier la création**

```bash
# Lister les groups d'un stream
redis-cli XINFO GROUPS email.received

# Output attendu:
# 1) name: email-processor
# 2) consumers: 0
# 3) pending: 0
# 4) last-delivered-id: 0-0
```

---

## 📤 Producer : Publier un événement

### **Python (asyncio)**

```python
# agents/src/utils/redis_streams.py

import redis.asyncio as redis
import json
from typing import Dict, Any

class RedisStreamsPublisher:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def publish_event(self, stream: str, payload: Dict[str, Any]) -> str:
        """
        Publie un événement dans un stream Redis

        Returns:
            event_id: ID de l'événement publié (ex: "1517574547834-0")
        """
        # Sérialiser le payload en JSON string
        serialized_payload = {
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in payload.items()
        }

        # XADD: Ajouter événement au stream
        event_id = await self.redis.xadd(
            stream,
            serialized_payload,
            maxlen=10000,  # Garder max 10k événements (FIFO)
            approximate=True  # Performance: trim approximatif OK
        )

        return event_id

# Usage
publisher = RedisStreamsPublisher("redis://localhost:6379")

await publisher.publish_event("email.received", {
    "email_id": "abc123",
    "category": "medical",
    "priority": "high",
    "has_attachments": True
})
```

### **n8n (HTTP Request node)**

```javascript
// n8n: Publish to Redis Stream node

const stream = "email.received";
const payload = {
    email_id: $json.email_id,
    category: $json.category,
    priority: $json.priority,
    has_attachments: $json.attachments.length > 0
};

// Appeler FastAPI endpoint qui publish dans Redis
return {
    method: "POST",
    url: `http://gateway:8000/api/v1/events/publish`,
    body: {
        stream: stream,
        payload: payload
    }
};
```

---

## 📥 Consumer : Lire les événements

### **Python (asyncio) - Consumer simple**

```python
# services/email-processor/consumer.py

import redis.asyncio as redis
import json
import asyncio

class RedisStreamsConsumer:
    def __init__(self, redis_url: str, stream: str, group: str, consumer_name: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.stream = stream
        self.group = group
        self.consumer_name = consumer_name

    async def consume(self, handler):
        """
        Consomme les événements d'un stream avec consumer group

        Args:
            handler: Fonction async à appeler pour chaque événement
        """
        print(f"🔄 Listening to {self.stream} as {self.group}/{self.consumer_name}")

        while True:
            try:
                # XREADGROUP: Lire nouveaux événements
                events = await self.redis.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer_name,
                    streams={self.stream: ">"},  # ">" = nouveaux messages uniquement
                    count=10,  # Batch de 10 événements max
                    block=5000  # Block 5s si aucun événement
                )

                if not events:
                    continue  # Timeout, retry

                for stream_name, messages in events:
                    for event_id, payload in messages:
                        try:
                            # Désérialiser payload
                            data = {
                                k: json.loads(v) if v.startswith(("{", "[")) else v
                                for k, v in payload.items()
                            }

                            # Traiter événement
                            await handler(event_id, data)

                            # ACK: Marquer comme traité
                            await self.redis.xack(self.stream, self.group, event_id)

                        except Exception as e:
                            print(f"❌ Error processing {event_id}: {e}")
                            # Ne pas ACK → restera dans Pending List

            except asyncio.CancelledError:
                print("🛑 Consumer stopped")
                break
            except Exception as e:
                print(f"❌ Consumer error: {e}")
                await asyncio.sleep(5)  # Retry après 5s

# Usage
async def handle_email_received(event_id: str, payload: dict):
    print(f"📧 Processing email {payload['email_id']}")
    # ... traitement ...

consumer = RedisStreamsConsumer(
    redis_url="redis://localhost:6379",
    stream="email.received",
    group="email-processor",
    consumer_name="worker-1"
)

await consumer.consume(handle_email_received)
```

---

## 🔄 Retry & Recovery

### **Pending List : Récupérer événements non ACKés**

Si un consumer crash avant d'ACK, les événements restent dans la **Pending Entries List**.

**Script de recovery** :

```python
async def claim_pending_events(self, idle_time_ms: int = 60000):
    """
    Récupère les événements pending depuis plus de idle_time_ms

    Args:
        idle_time_ms: Temps minimum depuis dernier delivery (défaut: 60s)
    """
    # XPENDING: Lister événements pending
    pending = await self.redis.xpending_range(
        self.stream,
        self.group,
        min="-",
        max="+",
        count=100
    )

    if not pending:
        return

    print(f"⚠️  Found {len(pending)} pending events")

    for entry in pending:
        event_id = entry['message_id']
        consumer = entry['consumer']
        idle_ms = entry['time_since_delivered']

        if idle_ms < idle_time_ms:
            continue  # Pas encore timeout

        # XCLAIM: Réclamer l'événement
        claimed = await self.redis.xclaim(
            self.stream,
            self.group,
            self.consumer_name,
            min_idle_time=idle_time_ms,
            message_ids=[event_id]
        )

        if claimed:
            event_id_claimed, payload = claimed[0]
            print(f"🔁 Reclaimed event {event_id} from {consumer}")
            # Retraiter l'événement...
```

**Cron de recovery** (toutes les minutes) :

```python
# services/recovery/cron.py

async def recovery_loop():
    consumer = RedisStreamsConsumer(...)

    while True:
        await consumer.claim_pending_events(idle_time_ms=60000)
        await asyncio.sleep(60)  # Vérifier toutes les 1min
```

---

## 🔍 Monitoring

### **Dashboard Redis Streams**

```bash
# scripts/redis-streams-status.sh

#!/bin/bash

echo "📊 Redis Streams Status"
echo "======================="

for stream in "email.received" "document.processed" "pipeline.error"; do
    echo ""
    echo "Stream: $stream"
    echo "----------------------------------------"

    # Longueur du stream
    redis-cli XLEN $stream

    # Consumer groups
    redis-cli XINFO GROUPS $stream

    # Pending entries
    redis-cli XPENDING $stream email-processor
done
```

### **Métriques à surveiller**

| Métrique | Commande | Alerte si |
|----------|----------|-----------|
| Stream length | `XLEN email.received` | > 1000 (backlog) |
| Pending count | `XPENDING email.received email-processor` | > 100 (consumers lents) |
| Lag (derniers 5min) | Custom script | > 500 events |
| Consumer actifs | `XINFO GROUPS` | = 0 (aucun consumer) |

---

## 🧹 Maintenance

### **Trim automatique**

Redis Streams garde tous les événements par défaut. Utiliser `MAXLEN` pour limiter :

```bash
# Garder max 10k événements par stream
redis-cli XTRIM email.received MAXLEN ~ 10000
```

### **Supprimer anciens consumer groups**

```bash
# Supprimer un consumer group (si plus utilisé)
redis-cli XGROUP DESTROY email.received old-processor
```

---

## 📋 Checklist production

- [ ] Consumer groups créés (`./scripts/setup-redis-streams.sh`)
- [ ] Consumers démarrés (1+ par groupe)
- [ ] Recovery cron actif (claim pending events)
- [ ] Monitoring alertes configurées (backlog, pending, lag)
- [ ] MAXLEN configuré sur tous les streams (limite taille)
- [ ] Tests end-to-end passent (publish → consume → ACK)

---

**Créé le** : 2026-02-05
**Version** : 1.0.0
**Contributeur** : Claude (Code Review Adversarial - Issue #4)
