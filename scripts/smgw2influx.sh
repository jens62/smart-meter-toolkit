#!/usr/bin/env bash
#
# Fetches recent smart meter readings from a PPC Smart Meter Gateway (via
# readSMGW_multipleContracts.sh) and writes them to an InfluxDB v2 bucket as
# line protocol.
#
# Portable between GNU date (Linux) and BSD date (macOS) — the two flavors
# parse an ISO-8601 UTC timestamp differently ("date -d" vs "date -jf").

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<EOF
Usage: $(basename "$0") --user USER --password PASSWORD --meter METER \\
    --influx-url URL --influx-org ORG --influx-bucket BUCKET --measurement NAME \\
    [options]

Gateway options:
  --host HOST                Gateway IP (default: readSMGW_multipleContracts.sh's own default)
  --user USER                Gateway user (required)
  --password PASSWORD        Gateway password (required; or set SMGW_PASSWORD)
  --meter METER               Meter logical name, e.g. 0100aabbccdd.1abc0012345678.sm (required)
  --past MINUTES               How many minutes back to fetch (default: 30)
  --out-path PATH             Working directory for readSMGW_multipleContracts.sh's log/
                              and data/ subfolders (default: a temporary directory,
                              removed on exit)
  --readsmgw-script PATH      Path to readSMGW_multipleContracts.sh
                              (default: $SCRIPT_DIR/readSMGW_multipleContracts.sh)

Value conversion:
  --divisor N                 Divide the raw counter value by N to get the target unit
                              (default: 10000, i.e. Wh -> kWh)

InfluxDB options:
  --influx-url URL            InfluxDB base URL, e.g. http://192.168.0.194:8086 (required)
  --influx-org ORG            InfluxDB org (required)
  --influx-bucket BUCKET      InfluxDB bucket (required)
  --influx-token TOKEN        InfluxDB API token (required; or set INFLUXDB_TOKEN)
  --measurement NAME          InfluxDB measurement/item name, e.g. SMGW_EPPC0211923304 (required)
EOF
}

HOST=""
SMGW_USER=""
SMGW_PASSWORD="${SMGW_PASSWORD:-}"
METER=""
PAST="30"
OUT_PATH=""
READSMGW_SCRIPT="$SCRIPT_DIR/readSMGW_multipleContracts.sh"
DIVISOR="10000"
INFLUX_URL=""
INFLUX_ORG=""
INFLUX_BUCKET=""
INFLUX_TOKEN="${INFLUXDB_TOKEN:-}"
MEASUREMENT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) SMGW_USER="$2"; shift 2 ;;
    --password) SMGW_PASSWORD="$2"; shift 2 ;;
    --meter) METER="$2"; shift 2 ;;
    --past) PAST="$2"; shift 2 ;;
    --out-path) OUT_PATH="$2"; shift 2 ;;
    --readsmgw-script) READSMGW_SCRIPT="$2"; shift 2 ;;
    --divisor) DIVISOR="$2"; shift 2 ;;
    --influx-url) INFLUX_URL="$2"; shift 2 ;;
    --influx-org) INFLUX_ORG="$2"; shift 2 ;;
    --influx-bucket) INFLUX_BUCKET="$2"; shift 2 ;;
    --influx-token) INFLUX_TOKEN="$2"; shift 2 ;;
    --measurement) MEASUREMENT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

missing=()
[[ -z "$SMGW_USER" ]] && missing+=("--user")
[[ -z "$SMGW_PASSWORD" ]] && missing+=("--password (or \$SMGW_PASSWORD)")
[[ -z "$METER" ]] && missing+=("--meter")
[[ -z "$INFLUX_URL" ]] && missing+=("--influx-url")
[[ -z "$INFLUX_ORG" ]] && missing+=("--influx-org")
[[ -z "$INFLUX_BUCKET" ]] && missing+=("--influx-bucket")
[[ -z "$INFLUX_TOKEN" ]] && missing+=("--influx-token (or \$INFLUXDB_TOKEN)")
[[ -z "$MEASUREMENT" ]] && missing+=("--measurement")
if (( ${#missing[@]} > 0 )); then
  printf 'Missing required argument(s): %s\n\n' "${missing[*]}" >&2
  usage
  exit 1
fi

if [[ ! -f "$READSMGW_SCRIPT" ]]; then
  echo "readSMGW_multipleContracts.sh not found at: $READSMGW_SCRIPT" >&2
  exit 1
fi

if [[ -z "$OUT_PATH" ]]; then
  OUT_PATH="$(mktemp -d)"
  trap 'rm -rf "$OUT_PATH"' EXIT
fi

readsmgw_args=(
  --user "$SMGW_USER"
  --password "$SMGW_PASSWORD"
  --meter "$METER"
  --past "$PAST"
  --path "$OUT_PATH"
  --out csv
)
[[ -n "$HOST" ]] && readsmgw_args+=(--host "$HOST")

CSV_OUTPUT="$("$READSMGW_SCRIPT" "${readsmgw_args[@]}" 2>/dev/null)"

# Detect GNU vs BSD date once, up front, rather than per row.
if date -u -d "1970-01-01T00:00:00Z" +%s >/dev/null 2>&1; then
  DATE_FLAVOR="gnu"
else
  DATE_FLAVOR="bsd"
fi

iso_to_epoch() {
  local iso="$1"
  if [[ "$DATE_FLAVOR" == "gnu" ]]; then
    date -u -d "$iso" +%s
  else
    date -u -jf "%Y-%m-%dT%H:%M:%SZ" "$iso" +%s
  fi
}

# readSMGW_multipleContracts.sh's CSV columns are: id;value;scaler;unit;status;capture_time
LINE_PROTOCOL=""
while IFS=';' read -r id value scaler unit status capture_time; do
  [[ "$id" == "id" || -z "$id" ]] && continue
  epoch="$(iso_to_epoch "$capture_time")"
  value_converted="$(LC_ALL=C awk -v v="$value" -v d="$DIVISOR" 'BEGIN { printf "%.4f", v / d }')"
  LINE_PROTOCOL+="${MEASUREMENT},item=${MEASUREMENT} value=${value_converted} ${epoch}000000000"$'\n'
done <<< "$CSV_OUTPUT"

if [[ -z "$LINE_PROTOCOL" ]]; then
  echo "No readings retrieved; nothing to send to InfluxDB." >&2
  exit 0
fi

curl -sS -i -XPOST "${INFLUX_URL}/api/v2/write?org=${INFLUX_ORG}&bucket=${INFLUX_BUCKET}" \
  --header "Authorization: Token ${INFLUX_TOKEN}" \
  --data-binary "$LINE_PROTOCOL"
