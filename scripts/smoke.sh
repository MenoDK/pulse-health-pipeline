#!/usr/bin/env bash
# Black-box check of the running demo: the doors in front of it, then every guarantee the landing page makes, driven
# through the same HTTP API the lab uses, against the real PostgreSQL, Redis, worker and stand-ins.
#
#   scripts/smoke.sh [base-url]        default http://localhost:8300   (make demo first)
#
# It starts each flow from a clean slate and leaves one behind, so it can be run again.
set -uo pipefail

A="${1:-http://localhost:8300}"
n=0
pass() { n=$((n + 1)); printf '  ok %2d  %s\n' "$n" "$1"; }
die() { printf '  FAIL    %s\n' "$1" >&2; exit 1; }

post() { curl -sS -m 60 -X POST "$A$1" -H 'content-type: application/json' -d "${2:-{\}}"; }
get() { curl -sS -m 30 "$A$1"; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
# check <label> <json> <jq expression that must be true>
check() { printf '%s' "$2" | jq -e "$3" >/dev/null 2>&1 || die "$1  (got: $(printf '%s' "$2" | jq -c . 2>/dev/null | head -c 400))"; pass "$1"; }

# Drain until nothing is due or a worker gives up early; prints the sum of one field over all batches.
drain_all() {
  local field="$1" total=0 i out claimed stopped value
  for i in $(seq 1 80); do
    out="$(post /api/queue/drain)"
    claimed="$(printf '%s' "$out" | jq '.claimed')"
    value="$(printf '%s' "$out" | jq ".$field")"
    total=$((total + value))
    stopped="$(printf '%s' "$out" | jq -r '.stopped // ""')"
    { [ "$claimed" = "0" ] || [ -n "$stopped" ]; } && break
  done
  printf '%s' "$total"
}
gateway() { post /api/lab/gateway/scenario "{\"name\":\"$1\"}" >/dev/null; }
move() { post /api/lab/clock "{\"seconds\":$1}" >/dev/null; }

echo "pulse smoke test against $A"

# --- the front door -----------------------------------------------------------------------------------------------------
[ "$(code "$A/health/live")" = "200" ] || die "the liveness probe does not answer"
pass "the liveness probe answers"
check "readiness says the database and the broker answer" "$(get /health/ready)" '.status != "down" and ([.checks[] | select(.component == "database" or .component == "broker") | .status] | all(. == "ok"))'
[ "$(code -H 'Host: evil.example.test' "$A/api/overview")" = "421" ] || die "a foreign Host header was answered"
pass "a foreign Host header is refused"
[ "$(code -X POST -H 'Origin: https://evil.example.test' -H 'content-type: application/json' -d '{}' "$A/api/lab/reset")" = "403" ] || die "a foreign Origin was accepted"
pass "a change from another origin is refused"
[ "$(code -X POST -H 'Sec-Fetch-Site: cross-site' -H 'content-type: application/json' -d '{}' "$A/api/lab/reset")" = "403" ] || die "a cross-site request was accepted"
pass "a change the browser marks cross-site is refused"
[ "$(code "$A/")" = "200" ] && [ "$(code "$A/lab.html")" = "200" ] || die "the landing page or the lab page is not served"
pass "the landing page and the lab page are served"
curl -sSI -m 5 "$A/" | grep -qi "^content-security-policy: default-src 'self'" || die "the page has no strict content security policy"
pass "the page carries a strict content security policy"
[ "$(code --path-as-is "$A/../etc/passwd")" != "200" ] || die "a path outside the site was served"
pass "nothing outside the site is served"

# --- a first synchronisation ----------------------------------------------------------------------------------------------
post /api/lab/reset >/dev/null
first="$(post /api/sync/run)"
check "the first sync reads and writes everything" "$first" '.status == "ok" and .totals.applied > 0 and .totals.fetched >= .totals.applied'
check "records that do not fit are counted, and the team listed twice is stale" "$first" '.totals.rejected >= 1 and .totals.stale >= 3'
check "every written encounter queued exactly one message" "$first" ".queued > 0 and .queued == $(get /api/queue | jq '.counts.pending')"
queued="$(printf '%s' "$first" | jq '.queued')"
second="$(post /api/sync/run)"
check "a second sync, with the overlap window re-read, writes nothing" "$second" '.status == "ok" and .totals.applied == 0 and .totals.fetched > 0'
check "and queues nothing" "$second" '.queued == 0'
check "a full re-read writes nothing either" "$(post /api/sync/run '{"full":true}')" '.status == "ok" and .totals.applied == 0 and .totals.fetched > 0'
check "the position stored is a time, and nothing else" "$(get '/api/sync/runs?limit=3')" '([.positions[] | keys[]] | unique) == ["updated_at"]'

# --- delivery ------------------------------------------------------------------------------------------------------------
delivered="$(drain_all delivered)"
[ "$delivered" = "$queued" ] || die "drained $delivered of $queued messages"
pass "draining delivers every message ($queued)"
check "the gateway holds each report once and refused no duplicate" "$(get /api/lab/gateway)" ".received_unique == $queued and .duplicates == 0"
check "nothing is left pending or dead" "$(get /api/queue)" ".counts.pending == 0 and .counts.sending == 0 and .counts.dead == 0 and .counts.done == $queued"

# --- a registry that is busy -----------------------------------------------------------------------------------------------
post /api/lab/registry/advance '{"new":20,"changed":10,"removed":3}' >/dev/null
post /api/lab/registry/flaky '{"next_requests":3}' >/dev/null
busy="$(post /api/sync/run)"
check "a registry that fails three times in a row fails the run, and says only that" "$busy" '.status == "failed" and (.error | test("could not be read after 3 tries")) and (.error | test("reg-") | not)'
check "the failed run moved no position" "$(get '/api/sync/runs?limit=1')" '.runs[0].status == "failed" and .runs[0].applied == 0'
check "the next run succeeds and picks up the week of work" "$(post /api/sync/run)" '.status == "ok" and .totals.applied == 33 and .queued == 33'

# --- a worker that dies ----------------------------------------------------------------------------------------------------
crash="$(post /api/lab/queue/crash '{"count":5}')"
check "a worker claims five messages and walks away" "$crash" '(.abandoned | length) == 5'
check "they sit in sending" "$(get /api/queue)" '.counts.sending == 5'
check "a drain before the lease ends does not touch them" "$(post /api/queue/drain)" '.taken_over == 0'
move 600
check "after the lease, the next drain takes them over first and says so" "$(post /api/queue/drain)" '.taken_over == 5 and .delivered >= 5'
drain_all delivered >/dev/null
check "the rest is delivered" "$(get /api/queue)" '.counts.pending == 0 and .counts.sending == 0 and .counts.dead == 0'

# --- a gateway slower than its timeout -------------------------------------------------------------------------------------
post /api/lab/registry/advance '{"new":120,"changed":0,"removed":0}' >/dev/null
post /api/sync/run >/dev/null
gateway slow
slow="$(post /api/queue/drain)"
check "three timeouts in a row stop the worker, which gives the rest back untouched" "$slow" '.stopped == "3 transport failures in a row" and .released > 0 and .retried == 3'
gateway normal
move 3600
drain_all delivered >/dev/null
check "afterwards everything is delivered" "$(get /api/queue)" '.counts.pending == 0 and .counts.dead == 0'

# --- an acknowledgement that is lost ----------------------------------------------------------------------------------------
post /api/lab/registry/advance '{"new":60,"changed":0,"removed":0}' >/dev/null
post /api/sync/run >/dev/null
gateway lose-ack
lost="$(drain_all retried)"
[ "$lost" -ge 60 ] || die "expected at least 60 messages to fail their acknowledgement, got $lost"
pass "the gateway keeps $lost reports and fails to say so"
gateway normal
move 3600
again="$(drain_all duplicate)"
[ "$again" -ge 60 ] || die "expected at least 60 duplicate answers, got $again"
pass "the second pass is answered 'duplicate' $again times, and counted as delivered"
done_count="$(get /api/queue | jq '.counts.done')"
check "the gateway holds exactly one report per message" "$(get /api/lab/gateway)" ".received_unique == $done_count"

# --- the connector ------------------------------------------------------------------------------------------------------------
check "with its client certificate the connector is let in" "$(post /api/lab/connector/check '{"with_certificate":true}')" '.tls == true and .ok == true'
check "without one the handshake is refused" "$(post /api/lab/connector/check '{"with_certificate":false}')" '.tls == true and .ok == false'

# --- indicators and the narrator ------------------------------------------------------------------------------------------
report="$(get '/api/indicators?narrate=true')"
check "five indicators and a score" "$report" '(.indicators | length) == 5 and .score != null and .indicators_with_data >= 3'
check "the template's own words pass the check" "$report" '.narration.accepted == true and .narration.source == "narrator"'
for mode in rounds invents leaks; do
  post /api/lab/narrator "{\"mode\":\"$mode\"}" >/dev/null
  check "a narrator that $mode is refused, and replaced by the template" "$(get '/api/indicators?narrate=true' | jq '.narration')" '.accepted == false and .source == "template" and (.violations | length) > 0'
done
post /api/lab/narrator '{"mode":"template"}' >/dev/null
[ "$(code -X POST -H 'content-type: application/json' -d '{"mode":"nope"}' "$A/api/lab/narrator")" = "422" ] || die "an unknown narrator was accepted"
pass "an unknown narrator is refused"

# --- search -----------------------------------------------------------------------------------------------------------------
check "a typo finds nothing by keywords" "$(get '/api/search?q=synchronisaton&mode=lexical')" '.hits == []'
check "but is found by the vectors" "$(get '/api/search?q=synchronisaton&mode=vector&k=3')" '[.hits[].title | ascii_downcase | test("sync")] | any'
check "the hybrid answers with where each hit came from" "$(get '/api/search?q=advisory+lock&mode=hybrid&k=3')" '(.hits | length) > 0 and (.hits[0].ranks | length) > 0'
check "the hybrid beats either list alone on recall@3" "$(get /api/search/eval)" '.hybrid.all.recall_at_3 > .lexical.all.recall_at_3 and .hybrid.all.recall_at_3 > .vector.all.recall_at_3'
check "the gap queries are the weakest for every method" "$(get /api/search/eval)" '[.[] | .gap.recall_at_3 < .natural.recall_at_3] | all'

# --- privacy ------------------------------------------------------------------------------------------------------------------
priv="$(get /api/lab/privacy)"
check "the names and identifiers of forty people are nowhere in the database" "$priv" '.scan.clean == true and .searched_for == 120'
check "and the scan did look: it examined columns" "$priv" '.scan.columns_examined >= 20'
check "what is stored for a person is a keyed hash, a month and a team" "$priv" '(.stored_for_them | length) == 3 and ([.stored_for_them[].subject_key | test("^p[a-z0-9]+\\.[a-z2-7]{26}$")] | all)'

# --- health ---------------------------------------------------------------------------------------------------------------------
check "health lists six components" "$(get /api/health)" '(.checks | length) == 6'
post /api/lab/queue/crash '{"count":1}' >/dev/null
post /api/sync/run >/dev/null
post /api/lab/registry/advance '{"new":5,"changed":0,"removed":0}' >/dev/null
post /api/sync/run >/dev/null
move 86400
check "a day later, messages that nobody sent make the queue down and the whole degraded" "$(get /api/health)" '(.checks[] | select(.component == "queue") | .status) == "down" and .status == "degraded"'

# --- leave it clean -----------------------------------------------------------------------------------------------------------
post /api/lab/reset >/dev/null
check "start over empties the database" "$(get /api/overview)" '.data.encounters == 0 and .data.kb_chunks > 0 and .queue.pending == 0'

echo "all $n checks passed"
