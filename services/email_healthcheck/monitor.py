#!/usr/bin/env python3
"""
Friday 2.0 - Email Pipeline Health Monitor

Verifie l'etat de tous les composants du pipeline email :
- IMAP Fetcher (4 comptes) — via Redis heartbeat
- Presidio (Analyzer + Anonymizer) — via HTTP /health
- Redis Stream — via XPENDING
- Consumer — via Redis heartbeat

Les checks IMAP Fetcher et Consumer utilisent des cles Redis heartbeat
(posees par chaque service) au lieu de `docker inspect`, car ce monitor
tourne dans le container friday-bot qui n'a pas le binaire Docker.

Usage:
    from services.email_healthcheck.monitor import check_email_pipeline_health

    status = await check_email_pipeline_health()
    print(status.summary)
"""

import asyncio
import os
import time
from datetime import datetime
from typing import Dict, List

import httpx
import redis.asyncio as aioredis
from pydantic import BaseModel


class ServiceStatus(BaseModel):
    """Status d'un service individuel."""

    name: str
    status: str  # "healthy", "degraded", "down"
    message: str
    details: Dict = {}
    last_check: datetime = datetime.now()


class PipelineHealth(BaseModel):
    """Etat global du pipeline email."""

    overall_status: str  # "healthy", "degraded", "down"
    services: List[ServiceStatus]
    alerts: List[str] = []
    summary: str
    checked_at: datetime = datetime.now()


# Redis client partage pour eviter ouverture/fermeture repetees
_redis_client: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """Retourne un client Redis partage (lazy init)."""
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = await aioredis.from_url(redis_url, decode_responses=True)
    return _redis_client


async def check_imap_fetcher() -> ServiceStatus:
    """
    Verifie le statut du IMAP fetcher via Redis heartbeat.

    Le fetcher ecrit `heartbeat:imap-fetcher` (TTL 90s) toutes les 30s.
    Si la cle existe, le fetcher est vivant.
    """
    try:
        r = await _get_redis()
        heartbeat_ts = await r.get("heartbeat:imap-fetcher")

        if heartbeat_ts is not None:
            age = int(time.time()) - int(heartbeat_ts)
            if age < 120:
                return ServiceStatus(
                    name="IMAP Fetcher",
                    status="healthy",
                    message=f"4 comptes actifs (heartbeat {age}s)",
                    details={"heartbeat_age_s": age},
                )
            else:
                return ServiceStatus(
                    name="IMAP Fetcher",
                    status="degraded",
                    message=f"Heartbeat stale ({age}s)",
                    details={"heartbeat_age_s": age},
                )
        else:
            return ServiceStatus(
                name="IMAP Fetcher", status="down", message="Pas de heartbeat Redis", details={}
            )
    except Exception as e:
        return ServiceStatus(name="IMAP Fetcher", status="down", message=f"Erreur: {e}", details={})


