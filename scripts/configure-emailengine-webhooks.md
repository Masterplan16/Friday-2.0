# Configuration Webhooks EmailEngine - Interface Web

## Accès interface web

Tunnel SSH déjà ouvert :
```
http://localhost:3001
```

## Configuration webhooks

1. **Navigation**
   - Menu latéral → **Configuration** → **Webhooks**

2. **Activer webhooks globalement**
   - ☑ **Webhooks Enabled** = `true`

3. **URL webhook**
   - **Webhook URL** = `http://friday-gateway:8000/api/v1/webhooks/emailengine/all`

4. **Sauvegarder**
   - Cliquer **Save**

## Vérification

```bash
ssh friday-vps bash <<'ENDSSH'
cd /opt/friday && source .env.email
curl -s -H "Authorization: Bearer $EMAILENGINE_ACCESS_TOKEN" \
  http://localhost:3000/v1/settings | python3 -m json.tool | grep -E '(webhooks|Enabled)'
ENDSSH
```

Devrait afficher :
```json
"webhooksEnabled": true,
"webhooks": "http://friday-gateway:8000/api/v1/webhooks/emailengine/all"
```

## Test E2E après configuration

1. Envoyer email test → antonio.lopez@umontpellier.fr (account_faculty)
2. Vérifier réception webhook dans logs gateway
3. Vérifier événement Redis Streams

