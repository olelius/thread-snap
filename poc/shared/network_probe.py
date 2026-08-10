"""对联通样本执行 DNS、TCP、TLS 和普通 HTTP 基线探测。"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def utc_now() -> str:
    """返回带时区的 UTC 时间。"""

    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    urls = [line.strip() for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not urls:
        raise ValueError("联通样本为空")
    parsed = urlsplit(urls[0])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("联通样本必须是 HTTP(S) URL")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    result: dict = {
        "schema_version": "1.0",
        "started_at": utc_now(),
        "target": {"scheme": parsed.scheme, "host": host, "port": port},
        "dns": {"ok": False, "addresses": [], "error_category": None},
        "tcp": {"ok": False, "duration_ms": None, "error_category": None},
        "tls": {"required": parsed.scheme == "https", "ok": parsed.scheme != "https", "error_category": None},
        "http": {"ok": False, "status": None, "duration_ms": None, "content_type": None, "body_bytes_sampled": 0, "error_category": None},
    }

    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        result["dns"].update(ok=bool(addresses), addresses=addresses)
    except OSError as exc:
        result["dns"]["error_category"] = type(exc).__name__

    tcp_started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=args.timeout):
            result["tcp"]["ok"] = True
    except OSError as exc:
        result["tcp"]["error_category"] = type(exc).__name__
    result["tcp"]["duration_ms"] = round((time.perf_counter() - tcp_started) * 1000)

    if parsed.scheme == "https" and result["tcp"]["ok"]:
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=args.timeout) as raw:
                with context.wrap_socket(raw, server_hostname=host) as secure:
                    certificate = secure.getpeercert()
                    result["tls"].update(
                        ok=True,
                        version=secure.version(),
                        cipher=secure.cipher()[0] if secure.cipher() else None,
                        certificate_not_after=certificate.get("notAfter"),
                    )
        except (OSError, ssl.SSLError) as exc:
            result["tls"]["error_category"] = type(exc).__name__

    http_started = time.perf_counter()
    request = urllib.request.Request(urls[0], headers={"User-Agent": "ThreadSnap-Connectivity/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = response.read(262_144)
            result["http"].update(
                ok=True,
                status=response.status,
                content_type=response.headers.get("Content-Type"),
                body_bytes_sampled=len(body),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read(262_144)
        result["http"].update(
            ok=True,
            status=exc.code,
            content_type=exc.headers.get("Content-Type"),
            body_bytes_sampled=len(body),
            error_category="http_status",
        )
    except (OSError, urllib.error.URLError) as exc:
        result["http"]["error_category"] = type(exc).__name__
    result["http"]["duration_ms"] = round((time.perf_counter() - http_started) * 1000)
    result["ended_at"] = utc_now()
    result["transport_ready"] = bool(
        result["dns"]["ok"] and result["tcp"]["ok"] and result["tls"]["ok"] and result["http"]["ok"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"transport_ready": result["transport_ready"], "http_status": result["http"]["status"]}))
    return 0 if result["transport_ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
