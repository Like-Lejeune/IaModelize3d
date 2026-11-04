#!/usr/bin/env bash
# Smoke test of a deployed Formwright, from any machine with bash, curl and python3:
#   bash deploy/smoke.sh https://formwright.example.com
# It calls no model and pays for nothing. It checks the home page data (the example cards and the featured runs),
# opens the PCB example as a project (its board, Gerbers, BOM and previews), asks that project for an instant quote,
# and loads the web app's routes and scripts. Each run leaves one anonymous user with one example project on the
# server. Exit status: 0 when every check passed, else the number of failed checks.
#   FW_SMOKE_EXAMPLES=13       how many example cards the home page must show
#   FW_SMOKE_PCB_KEY=<key>     the PCB example's key (default: the card whose pack is 'pcb')
#   FW_SMOKE_FEATURED=0        fail when fewer featured runs are listed (0: only report them)
#   PYTHON=python3             the interpreter for reading JSON
set -uo pipefail

BASE=${1:-${FW_SMOKE_URL:-}}
BASE=${BASE%/}
if [ -z "$BASE" ]; then
  echo "usage: bash deploy/smoke.sh https://your.domain" >&2
  exit 2
fi
EXAMPLES=${FW_SMOKE_EXAMPLES:-13}
FEATURED=${FW_SMOKE_FEATURED:-0}
PY=${PYTHON:-$(command -v python3 || command -v python || true)}
if [ -z "$PY" ]; then
  echo "python3 is needed to read the JSON answers" >&2
  exit 2
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
JAR="$TMP/cookies"
BODY="$TMP/body"
: >"$JAR"
FAILED=0

ok() { printf '  ok    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAILED=$((FAILED + 1)); }
note() { printf '  note  %s\n' "$*"; }

# req METHOD PATH [JSON body] -> "<status> <content type>"; the body lands in $BODY. One cookie jar: one visitor.
req() {
  local method=$1 path=$2 data=${3:-} out
  local args=(-sS -m 120 -X "$method" -b "$JAR" -c "$JAR" -o "$BODY" -w '%{http_code} %{content_type}')
  [ -n "$data" ] && args+=(-H 'content-type: application/json' -d "$data")
  : >"$BODY"
  out=$(curl "${args[@]}" "$BASE$path" 2>"$TMP/err") || out="000 $(tr -d '\r\n' <"$TMP/err")"
  echo "$out"
}

# js 'expression over d' -> prints the result; d is the JSON in $BODY
js() {
  "$PY" -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
r = eval(sys.argv[2])
print(r if isinstance(r, str) else json.dumps(r))' "$BODY" "$1" 2>/dev/null
}

echo "Formwright smoke test: $BASE"

echo "home page data"
read -r code type <<<"$(req GET /api/examples)"
if [ "$code" = 200 ]; then
  n=$(js 'len(d)')
  if [ "$n" = "$EXAMPLES" ]; then ok "/api/examples: $n cards"; else bad "/api/examples: $n cards, expected $EXAMPLES"; fi
  PCB_KEY=${FW_SMOKE_PCB_KEY:-$(js 'next((e["key"] for e in d if e.get("pack") == "pcb"), "")')}
  FIRST_KEY=$(js 'd[0]["key"] if d else ""')
  DEVICE_KEY=$(js 'next((e["key"] for e in d if e.get("pack") == "device"), "")')
  covers=$(js '" ".join(e["cover"] for e in d if e.get("cover"))')
  before=$FAILED
  for cover in $covers; do
    read -r ccode ctype <<<"$(req GET "$cover")"
    if [ "$ccode" = 200 ] && [ "${ctype%%;*}" = image/png ]; then :; else bad "cover $cover: $ccode $ctype"; fi
  done
  if [ -z "$covers" ]; then bad "the example cards have no covers"; elif [ "$FAILED" = "$before" ]; then ok "example covers load"; fi
else
  bad "/api/examples: $code $type"
  PCB_KEY=${FW_SMOKE_PCB_KEY:-}
  FIRST_KEY=""
  DEVICE_KEY=""
fi

read -r code type <<<"$(req GET /api/featured)"
if [ "$code" = 200 ] && js 'isinstance(d, list)' | grep -q true; then
  n=$(js 'len(d)')
  if [ "$n" -lt "$FEATURED" ]; then bad "/api/featured: $n runs, expected at least $FEATURED"
  elif [ "$n" = 0 ]; then note "/api/featured: no featured runs yet (scripts/ship_runs.py, scripts/curate_demo.py)"
  else ok "/api/featured: $n runs ($(js '", ".join(f["title"] for f in d)'))"; fi
else
  bad "/api/featured: $code $type"
fi

echo "the PCB example"
PROJECT=""
if [ -z "$PCB_KEY" ]; then
  bad "no example card with pack 'pcb' (set FW_SMOKE_PCB_KEY)"
else
  read -r code type <<<"$(req POST "/api/examples/$PCB_KEY" '{"lang":"en"}')"
  if [ "$code" = 200 ]; then
    PROJECT=$(js 'd["id"]')
    ok "opened $PCB_KEY as $PROJECT"
  else
    bad "POST /api/examples/$PCB_KEY: $code $(head -c 200 "$BODY")"
  fi
fi
if [ -n "$PROJECT" ]; then
  read -r code type <<<"$(req GET "/api/projects/$PROJECT")"
  if [ "$code" = 200 ] && [ "$(js '(d.get("program") or {}).get("version", 0) >= 1')" = true ]; then
    ok "project opens with a model (v$(js 'd["program"]["version"]'), pack $(js 'd.get("pack")'))"
  else
    bad "GET /api/projects/$PROJECT: $code, no program"
  fi
  read -r code type <<<"$(req GET "/api/projects/$PROJECT/pcb")"
  if [ "$code" = 200 ] && [ "$(js 'len(d) >= 1')" = true ]; then
    ok "PCB v$(js 'd[-1]["version"]'): $(js 'd[-1]["drc"]["errors"]') DRC errors, $(js '(d[-1].get("counts") or {}).get("traces")') traces"
    [ "$(js 'd[-1]["drc"]["errors"]')" = 0 ] || bad "the PCB example has DRC errors"
    # tr: a Windows python ends its lines with \r\n
    "$PY" -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for name, url in sorted(d[-1]["artifacts"].items()):
    print(name, url)' "$BODY" | tr -d '\r' >"$TMP/artifacts"
    before=$FAILED
    while read -r name url; do
      read -r acode atype <<<"$(req GET "$url")"
      size=$(wc -c <"$BODY" | tr -d ' ')
      if [ "$acode" = 200 ] && [ "$size" -gt 0 ]; then :; else bad "artifact $name: $acode, $size bytes"; fi
    done <"$TMP/artifacts"
    have=$(cut -d' ' -f1 "$TMP/artifacts" | tr '\n' ' ')
    for need in gerbers.zip bom.csv cpl.csv pcb_top.svg schematic.svg board.glb route_frames.json; do
      case " $have" in *" $need "*) ;; *) bad "PCB artifact $need is missing" ;; esac
    done
    [ "$FAILED" = "$before" ] && ok "artifacts served: $have"
  else
    bad "GET /api/projects/$PROJECT/pcb: $code, no version"
  fi
