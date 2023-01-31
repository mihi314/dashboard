#!/bin/sh
set -e

CERT_FILE=/etc/nginx/ssl/certs/cert.pem
KEY_FILE=/etc/nginx/ssl/certs/key.pem
DOMAIN=${DOMAIN:-localhost}

# if no certificate got mounted into the container, generate a self-signed one so that nginx can at least start
if [[ ! -f $CERT_FILE ]] || [[ ! -f $KEY_FILE ]]; then
    echo "No certificate found at $CERT_FILE and $KEY_FILE, generating a self-signed one for '$DOMAIN'"
    openssl req -x509 -newkey rsa:4096 -keyout "$KEY_FILE" -out "$CERT_FILE" -days 365 -nodes -subj "/CN=$DOMAIN"
fi

# reload the nginx config every once in a while to pick up any certificates that potentially got refreshed
reload_config() {
    # send SIGTERM to the parent shell if this background job fails or gets killed
    trap "kill $$" SIGINT SIGTERM EXIT

    while true; do
        sleep 12h
        echo "$(date -Iminute) Reloading nginx config"
        nginx -s reload
    done
}

reload_config&

# exectue the original entry point
exec /docker-entrypoint.sh "$@"
