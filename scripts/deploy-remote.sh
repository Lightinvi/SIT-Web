#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

bundle="${1:?Missing deployment bundle}"
[[ "$bundle" =~ ^/tmp/sit-web-deploy\.[a-zA-Z0-9]{10}$ ]] || { echo 'Invalid deployment bundle' >&2; exit 1; }
deploy_dir="${SIT_DEPLOY_DIR:-$HOME/sit-web}"
export DOCKER_CONFIG="$bundle/docker-config"
trap 'rm -rf -- "$bundle"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ -f "$deploy_dir/.env" ]] || { echo 'Create ~/sit-web/.env with SECRET_KEY before deploying.' >&2; exit 1; }
docker compose version
docker info > /dev/null

# Keep registry credentials only in the temporary bundle.
docker login ghcr.io --username "$(cat "$bundle/registry.user")" --password-stdin < "$bundle/registry.token"
compose=(docker compose --project-name sit-web --project-directory "$deploy_dir" --env-file "$deploy_dir/.env" --env-file "$bundle/images.env" -f "$bundle/compose.production.yaml")
"${compose[@]}" config --quiet
"${compose[@]}" pull
# Recreate both services so Nginx resolves the current backend container address.
"${compose[@]}" up -d --force-recreate --wait --wait-timeout 120

cp "$bundle/compose.production.yaml" "$deploy_dir/compose.production.yaml"
cp "$bundle/images.env" "$deploy_dir/images.env"
cp "$bundle/setup-https.sh" "$deploy_dir/setup-https.sh"
"${compose[@]}" ps