fi

echo "the device example"
if [ -z "$DEVICE_KEY" ]; then
  bad "no example card with pack 'device'"
else
  read -r code type <<<"$(req POST "/api/examples/$DEVICE_KEY" '{"lang":"en"}')"
  if [ "$code" = 200 ]; then
    DEVICE=$(js 'd["id"]')
    read -r code type <<<"$(req GET "/api/projects/$DEVICE/device")"
    if [ "$code" = 200 ] && [ "$(js 'len(d["doc"]["nodes"]) > 0 and d["pcb"]["ok"] and not d["pcb"]["stale"]')" = True ] || [ "$(js 'len(d["doc"]["nodes"]) > 0 and d["pcb"]["ok"] and not d["pcb"]["stale"]')" = true ]; then
      ok "$DEVICE_KEY opens with its parts and its board ($(js 'len(d["doc"]["nodes"])') parts, board v$(js 'd["pcb"]["version"]'))"
    else
      bad "GET /api/projects/$DEVICE/device: $code"
    fi
  else
    bad "POST /api/examples/$DEVICE_KEY: $code $(head -c 200 "$BODY")"
  fi
fi

echo "instant quote"
QUOTED=$PROJECT
if [ -z "$QUOTED" ] && [ -n "$FIRST_KEY" ]; then
  read -r code type <<<"$(req POST "/api/examples/$FIRST_KEY" '{"lang":"en"}')"
  [ "$code" = 200 ] && QUOTED=$(js 'd["id"]') && note "no PCB project; quoting the $FIRST_KEY example instead"
fi
if [ -n "$QUOTED" ]; then
  read -r code type <<<"$(req GET "/api/shop/instant-quote/$QUOTED?material=PETG&delivery=courier")"
  if [ "$code" = 200 ] && [ "$(js 'd["currency"] == "KZT" and d["total"] > 0 and d["range"]["total"][0] <= d["total"] <= d["range"]["total"][1]')" = true ]; then
    ok "$(js '"%s KZT ($%s), range %s-%s KZT, %s g each, from the %s" % (d["total"], d["usd"]["total"], d["range"]["total"][0], d["range"]["total"][1], d["grams_each"], d["source"])')"
    [ "$(js 'any(k in d for k in ("cost", "royalty", "gross_profit", "gross_margin"))')" = false ] || bad "the quote shows the farm's costs to a customer"
  else
    bad "GET /api/shop/instant-quote/$QUOTED: $code $(head -c 200 "$BODY")"
  fi
else
  bad "no project to quote"
fi

echo "web app"
asset=""
for route in / /parts /snap; do
  read -r code type <<<"$(req GET "$route")"
  if [ "$code" = 200 ] && [ "${type%%;*}" = text/html ] && grep -q '/_app/' "$BODY"; then
    ok "$route"
    [ -n "$asset" ] || asset=$(grep -o '/_app/immutable/[^"]*\.js' "$BODY" | head -n 1)
  else
    bad "$route: $code $type"
  fi
done
if [ -n "$asset" ]; then
  read -r code type <<<"$(req GET "$asset")"
  if [ "$code" = 200 ]; then ok "app script $asset"; else bad "app script $asset: $code"; fi
fi
case "$BASE" in
  https://*)
    plain="http://${BASE#https://}/"
    redirect=$(curl -sS -m 30 -o /dev/null -w '%{http_code} %{redirect_url}' "$plain" 2>/dev/null || echo "000")
    case "$redirect" in 30[178]\ https://*) ok "http redirects to https" ;; *) bad "http://: $redirect (expected a redirect to https)" ;; esac
    ;;
esac

echo
if [ "$FAILED" = 0 ]; then echo "all checks passed"; else echo "$FAILED check(s) failed"; fi
exit "$FAILED"
