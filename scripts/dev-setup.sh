#!/usr/bin/env bash
# Friday 2.0 - Dev Environment Setup
# Usage: ./scripts/dev-setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON="${PYTHON:-python3}"
VENV_DIR="${PROJECT_ROOT}/.venv"

echo "=== Friday 2.0 - Setup environnement dev ==="
echo ""

# 1. Check Python version
echo "[1/7] Verification Python..."
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERREUR: Python 3.11+ requis. Installe-le d'abord."
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "ERREUR: Python 3.11+ requis (trouve: $PY_VERSION)"
    exit 1
fi
echo "  Python $PY_VERSION OK"

# 2. Create venv
echo "[2/7] Creation virtualenv..."
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
    echo "  Cree: $VENV_DIR"
else
    echo "  Existe deja: $VENV_DIR"
fi

# Activate venv
if [ -f "$VENV_DIR/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
elif [ -f "$VENV_DIR/Scripts/activate" ]; then
    # Windows
    # shellcheck disable=SC1091
    source "$VENV_DIR/Scripts/activate"
fi

# 3. Install dependencies
echo "[3/7] Installation dependances..."
pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet
echo "  Dependances installees (core + dev)"

# 4. Install spaCy French model
echo "[4/7] Installation modele spaCy francais..."
if python -c "import spacy; spacy.load('fr_core_news_lg')" 2>/dev/null; then
    echo "  fr_core_news_lg deja installe"
else
    python -m spacy download fr_core_news_lg --quiet
    echo "  fr_core_news_lg installe"
fi

# 5. Pre-commit hooks
echo "[5/7] Configuration pre-commit hooks..."
if command -v pre-commit &>/dev/null; then
    cd "$PROJECT_ROOT"
    pre-commit install
    echo "  Pre-commit hooks installes"
else
    echo "  ATTENTION: pre-commit non trouve. Installe avec: pip install pre-commit"
fi

# 6. Environment file
echo "[6/7] Verification .env..."
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "  ATTENTION: .env n'existe pas."
    echo "  Copie le template: cp .env.example .env"
    echo "  Puis remplis les valeurs (ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, etc.)"
else
    echo "  .env existe"
fi

# 7. Docker services check
echo "[7/7] Verification Docker..."
if command -v docker &>/dev/null; then
    if docker compose version &>/dev/null; then
        echo "  Docker Compose disponible"
        echo "  Pour demarrer les services: docker compose up -d postgres redis qdrant"
    else
        echo "  ATTENTION: docker compose non disponible"
    fi
else
    echo "  ATTENTION: Docker non installe (requis pour PostgreSQL, Redis, Qdrant)"
fi

echo ""
echo "=== Setup termine ==="
echo ""
echo "Prochaines etapes:"
echo "  1. cp .env.example .env && editer .env"
echo "  2. docker compose up -d postgres redis qdrant"
echo "  3. python scripts/apply_migrations.py"
echo "  4. pytest tests/unit -v"
echo ""
