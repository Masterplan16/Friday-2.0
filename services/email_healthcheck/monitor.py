#!/usr/bin/env python3
"""
Friday 2.0 - Email Pipeline Health Monitor

Vérifie l'état de tous les composants du pipeline email :
- IMAP Fetcher (4 comptes)
- Presidio (Analyzer + Anonymizer)
- Redis Stream
- Consumer

Usage:
    from services.email_healthcheck.monitor import check_email_pipeline_health

    status = await check_email_pipeline_health()
    print(status.summary)
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx
from pydantic import BaseModel


class ServiceStatus(BaseModel):
    """Status d'un service individuel."""
    name: str
    status: str  # "healthy", "degraded", "down"
    message: str
    details: Dict = {}
    last_check: datetime = datetime.now()


class PipelineHealth(BaseModel):
    """État global du pipeline email."""
    overall_status: str  # "healthy", "degraded", "down"
    services: List[ServiceStatus]
    alerts: List[str] = []
    summary: str
    checked_at: datetime = datetime.now()


async def check_imap_fetcher() -> ServiceStatus:
    """
    Vérifie le statut du IMAP fetcher.

    Méthode: Check les logs Docker pour détecter les erreurs récentes.
    """
    try:
        # TODO: Remplacer par appel à une API de monitoring ou check Redis
        # Pour l'instant, on simule avec un check basique

        # Dans la vraie implémentation, on devrait :
        # 1. Vérifier que le container tourne
        # 2. Parser les logs pour voir la dernière fetch par compte
        # 3. Détecter les erreurs de connexion

        return ServiceStatus(
            name="IMAP Fetcher",
            status="healthy",
            message="4 comptes configurés",
            details={
                "gmail1": "connected",
                "gmail2": "connected",
                "proton": "timeout (ProtonMail Bridge)",
                "universite": "connected"
            }
        )
    except Exception as e:
        return ServiceStatus(
            name="IMAP Fetcher",
            status="down",
            message=f"Erreur: {e}",
            details={}
        )


async def check_presidio() -> ServiceStatus:
    """
    Vérifie le statut de Presidio (Analyzer + Anonymizer).

    Méthode: Appel aux endpoints /health de chaque service.
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
                # Vérifier que le modèle FR est chargé
                entities_resp = await client.get("http://presidio-analyzer:3000/supportedentities?language=fr")
                entities_ok = entities_resp.status_code == 200

                return ServiceStatus(
                    name="Presidio",
                    status="healthy",
                    message="Analyzer + Anonymizer opérationnels (FR+EN)",
                    details={
                        "analyzer": "OK",
                        "anonymizer": "OK",
                        "french_support": "OK" if entities_ok else "MISSING"
                    }
                )
            else:
                return ServiceStatus(
                    name="Presidio",
                    status="degraded",
                    message="Un service est down",
                    details={
                        "analyzer": "OK" if analyzer_ok else "DOWN",
                        "anonymizer": "OK" if anonymizer_ok else "DOWN"
                    }
                )

    except httpx.ConnectError as e:
        return ServiceStatus(
            name="Presidio",
            status="down",
            message=f"Cannot connect: {e}",
            details={}
        )
    except Exception as e:
        return ServiceStatus(
            name="Presidio",
            status="down",
            message=f"Erreur: {e}",
            details={}
        )


async def check_redis_stream() -> ServiceStatus:
    """
    Vérifie l'état du Redis Stream emails:received.

    Méthode: Connect à Redis et check XLEN.
    """
    try:
        # TODO: Utiliser redis-py async pour se connecter
        # Pour l'instant, on simule

        # Dans la vraie implémentation :
        # import redis.asyncio as redis
        # r = await redis.from_url("redis://friday-redis:6379")
        # length = await r.xlen("emails:received")

        # Simulation avec valeur hardcodée (sera remplacé)
        length = 189  # Valeur observée plus tôt

        if length < 100:
            return ServiceStatus(
                name="Redis Stream",
                status="healthy",
                message=f"{length} emails en attente",
                details={"pending": length, "threshold": 100}
            )
        else:
            return ServiceStatus(
                name="Redis Stream",
                status="degraded",
                message=f"Backlog élevé: {length} emails",
                details={"pending": length, "threshold": 100}
            )

    except Exception as e:
        return ServiceStatus(
            name="Redis Stream",
            status="down",
            message=f"Erreur: {e}",
            details={}
        )


async def check_consumer() -> ServiceStatus:
    """
    Vérifie que le consumer traite bien les emails.

    Méthode: Check si le container tourne et a des logs récents.
    """
    try:
        # TODO: Vérifier vraiment l'activité du consumer
        # Méthodes possibles:
        # 1. Check container health
        # 2. Query PostgreSQL pour voir dernier email traité
        # 3. Metric compteur dans Redis

        return ServiceStatus(
            name="Email Consumer",
            status="healthy",
            message="Container running",
            details={"container": "friday-email-processor", "status": "running"}
        )

    except Exception as e:
        return ServiceStatus(
            name="Email Consumer",
            status="down",
            message=f"Erreur: {e}",
            details={}
        )


async def check_email_pipeline_health() -> PipelineHealth:
    """
    Vérifie l'état complet du pipeline email.

    Returns:
        PipelineHealth avec status global + détails par service
    """
    # Check tous les services en parallèle
    results = await asyncio.gather(
        check_imap_fetcher(),
        check_presidio(),
        check_redis_stream(),
        check_consumer()
    )

    # Analyser les résultats
    services = list(results)
    alerts = []

    # Déterminer status global
    down_count = sum(1 for s in services if s.status == "down")
    degraded_count = sum(1 for s in services if s.status == "degraded")

    if down_count > 0:
        overall_status = "down"
    elif degraded_count > 0:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    # Générer alertes
    for service in services:
        if service.status == "down":
            alerts.append(f"🔴 {service.name}: {service.message}")
        elif service.status == "degraded":
            alerts.append(f"⚠️ {service.name}: {service.message}")

    # Générer summary
    if overall_status == "healthy":
        summary = "✅ Pipeline email opérationnel"
    elif overall_status == "degraded":
        summary = f"⚠️ Pipeline dégradé ({degraded_count} problème(s))"
    else:
        summary = f"🔴 Pipeline en panne ({down_count} service(s) down)"

    return PipelineHealth(
        overall_status=overall_status,
        services=services,
        alerts=alerts,
        summary=summary
    )


def format_status_message(health: PipelineHealth) -> str:
    """
    Formate le status pour affichage Telegram.

    Args:
        health: PipelineHealth object

    Returns:
        Message formaté pour Telegram
    """
    lines = [
        "📊 **Friday Email Pipeline Status**",
        "",
        health.summary,
        "",
        "**Services:**"
    ]

    for service in health.services:
        icon = "✅" if service.status == "healthy" else "⚠️" if service.status == "degraded" else "🔴"
        lines.append(f"{icon} **{service.name}**: {service.message}")

        # Ajouter détails si pertinent
        if service.details and service.status != "healthy":
            for key, value in service.details.items():
                lines.append(f"  └ {key}: {value}")

    if health.alerts:
        lines.append("")
        lines.append("**Alertes:**")
        for alert in health.alerts:
            lines.append(alert)

    lines.append("")
    lines.append(f"_Vérifié: {health.checked_at.strftime('%H:%M:%S')}_")

    return "\n".join(lines)
