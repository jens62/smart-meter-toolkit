#!/bin/bash

# Zielverzeichnisse
JS_DIR="./js"
CSS_DIR="./css"

# Hole neueste Version von Flatpickr via npm CDN
LATEST_VERSION=$(curl -s https://cdn.jsdelivr.net/npm/flatpickr/package.json | grep '"version"' | head -n 1 | sed 's/[^0-9.]//g')

# URLs
BASE_URL="https://cdn.jsdelivr.net/npm/flatpickr@$LATEST_VERSION/dist"
JS_URL="$BASE_URL/flatpickr.min.js"
CSS_URL="$BASE_URL/flatpickr.min.css"
LOCALE_URL="$BASE_URL/l10n/de.js"

# Verzeichnisse erstellen
mkdir -p "$JS_DIR" "$CSS_DIR"

echo "🔄 Aktualisiere Flatpickr auf Version $LATEST_VERSION..."

# Dateien herunterladen und ersetzen
curl -s -o "$JS_DIR/flatpickr.min.js" "$JS_URL"
curl -s -o "$CSS_DIR/flatpickr.min.css" "$CSS_URL"
curl -s -o "$JS_DIR/de.js" "$LOCALE_URL"

echo "✅ Update abgeschlossen:"
echo "→ JavaScript: $JS_DIR/flatpickr.min.js"
echo "→ CSS:        $CSS_DIR/flatpickr.min.css"
echo "→ Deutsch:    $JS_DIR/de.js"

