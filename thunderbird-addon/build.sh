#!/bin/bash
# Packs the add-on into antwortentwurf.xpi next to this script (a zip of the add-on files).
set -euo pipefail
cd "$(dirname "$0")"
rm -f antwortentwurf.xpi
zip -q -r antwortentwurf.xpi manifest.json background.html background.js options.html options.js icon.svg lib
echo "antwortentwurf.xpi: $(du -h antwortentwurf.xpi | cut -f1)"
