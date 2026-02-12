"""
Healthcheck pour email-processor consumer.
Verifie : connexion Redis, activite recente, queue non bloquee.
"""

import os
import sys
import time

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STREAM_NAME = "emails:received"
CONSUMER_GROUP = "email-processor-group"

r = redis.from_url(REDIS_URL)

try:
    # 1. Verifier connexion Redis
    r.ping()

    # 2. Verifier existence stream
    if not r.exists(STREAM_NAME):
        # Stream pas encore cree = OK (pas encore de messages)
        print("HEALTHY (stream not yet created)")
        sys.exit(0)

    # 3. Verifier consumer group existe
    groups = r.xinfo_groups(STREAM_NAME)
    if not any(g["name"] == CONSUMER_GROUP for g in groups):
        print(f"UNHEALTHY: Consumer group '{CONSUMER_GROUP}' missing")
        sys.exit(1)

    # 4. Verifier pending messages < 100 (sinon accumulation)
    pending = r.xpending(STREAM_NAME, CONSUMER_GROUP)
    pending_count = pending["pending"]
    if pending_count > 100:
        print(f"UNHEALTHY: {pending_count} pending messages (threshold: 100)")
        sys.exit(1)

    # 5. Verifier activite recente (detecter consumer zombie)
    last_processed = r.get("email-processor:last_processed_at")
    if last_processed:
        last_ts = float(last_processed)
        idle_seconds = time.time() - last_ts
        # Si des messages pending ET consumer idle >5min -> zombie
        if pending_count > 0 and idle_seconds > 300:
            print(f"UNHEALTHY: Consumer idle {idle_seconds:.0f}s with {pending_count} pending")
            sys.exit(1)

    # 6. Verifier throughput (si metrique disponible)
    throughput = r.get("email-processor:emails_per_minute")
    if throughput and float(throughput) == 0 and pending_count > 10:
        print(f"UNHEALTHY: 0 emails/min with {pending_count} pending")
        sys.exit(1)

    print("HEALTHY")
    sys.exit(0)

except redis.ConnectionError as e:
    print(f"UNHEALTHY: Redis connection failed - {e}")
    sys.exit(1)
except Exception as e:
    print(f"UNHEALTHY: {e}")
    sys.exit(1)
