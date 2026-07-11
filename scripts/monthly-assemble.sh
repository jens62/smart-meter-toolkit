#!/usr/bin/env bash
#
# Concatenates a month's daily tar files (data-YYYY-MM-DD.tar, as produced by
# daily-tar.sh) into one compressed monthly archive.
#
# Written for the Linux cron host this pipeline runs on (uses GNU `date -d`).

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [YYYY-MM] [options]

  YYYY-MM                Target month to assemble. Default: last month
                         (run this on day 2 of the following month).

Options:
  --daily-dir PATH       Directory containing the daily tar files
                         (default: current directory)
  --monthly-dir PATH     Directory to write the assembled monthly tar.gz into
                         (default: current directory)
  --tmp-dir PATH         Scratch directory for assembling before an atomic
                         move into place (default: \$TMPDIR or /tmp)
  -h, --help             Show this help and exit
EOF
}

DAILY_DIR="$(pwd)"
MONTHLY_DIR="$(pwd)"
TMP_DIR="${TMPDIR:-/tmp}"
MONTH_LABEL=""

if [[ $# -gt 0 && "$1" != --* ]]; then
  MONTH_LABEL="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --daily-dir) DAILY_DIR="$2"; shift 2 ;;
    --monthly-dir) MONTHLY_DIR="$2"; shift 2 ;;
    --tmp-dir) TMP_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$MONTH_LABEL" ]]; then
  MONTH_LABEL="$(date -d 'last month' +%Y-%m)"
fi

mkdir -p "$MONTHLY_DIR"

MONTH_TAR_TMP="$TMP_DIR/data-${MONTH_LABEL}.tar.$$"
MONTH_TAR_FINAL="$MONTHLY_DIR/data-${MONTH_LABEL}.tar"
MONTH_TAR_GZ="$MONTH_TAR_FINAL.gz"

# Find daily tar files for that month (assumes daily files named data-YYYY-MM-DD.tar)
shopt -s nullglob
daily_files=( "$DAILY_DIR"/data-"$MONTH_LABEL"-*.tar )
shopt -u nullglob

if [[ ${#daily_files[@]} -eq 0 ]]; then
  echo "No daily tar files found for $MONTH_LABEL" >&2
  exit 0
fi

# Concatenate into one tar (requires uncompressed tars): start with the
# first file, then --concatenate the rest.
cp "${daily_files[0]}" "$MONTH_TAR_TMP"
for f in "${daily_files[@]:1}"; do
  tar --concatenate --file="$MONTH_TAR_TMP" "$f"
done

mv "$MONTH_TAR_TMP" "$MONTH_TAR_FINAL"
gzip -9 "$MONTH_TAR_FINAL"

echo "Created $MONTH_TAR_GZ"
