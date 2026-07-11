#!/usr/bin/env bash
#
# Regression tests for smgw2influx.sh's CLI validation, CSV-to-line-protocol
# conversion, and argument forwarding. Runs with no network access and no
# real credentials: the gateway reader and curl are replaced with stub
# executables injected via --readsmgw-script and PATH.
#
# Run: ./scripts/test_smgw2influx.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/smgw2influx.sh"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (used as an independent timestamp oracle) but was not found." >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

MOCK_BIN="$WORKDIR/bin"
mkdir -p "$MOCK_BIN"
export PATH="$MOCK_BIN:$PATH"

export MOCK_CURL_LOG_FILE="$WORKDIR/curl.log"
export MOCK_CURL_BODY_FILE="$WORKDIR/curl.body"
export FAKE_READSMGW_ARGS_FILE="$WORKDIR/readsmgw_args.txt"

# Stub curl: records its arguments and the --data-binary payload, then
# returns a canned success response, exactly like a real InfluxDB write.
cat > "$MOCK_BIN/curl" <<'MOCKEOF'
#!/usr/bin/env bash
echo "$*" >> "$MOCK_CURL_LOG_FILE"
prev=""
for a in "$@"; do
  if [[ "$prev" == "--data-binary" ]]; then
    printf '%s' "$a" > "$MOCK_CURL_BODY_FILE"
  fi
  prev="$a"
done
echo "HTTP/1.1 204 No Content"
MOCKEOF
chmod +x "$MOCK_BIN/curl"

# Stub gateway reader: records the arguments it was invoked with, then
# prints whatever CSV the test put in $FAKE_CSV_OUTPUT.
cat > "$MOCK_BIN/fake_readsmgw.sh" <<'MOCKEOF'
#!/usr/bin/env bash
printf '%s\n' "$*" > "$FAKE_READSMGW_ARGS_FILE"
printf '%s' "$FAKE_CSV_OUTPUT"
MOCKEOF
chmod +x "$MOCK_BIN/fake_readsmgw.sh"
FAKE_READSMGW="$MOCK_BIN/fake_readsmgw.sh"

PASS=0
FAIL=0

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    PASS=$((PASS + 1)); echo "ok - $desc"
  else
    FAIL=$((FAIL + 1))
    echo "FAIL - $desc"
    echo "  expected: $expected"
    echo "  actual:   $actual"
  fi
}

assert_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    PASS=$((PASS + 1)); echo "ok - $desc"
  else
    FAIL=$((FAIL + 1))
    echo "FAIL - $desc (expected to contain: $needle)"
    echo "  actual: $haystack"
  fi
}

assert_not_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    PASS=$((PASS + 1)); echo "ok - $desc"
  else
    FAIL=$((FAIL + 1)); echo "FAIL - $desc (expected NOT to contain: $needle)"
  fi
}

assert_not_exists() {
  local desc="$1" path="$2"
  if [[ ! -e "$path" ]]; then
    PASS=$((PASS + 1)); echo "ok - $desc"
  else
    FAIL=$((FAIL + 1)); echo "FAIL - $desc (unexpectedly exists: $path)"
  fi
}

