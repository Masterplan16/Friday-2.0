"""
Pattern Detector pour Friday 2.0 - Détection de patterns de correction.

Clustering sémantique des corrections owner pour détecter des patterns récurrents
et proposer automatiquement des correction_rules.

Algorithme (ADD2 Section 2) :
1. Récupérer corrections semaine dernière (7 jours glissants)
2. Grouper par (module, action_type)
3. Calculer Levenshtein distance entre pairs de corrections
4. Détecter clusters avec similarité ≥0.85
5. Filtrer clusters avec ≥2 corrections similaires
6. Extraire pattern commun (mots-clés récurrents + catégorie majoritaire)
"""

import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg
import structlog
from Levenshtein import distance as levenshtein_distance
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class PatternCluster(BaseModel):
    """
    Cluster de corrections similaires détecté.

    Représente un groupe de corrections similaires qui suggèrent
    une règle de correction automatique.
    """

    module: str = Field(..., description="Module concerné (ex: 'email')")
    action_type: str = Field(..., description="Type d'action (ex: 'classify')")
    corrections: list[str] = Field(..., description="Liste des corrections textuelles similaires")
    receipt_ids: list[UUID] = Field(..., description="IDs des receipts correspondants")
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0, description="Score de similarité du cluster (0.0-1.0)"
    )
    common_keywords: list[str] = Field(..., description="Mots-clés récurrents dans les corrections")
    target_category: str | None = Field(
        None, description="Catégorie cible majoritaire (si détectable)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Date de détection du cluster"
    )


