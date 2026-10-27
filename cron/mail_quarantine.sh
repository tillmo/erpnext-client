#!/bin/bash
# Cron job: move mails with broken embedded images out of the ERPNext inbox before Frappe 14
# stalls on them (cron/mail_quarantine.py). Runs the check inside the ERPNext backend container
# so that it uses the very Pillow that Frappe uses. Credentials in $ERPNEXT_CLIENT_MAIL_ENV
# (default ~/.config/erpnext-client/mail-quarantine.env, template mail-quarantine.env.example).
# Crontab line - one minute before Frappe's pull, which runs every ten minutes on the full ten:
#
#   8-59/10 * * * * flock -n /tmp/mail-quarantine.lock $HOME/erpnext-client/cron/mail_quarantine.sh >> $HOME/logs/mail-quarantine.log 2>&1
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ERPNEXT_CLIENT_MAIL_ENV:-$HOME/.config/erpnext-client/mail-quarantine.env}"
STATE_FILE="${MAIL_QUARANTINE_STATE:-$HOME/.config/erpnext-client/mail-quarantine.state}"
CONTAINER="${ERPNEXT_BACKEND_CONTAINER:-erpnext-backend-1}"
PYTHON="${CONTAINER_PYTHON:-/home/frappe/frappe-bench/env/bin/python}"

if [ ! -r "$ENV_FILE" ]; then
    echo "$(date '+%F %T') Umgebungsdatei $ENV_FILE fehlt (Vorlage: $DIR/cron/mail-quarantine.env.example)" >&2
    exit 2
fi
# shellcheck disable=SC1090
source "$ENV_FILE"
for v in IMAP_HOST IMAP_USER IMAP_PASSWORD; do
    if [ -z "${!v:-}" ] || [[ "${!v}" == *"..."* ]]; then
        echo "$(date '+%F %T') $v ist in $ENV_FILE nicht gesetzt" >&2
        exit 2
    fi
done
LAST_UID="$(cat "$STATE_FILE" 2>/dev/null || true)"
OUT="$(docker exec -i -e IMAP_HOST="$IMAP_HOST" -e IMAP_USER="$IMAP_USER" -e IMAP_PASSWORD="$IMAP_PASSWORD" \
        -e IMAP_FOLDER="${IMAP_FOLDER:-Fehlerhaft}" -e IMAP_PORT="${IMAP_PORT:-993}" -e LAST_UID="$LAST_UID" \
        "$CONTAINER" "$PYTHON" - < "$DIR/cron/mail_quarantine.py")"
grep -v '^STATE ' <<< "$OUT" || true
STATE="$(grep '^STATE ' <<< "$OUT" | tail -1 | cut -d' ' -f2)"
if [ -n "$STATE" ]; then
    echo "$STATE" > "$STATE_FILE"
fi
