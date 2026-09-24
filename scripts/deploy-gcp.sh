#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

for variable in FRONTEND_IMAGE BACKEND_IMAGE GCP_VM_HOST GCP_VM_USER GCP_VM_SSH_KEY GCP_VM_KNOWN_HOSTS GHCR_USERNAME GHCR_PAT; do
    [[ -n "${!variable:-}" ]] || { printf 'Missing %s\n' "$variable" >&2; exit 1; }
done
[[ "$GCP_VM_HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo 'Invalid VM hostname or IPv4 address' >&2; exit 1; }
[[ "$GCP_VM_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo 'Invalid SSH username' >&2; exit 1; }
for image in "$FRONTEND_IMAGE" "$BACKEND_IMAGE"; do
    [[ "$image" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || { echo 'Expected a GHCR digest reference' >&2; exit 1; }
done

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
bundle="$(mktemp -d)"
remote_dir=''
remote="$GCP_VM_USER@$GCP_VM_HOST"
ssh_options=(-i "$bundle/key" -o "UserKnownHostsFile=$bundle/known_hosts" -o StrictHostKeyChecking=yes -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
cleanup() {
    if [[ -n "$remote_dir" ]]; then
        ssh "${ssh_options[@]}" "$remote" "rm -rf -- '$remote_dir'" || true
    fi
    rm -rf -- "$bundle"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' "$GCP_VM_SSH_KEY" > "$bundle/key"
printf '%s\n' "$GCP_VM_KNOWN_HOSTS" > "$bundle/known_hosts"
printf '%s' "$GHCR_PAT" > "$bundle/registry.token"
printf '%s\n' "$GHCR_USERNAME" > "$bundle/registry.user"
printf 'FRONTEND_IMAGE=%s\nBACKEND_IMAGE=%s\n' "$FRONTEND_IMAGE" "$BACKEND_IMAGE" > "$bundle/images.env"
cp "$root/compose.production.yaml" "$bundle/compose.production.yaml"
cp "$root/scripts/deploy-remote.sh" "$bundle/deploy-remote.sh"
cp "$root/scripts/setup-https.sh" "$bundle/setup-https.sh"

candidate="$(ssh "${ssh_options[@]}" "$remote" 'mktemp -d /tmp/sit-web-deploy.XXXXXXXXXX')"
[[ "$candidate" =~ ^/tmp/sit-web-deploy\.[a-zA-Z0-9]{10}$ ]] || { echo 'Invalid remote temporary directory' >&2; exit 1; }
remote_dir="$candidate"
scp "${ssh_options[@]}" "$bundle/registry.token" "$bundle/registry.user" "$bundle/images.env" "$bundle/compose.production.yaml" "$bundle/deploy-remote.sh" "$bundle/setup-https.sh" "$remote:$remote_dir/"
ssh "${ssh_options[@]}" "$remote" "bash '$remote_dir/deploy-remote.sh' '$remote_dir'"
