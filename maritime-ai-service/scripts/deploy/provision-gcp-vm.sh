#!/usr/bin/env bash
# =============================================================================
# Provision a new single-node Wiii production VM on Google Cloud.
#
# This script creates only infrastructure primitives:
#   - a regional static IP
#   - HTTP/HTTPS firewall rule
#   - SSH firewall rule scoped to your current public IP by default
#   - an Ubuntu VM with Docker-ready sizing
#
# It does not copy secrets, does not deploy containers, and does not touch the
# existing LMS VM.
#
# Usage:
#   PROJECT_ID=the-wiii-lab \
#   ZONE=asia-southeast1-c \
#     bash maritime-ai-service/scripts/deploy/provision-gcp-vm.sh
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
EXPECTED_PROJECT_PREFIX="${EXPECTED_PROJECT_PREFIX:-the-wiii-lab}"
ALLOW_NON_WIII_PROJECT="${ALLOW_NON_WIII_PROJECT:-false}"
ZONE="${ZONE:-asia-southeast1-c}"
REGION="${REGION:-${ZONE%-*}}"
INSTANCE_NAME="${INSTANCE_NAME:-wiii-production}"
STATIC_IP_NAME="${STATIC_IP_NAME:-wiii-production-ip}"
ASSIGN_EXTERNAL_IP="${ASSIGN_EXTERNAL_IP:-true}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}"
BOOT_DISK_SIZE="${BOOT_DISK_SIZE:-80GB}"
BOOT_DISK_TYPE="${BOOT_DISK_TYPE:-pd-balanced}"
IMAGE_FAMILY="${IMAGE_FAMILY:-ubuntu-2404-lts-amd64}"
IMAGE_PROJECT="${IMAGE_PROJECT:-ubuntu-os-cloud}"
NETWORK="${NETWORK:-default}"
NETWORK_TAG="${NETWORK_TAG:-wiii-prod}"
WEB_FIREWALL_RULE="${WEB_FIREWALL_RULE:-wiii-prod-allow-web}"
SSH_FIREWALL_RULE="${SSH_FIREWALL_RULE:-wiii-prod-allow-ssh}"
LABELS="${LABELS:-app=wiii,env=production,managed-by=codex}"
ALLOW_IAP_SSH="${ALLOW_IAP_SSH:-false}"
FORCE_UPDATE_SSH_RULE="${FORCE_UPDATE_SSH_RULE:-false}"

info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }
fail() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

detect_ssh_source_range() {
    if [ -n "${SSH_SOURCE_RANGES:-}" ]; then
        printf '%s' "$SSH_SOURCE_RANGES"
        return 0
    fi

    local ip
    ip="$(curl -fsS --max-time 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]' || true)"
    if [ -n "$ip" ]; then
        if [ "$ALLOW_IAP_SSH" = "true" ]; then
            printf '%s/32,35.235.240.0/20' "$ip"
        else
            printf '%s/32' "$ip"
        fi
        return 0
    fi

    if [ "$ALLOW_IAP_SSH" = "true" ]; then
        printf '35.235.240.0/20'
        return 0
    fi

    fail "Could not detect current public IP. Set SSH_SOURCE_RANGES explicitly or set ALLOW_IAP_SSH=true."
}

require_command gcloud
require_command curl

[ -n "$PROJECT_ID" ] || fail "PROJECT_ID is required. Set PROJECT_ID or gcloud config set project."

case "$PROJECT_ID" in
    "$EXPECTED_PROJECT_PREFIX"|"$EXPECTED_PROJECT_PREFIX"-*) ;;
    *)
        if [ "$ALLOW_NON_WIII_PROJECT" != "true" ]; then
            fail "Refusing to provision non-Wiii project '${PROJECT_ID}'. Set ALLOW_NON_WIII_PROJECT=true only if intentional."
        fi
        warn "Provisioning non-standard project because ALLOW_NON_WIII_PROJECT=true: ${PROJECT_ID}"
        ;;
esac

info "Project: ${PROJECT_ID}"
info "Zone: ${ZONE}"
info "Region: ${REGION}"
info "Instance: ${INSTANCE_NAME}"
info "Machine: ${MACHINE_TYPE}, disk ${BOOT_DISK_SIZE} ${BOOT_DISK_TYPE}"

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable compute.googleapis.com --project "$PROJECT_ID" >/dev/null

if [ "$ASSIGN_EXTERNAL_IP" = "true" ]; then
    if gcloud compute addresses describe "$STATIC_IP_NAME" \
        --project "$PROJECT_ID" --region "$REGION" >/dev/null 2>&1; then
        info "Static IP already exists: ${STATIC_IP_NAME}"
    else
        info "Creating static IP: ${STATIC_IP_NAME}"
        gcloud compute addresses create "$STATIC_IP_NAME" \
            --project "$PROJECT_ID" \
            --region "$REGION" >/dev/null
    fi

    STATIC_IP="$(gcloud compute addresses describe "$STATIC_IP_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format='value(address)')"
    ADDRESS_ARGS=(--address "$STATIC_IP")
