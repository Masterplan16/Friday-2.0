# Redis ACL Setup - Friday 2.0

**Date** : 2026-02-05
**Version** : 1.0.0
**Principe** : Moindre privilège par service

---

## 📋 Vue d'ensemble

Redis ACL (Access Control Lists) permet de restreindre l'accès de chaque service Friday 2.0 aux commandes et clés Redis nécessaires **uniquement**.

**Avantages** :
- ✅ Sécurité : Limiter blast radius si un service compromis
- ✅ Isolation : Chaque service voit uniquement ses données
- ✅ Audit : Tracer qui fait quoi dans Redis

---

## 🔐 ACL par service

### **1. Gateway API**

**Besoins** :
- Cache queries (GET, SET, EXPIRE)
- Pub/Sub informatif (PUBLISH)

**ACL** :
```redis
ACL SETUSER friday_gateway on >PASSWORD_GATEWAY ~cache:* +get +set +setex +del +expire +ttl +publish allchannels
```

---

### **2. Agents IA (email, archiviste, etc.)**

**Besoins** :
- Publier événements critiques (XADD sur Streams)
- Lire leur consumer group (XREADGROUP)
- Acknowledge messages (XACK)
- **Mapping Presidio** : READ/WRITE `presidio:mapping:*` (TTL 1h)

**ACL** :
```redis
ACL SETUSER friday_agents on >PASSWORD_AGENTS ~stream:* ~presidio:mapping:* +xadd +xreadgroup +xack +xpending +get +setex +del allchannels
```

**Note** : `+setex` pour mapping Presidio avec TTL automatique, `+get` pour désanonymisation, `+del` pour nettoyage manuel si besoin.

---

### **3. Alerting service**

**Besoins** :
- Consommer événements critiques (XREADGROUP sur tous Streams)
- Publier alertes (XADD)

**ACL** :
```redis
ACL SETUSER friday_alerting on >PASSWORD_ALERTING ~stream:* +xreadgroup +xack +xadd +xpending allchannels
```

---

### **4. Metrics service**

**Besoins** :
- Lire métriques (GET sur clés metrics:*)
- Écrire agrégations (SET, INCRBY)

**ACL** :
```redis
ACL SETUSER friday_metrics on >PASSWORD_METRICS ~metrics:* +get +set +incrby +expire allchannels
```

---

### **5. n8n workflows**

**Besoins** :
- Publier événements Pub/Sub informatifs
- Lire cache (lecture seule)

**ACL** :
```redis
ACL SETUSER friday_n8n on >PASSWORD_N8N ~cache:* +get +publish allchannels
```

---

## 🛠️ Configuration Redis

### **1. Créer fichier users.acl**

```bash
# /etc/redis/users.acl

# Admin (usage dev/debug uniquement, pas en prod)
user admin on >ADMIN_PASSWORD ~* &* +@all

# Gateway
user friday_gateway on >GATEWAY_PASSWORD ~cache:* +get +set +setex +del +expire +ttl +publish allchannels

# Agents IA (+ mapping Presidio)
user friday_agents on >AGENTS_PASSWORD ~stream:* ~presidio:mapping:* +xadd +xreadgroup +xack +xpending +get +setex +del allchannels

# Alerting
user friday_alerting on >ALERTING_PASSWORD ~stream:* +xreadgroup +xack +xadd +xpending allchannels

# Metrics
user friday_metrics on >METRICS_PASSWORD ~metrics:* +get +set +incrby +expire allchannels

# n8n
user friday_n8n on >N8N_PASSWORD ~cache:* +get +publish allchannels
```

---

### **2. Activer ACL dans redis.conf**

```bash
# /etc/redis/redis.conf

# Charger fichier ACL
aclfile /etc/redis/users.acl

# Désactiver user default (force authentification)
# user default off nopass ~* &* -@all
```

---

### **3. Recharger configuration Redis**

```bash
# Méthode 1 : Sans redémarrage (hot reload)
redis-cli CONFIG REWRITE
redis-cli ACL LOAD

# Méthode 2 : Redémarrage complet
docker compose restart redis
```

---

## 🔑 Génération mots de passe sécurisés