# Independent oracle for "ISO-8601 UTC string -> epoch seconds", using
# Python's datetime module rather than the `date` CLI logic under test.
iso_epoch_oracle() {
  python3 -c "
from datetime import datetime, timezone
print(int(datetime.strptime('$1', '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()))
"
}

reset_mocks() {
  rm -f "$MOCK_CURL_LOG_FILE" "$MOCK_CURL_BODY_FILE" "$FAKE_READSMGW_ARGS_FILE"
}

echo "# --help"
out=$("$TARGET" --help 2>&1); code=$?
assert_eq "help exits 0" "0" "$code"
assert_contains "help output lists --measurement" "$out" "--measurement"

echo "# missing required arguments"
out=$("$TARGET" 2>&1); code=$?
assert_eq "missing-args exit code" "1" "$code"
assert_contains "missing-args message mentions --user" "$out" "--user"
assert_contains "missing-args message mentions --influx-token" "$out" "influx-token"

echo "# unknown argument"
out=$("$TARGET" --does-not-exist 2>&1); code=$?
assert_eq "unknown-arg exit code" "1" "$code"
assert_contains "unknown-arg message" "$out" "Unknown argument"

echo "# happy path: two rows, default divisor, no --host"
reset_mocks
export FAKE_CSV_OUTPUT=$'id;value;scaler;unit;status;capture_time\n1;66870369;-1;30;0;2024-11-28T10:30:01Z\n2;66868984;-1;30;0;2024-11-28T10:15:01Z\n'
out=$("$TARGET" \
  --user testuser --password testpass --meter 01005e318002.1emh0011802881.sm \
  --readsmgw-script "$FAKE_READSMGW" \
  --influx-url http://influx.example --influx-org myorg --influx-bucket mybucket \
  --influx-token mytoken --measurement SMGW_TEST 2>&1)
code=$?
assert_eq "happy-path exit code" "0" "$code"

epoch1=$(iso_epoch_oracle "2024-11-28T10:30:01Z")
epoch2=$(iso_epoch_oracle "2024-11-28T10:15:01Z")
expected_body="SMGW_TEST,item=SMGW_TEST value=6687.0369 ${epoch1}000000000"$'\n'"SMGW_TEST,item=SMGW_TEST value=6686.8984 ${epoch2}000000000"$'\n'
printf '%s' "$expected_body" > "$WORKDIR/expected_body"
if [[ -f "$MOCK_CURL_BODY_FILE" ]] && cmp -s "$WORKDIR/expected_body" "$MOCK_CURL_BODY_FILE"; then
  PASS=$((PASS + 1)); echo "ok - happy-path line-protocol body matches exactly"
else
  FAIL=$((FAIL + 1))
  echo "FAIL - happy-path line-protocol body mismatch"
  echo "  expected: $(cat "$WORKDIR/expected_body" 2>/dev/null | tr '\n' '|')"
  echo "  actual:   $(cat "$MOCK_CURL_BODY_FILE" 2>/dev/null | tr '\n' '|')"
fi

args_content="$(cat "$FAKE_READSMGW_ARGS_FILE" 2>/dev/null || true)"
assert_contains "happy-path forwards default --past 30" "$args_content" "--past 30"
assert_contains "happy-path forwards --user/--meter" "$args_content" "--user testuser --password testpass --meter 01005e318002.1emh0011802881.sm"
assert_not_contains "happy-path omits --host when not given" "$args_content" "--host"

echo "# --host is forwarded when given"
reset_mocks
out=$("$TARGET" \
  --user u --password p --meter m --host 10.0.0.5 \
  --readsmgw-script "$FAKE_READSMGW" \
  --influx-url http://x --influx-org o --influx-bucket b \
  --influx-token t --measurement MEAS 2>&1)
code=$?
assert_eq "custom-host exit code" "0" "$code"
args_content="$(cat "$FAKE_READSMGW_ARGS_FILE" 2>/dev/null || true)"
assert_contains "custom-host forwards --host 10.0.0.5" "$args_content" "--host 10.0.0.5"

echo "# custom --divisor and --past"
reset_mocks
export FAKE_CSV_OUTPUT=$'id;value;scaler;unit;status;capture_time\n1;50000;-1;30;0;2024-01-01T00:00:00Z\n'
out=$("$TARGET" \
  --user u --password p --meter m --past 120 --divisor 1000 \
  --readsmgw-script "$FAKE_READSMGW" \
  --influx-url http://x --influx-org o --influx-bucket b \
  --influx-token t --measurement MEAS 2>&1)
code=$?
assert_eq "custom-divisor exit code" "0" "$code"
epoch=$(iso_epoch_oracle "2024-01-01T00:00:00Z")
expected_body="MEAS,item=MEAS value=50.0000 ${epoch}000000000"$'\n'
printf '%s' "$expected_body" > "$WORKDIR/expected_body"
if [[ -f "$MOCK_CURL_BODY_FILE" ]] && cmp -s "$WORKDIR/expected_body" "$MOCK_CURL_BODY_FILE"; then
  PASS=$((PASS + 1)); echo "ok - custom-divisor line-protocol body matches exactly"
else
  FAIL=$((FAIL + 1))
  echo "FAIL - custom-divisor line-protocol body mismatch"
  echo "  expected: $(cat "$WORKDIR/expected_body" 2>/dev/null | tr '\n' '|')"
  echo "  actual:   $(cat "$MOCK_CURL_BODY_FILE" 2>/dev/null | tr '\n' '|')"
fi
args_content="$(cat "$FAKE_READSMGW_ARGS_FILE" 2>/dev/null || true)"
assert_contains "custom-past forwards --past 120" "$args_content" "--past 120"

echo "# no data rows -> no InfluxDB write"
reset_mocks
export FAKE_CSV_OUTPUT=$'id;value;scaler;unit;status;capture_time\n'
out=$("$TARGET" \
  --user u --password p --meter m \
  --readsmgw-script "$FAKE_READSMGW" \
  --influx-url http://x --influx-org o --influx-bucket b \
  --influx-token t --measurement MEAS 2>&1)
code=$?
assert_eq "empty-data exit code" "0" "$code"
assert_contains "empty-data message" "$out" "No readings retrieved"
assert_not_exists "empty-data: curl was not invoked" "$MOCK_CURL_LOG_FILE"

echo "# SMGW_PASSWORD env var fallback"
reset_mocks
export FAKE_CSV_OUTPUT=$'id;value;scaler;unit;status;capture_time\n1;10000;-1;30;0;2024-01-01T00:00:00Z\n'
out=$(SMGW_PASSWORD=envpass "$TARGET" \
  --user u --meter m \
  --readsmgw-script "$FAKE_READSMGW" \
  --influx-url http://x --influx-org o --influx-bucket b \
  --influx-token t --measurement MEAS 2>&1)
code=$?
assert_eq "SMGW_PASSWORD fallback exit code" "0" "$code"
args_content="$(cat "$FAKE_READSMGW_ARGS_FILE" 2>/dev/null || true)"
assert_contains "SMGW_PASSWORD fallback forwards --password envpass" "$args_content" "--password envpass"

echo "# INFLUXDB_TOKEN env var fallback"
reset_mocks
out=$(INFLUXDB_TOKEN=envtoken "$TARGET" \
  --user u --password p --meter m \
  --readsmgw-script "$FAKE_READSMGW" \
  --influx-url http://x --influx-org o --influx-bucket b \
  --measurement MEAS 2>&1)
code=$?
assert_eq "INFLUXDB_TOKEN fallback exit code" "0" "$code"
log_content="$(cat "$MOCK_CURL_LOG_FILE" 2>/dev/null || true)"
assert_contains "INFLUXDB_TOKEN fallback used in Authorization header" "$log_content" "Token envtoken"

echo
echo "passed: $PASS, failed: $FAIL"
[[ "$FAIL" -eq 0 ]]
