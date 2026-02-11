"""
Bot Telegram Friday 2.0 - Formatters

Story 1.11: Helpers de formatage reutilisables pour commandes Telegram.
"""

from datetime import datetime, timezone

# Mapping status -> emoji (AC3)
STATUS_EMOJIS: dict[str, str] = {
    "auto": "\u2705",  # check mark
    "pending": "\u23f3",  # hourglass
    "approved": "\u2714\ufe0f",  # check
    "rejected": "\u274c",  # cross
    "corrected": "\u270f\ufe0f",  # pencil
    "expired": "\u26a0\ufe0f",  # warning
    "error": "\U0001f534",  # red circle
    "executed": "\u2699\ufe0f",  # gear
}


def format_confidence(value: float) -> str:
    """Formate une valeur de confidence avec barre visuelle + pourcentage.

    Args:
        value: Confidence 0.0-1.0

    Returns:
        Barre emoji + pourcentage
        (ex: "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2591 95.2%")
    """
    pct = value * 100
    filled = int(value * 10)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    return f"{bar} {pct:.1f}%"


def format_status_emoji(status: str) -> str:
    """Retourne l'emoji correspondant a un status.

    Args:
        status: Status de l'action

    Returns:
        Emoji correspondant, ou "?" si status inconnu
    """
    return STATUS_EMOJIS.get(status, "?")


def format_timestamp(dt: datetime | None, verbose: bool = False) -> str:
    """Formate un datetime pour affichage Telegram.

    Mode par defaut: format relatif (il y a Xmin/Xh/Xj).
    Mode verbose: format complet YYYY-MM-DD HH:MM.

    Args:
        dt: Datetime a formater (None retourne "N/A")
        verbose: Si True, format long YYYY-MM-DD HH:MM

    Returns:
        Timestamp formatte
    """
    if dt is None:
        return "N/A"

    if verbose:
        return dt.strftime("%Y-%m-%d %H:%M")

    # Format relatif
    now = datetime.now(tz=timezone.utc)

    # Handle naive datetimes (assume UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return dt.strftime("%H:%M:%S")
    elif seconds < 60:
        return f"il y a {seconds}s"
    elif seconds < 3600:
        return f"il y a {seconds // 60}min"
    elif seconds < 86400:
        return f"il y a {seconds // 3600}h"
    else:
        return f"il y a {seconds // 86400}j"


def format_eur(amount: float) -> str:
    """Formate un montant en EUR.

    Args:
        amount: Montant en euros

    Returns:
        Montant formatte (ex: "18.50 EUR")
    """
    return f"{amount:.2f} EUR"


def truncate_text(text: str, max_len: int = 100) -> str:
    """Tronque un texte avec "..." si trop long.

    Args:
        text: Texte a tronquer
        max_len: Longueur maximale

    Returns:
        Texte tronque ou original si assez court
    """
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def parse_verbose_flag(args: list[str] | None) -> bool:
    """Detecte le flag -v ou --verbose dans les arguments.

    Args:
        args: Liste d'arguments de la commande

    Returns:
        True si verbose demande
    """
    if not args:
        return False
    return "-v" in args or "--verbose" in args
