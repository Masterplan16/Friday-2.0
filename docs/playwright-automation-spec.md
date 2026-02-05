# Playwright Automation - Spécifications Friday 2.0

**Date** : 2026-02-05
**Version** : 1.0.0
**Statut** : Planifié (implémentation Story 18 - Menus & Courses)

---

## 🎯 Objectif

Friday 2.0 utilise **Playwright** pour automatiser les sites web connus et stables (alternative fiable à Browser-Use qui a montré 60% de réussite réelle vs 89% annoncée).

**Principe** : Scripts scriptés manuellement pour sites spécifiques, pas d'automatisation générique.

---

## 📋 Sites automatisés

### 1. Carrefour Drive (Story 18)

**Usage** : Commande courses hebdomadaires

**Mode** : **Semi-automatique**
- Friday génère la liste de courses (Pydantic model)
- Friday pré-remplit le formulaire Carrefour Drive via Playwright
- Antonio valide visuellement avant confirmation
- Friday finalise la commande (choix créneau + paiement)

**Script** : `agents/src/tools/automation/carrefour_drive.py`

**Steps** :
1. Login Carrefour Drive (credentials via SOPS)
2. Vider panier actuel
3. Pour chaque produit de la liste :
   - Rechercher produit
   - Sélectionner premier résultat (ou meilleure correspondance)
   - Ajouter au panier
4. Afficher récapitulatif à Antonio (via Telegram)
5. Attendre validation Antonio (inline buttons)
6. Si approuvé : choisir créneau + finaliser
7. Si rejeté : abandonner ou éditer

**Robustesse** :
- Retry 3x si élément pas trouvé
- Screenshot à chaque étape critique
- Logs détaillés pour debug
- Timeout 60s max par action

**Tests** :
- Test E2E avec compte test Carrefour
- Dataset 20 listes de courses types
- Vérifier accuracy ≥90% sur ajout produits

---

### 2. Sites futurs (non prioritaires)

| Site | Usage | Story | Priorité |
|------|-------|-------|----------|
| Doctolib | Prise RDV entretien véhicule/médecin | TBD | P2 |
| EDF/Free | Consultation factures | TBD | P3 |
| Banques | Export CSV automatique (si pas d'API) | TBD | P2 |

---

## 🛠️ Architecture Playwright

### Structure fichiers

```
agents/src/tools/automation/
├── __init__.py
├── base.py                  # Classe base PlaywrightAutomation
├── carrefour_drive.py       # Script Carrefour Drive
└── screenshots/             # Screenshots debug
```

### Classe base

```python
# agents/src/tools/automation/base.py
from playwright.async_api import async_playwright, Page
import logging

class PlaywrightAutomation:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.logger = logging.getLogger(__name__)
        self.browser = None
        self.context = None
        self.page: Page = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)...'
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def screenshot(self, name: str):
        """Capture screenshot pour debug"""
        path = f"agents/src/tools/automation/screenshots/{name}.png"
        await self.page.screenshot(path=path)
        self.logger.info(f"Screenshot saved: {path}")

    async def wait_and_click(self, selector: str, timeout: int = 30000):
        """Attendre élément + cliquer"""
        await self.page.wait_for_selector(selector, timeout=timeout)
        await self.page.click(selector)

    async def fill_field(self, selector: str, value: str):
        """Remplir champ texte"""
        await self.page.fill(selector, value)
```

### Exemple Carrefour Drive

```python
# agents/src/tools/automation/carrefour_drive.py
from .base import PlaywrightAutomation
from typing import List
from pydantic import BaseModel

class GroceryItem(BaseModel):
    name: str
    quantity: int
    category: str

class CarrefourDriveAutomation(PlaywrightAutomation):
    async def login(self, email: str, password: str):
        """Login Carrefour Drive"""
        await self.page.goto("https://www.carrefour.fr/drive")
        await self.wait_and_click("button[aria-label='Se connecter']")
        await self.fill_field("input[name='email']", email)
        await self.fill_field("input[name='password']", password)
        await self.wait_and_click("button[type='submit']")
        await self.screenshot("login_success")

    async def add_to_cart(self, items: List[GroceryItem]) -> dict:
        """Ajouter produits au panier"""
        added = 0
        failed = []

        for item in items:
            try:
                # Rechercher produit
                await self.fill_field("input[name='search']", item.name)
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_selector(".product-card", timeout=5000)

                # Ajouter premier résultat
                await self.wait_and_click(".product-card:first-child button.add-to-cart")
                added += 1
                self.logger.info(f"✅ Added: {item.name}")

            except Exception as e:
                self.logger.error(f"❌ Failed: {item.name} - {e}")
                failed.append(item.name)

        return {"added": added, "failed": failed}

    async def checkout(self, slot_preference: str = "earliest"):
        """Finaliser commande"""
        await self.page.goto("https://www.carrefour.fr/drive/cart")
        await self.wait_and_click("button.checkout")
        # ... sélection créneau, paiement, etc.
```

---

## 🧪 Tests

### Test unitaire (mock)

```python
# tests/unit/test_carrefour_automation.py
@pytest.mark.asyncio
@patch("playwright.async_api.async_playwright")
async def test_add_to_cart_success(mock_playwright):
    items = [
        GroceryItem(name="Pommes", quantity=6, category="fruits"),
        GroceryItem(name="Pain", quantity=1, category="boulangerie")
    ]

    automation = CarrefourDriveAutomation(headless=True)
    # Mock browser interactions...
    result = await automation.add_to_cart(items)

    assert result["added"] == 2
    assert len(result["failed"]) == 0
```

### Test E2E (vrai site)

```python
# tests/e2e/test_carrefour_e2e.py
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_grocery_order_flow():
    """Test complet commande Carrefour Drive"""
    async with CarrefourDriveAutomation(headless=False) as automation:
        # Login
        await automation.login(
            email=os.getenv("CARREFOUR_TEST_EMAIL"),
            password=os.getenv("CARREFOUR_TEST_PASSWORD")
        )

        # Ajouter produits
        items = load_test_grocery_list()
        result = await automation.add_to_cart(items)

        # Vérifier accuracy
        accuracy = result["added"] / len(items)
        assert accuracy >= 0.90, f"Accuracy {accuracy*100:.1f}% < 90%"

        # Checkout (sans finaliser vraiment)
        await automation.page.goto("https://www.carrefour.fr/drive/cart")
        assert "Votre panier" in await automation.page.content()
```

---

## 🚨 Limitations et risques

| Risque | Mitigation |
|--------|-----------|
| **Changement UI Carrefour** | Monitoring hebdomadaire (cron), alertes Telegram si script échoue |
| **Captcha** | Utiliser compte authentifié (moins de captchas), retry manuel si bloqué |
| **Produits indisponibles** | Accepter échec partiel, proposer alternatives à Antonio |
| **Performance** | Headless mode, timeout courts, screenshots uniquement si erreur |

---

## 📊 Métriques de succès

| Métrique | Seuil |
|----------|-------|
| Accuracy ajout produits | ≥90% |
| Durée exécution | <3 min (20 produits) |
| Taux d'échec scripts | <5% |
| Maintenance requise | <1x/mois |

---

## 🔒 Sécurité

- Credentials Carrefour stockés chiffrés (age/SOPS)
- Scripts exécutés dans container Docker isolé
- Logs anonymisés (pas de credentials en clair)
- Screenshots supprimés après 7 jours

---

**Version** : 1.0.0
**Dernière mise à jour** : 2026-02-05
**Status** : Spécifié, implémentation Story 18
