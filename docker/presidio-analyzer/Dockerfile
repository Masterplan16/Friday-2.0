# Friday 2.0 - Presidio Analyzer avec spaCy fr_core_news_lg pré-chargé
# Base image: Microsoft Presidio Analyzer 2.2.354
FROM mcr.microsoft.com/presidio-analyzer:2.2.354

# Installer le modèle spaCy français (large, ~560 MB)
# NOTE: Le téléchargement se fait pendant le build Docker (pas au runtime)
RUN python -m spacy download fr_core_news_lg

# Vérifier que le modèle est installé
RUN python -m spacy validate

# Valider que fr_core_news_lg est bien présent
RUN python -c "import spacy; nlp = spacy.load('fr_core_news_lg'); print('fr_core_news_lg loaded successfully')"

# Variables d'environnement par défaut
ENV SPACY_MODEL=fr_core_news_lg
ENV LOG_LEVEL=INFO

# Exposer le port Analyzer
EXPOSE 5001

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
  CMD wget --spider -q http://localhost:5001/health || exit 1

# CMD hérité de l'image parente (presidio-analyzer)