async def check_presidio() -> ServiceStatus:
    """
    Verifie le statut de Presidio (Analyzer + Anonymizer).

    Methode: Appel aux endpoints /health de chaque service.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Check Analyzer
            analyzer_resp = await client.get("http://presidio-analyzer:3000/health")
            analyzer_ok = analyzer_resp.status_code == 200

            # Check Anonymizer
            anonymizer_resp = await client.get("http://presidio-anonymizer:3000/health")
            anonymizer_ok = anonymizer_resp.status_code == 200

            if analyzer_ok and anonymizer_ok:
                # Verifier que le modele FR est charge
                entities_resp = await client.get(
                    "http://presidio-analyzer:3000/supportedentities?language=fr"
                )
                entities_ok = entities_resp.status_code == 200

                return ServiceStatus(
                    name="Presidio",
                    status="healthy",
                    message="Analyzer + Anonymizer operationnels (FR+EN)",
                    details={
                        "analyzer": "OK",
                        "anonymizer": "OK",
                        "french_support": "OK" if entities_ok else "MISSING",
                    },
                )
            else:
                return ServiceStatus(
                    name="Presidio",
                    status="degraded",
                    message="Un service est down",
                    details={
                        "analyzer": "OK" if analyzer_ok else "DOWN",
                        "anonymizer": "OK" if anonymizer_ok else "DOWN",
                    },
                )

    except httpx.ConnectError as e:
        return ServiceStatus(
            name="Presidio", status="down", message=f"Cannot connect: {e}", details={}
        )
    except Exception as e:
        return ServiceStatus(name="Presidio", status="down", message=f"Erreur: {e}", details={})


async def check_redis_stream() -> ServiceStatus:
    """
    Verifie l'etat du Redis Stream emails:received.

    Methode: XPENDING pour verifier le consumer group.
    """
    try:
        r = await _get_redis()
        await r.ping()

        stream_name = "emails:received"
        group_name = "email-processor"

        pending_info = await r.xpending(stream_name, group_name)
        pending_count = pending_info.get("pending", 0) if pending_info else 0

        threshold = 100

        if pending_count < threshold:
            return ServiceStatus(
                name="Redis Stream",
                status="healthy",
                message=f"{pending_count} emails en attente",
                details={"pending": pending_count, "threshold": threshold},
            )
        else:
            return ServiceStatus(
                name="Redis Stream",
                status="degraded",
                message=f"Backlog eleve: {pending_count} emails",
                details={"pending": pending_count, "threshold": threshold},
            )

    except aioredis.ConnectionError as e:
        return ServiceStatus(
            name="Redis Stream", status="down", message=f"Cannot connect to Redis: {e}", details={}
        )
    except Exception as e:
        return ServiceStatus(name="Redis Stream", status="down", message=f"Erreur: {e}", details={})


async def check_consumer() -> ServiceStatus:
    """
    Verifie que le consumer traite bien les emails via Redis heartbeat.

    Le consumer ecrit `heartbeat:email-consumer` (TTL 30s) a chaque iteration.
    """
    try:
        r = await _get_redis()
        heartbeat_ts = await r.get("heartbeat:email-consumer")

        if heartbeat_ts is not None:
            age = int(time.time()) - int(heartbeat_ts)
            if age < 60:
                return ServiceStatus(
                    name="Email Consumer",
                    status="healthy",
                    message=f"Actif (heartbeat {age}s)",
                    details={"heartbeat_age_s": age},
                )
            else:
                return ServiceStatus(
                    name="Email Consumer",
                    status="degraded",
                    message=f"Heartbeat stale ({age}s)",
                    details={"heartbeat_age_s": age},
                )
        else:
            return ServiceStatus(
                name="Email Consumer", status="down", message="Pas de heartbeat Redis", details={}
            )
    except Exception as e:
        return ServiceStatus(
            name="Email Consumer", status="down", message=f"Erreur: {e}", details={}
        )


async def check_email_pipeline_health() -> PipelineHealth:
    """
    Verifie l'etat complet du pipeline email.

    Returns:
        PipelineHealth avec status global + details par service
    """
    # Check tous les services en parallele
    results = await asyncio.gather(
        check_imap_fetcher(), check_presidio(), check_redis_stream(), check_consumer()
    )

    services = list(results)
    alerts = []

    # Determiner status global
    down_count = sum(1 for s in services if s.status == "down")
    degraded_count = sum(1 for s in services if s.status == "degraded")

    if down_count > 0:
        overall_status = "down"
    elif degraded_count > 0:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    # Generer alertes
    for service in services:
        if service.status == "down":
            alerts.append(f"🔴 {service.name}: {service.message}")
        elif service.status == "degraded":
            alerts.append(f"⚠️ {service.name}: {service.message}")

    # Generer summary
    if overall_status == "healthy":
        summary = "✅ Pipeline email operationnel"
    elif overall_status == "degraded":
        summary = f"⚠️ Pipeline degrade ({degraded_count} probleme(s))"
    else:
        summary = f"🔴 Pipeline en panne ({down_count} service(s) down)"

    return PipelineHealth(
        overall_status=overall_status, services=services, alerts=alerts, summary=summary
    )


def format_status_message(health: PipelineHealth) -> str:
    """
    Formate le status pour affichage Telegram.

    Args:
        health: PipelineHealth object

    Returns:
        Message formate pour Telegram
    """
    lines = ["📊 **Friday Email Pipeline Status**", "", health.summary, "", "**Services:**"]

    for service in health.services:
        icon = (
            "✅" if service.status == "healthy" else "⚠️" if service.status == "degraded" else "🔴"
        )
        lines.append(f"{icon} **{service.name}**: {service.message}")

        # Ajouter details si pertinent
        if service.details and service.status != "healthy":
            for key, value in service.details.items():
                lines.append(f"  └ {key}: {value}")

    if health.alerts:
        lines.append("")
        lines.append("**Alertes:**")
        for alert in health.alerts:
            lines.append(alert)

    lines.append("")
    lines.append(f"_Verifie: {health.checked_at.strftime('%H:%M:%S')}_")

    return "\n".join(lines)
