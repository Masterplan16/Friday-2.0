#!/usr/bin/env bash
# Script de validation: Vérifie que tous les services Docker ont restart: unless-stopped
# Story 1.13 - AC1: Docker restart policy sur tous les services
# Usage: ./validate-docker-restart-policy.sh [docker-compose-file]

set -euo pipefail

# Couleurs pour output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Variables
COMPOSE_FILE="${1:-docker-compose.yml}"
MISSING_SERVICES=()
EXIT_CODE=0

# Fonction: Parser YAML et extraire services sans restart policy
validate_restart_policies() {
    local compose_file="$1"

    echo "🔍 Validation restart policies dans: ${compose_file}"
    echo ""

    # Vérifier que le fichier existe
    if [ ! -f "$compose_file" ]; then
        echo -e "${RED}❌ Erreur: Fichier ${compose_file} introuvable${NC}"
        exit 1
    fi

    # Extraire liste des services
    # Utilise grep pour trouver les services (lignes qui ne sont pas indentées après 'services:')
    # et qui ne commencent pas par '#' ou 'version:' ou 'services:'
    local in_services=false
    local current_service=""

    while IFS= read -r line; do
        # Détecter section services:
        if [[ "$line" =~ ^services: ]]; then
            in_services=true
            continue
        fi

        # Si on est dans la section services
        if [ "$in_services" = true ]; then
            # Détecter un nouveau service (ligne non indentée ou 2 espaces d'indentation)
            if [[ "$line" =~ ^[[:space:]]{2}[a-zA-Z0-9_-]+: ]]; then
                # Extraire le nom du service
                current_service=$(echo "$line" | sed -E 's/^[[:space:]]{2}([a-zA-Z0-9_-]+):.*/\1/')

                # Initialiser flag: on suppose que restart manque
                local has_restart=false

                # Lire les propriétés du service jusqu'au prochain service
                while IFS= read -r prop_line; do
                    # Si on trouve "restart:", marquer comme présent
                    if [[ "$prop_line" =~ ^[[:space:]]{4}restart:[[:space:]]*(unless-stopped|always|on-failure) ]]; then
                        has_restart=true
                        break
                    fi

                    # Si on rencontre un nouveau service, sortir de la boucle
                    if [[ "$prop_line" =~ ^[[:space:]]{2}[a-zA-Z0-9_-]+: ]] || [[ "$prop_line" =~ ^[a-zA-Z] ]]; then
                        break
                    fi
                done

                # Si restart manque, ajouter à la liste
                if [ "$has_restart" = false ]; then
                    MISSING_SERVICES+=("$current_service")
                fi
            fi

            # Si on sort de la section services (ligne non indentée qui n'est pas un commentaire)
            if [[ "$line" =~ ^[a-zA-Z] ]] && [[ ! "$line" =~ ^services: ]]; then
                in_services=false
            fi
        fi
    done < "$compose_file"
}

# Fonction alternative: Parser avec yq si disponible (plus fiable)
validate_with_yq() {
    local compose_file="$1"

    if command -v yq &> /dev/null; then
        echo "📦 Utilisation de yq pour parsing YAML"

        # Extraire tous les services
        services=$(yq eval '.services | keys | .[]' "$compose_file" 2>/dev/null || echo "")

        if [ -z "$services" ]; then
            echo -e "${RED}❌ Aucun service trouvé dans ${compose_file}${NC}"
            return 1
        fi

        # Vérifier restart policy pour chaque service
        for service in $services; do
            restart_policy=$(yq eval ".services.${service}.restart" "$compose_file" 2>/dev/null || echo "null")

            if [ "$restart_policy" = "null" ] || [ -z "$restart_policy" ]; then
                MISSING_SERVICES+=("$service")
            fi
        done

        return 0
    else
        return 1
    fi
}

# Main: Validation
main() {
    echo "════════════════════════════════════════════════════════"
    echo "  Docker Compose Restart Policy Validator"
    echo "  Story 1.13 - AC1"
    echo "════════════════════════════════════════════════════════"
    echo ""

    # Tenter validation avec yq (si disponible), sinon parser manuel
    if ! validate_with_yq "$COMPOSE_FILE"; then
        echo "⚠️  yq non disponible, utilisation du parser bash manuel"
        echo ""
        validate_restart_policies "$COMPOSE_FILE"
    fi

    # Afficher résultats
    echo "────────────────────────────────────────────────────────"

    if [ ${#MISSING_SERVICES[@]} -eq 0 ]; then
        echo -e "${GREEN}✅ SUCCÈS: Tous les services ont une restart policy configurée${NC}"
        echo ""
        exit 0
    else
        echo -e "${RED}❌ ÉCHEC: ${#MISSING_SERVICES[@]} service(s) sans restart policy${NC}"
        echo ""
        echo "Services manquants:"
        for service in "${MISSING_SERVICES[@]}"; do
            echo -e "  ${RED}✗${NC} ${service}"
        done
        echo ""
        echo "🔧 Action requise: Ajouter 'restart: unless-stopped' à ces services"
        echo ""
        exit 1
    fi
}

# Vérifier si on est sourcé ou exécuté directement
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
