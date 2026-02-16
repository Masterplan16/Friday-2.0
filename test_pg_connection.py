#!/usr/bin/env python3
"""Test connexion PostgreSQL"""

import asyncio

import asyncpg


async def test_connection():
    """Test différentes connexions PostgreSQL"""

    # Test 1: Sans password
    print("Test 1: postgresql://friday:@localhost:5432/friday")
    try:
        conn = await asyncpg.connect("postgresql://friday:@localhost:5432/friday")
        print("✅ Connexion réussie!")
        await conn.close()
    except Exception as e:
        print(f"❌ Échec: {e}")

    # Test 2: Sans password avec port explicite
    print("\nTest 2: host=localhost port=5432 user=friday database=friday")
    try:
        conn = await asyncpg.connect(host="localhost", port=5432, user="friday", database="friday")
        print("✅ Connexion réussie!")
        await conn.close()
    except Exception as e:
        print(f"❌ Échec: {e}")

    # Test 3: Avec password vide explicite
    print("\nTest 3: password=''")
    try:
        conn = await asyncpg.connect(
            host="localhost", port=5432, user="friday", database="friday", password=""
        )
        print("✅ Connexion réussie!")
        version = await conn.fetchval("SELECT version()")
        print(f"PostgreSQL version: {version[:50]}...")
        await conn.close()
    except Exception as e:
        print(f"❌ Échec: {e}")


if __name__ == "__main__":
    asyncio.run(test_connection())
