#!/bin/bash

# Zielverzeichnisse
JS_DIR="./js"
CSS_DIR="./css"

# Flatpickr-Version
VERSION="4.6.13"

# URLs
BASE_URL="https://cdn.jsdelivr.net/npm/flatpickr@$VERSION/dist"
JS_URL="$BASE_URL/flatpickr.min.js"
CSS_URL="$BASE_URL/flatpickr.min.css"
LOCALE_URL="$BASE_URL/l10n/de.js"

# Verzeichnisse erstellen
mkdir -p "$JS_DIR" "$CSS_DIR"

echo "📦 Lade Flatpickr v$VERSION herunter..."

# Dateien herunterladen
curl -s -o "$JS_DIR/flatpickr.min.js" "$JS_URL"
curl -s -o "$CSS_DIR/flatpickr.min.css" "$CSS_URL"
curl -s -o "$JS_DIR/de.js" "$LOCALE_URL"

echo "✅ Flatpickr wurde erfolgreich installiert:"
echo "→ JavaScript: $JS_DIR/flatpickr.min.js"
echo "→ CSS:        $CSS_DIR/flatpickr.min.css"
echo "→ Deutsch:    $JS_DIR/de.js"

