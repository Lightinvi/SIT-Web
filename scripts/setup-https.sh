#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    echo 'Usage: sudo bash setup-https.sh DOMAIN EMAIL [APP_PORT=8080]' >&2
    echo 'Preview: bash setup-https.sh --print-config DOMAIN [APP_PORT=8080]' >&2
    exit 1
}

preview=false
if [[ "${1:-}" == --print-config ]]; then
    preview=true
    shift
    [[ $# -ge 1 && $# -le 2 ]] || usage
    domain="$1"
    port="${2:-8080}"
else
    [[ $# -ge 2 && $# -le 3 ]] || usage
    domain="$1"
    email="$2"
    port="${3:-8080}"
fi

[[ ${#domain} -le 253 && "$domain" == *.* && ! "$domain" =~ [^a-z0-9.-] ]] || { echo 'Use a lowercase DNS hostname.' >&2; exit 1; }
IFS='.' read -r -a labels <<< "$domain"
for label in "${labels[@]}"; do
    [[ ${#label} -ge 1 && ${#label} -le 63 && "$label" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || { echo 'Invalid DNS label.' >&2; exit 1; }
done
[[ "$domain" != *. && "$port" =~ ^[0-9]{1,5}$ ]] || usage
port=$((10#$port))
(( port > 0 && port <= 65535 && port != 80 && port != 443 )) || { echo 'App port must be 1-65535, excluding 80 and 443.' >&2; exit 1; }

render_config() {
    cat <<NGINX
# SIT-Web managed bootstrap: $domain -> 127.0.0.1:$port
# Certbot will add TLS and HTTP-to-HTTPS redirects to this file.
server {
    listen 80;
    server_name $domain;

    location / {
        proxy_pass http://127.0.0.1:$port;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
}

if "$preview"; then
    render_config
    exit 0
fi

[[ "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || { echo 'Provide a valid contact email.' >&2; exit 1; }
(( EUID == 0 )) || { echo 'Run this script with sudo on the GCP VM, not in WSL.' >&2; exit 1; }
command -v apt-get >/dev/null || { echo 'This setup supports Debian/Ubuntu with apt and systemd.' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'systemd is required for automatic renewal.' >&2; exit 1; }
if command -v certbot >/dev/null && [[ "$(command -v certbot)" != /usr/bin/certbot ]]; then
    echo 'An existing non-apt Certbot installation was found. Use its renewal setup instead of mixing installations.' >&2
    exit 1
fi

getent ahostsv4 "$domain" >/dev/null || { echo 'The domain needs a public DNS A record before setup.' >&2; exit 1; }
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx certbot python3-certbot-nginx curl
curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:$port/api/users" > /dev/null

site="/etc/nginx/sites-available/sit-web-$domain.conf"
enabled="/etc/nginx/sites-enabled/sit-web-$domain.conf"
marker="# SIT-Web managed bootstrap: $domain -> 127.0.0.1:$port"
if [[ -e "$site" ]]; then
    # Preserve Certbot's TLS additions on repeat runs.
    grep -Fxq "$marker" "$site" || { echo "Existing config differs: $site. Review it manually." >&2; exit 1; }
else
    render_config > "$site"
    chmod 644 "$site"
fi
if [[ -e "$enabled" || -L "$enabled" ]]; then
    [[ -L "$enabled" && "$(readlink "$enabled")" == "$site" ]] || { echo "Refusing to replace $enabled" >&2; exit 1; }
else
    ln -s "$site" "$enabled"
fi
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# The nginx plugin installs the certificate and reloads Nginx after renewal.
/usr/bin/certbot --nginx --non-interactive --agree-tos --redirect \
    --email "$email" --cert-name "$domain" -d "$domain"
nginx -t
systemctl enable --now certbot.timer
systemctl is-active --quiet certbot.timer
/usr/bin/certbot renew --cert-name "$domain" --dry-run

printf '\nHTTPS ready: https://%s\nAutomatic renewal: certbot.timer\n' "$domain"
