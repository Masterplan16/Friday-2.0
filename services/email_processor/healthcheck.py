"""
Healthcheck pour email-processor consumer.
Verifie : connexion Redis, existence stream/consumer group.
"""

import os
import sys

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STREAM_NAME = "email.received"
CONSUMER_GROUP = "email-processor"

try:
    r = redis.from_url(REDIS_URL)

    # 1. Verifier connexion Redis
    r.ping()

    # 2. Verifier existence stream (cree par MKSTREAM au setup)
    if not r.exists(STREAM_NAME):
        # Stream pas encore cree = OK (pas encore de messages)
        print("HEALTHY (stream not yet created)")
        sys.exit(0)

    # 3. Verifier consumer group existe
    groups = r.xinfo_groups(STREAM_NAME)
    group_names = [g["name"].decode() if isinstance(g["name"], bytes) else g["name"] for g in groups]
    if CONSUMER_GROUP not in group_names:
        print(f"UNHEALTHY: Consumer group '{CONSUMER_GROUP}' missing")
        sys.exit(1)

    print("HEALTHY")
    sys.exit(0)

except redis.ConnectionError as e:
    print(f"UNHEALTHY: Redis connection failed - {e}")
    sys.exit(1)
except Exception as e:
    print(f"UNHEALTHY: {e}")
    sys.exit(1)
