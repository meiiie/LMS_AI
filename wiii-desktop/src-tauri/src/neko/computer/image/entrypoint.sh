#!/bin/sh
set -eu

if [ ! -r /run/secrets/wiii-vnc-password ]; then
  echo "Wiii computer display credential is unavailable" >&2
  exit 70
fi

legacy_chrome_profile="$HOME/.config/google-chrome"
chrome_profile="$HOME/.wiii/google-chrome"
mkdir -p "$HOME/.wiii"
if [ ! -d "$chrome_profile" ]; then
  if [ -d "$legacy_chrome_profile" ]; then
    # Chrome 136+ disables DevTools for its platform-default profile. Move the
    # existing durable profile once so signed-in sessions survive the upgrade
    # while Wiii can verify browser navigation through loopback-only CDP.
    mv "$legacy_chrome_profile" "$chrome_profile"
  else
    mkdir -p "$chrome_profile"
  fi
fi

mkdir -p \
  "$HOME/.config/lxpanel/Wiii/panels" \
  "$HOME/.config/pcmanfm/Wiii" \
  "$HOME/.vnc" \
  "$HOME/Desktop"
if [ ! -f "$HOME/.config/lxpanel/Wiii/panels/panel" ]; then
  cp /usr/share/wiii-computer/panel.conf "$HOME/.config/lxpanel/Wiii/panels/panel"
fi
desktop_config="$HOME/.config/pcmanfm/Wiii/desktop-items-0.conf"
if [ ! -f "$desktop_config" ] || ! grep -q '^wallpaper=' "$desktop_config"; then
  cp /usr/share/wiii-computer/desktop-items-0.conf "$desktop_config"
fi
for launcher in /usr/share/wiii-computer/desktop/*.desktop; do
  destination="$HOME/Desktop/$(basename "$launcher")"
  cp "$launcher" "$destination"
  chmod 0755 "$destination"
done
printf '%s\n' "$(cat /run/secrets/wiii-vnc-password)" | tigervncpasswd -f >"$HOME/.vnc/passwd"
chmod 600 "$HOME/.vnc/passwd"

# The accessibility bus belongs to the durable Computer session, not to an
# individual viewer connection. Docker exec clients source this file before
# calling the semantic bridge.
eval "$(dbus-launch --sh-syntax)"
printf "export DBUS_SESSION_BUS_ADDRESS='%s'\n" "$DBUS_SESSION_BUS_ADDRESS" >/tmp/wiii-dbus-env
chmod 600 /tmp/wiii-dbus-env

office_profile=/tmp/wiii-work-plane-office-profile
mkdir -p "$office_profile"
rm -f "$office_profile/.lock"
libreoffice \
  --headless \
  --nologo \
  --nodefault \
  --nofirststartwizard \
  --norestore \
  "-env:UserInstallation=file://$office_profile" \
  "--accept=pipe,name=wiii_work_plane_office;urp;StarOffice.ServiceManager" \
  >/tmp/wiii-work-plane-office.log 2>&1 &
office_pid=$!

# A container restart changes its hostname. Chrome's persisted SingletonLock
# therefore points at the previous container even though no browser can still be
# using this dedicated profile. Clear only these process-coordination files;
# cookies, sign-ins, extensions, and all other profile data remain durable.
rm -f \
  "$chrome_profile/SingletonCookie" \
  "$chrome_profile/SingletonLock" \
  "$chrome_profile/SingletonSocket"

Xtigervnc :1 \
  -Desktop "Wiii Web Computer" \
  -geometry 1440x900 \
  -depth 24 \
  -rfbport 5900 \
  -PasswordFile "$HOME/.vnc/passwd" \
  -SecurityTypes VncAuth \
  -localhost yes \
  -AlwaysShared \
  -DisconnectClients=0 \
  -NeverShared=0 \
  -AcceptKeyEvents \
  -AcceptPointerEvents \
  -SendPrimary=0 \
  -SetPrimary=0 \
  >/tmp/tigervnc.log 2>&1 &
display_pid=$!

cleanup() {
  kill "$display_pid" 2>/dev/null || true
  kill "$office_pid" 2>/dev/null || true
  if [ -n "${semantic_bridge_pid:-}" ]; then
    kill "$semantic_bridge_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

tries=0
while [ ! -S /tmp/.X11-unix/X1 ]; do
  tries=$((tries + 1))
  if [ "$tries" -gt 100 ]; then
    echo "Wiii computer display did not become ready" >&2
    exit 71
  fi
  sleep 0.05
done

openbox-session >/tmp/openbox.log 2>&1 &

pcmanfm --desktop --profile Wiii >/tmp/pcmanfm.log 2>&1 &
lxpanel --profile Wiii >/tmp/lxpanel.log 2>&1 &

wiii-browser \
  --window-position=150,40 \
  --window-size=1120,760 \
  about:blank >/tmp/google-chrome.log 2>&1 &

python3 /usr/local/lib/wiii-computer/semantic_bridge.py serve \
  >/tmp/wiii-semantic-bridge.log 2>&1 &
semantic_bridge_pid=$!

tries=0
while ! curl --fail --silent --max-time 1 http://127.0.0.1:9234/health >/dev/null; do
  tries=$((tries + 1))
  if [ "$tries" -gt 100 ] || ! kill -0 "$semantic_bridge_pid" 2>/dev/null; then
    echo "Wiii semantic bridge did not become ready" >&2
    exit 72
  fi
  sleep 0.05
done

exec websockify --web=/usr/share/novnc 0.0.0.0:6080 localhost:5900
