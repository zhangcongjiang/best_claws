from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def is_bad_repo(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    if "your-app-name" in u:
        return True
    if "u003corg" in u or "<org>" in u:
        return True
    if u.strip() == "https://github.com/\\u003corg\\u003e/nanoclaw.git":
        return True
    return False


def infer_open_source_from_deploy(deploy: Any) -> bool | None:
    if not isinstance(deploy, str):
        return None
    s = deploy.lower()
    if any(x in s for x in ["saas", "云端", "零部署", "托管", "平台侧"]):
        return False
    return None


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "claws-info.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("claws-info.json must be array")

    changed = 0
    for item in data:
        if not isinstance(item, dict):
            continue

        if is_bad_repo(item.get("git仓库地址")):
            item["git仓库地址"] = None
            item["编程语言"] = None
            changed += 1

        vendor = item.get("供应商")
        if isinstance(vendor, str) and ("u003corg" in vendor.lower() or vendor == "<org>"):
            item["供应商"] = None
            changed += 1

        if item.get("是否开源") is True and item.get("git仓库地址") is None:
            inferred = infer_open_source_from_deploy(item.get("部署形态"))
            item["是否开源"] = inferred
            changed += 1

    path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8-sig")
    print(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

