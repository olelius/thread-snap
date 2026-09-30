#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo/root" >&2
  exit 2
fi

# 与固定保留任务互斥，正在备份或恢复时不能移除恢复点。
exec 9>/run/lock/threadsnap-backup-maintenance.lock
flock -x 9
if [[ $# -ne 2 || "$2" != "--confirm" ]]; then
  echo "Usage: sudo bash deploy/restore-backup.sh BACKUP.tar.gz --confirm" >&2
  exit 2
fi

# 停服前从已安装的单server配置读取端口；绝不默认80探测其它业务。
LISTEN_PORT="$(python3 - /etc/threadsnap/nginx-site.conf <<'PORT_PY'
import re
import sys
from pathlib import Path

try:
    source = Path(sys.argv[1]).read_text(encoding="utf-8-sig")
except (OSError, UnicodeError) as error:
    raise SystemExit("ERROR: cannot read installed Nginx site configuration") from error
source = re.sub(r"#.*$", "", source, flags=re.MULTILINE)
directives = re.findall(r"\blisten\s+([^;{}]+);", source)
if not directives or len(directives) != len(re.findall(r"\blisten\b", source)):
    raise SystemExit("ERROR: Nginx listen port is missing or unclear")
ports = set()
for directive in directives:
    endpoint = directive.split()[0]
    match = re.fullmatch(r"(?:([0-9]+)|(?:127\.0\.0\.1|0\.0\.0\.0|\[::\]):([0-9]+))", endpoint)
    if not match:
        raise SystemExit("ERROR: unsupported or implicit Nginx listen port")
    port = int(match.group(1) or match.group(2))
    if not 1 <= port <= 65535:
        raise SystemExit("ERROR: Nginx listen port is out of range")
    ports.add(port)
if len(ports) != 1:
    raise SystemExit("ERROR: Nginx site has multiple different listen ports")
print(ports.pop())
PORT_PY
)"

ARCHIVE="$(readlink -f "$1")"
[[ -f "$ARCHIVE" ]] || { echo "ERROR: backup archive missing" >&2; exit 3; }
[[ -f "$ARCHIVE.sha256" ]] || { echo "ERROR: checksum sidecar missing: $ARCHIVE.sha256" >&2; exit 3; }
(cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE.sha256")")

WORK="$(mktemp -d "${TMPDIR:-/tmp}/threadsnap-restore.XXXXXX")"
restore_started=false
restore_verified=false
old_data_moved=false
new_data_installed=false
old_env_saved=false
env_write_started=false
backups_moved=false
was_active=false
nginx_was_active=false
cleanup() {
  local status=$?
  trap - EXIT
  if [[ "$restore_started" == true && "$restore_verified" != true ]]; then
    # 任何中途错误都走同一回退，不只处理健康检查失败；不递归删除恢复点入口。
    set +e
    systemctl stop threadsnap-nginx.service
    systemctl stop threadsnap.service
    local recovered=true
    if [[ "$backups_moved" == true ]]; then
      if mv -- "$DATA_DIR/backups" "$ROLLBACK_DATA/backups"; then
        backups_moved=false
      else
        recovered=false
        echo "ERROR: retained backups remain at $DATA_DIR/backups; no data directory deleted" >&2
      fi
    fi
    if [[ "$recovered" == true && "$new_data_installed" == true && ( -e "$DATA_DIR" || -L "$DATA_DIR" ) ]]; then
      mv -T -- "$DATA_DIR" "$FAILED_DATA" || recovered=false
    fi
    if [[ "$recovered" == true && "$old_data_moved" == true ]]; then
      mv -T -- "$ROLLBACK_DATA" "$DATA_DIR" || recovered=false
    fi
    if [[ "$old_env_saved" == true ]]; then
      mv -T -- "$ROLLBACK_ENV" /etc/threadsnap/threadsnap.env || recovered=false
    elif [[ "$env_write_started" == true ]]; then
      rm -f -- /etc/threadsnap/threadsnap.env || recovered=false
    fi
    if [[ "$recovered" == true ]]; then
      [[ "$was_active" == true ]] && systemctl start threadsnap.service
      [[ "$nginx_was_active" == true ]] && systemctl start threadsnap-nginx.service
      echo "ERROR: restore failed; original data/config and backups entry preserved" >&2
    else
      echo "ERROR: rollback incomplete; preserve $DATA_DIR, $ROLLBACK_DATA and $FAILED_DATA for recovery" >&2
    fi
  fi
  rm -rf -- "$WORK"
  exit "$status"
}
trap cleanup EXIT

python3 - "$ARCHIVE" "$WORK" <<'PY'
import hashlib
import os
import sys
import tarfile
from pathlib import Path, PurePosixPath, PureWindowsPath


def safe_name(value):
    """归档使用POSIX相对名，同时拒绝Windows转义和控制字符。"""
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or PureWindowsPath(value).drive
        or ".." in path.parts
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise SystemExit(f"ERROR: unsafe backup path: {value!r}")
    return path


archive, destination = sys.argv[1:]
destination = Path(destination)
if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
    raise SystemExit("ERROR: backup staging directory must be empty and not a symlink")
with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    declared = {}
    for member in members:
        path = safe_name(member.name)
        if path in declared:
            raise SystemExit(f"ERROR: duplicate backup member: {member.name}")
        if (
            member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.LNKTYPE)
            or member.issparse()
        ):
            raise SystemExit(f"ERROR: unsafe backup member: {member.name}")
        if path.parts[1:3] == ("data", "backups"):
            raise SystemExit("ERROR: data/backups is a host-owned recovery entry, not backup payload")
        declared[path] = member
    roots = {path.parts[0] for path in declared}
    if len(roots) != 1:
        raise SystemExit("ERROR: backup must contain one top-level directory")
    root = next(iter(roots))
    links = {}
    for path, member in declared.items():
        for parent in path.parents:
            if parent in declared and not declared[parent].isdir():
                raise SystemExit(f"ERROR: non-directory backup parent: {parent}")
        if member.islnk():
            target = safe_name(member.linkname)
            # 只接受同根内显式登记的普通文件，允许前向引用但不解析链接链。
            target_member = declared.get(target)
            if (
                target.parts[0] != root
                or target_member is None
                or target_member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
            ):
                raise SystemExit(f"ERROR: unsafe hardlink target: {member.linkname}")
            links[path] = target
    sums_name = PurePosixPath(root, "SHA256SUMS")
    if sums_name not in declared or not declared[sums_name].isfile():
        raise SystemExit("ERROR: backup SHA256SUMS must be a declared regular file")

    # 不使用extractall：先写普通文件，再建立已验证的硬链接；永不创建软链或设备。
    digests = {}
    for path, member in declared.items():
        output = destination.joinpath(*path.parts)
        if member.isdir():
            output.mkdir(parents=True, exist_ok=True)
        elif member.isfile():
            output.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with bundle.extractfile(member) as source, output.open("xb") as target:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(block)
                    digest.update(block)
            digests[path] = digest.hexdigest()
            os.chmod(output, member.mode & 0o777)
            os.utime(output, (member.mtime, member.mtime))
    for path, source in links.items():
        output = destination.joinpath(*path.parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        os.link(destination.joinpath(*source.parts), output)
        digests[path] = digests[source]

    # 内层校验覆盖普通文件与每个硬链接路径；拒绝校验清单自身越界或漏项。
    checked = set()
    sums_file = destination.joinpath(*sums_name.parts)
    for line in sums_file.read_text(encoding="utf-8").splitlines():
        digest, separator, raw_path = line.partition("  ")
        relative = safe_name(raw_path)
        name = PurePosixPath(root, relative)
        if (
            separator != "  "
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or name == sums_name
            or name in checked
            or digests.get(name) != digest
        ):
            raise SystemExit(f"ERROR: backup checksum invalid: {raw_path!r}")
        checked.add(name)
    if checked != set(digests) - {sums_name}:
        raise SystemExit("ERROR: backup checksum list does not cover every file")
    for path, member in sorted(declared.items(), key=lambda item: len(item[0].parts), reverse=True):
        if member.isdir():
            output = destination.joinpath(*path.parts)
            os.chmod(output, member.mode & 0o777)
            os.utime(output, (member.mtime, member.mtime))
print(next(iter(roots)))
PY
BACKUP_ROOT="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d -print -quit)"
[[ -f "$BACKUP_ROOT/SHA256SUMS" && -d "$BACKUP_ROOT/data" && -f "$BACKUP_ROOT/config/threadsnap.env" ]] || {
  echo "ERROR: backup structure invalid" >&2
  exit 3
}
# 内层每条路径的SHA-256已由安全解包器校验，外层归档校验仍在解包前执行。

RESTORED_ENV="$BACKUP_ROOT/config/threadsnap.env"
DATA_DIR="$(sed -n 's/^THREADSNAP_DATA_DIR=//p' "$RESTORED_ENV" | tail -n 1)"
[[ "$DATA_DIR" == /* && "$DATA_DIR" != / ]] || { echo "ERROR: invalid restored data directory" >&2; exit 3; }

STAMP="$(date +%Y%m%d-%H%M%S)"
ROLLBACK_DATA="${DATA_DIR}.before-restore-$STAMP"
FAILED_DATA="${DATA_DIR}.failed-restore-$STAMP"
ROLLBACK_ENV="/etc/threadsnap/threadsnap.env.before-restore-$STAMP"
for reserved in "$ROLLBACK_DATA" "$FAILED_DATA" "$ROLLBACK_ENV"; do
  [[ ! -e "$reserved" && ! -L "$reserved" ]] || { echo "ERROR: recovery path already exists: $reserved" >&2; exit 3; }
done
if systemctl is-active --quiet threadsnap.service; then
  was_active=true
fi
if systemctl is-active --quiet threadsnap-nginx.service; then
  nginx_was_active=true
fi
systemctl stop threadsnap-nginx.service
systemctl stop threadsnap.service
restore_started=true

if [[ -e "$DATA_DIR" || -L "$DATA_DIR" ]]; then
  mv "$DATA_DIR" "$ROLLBACK_DATA"
  old_data_moved=true
fi
if [[ -e /etc/threadsnap/threadsnap.env || -L /etc/threadsnap/threadsnap.env ]]; then
  cp -a /etc/threadsnap/threadsnap.env "$ROLLBACK_ENV"
  old_env_saved=true
fi

mkdir -p "$(dirname "$DATA_DIR")"
# 跨分区mv失败可能已留下部分目标；先登记意图，回退时将其隔离，禁止把旧目录嵌进去。
new_data_installed=true
mv -T -- "$BACKUP_ROOT/data" "$DATA_DIR"
env_write_started=true
mv -T -- "$RESTORED_ENV" /etc/threadsnap/threadsnap.env
chown -R threadsnap:threadsnap "$DATA_DIR"
chown root:threadsnap /etc/threadsnap/threadsnap.env
chmod 0700 "$DATA_DIR"
chmod 0640 /etc/threadsnap/threadsnap.env
# 权限整理完成后再移回本机恢复点入口，避免递归chown历史备份或跨分区入口。
if [[ "$old_data_moved" == true && ( -e "$ROLLBACK_DATA/backups" || -L "$ROLLBACK_DATA/backups" ) ]]; then
  mv -- "$ROLLBACK_DATA/backups" "$DATA_DIR/backups"
  backups_moved=true
fi

systemctl start threadsnap.service
for _ in $(seq 1 50); do
  curl --fail --silent http://127.0.0.1:8000/health >/dev/null && break
  sleep 0.2
done
curl --fail --silent http://127.0.0.1:8000/health >/dev/null
systemctl start threadsnap-nginx.service
if ! bash /opt/threadsnap/current/deploy/verify.sh --quick --listen-port "$LISTEN_PORT" --server-name _; then
  echo "ERROR: restored backup failed health verification" >&2
  exit 4
fi

restore_verified=true
trap - EXIT
rm -rf -- "$WORK"
echo "restored_backup=$ARCHIVE"
echo "previous_data=$ROLLBACK_DATA"
echo "previous_environment=$ROLLBACK_ENV"
