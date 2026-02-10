# Friday 2.0 - Components Versions

Documentation des versions des composants critiques installés dans l'infrastructure Friday 2.0.

## Encryption & Security

### age (Asymmetric Encryption)

**Version installée** : `v1.3.0`
**Source** : [FiloSottile/age GitHub](https://github.com/FiloSottile/age/releases/tag/v1.3.0)
**Installation** : Dockerfile.n8n (Story 1.12)
**Container** : friday-n8n
**Usage** : Chiffrement backups PostgreSQL (AC3 Story 1.12)
**Features** :
- Support post-quantum keys (ML-KEM, X25519Kyber768Draft00)
- Chiffrement asymétrique (clé publique VPS, clé privée PC-only)
- Compatible avec OpenSSH keys

**Vérification installation** :
```bash
docker exec friday-n8n age --version
# Output attendu: v1.3.0
```

**Réévaluation** : Upgrade si vulnérabilité CVE détectée ou nouvelle version majeure (v2.x)

---

## Database

### PostgreSQL

**Version** : `16` (avec extension pgvector)
**Image** : `pgvector/pgvector:pg16`
**Story** : 1.1 Infrastructure Docker Compose

### pgvector Extension

**Version** : Incluse dans image pgvector:pg16
**Decision** : D19 (2026-02-09) - Remplace Qdrant pour Day 1
**Capacity** : 100k vecteurs, 1 utilisateur
**Réévaluation** : Si >300k vecteurs ou latence >100ms

---

## Workflow Automation

### n8n

**Version** : `2.2.4`
**Image base** : `n8nio/n8n:2.2.4`
**Dockerfile custom** : `Dockerfile.n8n` (Story 1.12)
**Customisations** :
- age CLI v1.3.0 installé
- Volume /backups monté
- Scripts/ accessible en lecture seule

---

## Cache & Pub/Sub

### Redis

**Version** : `7.4-alpine`
**Image** : `redis:7.4-alpine`
**Story** : 1.1 Infrastructure Docker Compose

---

## Reverse Proxy

### Caddy

**Version** : `2.10.2-alpine`
**Image** : `caddy:2.10.2-alpine`
**Story** : 1.1 Infrastructure Docker Compose

---

## Bot Telegram

### Python Base Image

**Version** : À documenter (Dockerfile.bot)
**Story** : 1.9 Bot Telegram Core & Topics

---

**Dernière mise à jour** : 2026-02-10 (Story 1.12 - Task 1.1)