```bash
# Générer 6 passwords forts (1 par service + admin)
for service in admin gateway agents alerting metrics n8n; do
  echo "$service: $(openssl rand -base64 32)"
done > redis_passwords.txt

# Chiffrer avec age/SOPS (JAMAIS en clair)
age -r $(cat ~/.ssh/id_ed25519.pub) -o redis_passwords.txt.age redis_passwords.txt
rm redis_passwords.txt  # Supprimer version clair
```

---

## 📝 Variables d'environnement

Dans `.env` (chiffré avec SOPS) :

```env
# Redis ACL credentials
REDIS_GATEWAY_PASSWORD=<généré>
REDIS_AGENTS_PASSWORD=<généré>
REDIS_ALERTING_PASSWORD=<généré>
REDIS_METRICS_PASSWORD=<généré>
REDIS_N8N_PASSWORD=<généré>
```

Dans `docker-compose.yml` :

```yaml
services:
  gateway:
    environment:
      - REDIS_URL=redis://friday_gateway:${REDIS_GATEWAY_PASSWORD}@redis:6379/0

  agents:
    environment:
      - REDIS_URL=redis://friday_agents:${REDIS_AGENTS_PASSWORD}@redis:6379/0

  # ... etc
```

---

## 🧪 Tests ACL

### **Test 1 : Gateway peut lire/écrire cache**

```bash
redis-cli -u redis://friday_gateway:PASSWORD@localhost:6379
> SET cache:test "hello"
OK
> GET cache:test
"hello"
> XADD stream:test * field value
(error) NOPERM this user has no permissions to run the 'xadd' command
```

✅ Correct : Gateway peut cache, PAS streams.

---

### **Test 2 : Agents peuvent publier streams + mapping Presidio**

```bash
redis-cli -u redis://friday_agents:PASSWORD@localhost:6379
> XADD stream:email.received * message_id "123"
"1707139200000-0"
> SETEX presidio:mapping:[EMAIL_abc123] 3600 "mainteneur@example.com"
OK
> GET presidio:mapping:[EMAIL_abc123]
"mainteneur@example.com"
> SET cache:test "fail"
(error) NOPERM this user has no permissions to access one of the keys used as arguments
```

✅ Correct : Agents peuvent streams + mapping Presidio (TTL 1h), PAS cache.

---

## 🔍 Monitoring ACL

### **Commandes utiles**

```bash
# Lister tous les users
redis-cli ACL LIST

# Voir permissions d'un user
redis-cli ACL GETUSER friday_gateway

# Logs des échecs ACL
redis-cli ACL LOG 10
```

---

## 🚨 Troubleshooting

### **Erreur : NOAUTH Authentication required**

**Cause** : Service utilise URL Redis sans credentials.

**Fix** :
```bash
# Vérifier .env
grep REDIS docker-compose.yml
grep REDIS .env

# Doit être : redis://user:password@redis:6379/0
# PAS : redis://redis:6379/0
```

---

### **Erreur : NOPERM this user has no permissions**

**Cause** : User essaie commande non autorisée.

**Debug** :
```bash
# Vérifier ACL user
redis-cli ACL GETUSER friday_gateway

# Ajouter permission si légitime
redis-cli ACL SETUSER friday_gateway +command
redis-cli CONFIG REWRITE
```

---

## 📊 Tableau récapitulatif ACL

| Service | User | Clés autorisées | Commandes | Channels |
|---------|------|-----------------|-----------|----------|
| Gateway | `friday_gateway` | `cache:*` | GET, SET, SETEX, DEL, EXPIRE, TTL, PUBLISH | all |
| Agents | `friday_agents` | `stream:*`, `presidio:mapping:*` | XADD, XREADGROUP, XACK, XPENDING, GET, SETEX, DEL | all |
| Alerting | `friday_alerting` | `stream:*` | XREADGROUP, XACK, XADD, XPENDING | all |
| Metrics | `friday_metrics` | `metrics:*` | GET, SET, INCRBY, EXPIRE | all |
| n8n | `friday_n8n` | `cache:*` | GET, PUBLISH | all |

---

## 🔗 Références

- [Redis ACL Documentation](https://redis.io/docs/manual/security/acl/)
- [Redis ACL Tutorial](https://redis.io/docs/manual/security/acl/#acl-rules)
- [age encryption](https://github.com/FiloSottile/age)
- [SOPS](https://github.com/mozilla/sops)

---

**Version** : 1.0.0
**Dernière mise à jour** : 2026-02-05
