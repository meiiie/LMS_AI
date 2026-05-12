#!/bin/bash
# smoke-test.sh
# Post-deployment verification for wiii.holilihu.online
#
# Usage:
#   bash smoke-test.sh [BASE_URL]
#   API_KEY=your-key bash smoke-test.sh https://wiii.holilihu.online

set -euo pipefail

BASE_URL="${1:-https://wiii.holilihu.online}"
API_KEY="${API_KEY:-}"
PASS=0
FAIL=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "true" ]; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Wiii Smoke Test: ${BASE_URL} ==="
echo ""

# 1. Health Checks
echo "1. Health Checks"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/v1/health" 2>/dev/null || echo "000")
check "Shallow health (GET /health)" "$([ "$HTTP" = "200" ] && echo true || echo false)"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/v1/health/live" 2>/dev/null || echo "000")
check "Liveness probe (GET /health/live)" "$([ "$HTTP" = "200" ] && echo true || echo false)"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/v1/health/db" 2>/dev/null || echo "000")
check "Deep health — DB (GET /health/db)" "$([ "$HTTP" = "200" ] && echo true || echo false)"

LLM_MODEL_HEALTH=$(curl -s "${BASE_URL}/api/v1/health/llm-models" 2>/dev/null || true)
check "LLM model health visible" "$(echo "$LLM_MODEL_HEALTH" | grep -q '"model_count"' && echo true || echo false)"
check "LLM model health redacts raw errors" "$([ -n "$LLM_MODEL_HEALTH" ] && ! echo "$LLM_MODEL_HEALTH" | grep -q 'last_error_detail' && echo true || echo false)"

# 2. Security Headers
echo ""
echo "2. Security Headers"
HEADERS=$(curl -s -D - -o /dev/null "${BASE_URL}/api/v1/health" 2>/dev/null)
check "X-Request-ID present" "$(echo "$HEADERS" | grep -qi "x-request-id" && echo true || echo false)"

EMBED_HEADERS=$(curl -s -D - -o /dev/null "${BASE_URL}/embed/" 2>/dev/null)
check "CSP frame-ancestors on /embed" "$(echo "$EMBED_HEADERS" | grep -qi "frame-ancestors" && echo true || echo false)"

# 3. Pages Load
echo ""
echo "3. Page Loading"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/embed/" 2>/dev/null || echo "000")
check "Embed page loads (GET /embed/)" "$([ "$HTTP" = "200" ] && echo true || echo false)"

EMBED_HTML=$(curl -s "${BASE_URL}/embed/" 2>/dev/null || true)
check "Embed HTML includes built asset references" "$(echo "$EMBED_HTML" | grep -Eq '/assets/|<script[^>]+type="module"' && echo true || echo false)"

POINTY_HEADERS="$(mktemp)"
POINTY_BODY="$(mktemp)"
HTTP=$(curl -s -D "$POINTY_HEADERS" -o "$POINTY_BODY" -w "%{http_code}" "${BASE_URL}/pointy/wiii-pointy.umd.js" 2>/dev/null || echo "000")
check "Pointy bundle loads (GET /pointy/wiii-pointy.umd.js)" "$([ "$HTTP" = "200" ] && echo true || echo false)"
check "Pointy bundle returns JavaScript content type" "$(grep -qiE 'content-type:.*(javascript|ecmascript)' "$POINTY_HEADERS" && echo true || echo false)"
check "Pointy bundle is not SPA HTML" "$([ -s "$POINTY_BODY" ] && ! grep -qiE '<!doctype html|<html' "$POINTY_BODY" && echo true || echo false)"
rm -f "$POINTY_HEADERS" "$POINTY_BODY"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/" 2>/dev/null || echo "000")
check "SPA loads (GET /)" "$([ "$HTTP" = "200" ] && echo true || echo false)"

