#!/bin/bash
# Cron job: export the vCards of the assigned leads to the Nextcloud address books.
#
# Reads the credentials from $ERPNEXT_CLIENT_ENV (default ~/.config/erpnext-client/vcard-export.env,
# see vcard-export.env.example), runs vcard_export.py with the system python3 (only `requests`
# is needed, no GUI) and prefixes the output with a timestamp. Crontab line, every 15 minutes:
#
#   */15 * * * * flock -n /tmp/vcard-export.lock $HOME/erpnext-client/cron/vcard_export.sh >> $HOME/logs/vcard-export.log 2>&1
#
# The log is rotated monthly by cron/logrotate.conf (crontab line in its header).
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ERPNEXT_CLIENT_ENV:-$HOME/.config/erpnext-client/vcard-export.env}"
PYTHON="${PYTHON:-python3}"

if [ ! -r "$ENV_FILE" ]; then
    echo "$(date '+%F %T') Umgebungsdatei $ENV_FILE fehlt (Vorlage: $DIR/cron/vcard-export.env.example)" >&2
    exit 2
fi
# shellcheck disable=SC1090
source "$ENV_FILE"
for v in ERPNEXT_SERVER ERPNEXT_KEY ERPNEXT_SECRET NEXTCLOUD_URL NEXTCLOUD_USER NEXTCLOUD_PASSWORD; do
    if [ -z "${!v:-}" ] || [[ "${!v}" == *"..."* ]]; then
        echo "$(date '+%F %T') $v ist in $ENV_FILE nicht gesetzt" >&2
        exit 2
    fi
done
export NEXTCLOUD_URL NEXTCLOUD_USER NEXTCLOUD_PASSWORD

echo "$(date '+%F %T') vCard-Export startet"
cd "$DIR"
"$PYTHON" vcard_export.py --server "$ERPNEXT_SERVER" --key "$ERPNEXT_KEY" --secret "$ERPNEXT_SECRET" \
    --apply --create --delete 2>&1 | sed "s/^/$(date '+%F %T') /"
exit "${PIPESTATUS[0]}"
