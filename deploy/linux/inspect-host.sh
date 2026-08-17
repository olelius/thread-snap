#!/usr/bin/env bash
set -euo pipefail

REPORT_PATH="${1:-./threadsnap-host-report.txt}"
MIN_FREE_GIB="${THREADSNAP_MIN_FREE_GIB:-20}"

mkdir -p "$(dirname "$REPORT_PATH")"
exec > >(tee "$REPORT_PATH") 2>&1

section() {
  printf '\n===== %s =====\n' "$1"
}

section "ThreadSnap Linux host inspection"
printf 'timestamp=%s\n' "$(date --iso-8601=seconds)"
printf 'hostname=%s\n' "$(hostname -f 2>/dev/null || hostname)"
printf 'kernel=%s\n' "$(uname -srmo)"
printf 'architecture=%s\n' "$(uname -m)"

section "Operating system"
if [[ -r /etc/os-release ]]; then
  cat /etc/os-release
else
  echo "WARN: /etc/os-release missing"
fi

section "CPU and memory"
command -v lscpu >/dev/null && lscpu || true
command -v free >/dev/null && free -h || true

section "Block devices and mount points"
lsblk -e 7 -o NAME,TYPE,FSTYPE,SIZE,FSAVAIL,FSUSE%,MOUNTPOINTS
printf '\n-- findmnt --\n'
findmnt -D
printf '\n-- df space --\n'
df -hT
printf '\n-- df inodes --\n'
df -Pi

section "Recommended path checks"
for path in /opt /var/lib /var/backups /data /srv /mnt; do
  [[ -e "$path" ]] || continue
  printf '\n[%s]\n' "$path"
  findmnt -T "$path" -o TARGET,SOURCE,FSTYPE,OPTIONS -n || true
  df -hT "$path" | tail -n 1
done

section "Runtime and service commands"
for command_name in python3 systemctl nginx weston curl tar sha256sum ss; do
  if command -v "$command_name" >/dev/null 2>&1; then
    printf '%-12s %s\n' "$command_name" "$(command -v "$command_name")"
  else
    printf '%-12s MISSING\n' "$command_name"
  fi
done
python3 --version 2>/dev/null || true

section "Network listeners"
ss -lntp 2>/dev/null || true

section "SELinux and firewall"
command -v getenforce >/dev/null && getenforce || echo "SELinux command not installed"
command -v firewall-cmd >/dev/null && firewall-cmd --state || echo "firewalld command not installed or inactive"

section "Placement decision"
cat <<EOF
Application releases: /opt/threadsnap/releases
Current release link: /opt/threadsnap/current
Configuration:        /etc/threadsnap
Default persistent:   /var/lib/threadsnap
Default backups:      /var/backups/threadsnap

Linux has mount points rather than Windows drive letters. Inspect lsblk/findmnt/df above before installation.
Keep application releases under /opt. Put the persistent data directory on /var/lib only when its backing
filesystem has enough growth space. If a separate SSD/data mount has more space, use for example
/data/threadsnap and pass --data-dir /data/threadsnap to install.sh. Keep backups on another filesystem or host.
Current warning threshold: ${MIN_FREE_GIB} GiB free; recommended initial capacity: 50 GiB or more.
EOF

root_available_kib="$(df -Pk /var/lib 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ "$root_available_kib" =~ ^[0-9]+$ ]]; then
  required_kib=$((MIN_FREE_GIB * 1024 * 1024))
  if (( root_available_kib < required_kib )); then
    echo "WARN: /var/lib backing filesystem has less than ${MIN_FREE_GIB} GiB free; select a separate data mount."
  else
    echo "OK: /var/lib backing filesystem meets the ${MIN_FREE_GIB} GiB warning threshold."
  fi
fi

echo "report=$REPORT_PATH"