else
    warn "ASSIGN_EXTERNAL_IP=false; VM will not receive a public IP."
    STATIC_IP="none"
    ADDRESS_ARGS=(--no-address)
fi

if gcloud compute firewall-rules describe "$WEB_FIREWALL_RULE" \
    --project "$PROJECT_ID" >/dev/null 2>&1; then
    info "Web firewall rule already exists: ${WEB_FIREWALL_RULE}"
else
    info "Creating web firewall rule: ${WEB_FIREWALL_RULE}"
    gcloud compute firewall-rules create "$WEB_FIREWALL_RULE" \
        --project "$PROJECT_ID" \
        --network "$NETWORK" \
        --allow tcp:80,tcp:443 \
        --target-tags "$NETWORK_TAG" \
        --source-ranges 0.0.0.0/0 \
        --description "Allow public HTTP/HTTPS for Wiii production" >/dev/null
fi

SSH_SOURCE_RANGE="$(detect_ssh_source_range)"
if gcloud compute firewall-rules describe "$SSH_FIREWALL_RULE" \
    --project "$PROJECT_ID" >/dev/null 2>&1; then
    info "SSH firewall rule already exists: ${SSH_FIREWALL_RULE}"
    existing_ranges="$(gcloud compute firewall-rules describe "$SSH_FIREWALL_RULE" \
        --project "$PROJECT_ID" \
        --format='value(sourceRanges)' | tr ';' ',' || true)"
    info "Existing SSH source ranges: ${existing_ranges:-<none>}"
    if [ "$existing_ranges" != "$SSH_SOURCE_RANGE" ]; then
        warn "Desired SSH source ranges: ${SSH_SOURCE_RANGE}"
        if [ "$FORCE_UPDATE_SSH_RULE" = "true" ]; then
            info "Updating SSH firewall source ranges because FORCE_UPDATE_SSH_RULE=true"
            gcloud compute firewall-rules update "$SSH_FIREWALL_RULE" \
                --project "$PROJECT_ID" \
                --source-ranges "$SSH_SOURCE_RANGE" >/dev/null
        else
            warn "SSH ranges differ. Re-run with FORCE_UPDATE_SSH_RULE=true to update ${SSH_FIREWALL_RULE}."
        fi
    fi
else
    info "Creating SSH firewall rule: ${SSH_FIREWALL_RULE} (${SSH_SOURCE_RANGE})"
    gcloud compute firewall-rules create "$SSH_FIREWALL_RULE" \
        --project "$PROJECT_ID" \
        --network "$NETWORK" \
        --allow tcp:22 \
        --target-tags "$NETWORK_TAG" \
        --source-ranges "$SSH_SOURCE_RANGE" \
        --description "Allow SSH for Wiii production maintainers" >/dev/null
fi

if gcloud compute instances describe "$INSTANCE_NAME" \
    --project "$PROJECT_ID" --zone "$ZONE" >/dev/null 2>&1; then
    info "Instance already exists: ${INSTANCE_NAME}"
else
    info "Creating VM: ${INSTANCE_NAME}"
    gcloud compute instances create "$INSTANCE_NAME" \
        --project "$PROJECT_ID" \
        --zone "$ZONE" \
        --machine-type "$MACHINE_TYPE" \
        --network "$NETWORK" \
        "${ADDRESS_ARGS[@]}" \
        --tags "$NETWORK_TAG" \
        --metadata=enable-oslogin=TRUE \
        --no-service-account \
        --no-scopes \
        --image-family "$IMAGE_FAMILY" \
        --image-project "$IMAGE_PROJECT" \
        --boot-disk-size "$BOOT_DISK_SIZE" \
        --boot-disk-type "$BOOT_DISK_TYPE" \
        --boot-disk-device-name "$INSTANCE_NAME" \
        --labels "$LABELS" \
        --maintenance-policy MIGRATE \
        --shielded-secure-boot \
        --shielded-vtpm \
        --shielded-integrity-monitoring >/dev/null
fi

echo ""
info "Provisioning complete."
echo "  Instance: ${INSTANCE_NAME}"
echo "  Project:  ${PROJECT_ID}"
echo "  Zone:     ${ZONE}"
echo "  Static IP:${STATIC_IP}"
echo ""
echo "Next steps:"
echo "  1. Point wiii.holilihu.online DNS/Cloudflare origin to ${STATIC_IP}."
echo "  2. SSH: gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} --project=${PROJECT_ID}"
echo "  3. Run setup-server.sh on the VM, clone repo into /opt/wiii, create .env.production, then deploy pinned images."