# 4. API Endpoints
echo ""
echo "4. API Endpoints"
if [ -n "$API_KEY" ]; then
    # Production API key auth is a service-client path.
    # Do not send X-User-ID here; auth resolves to api-client.
    #
    # Keep this sync smoke deterministic. The generic "test" prompt can route
    # through the legacy sync LLM path and exceed the deploy budget even when
    # the product-critical SSE path below is healthy. "doi phet" intentionally
    # exercises Wiii's conservative fast social route without depending on LLM
    # latency, while the visual SSE smoke remains the end-to-end LLM check.
    CHAT_SESSION_ID="smoke-test-chat-$(date -u +%Y%m%d%H%M%S)-$$"
    CHAT_BODY="$(mktemp)"
    CHAT_METRICS=$(curl -s -o "$CHAT_BODY" -w "%{http_code} %{time_total}" \
        -X POST "${BASE_URL}/api/v1/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${API_KEY}" \
        -H "X-Session-ID: ${CHAT_SESSION_ID}" \
        -d "$(printf '{"user_id":"api-client","message":"doi phet","role":"student","session_id":"%s","domain_id":"maritime"}' "$CHAT_SESSION_ID")" \
        --max-time 30 \
        2>/dev/null || true)
    CHAT_HTTP="$(printf '%s' "$CHAT_METRICS" | awk '{print $1}')"
    CHAT_SECONDS="$(printf '%s' "$CHAT_METRICS" | awk '{print $2}')"
    CHAT_HTTP="${CHAT_HTTP:-000}"
    CHAT_SECONDS="${CHAT_SECONDS:-0}"
    echo "  [INFO] Chat API HTTP ${CHAT_HTTP} in ${CHAT_SECONDS}s"
    check "Chat API (POST /chat)" "$([ "$CHAT_HTTP" = "200" ] && [ -s "$CHAT_BODY" ] && echo true || echo false)"
    rm -f "$CHAT_BODY"

    VOICE_BODY="$(mktemp)"
    VOICE_HTTP=$(curl -s -o "$VOICE_BODY" -w "%{http_code}" \
        "${BASE_URL}/api/v1/voice/status" \
        -H "X-API-Key: ${API_KEY}" \
        --max-time 20 \
        2>/dev/null || echo "000")
    check "Pointy voice status endpoint registered" "$([ "$VOICE_HTTP" = "200" ] && echo true || echo false)"
    check "Pointy voice status reports ElevenLabs provider" "$([ "$VOICE_HTTP" = "200" ] && grep -q '"provider":"elevenlabs"' "$VOICE_BODY" && echo true || echo false)"
    rm -f "$VOICE_BODY"

    VISUAL_SESSION_ID="smoke-test-visual-$(date -u +%Y%m%d%H%M%S)-$$"
    VISUAL_PAYLOAD=$(printf '{"user_id":"api-client","message":"Create a compact inline visual comparing soft attention and linear attention. Use structured visual lifecycle.","role":"student","session_id":"%s","domain_id":"maritime"}' "$VISUAL_SESSION_ID")
    STREAM_BODY=$(curl -sN \
        -X POST "${BASE_URL}/api/v1/chat/stream/v3" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${API_KEY}" \
        -H "X-Session-ID: ${VISUAL_SESSION_ID}" \
        -d "$VISUAL_PAYLOAD" \
        --max-time 90 \
        2>/dev/null || true)
    VISUAL_EVENTS="$(printf '%s\n' "$STREAM_BODY" | grep '^event:' | tr '\n' ' ' || true)"
    echo "  [INFO] Structured visual SSE events: ${VISUAL_EVENTS:-none}"
    check "Structured visual SSE opens or patches visual lifecycle" "$(printf '%s\n' "$STREAM_BODY" | grep -Eq '^event: visual_(open|patch)$' && echo true || echo false)"
    check "Structured visual SSE commits visual lifecycle" "$(echo "$STREAM_BODY" | grep -q '^event: visual_commit$' && echo true || echo false)"
    check "Structured visual stream hides raw widget fences" "$([ -n "$STREAM_BODY" ] && ! echo "$STREAM_BODY" | grep -q '```widget' && echo true || echo false)"
else
    echo "  [SKIP] Chat API — set API_KEY to test"
fi

# Summary
echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
[ "$FAIL" -eq 0 ] && echo "All checks passed!" || echo "Some checks failed — investigate above."
exit "$FAIL"
