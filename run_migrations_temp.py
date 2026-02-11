#!/usr/bin/env python3
"""Script temporaire pour appliquer les migrations avec DATABASE_URL"""

import os
import sys
import subprocess

# Définir DATABASE_URL (credentials de test depuis .env.test)
# Port 5433 car 5432 déjà utilisé (voir docker-compose.yml ligne 37)
os.environ['DATABASE_URL'] = 'postgresql://friday:friday_test_local_dev_123@localhost:5433/friday'

# Exécuter apply_migrations.py (sans backup car pg_dump pas dispo Windows)
result = subprocess.run(
    [sys.executable, 'scripts/apply_migrations.py', '--no-backup'],
    cwd=os.path.dirname(__file__)
)

sys.exit(result.returncode)
