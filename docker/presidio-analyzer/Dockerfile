# Friday 2.0 - Presidio Analyzer avec spaCy fr_core_news_lg pré-chargé
# Base image: Microsoft Presidio Analyzer 2.2.354
FROM mcr.microsoft.com/presidio-analyzer:2.2.354

# Installer build tools (gcc nécessaire pour blis/thinc/spacy)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ build-essential && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip + installer spaCy + modèle français
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir spacy && \
    python -m spacy download fr_core_news_lg

# Vérifier que le modèle est installé
RUN python -m spacy validate

# Valider que fr_core_news_lg est bien présent
RUN python -c "import spacy; nlp = spacy.load('fr_core_news_lg'); print('fr_core_news_lg loaded successfully')"

# Cleanup build tools pour réduire taille image
RUN apt-get purge -y gcc g++ build-essential && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Copier configuration Presidio pour recognizers français
COPY analyzer_conf.json /usr/src/app/conf/

# Copier app custom qui charge la configuration FR
COPY app_custom.py /usr/bin/presidio-analyzer/app_custom.py

# Variables d'environnement par défaut
ENV SPACY_MODEL=fr_core_news_lg
ENV LOG_LEVEL=INFO
ENV NLP_CONF_FILE=/usr/src/app/conf/analyzer_conf.json

# Exposer le port Analyzer
EXPOSE 3000

# Healthcheck (Python car wget/curl absents de l'image)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/health')" || exit 1

# Lancer app_custom.py au lieu de app.py pour charger config FR
WORKDIR /usr/bin/presidio-analyzer
CMD ["sh", "-c", "pipenv run python app_custom.py --host 0.0.0.0"]