class PatternDetector:
    """
    Détecteur de patterns de correction pour le feedback loop.

    Analyse les corrections d'owner sur 7 jours glissants et détecte
    des patterns récurrents via clustering sémantique (Levenshtein distance).
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool | None = None,
        similarity_threshold: float = 0.85,
        min_cluster_size: int = 2,
    ):
        """
        Initialise le détecteur de patterns.

        Args:
            db_pool: Pool de connexions PostgreSQL (créé si None)
            similarity_threshold: Seuil de similarité Levenshtein (0.0-1.0)
            min_cluster_size: Nombre minimum de corrections par cluster
        """
        self.db_pool = db_pool
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size
        self.db_url = os.getenv(
            "DATABASE_URL",
            "postgresql://friday:friday_dev_password@localhost:5432/friday",
        )

    async def connect(self) -> None:
        """Connecte à PostgreSQL si nécessaire."""
        if not self.db_pool:
            self.db_pool = await asyncpg.create_pool(self.db_url)
            logger.info("PatternDetector connected to PostgreSQL")

    async def disconnect(self) -> None:
        """Déconnecte proprement."""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("PatternDetector disconnected from PostgreSQL")

    async def get_recent_corrections(self, days: int = 7) -> list[dict[str, Any]]:
        """
        Récupère les corrections des N derniers jours.

        Args:
            days: Nombre de jours glissants (défaut: 7)

        Returns:
            Liste de corrections avec métadonnées
        """
        if not self.db_pool:
            raise RuntimeError("Not connected to database - call connect() first")

        cutoff_date = datetime.utcnow() - timedelta(days=days)

        query = """
            SELECT
                id,
                module,
                action_type,
                correction,
                input_summary,
                output_summary,
                created_at
            FROM core.action_receipts
            WHERE status = 'corrected'
              AND correction IS NOT NULL
              AND created_at >= $1
            ORDER BY module, action_type, created_at DESC
        """

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, cutoff_date)

        corrections = [
            {
                "id": row["id"],
                "module": row["module"],
                "action_type": row["action_type"],
                "correction": row["correction"],
                "input_summary": row["input_summary"],
                "output_summary": row["output_summary"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

        logger.info(
            "Retrieved recent corrections",
            count=len(corrections),
            days=days,
            cutoff_date=cutoff_date.isoformat(),
        )

        return corrections

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calcule la similarité entre deux textes via Levenshtein distance.

        Normalise la distance par la longueur max pour obtenir un score 0.0-1.0.
        Similarité = 1.0 - (distance / max_length)

        Args:
            text1: Premier texte
            text2: Deuxième texte

        Returns:
            Score de similarité (1.0 = identique, 0.0 = totalement différent)
        """
        if not text1 or not text2:
            return 0.0

        # Normalisation : lowercase pour comparaison insensible à la casse
        t1 = text1.lower().strip()
        t2 = text2.lower().strip()

        if t1 == t2:
            return 1.0

        # Calcul Levenshtein distance
        dist = levenshtein_distance(t1, t2)
        max_len = max(len(t1), len(t2))

        if max_len == 0:
            return 1.0

        # Normaliser en score de similarité
        similarity = 1.0 - (dist / max_len)
        return max(0.0, similarity)  # Clamp à 0.0 minimum

    def cluster_corrections(self, corrections: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """
        Groupe les corrections en clusters par similarité.

        Utilise un algorithme de clustering simple :
        1. Pour chaque correction, comparer avec toutes les autres
        2. Si similarité ≥ threshold, ajouter au cluster
        3. Filtrer clusters avec ≥ min_cluster_size

        Args:
            corrections: Liste de corrections à clusterer

        Returns:
            Liste de clusters (chaque cluster = liste de corrections)
        """
        if len(corrections) < self.min_cluster_size:
            return []

        clusters: list[list[dict[str, Any]]] = []
        used_indices: set[int] = set()

        for i, corr1 in enumerate(corrections):
            if i in used_indices:
                continue

            # Nouveau cluster avec correction actuelle
            cluster = [corr1]
            used_indices.add(i)

            # Comparer avec toutes les corrections restantes
            for j, corr2 in enumerate(corrections):
                if j <= i or j in used_indices:
                    continue

                similarity = self.calculate_similarity(corr1["correction"], corr2["correction"])

                if similarity >= self.similarity_threshold:
                    cluster.append(corr2)
                    used_indices.add(j)

            # Ne garder que les clusters avec assez d'éléments
            if len(cluster) >= self.min_cluster_size:
                clusters.append(cluster)

        logger.info(
            "Clustered corrections",
            total_corrections=len(corrections),
            clusters_found=len(clusters),
            threshold=self.similarity_threshold,
            min_size=self.min_cluster_size,
        )

        return clusters

    def extract_common_pattern(self, cluster: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Extrait le pattern commun d'un cluster de corrections.

        Analyse :
        1. Mots-clés récurrents (via Counter sur tokenisation simple)
        2. Catégorie cible majoritaire (parsing "→ category")
        3. Score de similarité moyen du cluster

        Args:
            cluster: Liste de corrections similaires

        Returns:
            Dict avec keywords, target_category, avg_similarity
        """
        # Tokenisation simple : split sur espaces, lowercase, filtre mots courts
        all_words: list[str] = []
        target_categories: list[str] = []

        for corr in cluster:
            text = corr["correction"].lower()

            # Extraire catégorie cible si format "X → category"
            if "→" in text or "->" in text:
                arrow = "→" if "→" in text else "->"
                parts = text.split(arrow)
                if len(parts) == 2:
                    category = parts[1].strip()
                    target_categories.append(category)

            # Tokeniser mots (filtre mots courts <3 caractères)
            words = [w.strip() for w in text.split() if len(w.strip()) >= 3]
            all_words.extend(words)

        # Compter occurrences
        word_counter = Counter(all_words)
        common_keywords = [word for word, count in word_counter.most_common(5)]

        # Catégorie majoritaire
        if target_categories:
            category_counter = Counter(target_categories)
            target_category = category_counter.most_common(1)[0][0]
        else:
            target_category = None

        # Similarité moyenne du cluster
        similarities: list[float] = []
        for i, corr1 in enumerate(cluster):
            for corr2 in cluster[i + 1 :]:
                sim = self.calculate_similarity(corr1["correction"], corr2["correction"])
                similarities.append(sim)

        avg_similarity = sum(similarities) / len(similarities) if similarities else 1.0

        return {
            "common_keywords": common_keywords,
            "target_category": target_category,
            "avg_similarity": avg_similarity,
        }

    async def detect_patterns(self, days: int = 7) -> list[PatternCluster]:
        """
        Détecte les patterns de correction sur N jours glissants.

        Pipeline complet :
        1. Récupérer corrections récentes
        2. Grouper par (module, action_type)
        3. Clusterer chaque groupe
        4. Extraire patterns communs
        5. Créer PatternCluster pour chaque cluster détecté

        Args:
            days: Nombre de jours glissants (défaut: 7)

        Returns:
            Liste de PatternCluster détectés
        """
        logger.info("Starting pattern detection", days=days)

        # 1. Récupérer corrections
        corrections = await self.get_recent_corrections(days)

        if not corrections:
            logger.info("No corrections found in period")
            return []

        # 2. Grouper par (module, action_type)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for corr in corrections:
            key = (corr["module"], corr["action_type"])
            if key not in groups:
                groups[key] = []
            groups[key].append(corr)

        # 3. Détecter clusters pour chaque groupe
        detected_patterns: list[PatternCluster] = []

        for (module, action_type), group_corrections in groups.items():
            clusters = self.cluster_corrections(group_corrections)

            for cluster in clusters:
                # Extraire pattern commun
                pattern_data = self.extract_common_pattern(cluster)

                # Créer PatternCluster
                pattern = PatternCluster(
                    module=module,
                    action_type=action_type,
                    corrections=[c["correction"] for c in cluster],
                    receipt_ids=[c["id"] for c in cluster],
                    similarity_score=pattern_data["avg_similarity"],
                    common_keywords=pattern_data["common_keywords"],
                    target_category=pattern_data["target_category"],
                )

                detected_patterns.append(pattern)

                logger.info(
                    "Pattern detected",
                    module=module,
                    action_type=action_type,
                    corrections_count=len(cluster),
                    similarity=pattern_data["avg_similarity"],
                    keywords=pattern_data["common_keywords"],
                    target=pattern_data["target_category"],
                )

        logger.info(
            "Pattern detection completed",
            patterns_count=len(detected_patterns),
        )

        return detected_patterns


async def main() -> None:
    """Point d'entrée pour tests manuels."""
    detector = PatternDetector()
    await detector.connect()

    try:
        patterns = await detector.detect_patterns(days=7)

        print(f"\n🔍 Détection de patterns terminée : {len(patterns)} pattern(s) trouvé(s)\n")

        for i, pattern in enumerate(patterns, 1):
            print(f"Pattern #{i}")
            print(f"  Module: {pattern.module}.{pattern.action_type}")
            print(f"  Corrections: {len(pattern.corrections)}")
            print(f"  Similarité: {pattern.similarity_score:.2f}")
            print(f"  Mots-clés: {', '.join(pattern.common_keywords)}")
            print(f"  Catégorie cible: {pattern.target_category or 'N/A'}")
            print(f"  Receipts: {len(pattern.receipt_ids)}")
            print()

    finally:
        await detector.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
