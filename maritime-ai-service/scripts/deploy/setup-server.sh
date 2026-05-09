#!/bin/bash
# =============================================================================
# Wiii Production Server Setup — GCP Ubuntu 22.04/24.04
# by The Wiii Lab (Hong Linh Linh Hung)
#
# Usage: ssh into your GCP VM, then:
#   chmod +x setup-server.sh && ./setup-server.sh
#
# What this does:
#   1. Updates system packages
#   2. Installs Docker + Docker Compose v2
#   3. Installs Caddy (auto-SSL reverse proxy)
#   4. Creates /opt/wiii app directory
#   5. Configures swap (default 4G, override via SWAP_SIZE)
#   6. Kernel tuning for high-connection server
#   7. Installs fail2ban (brute-force protection)
#   8. Configures UFW firewall (SSH + HTTP + HTTPS only)
#   9. Hardens SSH (key-only auth)
#  10. Creates Caddy log directory
# =============================================================================

set -euo pipefail

SWAP_SIZE="${SWAP_SIZE:-4G}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Must run as non-root user with sudo access
if [ "$(id -u)" -eq 0 ]; then
    error "Do not run as root. Run as your normal user (docker group will be added)."
    exit 1
fi

echo ""
echo "============================================="
echo "   Wiii Production Server Setup"
echo "   by Hong Linh Linh Hung"
echo "   $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================="
echo ""

# ─────────────────────────────────────────────────
# 1. System Update
# ─────────────────────────────────────────────────
info "Step 1/10: Updating system packages..."
sudo apt update && sudo apt upgrade -y

# ─────────────────────────────────────────────────
# 2. Install Docker
# ─────────────────────────────────────────────────
if command -v docker &> /dev/null; then
    info "Step 2/10: Docker already installed — $(docker --version)"
else
    info "Step 2/10: Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    sudo systemctl enable docker
    info "Docker installed. You'll need to log out/in for group changes."
fi

# ─────────────────────────────────────────────────
# 3. Install Docker Compose v2
# ─────────────────────────────────────────────────
if docker compose version &> /dev/null 2>&1; then
    info "Step 3/10: Docker Compose already installed — $(docker compose version)"
else
    info "Step 3/10: Installing Docker Compose plugin..."
    sudo apt install -y docker-compose-plugin
fi

# ─────────────────────────────────────────────────
# 4. Install Caddy
# ─────────────────────────────────────────────────
if command -v caddy &> /dev/null; then
    info "Step 4/10: Caddy already installed — $(caddy version)"
else
    info "Step 4/10: Installing Caddy..."
    sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt update && sudo apt install -y caddy
    info "Caddy installed. Will auto-obtain SSL certificates."
fi

# ─────────────────────────────────────────────────
# 5. Create app directory
# ─────────────────────────────────────────────────
info "Step 5/10: Setting up directories..."
sudo mkdir -p /opt/wiii
sudo chown "$USER":"$USER" /opt/wiii

# Caddy log directory. Install with explicit ownership so Caddy can create and
# rotate access logs after config reloads.
sudo install -d -o caddy -g caddy -m 0755 /var/log/caddy
sudo touch /var/log/caddy/wiii-access.log
sudo chown caddy:caddy /var/log/caddy/wiii-access.log

# ─────────────────────────────────────────────────
# 6. Configure swap (critical for single-node Docker production)
# ─────────────────────────────────────────────────
if [ -f /swapfile ]; then
    info "Step 6/10: Swap already configured."
else
    info "Step 6/10: Creating ${SWAP_SIZE} swap..."
    sudo fallocate -l "$SWAP_SIZE" /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
    # Low swappiness — keep app in RAM, only swap under pressure
    echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf > /dev/null
    sudo sysctl vm.swappiness=10
    info "${SWAP_SIZE} swap created (swappiness=10)."
fi

# ─────────────────────────────────────────────────
# 7. Kernel tuning for high-connection server
# ─────────────────────────────────────────────────
info "Step 7/10: Kernel tuning..."
if ! grep -q "wiii-tuning" /etc/sysctl.conf 2>/dev/null; then
    cat << 'EOF' | sudo tee -a /etc/sysctl.conf > /dev/null

# === Wiii production tuning (wiii-tuning) ===
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
fs.file-max = 2097152
EOF
    sudo sysctl -p
    info "Kernel parameters tuned."
else
    info "Step 7/10: Kernel already tuned."
fi

# ─────────────────────────────────────────────────
# 8. Install fail2ban (brute-force protection)
# ─────────────────────────────────────────────────
if command -v fail2ban-client &> /dev/null; then
    info "Step 8/10: fail2ban already installed."
else
    info "Step 8/10: Installing fail2ban..."
    sudo apt install -y fail2ban

    # Configure fail2ban for SSH
    cat << 'EOF' | sudo tee /etc/fail2ban/jail.local > /dev/null
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3

[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 86400
EOF
    sudo systemctl enable fail2ban
    sudo systemctl restart fail2ban
    info "fail2ban installed (SSH: 3 attempts → 24h ban)."
fi

# ─────────────────────────────────────────────────
# 9. Configure UFW firewall
# ─────────────────────────────────────────────────
info "Step 9/10: Configuring UFW firewall..."
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP (Caddy redirect to HTTPS)'
sudo ufw allow 443/tcp comment 'HTTPS (Caddy auto-SSL)'
sudo ufw --force enable
sudo ufw status verbose

# ─────────────────────────────────────────────────
# 10. Harden SSH
# ─────────────────────────────────────────────────
info "Step 10/10: Hardening SSH..."
# Only disable password auth if SSH keys are already set up (GCP uses keys by default)
if [ -f ~/.ssh/authorized_keys ] && [ -s ~/.ssh/authorized_keys ]; then
    sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
    sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
    sudo sed -i 's/^#\?MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config
    sudo systemctl restart sshd 2>/dev/null || sudo systemctl restart ssh
    info "SSH hardened: password auth disabled, root login disabled."
else
    warn "No SSH keys found — skipping SSH hardening (add keys first!)."
fi

# ─────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────
echo ""
echo "============================================="
info "Server setup complete!"
echo "============================================="
echo ""
echo "System info:"
echo "  RAM:  $(free -h | awk 'NR==2 {print $2}')"
echo "  Swap: $(free -h | awk 'NR==3 {print $2}')"
echo "  Disk: $(df -h / | awk 'NR==2 {print $2, "total,", $4, "free"}')"
echo ""
echo "Next steps:"
echo "  1. Log out and back in (for docker group)"
echo "  2. Clone your repo:  git clone <repo-url> /opt/wiii"
echo "  3. Create secrets:   cp scripts/deploy/.env.production.template maritime-ai-service/.env.production"
echo "  4. Edit secrets:     nano maritime-ai-service/.env.production"
echo "  5. Install Caddy:    sudo cp maritime-ai-service/scripts/deploy/Caddyfile /etc/caddy/Caddyfile"
echo "  6. Deploy:           ./maritime-ai-service/scripts/deploy/deploy.sh"
echo ""
echo "Quick test after re-login:"
echo "  docker --version && docker compose version && caddy version"
echo ""
