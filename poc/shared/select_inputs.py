"""从固定 URL 输入池生成跨平台可复现的 PoC 清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ALGORITHM = "sha256(seed + NUL + utf8_url), ascending digest then URL, take first N"


def sha256_bytes(data: bytes) -> str:
    """返回字节串的小写 SHA-256。"""

    return hashlib.sha256(data).hexdigest()


def read_pool(path: Path) -> list[str]:
    """读取并验证帖子 URL 输入池，拒绝空值、重复项和非 HTTPS 链接。"""

    urls = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()]
    urls = [url for url in urls if url]
    if not urls:
        raise ValueError("输入池为空")
    if len(set(urls)) != len(urls):
        raise ValueError("输入池包含重复 URL")
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"输入池包含非 HTTPS URL: {url!r}")
    return urls


def select_urls(urls: list[str], seed: str, count: int) -> list[str]:
    """按稳定 SHA-256 排名选择 URL，不依赖语言运行时的伪随机算法。"""

    if not seed:
        raise ValueError("随机种子不能为空")
    if count < 1 or count > len(urls):
        raise ValueError(f"抽样数量必须在 1..{len(urls)} 之间")
    seed_bytes = seed.encode("utf-8") + b"\0"
    ranked = sorted(urls, key=lambda url: (hashlib.sha256(seed_bytes + url.encode("utf-8")).digest(), url))
    return ranked[:count]


def write_lf(path: Path, lines: list[str]) -> str:
    """以 UTF-8/LF 写入清单并返回文件哈希。"""

    payload = ("\n".join(lines) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()

    pool_bytes = args.pool.read_bytes()
    pool = read_pool(args.pool)
    selected = select_urls(pool, args.seed, args.count)
    output_hash = write_lf(args.output, selected)
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": ALGORITHM,
        "seed": args.seed,
        "pool_count": len(pool),
        "pool_sha256": sha256_bytes(pool_bytes),
        "selected_count": len(selected),
        "selected_sha256": output_hash,
        "output_name": args.output.name,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
