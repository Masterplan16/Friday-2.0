"""
Prompts few-shot pour extraction de garanties (Story 3.4 AC1).

5 exemples français couvrant les catégories :
Electronics, Appliances, Automotive, Medical, Furniture
"""
import json

WARRANTY_EXTRACTION_SYSTEM_PROMPT = """Tu es un assistant spécialisé dans l'extraction d'informations de garantie depuis des documents (factures, bons de garantie, reçus).

Analyse le texte OCR fourni et extrait les informations de garantie au format JSON strict.

Si AUCUNE information de garantie n'est détectée, retourne :
{"warranty_detected": false, "item_name": "", "item_category": "other", "vendor": null, "purchase_date": "", "warranty_duration_months": 0, "purchase_amount": null, "confidence": 0.0}

Catégories possibles : electronics, appliances, automotive, medical, furniture, other

Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

WARRANTY_EXTRACTION_EXAMPLES = [
    {
        "input": "Facture Amazon\nRef: 402-1234567-8901234\nImprimante HP DeskJet 3720\nDate: 04/02/2026\nPrix TTC: 149,99 EUR\nGarantie fabricant: 2 ans\nVendeur: Amazon EU S.a.r.l.",
        "output": {
            "warranty_detected": True,
            "item_name": "Imprimante HP DeskJet 3720",
            "item_category": "electronics",
            "vendor": "Amazon",
            "purchase_date": "2026-02-04",
            "warranty_duration_months": 24,
            "purchase_amount": 149.99,
            "confidence": 0.95
        }
    },
    {
        "input": "BON DE LIVRAISON\nDarty\nLave-linge Bosch Serie 4 WAN28228FF\nDate achat: 15/11/2025\nMontant: 549,00 EUR\nGarantie contractuelle Darty: 5 ans pièces et main d'oeuvre\nN° série: WAN28228FF-2025-789",
        "output": {
            "warranty_detected": True,
            "item_name": "Lave-linge Bosch Serie 4 WAN28228FF",
            "item_category": "appliances",
            "vendor": "Darty",
            "purchase_date": "2025-11-15",
            "warranty_duration_months": 60,
            "purchase_amount": 549.00,
            "confidence": 0.92
        }
    },
    {
        "input": "FACTURE\nNorauto Montpellier\nBatterie Bosch S4 005 60Ah\nDate: 23/08/2025\nPrix: 89,90 EUR TTC\nGarantie: 3 ans\nVéhicule: Peugeot 3008",
        "output": {
            "warranty_detected": True,
            "item_name": "Batterie Bosch S4 005 60Ah",
            "item_category": "automotive",
            "vendor": "Norauto",
            "purchase_date": "2025-08-23",
            "warranty_duration_months": 36,
            "purchase_amount": 89.90,
            "confidence": 0.90
        }
    },
    {
        "input": "FACTURE PROFORMA\nGIE AGORA\nOtoscope Heine Beta 200\nDate: 10/01/2026\nMontant HT: 285,00 EUR\nTVA 20%: 57,00 EUR\nTTC: 342,00 EUR\nGarantie constructeur: 2 ans",
        "output": {
            "warranty_detected": True,
            "item_name": "Otoscope Heine Beta 200",
            "item_category": "medical",
            "vendor": "GIE AGORA",
            "purchase_date": "2026-01-10",
            "warranty_duration_months": 24,
            "purchase_amount": 342.00,
            "confidence": 0.93
        }
    },
    {
        "input": "Facture IKEA Montpellier\nBureau MALM blanc 140x65cm\nRéf: 602.141.59\nDate: 20/12/2025\nPrix: 169,00 EUR\nGarantie: 10 ans sur structure\nMerci de votre visite",
        "output": {
            "warranty_detected": True,
            "item_name": "Bureau MALM blanc 140x65cm",
            "item_category": "furniture",
            "vendor": "IKEA",
            "purchase_date": "2025-12-20",
            "warranty_duration_months": 120,
            "purchase_amount": 169.00,
            "confidence": 0.91
        }
    }
]


def build_warranty_extraction_prompt(
    ocr_text: str,
    correction_rules: list | None = None
) -> str:
    """
    Construit le prompt utilisateur pour extraction de garantie.

    Args:
        ocr_text: Texte OCR du document (anonymisé)
        correction_rules: Règles de correction injectées par @friday_action

    Returns:
        Prompt formaté avec few-shot examples
    """
    # Section correction rules si disponibles
    rules_section = ""
    if correction_rules:
        rules_lines = []
        for rule in correction_rules:
            conditions = rule.get("conditions", "")
            output = rule.get("output", "")
            rules_lines.append(f"- Si {conditions} alors {output}")
        rules_section = (
            "\n**Règles de correction prioritaires (applique-les EN PREMIER) :**\n"
            + "\n".join(rules_lines)
            + "\n"
        )

    # Construire exemples few-shot
    examples_text = ""
    for i, example in enumerate(WARRANTY_EXTRACTION_EXAMPLES, 1):
        examples_text += f"\n--- Exemple {i} ---\nTexte OCR:\n{example['input']}\n\nRéponse:\n"
        examples_text += json.dumps(example["output"], ensure_ascii=False, indent=2)
        examples_text += "\n"

    # Tronquer OCR text pour économiser tokens
    truncated_text = ocr_text[:2000]

    prompt = f"""Analyse le document OCR suivant et extrait les informations de garantie.
{rules_section}
--- Exemples ---
{examples_text}
--- Document à analyser ---
Texte OCR:
{truncated_text}

Réponds UNIQUEMENT avec le JSON, sans texte additionnel."""

    return prompt
