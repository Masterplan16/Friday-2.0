# Security Policy - Friday 2.0

## 🎯 Objectif

Friday 2.0 est un assistant personnel intelligent gérant des données sensibles (emails, documents, informations médicales/financières). La sécurité et le respect du RGPD sont **critiques**.

---

## 🔒 Principes de sécurité

### 1. Protection des données personnelles (RGPD)

- **Anonymisation obligatoire** : Toute donnée sensible envoyée au LLM cloud (Claude Sonnet 4.5) passe par [Presidio](https://microsoft.github.io/presidio/) pour anonymisation
- **Fail-explicit** : Si Presidio n'est pas opérationnel, le système s'arrête plutôt que de transmettre des données en clair
- **Chiffrement pgcrypto** : Colonnes sensibles PostgreSQL (données médicales, financières) chiffrées au repos
- **Mapping éphémère** : Correspondances anonymisation/déanonymisation stockées en mémoire uniquement (jamais persistées)

### 2. Gestion des secrets

- **age + SOPS** : Tous les secrets (`.env`, credentials) sont chiffrés avec [age](https://github.com/FiloSottile/age) et [SOPS](https://github.com/getsops/sops)
- **Zéro credential en clair** : Aucun secret dans le code source ou l'historique Git
- **Rotation régulière** : Tokens API renouvelés tous les 3-6 mois
- **Clé age privée** : Stockée localement (`~/.age/friday-key.txt`), jamais commitée

### 3. Sécurité réseau

- **Tailscale VPN mesh** : Aucun service exposé sur Internet public
- **SSH via Tailscale uniquement** : Pas de port 22 ouvert publiquement
- **2FA obligatoire** : Authentification Tailscale nécessite 2FA + device authorization
- **Caddy reverse proxy** : TLS automatique pour services internes
- **Redis ACL** : Moindre privilège par service (gateway, agents, metrics, etc.)

### 4. Infrastructure sécurisée

- **VPS OVH VPS-4** : 48 Go RAM, 12 vCores, basé en France (RGPD-compliant)
- **Backups chiffrés quotidiens** : PostgreSQL + volumes Docker sauvegardés avec age, copiés sur PC via Tailscale
- **Monitoring RAM** : Alerte Telegram si >85% (40.8 Go sur 48 Go)
- **Self-Healing Tier 1-2** : Redémarrage automatique services critiques

---

## 🛡️ Versions supportées

| Version | Statut | Fin support |
|---------|--------|-------------|
| 2.0 (Sprint 1 MVP) | 🚧 En développement | N/A |
| 1.x (Jarvis Friday) | ❌ Legacy | 2026-02-01 |

**Note** : Friday 2.0 est actuellement en développement pré-release. Aucune version publique n'est disponible.

---

## 🚨 Signaler une vulnérabilité

### Pour les contributeurs externes (si le repo devient public)

**NE PAS** créer d'issue publique GitHub pour les vulnérabilités de sécurité.

**Procédure** :
1. **Email privé** : Contactez Friday 2.0 Maintainer via [security@friday-project.example.com](mailto:security@friday-project.example.com) *(remplacer par vraie adresse)*
2. **Objet** : `[SECURITY] Friday 2.0 - <description courte>`
3. **Contenu** :
   - Description détaillée de la vulnérabilité
   - Steps to reproduce
   - Impact potentiel (RGPD, credentials leak, etc.)
   - Preuve de concept (optionnel, sécurisé)

**Engagement** :
- Accusé réception sous **48h**
- Analyse et correction sous **7 jours** (critique), **14 jours** (high), **30 jours** (medium)
- Publication coordonnée du fix (CVE si applicable)

### Pour Mainteneur (développeur principal)

En cas de découverte de vulnérabilité interne :
1. **Évaluation immédiate** : Risque RGPD ? Exposition credentials ?
2. **Mitigation rapide** : Rotation secrets, patch temporaire
3. **Fix définitif** : Tests, review adversarial, déploiement
4. **Post-mortem** : Documentation dans `docs/DECISION_LOG.md`

---

## 📋 Checklist sécurité mensuelle

- [ ] **Audit git-secrets** : Scanner historique Git avec `git secrets --scan-history`
- [ ] **Rotation secrets non-critiques** : Régénérer tokens API non-essentiels
- [ ] **Review logs sécurité** : Vérifier logs Caddy, Presidio, PostgreSQL pour anomalies
- [ ] **Backup restore test** : Tester restauration backup chiffré sur environnement test
- [ ] **Dépendances CVE** : Scanner avec Dependabot, appliquer patches critiques sous 7j
- [ ] **Review .gitignore** : Vérifier aucun nouveau secret exposé

---

## 🔐 Gestion des secrets - Accès équipe

### Clé age publique du projet

```
age17zcpkgjxdyk6g34anhymukncq49dtf6k4f3vgp5fchsv04a8quzq7rjn8t
```

Cette clé publique est utilisée pour chiffrer les secrets commitables (`.env.enc`, etc.).

### Ajouter un nouveau développeur

Voir [docs/secrets-management.md](docs/secrets-management.md) - Section "Partage de secrets avec l'équipe".

**Résumé** :
1. Nouveau dev génère sa clé age : `age-keygen -o ~/.age/friday-key.txt`
2. Partage sa clé **publique** (secure channel)
3. Admin ajoute la clé publique à `.sops.yaml`
4. Admin re-chiffre secrets avec nouvelle config
5. Nouveau dev peut déchiffrer avec sa clé privée

---

## 🧪 Tests de sécurité

### Tests critiques RGPD

| Test | Fréquence | Responsable |
|------|-----------|-------------|
| Anonymisation Presidio | Chaque PR | CI/CD (pytest) |
| Détection secrets Git | Pre-commit | git-secrets hook |
| Backup restore | Hebdomadaire | Cron VPS |
| Rotation credentials | Mensuel | Mainteneur |
| Scan CVE dépendances | Quotidien | Dependabot |

### Datasets de test PII

Voir [tests/fixtures/README.md](tests/fixtures/README.md) pour les datasets anonymisés utilisés dans les tests :
- **PII samples** : Noms, emails, téléphones, IBAN (fictifs)
- **Medical data** : Pathologies, prescriptions (synthétiques)
- **Financial data** : Transactions, comptes (générées)

---

## 📚 Références

- **Architecture complète** : [_docs/architecture-friday-2.0.md](_docs/architecture-friday-2.0.md)
- **Secrets management** : [docs/secrets-management.md](docs/secrets-management.md)
- **Audit sécurité** : [docs/security-audit.md](docs/security-audit.md)
- **Redis ACL** : Configuration dans `config/redis.acl`
- **RGPD compliance** : Section 5 de l'architecture

---

## 📜 Licence

Voir [LICENSE](LICENSE) pour les détails.

---

**Dernière mise à jour** : 2026-02-10
**Contact sécurité** : security@friday-project.example.com *(à remplacer)*
**Version** : 1.0.0
