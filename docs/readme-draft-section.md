### 📝 Brouillons Réponse Email avec Few-Shot Learning (Story 2.5) ✅

**Friday génère automatiquement des brouillons de réponse email en apprenant votre style rédactionnel**

| Feature | Description |
|---------|-------------|
| **Modèle** | Claude Sonnet 4.5 (temperature 0.7, créatif) |
| **Apprentissage** | Few-shot learning : 0→5→10 exemples injectés dans prompt |
| **Style** | Formes de politesse, structure, vocabulaire, verbosité appris automatiquement |
| **RGPD** | Presidio anonymisation AVANT appel Claude cloud (fail-explicit) |
| **Trust Level** | **Toujours propose** - validation obligatoire même après 100% accuracy |
| **Threading** | inReplyTo + references correct (conversation cohérente) |
| **Interface** | Telegram inline buttons [Approve][Reject][Edit] |
| **Latence** | <10s (génération brouillon + notification Telegram) |
| **Coût** | ~$0.03-0.05 par brouillon (~$2-3/mois pour 50 brouillons) |

**Workflow** :

```
Email reçu → Classification → Brouillon généré →
  ↓
  Presidio anonymisation (RGPD)
  ↓
  Load writing_examples (top 5, filtre email_type)
  ↓
  Load correction_rules (module='email', scope='draft_reply')
  ↓
  Build prompts (few-shot + rules + user preferences)
  ↓
  Claude Sonnet 4.5 (temp=0.7, max_tokens=2000)
  ↓
  Dé-anonymisation + validation
  ↓
  Telegram notification topic Actions [Approve][Reject][Edit]
  ↓
  [Approve] → aiosmtplib send + INSERT writing_example [D25 : SMTP direct]
```

**Commandes Telegram** :
- `/draft <email_id>` — Générer brouillon manuellement
- Inline buttons [✅ Approve] [❌ Reject] [✏️ Edit] sur notifications

**Documentation** : [docs/email-draft-reply.md](docs/email-draft-reply.md)

---

**Note** : Insérer cette section dans README.md après la section Story 2.2 Classification Email, avant Story 2.3.
