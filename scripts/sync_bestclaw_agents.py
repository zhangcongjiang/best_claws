from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "claws-web"})
    with urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_meta(html: str, name: str) -> Optional[str]:
    m = re.search(rf'<meta name="{re.escape(name)}" content="([^"]*)"', html)
    return m.group(1).strip() if m else None


def get_dt_dd(html: str, label: str) -> Optional[str]:
    pat = rf"(?s)<dt[^>]*>\s*{re.escape(label)}\s*</dt>\s*<dd[^>]*>(.*?)</dd>"
    m = re.search(pat, html)
    return strip_html(m.group(1)) if m else None


def get_list(html: str, h3_text: str) -> list[str]:
    pat = rf"(?s)<h3[^>]*>.*?{re.escape(h3_text)}\s*</h3>\s*<ul[^>]*>(.*?)</ul>"
    m = re.search(pat, html)
    if not m:
        return []
    ul = m.group(1)
    items = []
    for sm in re.finditer(r"(?s)<span>(.*?)</span>", ul):
        v = strip_html(sm.group(1))
        if v:
            items.append(v)
    return items


def find_github_repo(html: str) -> Optional[str]:
    def looks_invalid(url: str) -> bool:
        u = url.lower()
        if "your-app-name" in u:
            return True
        if "u003corg" in u or "<org>" in u:
            return True
        return False

    def repo_exists(owner: str, repo: str) -> bool:
        try:
            api = f"https://api.github.com/repos/{owner}/{repo}"
            req = Request(api, headers={"User-Agent": "claws-web"})
            with urlopen(req, timeout=8) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    for m in re.finditer(r"https://github\.com/([^\s\"'<)]+)", html):
        url = m.group(0).rstrip("/")
        if looks_invalid(url):
            continue
        path = url.replace("https://github.com/", "")
        path = path.removesuffix(".git")
        parts = path.split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            if looks_invalid(owner) or looks_invalid(repo):
                continue
            if repo_exists(owner, repo):
                return f"https://github.com/{owner}/{repo}"
    return None


def parse_scores_from_rankings(html: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in re.finditer(r'href="/(?:zh/)?agents/(?P<slug>[^"]+)"', html):
        slug = m.group("slug").strip()
        if not slug or slug in out:
            continue
        frag = html[m.start() : min(len(html), m.start() + 3200)]
        m2 = re.search(r'tabular-nums">(?P<score>[0-9.]+)</span>', frag)
        if not m2:
            continue
        try:
            out[slug] = float(m2.group("score"))
        except ValueError:
            continue
    return out


def parse_agents_listing(html: str) -> dict[str, dict[str, str]]:
    pattern = re.compile(
        r'(?s)<h3[^>]*>(?P<name>[^<]+)</h3>.*?'
        r'<p class="text-muted-foreground[^"]*"[^>]*>(?P<tagline>.*?)</p>.*?'
        r'href="/zh/agents/(?P<slug>[^"]+)"'
    )
    out: dict[str, dict[str, str]] = {}
    for match in pattern.finditer(html):
        slug = match.group("slug").strip()
        name = strip_html(match.group("name"))
        tagline = strip_html(match.group("tagline"))
        if slug and slug not in out:
            out[slug] = {"name": name, "tagline": tagline}
    return out


def infer_open_source(license_text: Optional[str], tags_text: str, repo: Optional[str]) -> Optional[bool]:
    hay = " ".join([license_text or "", tags_text]).lower()
    if repo:
        return True
    if any(x in hay for x in ["apache", "mit", "gpl", "bsd", "mpl", "开源"]):
        return True
    if any(x in hay for x in ["闭源", "云端托管", "平台托管", "saas", "零部署"]):
        return False
    return None


def infer_local_deploy(deployment: str) -> Optional[bool]:
    s = deployment.lower()
    if any(x in s for x in ["云端", "saas", "零部署", "托管"]):
        return False
    if any(x in s for x in ["自托管", "本地", "离线", "docker", "kubernetes"]):
        return True
    return None


def infer_windows_support(overview: str, deployment: str) -> Optional[bool | str]:
    s = f"{overview} {deployment}".lower()
    if "wsl" in s:
        return "wsl2"
    if any(x in s for x in ["windows 原生", "windows 原生部署", "windows 桌面", "windows 客户端"]):
        return True
    if any(x in s for x in ["不支持 windows", "windows 不支持"]):
        return False
    if any(x in s for x in ["云端", "saas", "零部署"]):
        return False
    return None


@dataclass(frozen=True)
class Record:
    id: str
    中文名称: str
    概览: str
    部署形态: str
    许可源码说明: Optional[str]
    优点: list[str]
    缺点: list[str]
    logo: str
    git仓库地址: Optional[str]
    评分: Optional[float]


def build_record(slug: str, score_map: dict[str, float]) -> dict[str, Any]:
    url = f"https://bestclaw.io/zh/agents/{slug}"
    html = fetch(url)

    title = None
    m = re.search(r"(?s)<h1[^>]*>(.*?)</h1>", html)
    if m:
        title = strip_html(m.group(1))

    if not title:
        og = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        if og:
            title = og.group(1).strip()

    name = title or slug
    overview = get_meta(html, "description") or "—"
    deployment = get_dt_dd(html, "部署形态") or "—"
    license_text = get_dt_dd(html, "许可 / 源码") or get_dt_dd(html, "许可/源码")
    pros = get_list(html, "优点")
    cons = get_list(html, "局限")

    logo = f"https://bestclaw.io/images/claw-platforms/{slug}.png"
    m_logo = re.search(r'<link rel="preload" as="image" href="(/images/claw-platforms/[^"]+)"', html)
    if m_logo:
        logo = "https://bestclaw.io" + m_logo.group(1)

    repo = find_github_repo(html)
    is_open = infer_open_source(license_text, overview, repo)
    local_deploy = infer_local_deploy(deployment)
    windows_support = infer_windows_support(overview, deployment)

    record: dict[str, Any] = {
        "id": slug,
        "中文名称": name,
        "是否开源": is_open,
        "部署形态": deployment,
        "概览": overview,
        "优点": pros,
        "缺点": cons,
        "部署便捷性": "—",
        "扩展性": "—",
        "安全性": "—",
        "生态成熟度": "—",
        "可玩性": "—",
        "维护成本": "—",
        "大模型支持范围": [],
        "logo": logo,
        "是否支持本地部署": local_deploy,
        "是否支持多模态大模型": None,
        "是否支持windows原生部署": windows_support,
        "编程语言": None,
        "git仓库地址": repo,
        "评分": score_map.get(slug),
        "许可源码说明": license_text,
    }
    return record


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    json_path = root / "claws-info.json"
    raw = json_path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("claws-info.json must be array")

    existing = {x.get("id") for x in data if isinstance(x, dict)}

    agents_html = fetch("https://bestclaw.io/zh/agents")
    listing = parse_agents_listing(agents_html)
    slugs = sorted(set(re.findall(r'href="/zh/agents/([^"]+)"', agents_html)))

    rankings_html = fetch("https://bestclaw.io/zh/rankings")
    score_map = parse_scores_from_rankings(rankings_html)

    added = 0
    updated = 0
    for slug in slugs:
        if slug in existing:
            info = listing.get(slug)
            if not info:
                continue
            for item in data:
                if not isinstance(item, dict) or item.get("id") != slug:
                    continue
                if info.get("name"):
                    item["中文名称"] = info["name"]
                    updated += 1
                if (not item.get("概览") or item.get("概览") == "—") and info.get("tagline"):
                    item["概览"] = info["tagline"]
                    updated += 1
                if slug in score_map and item.get("评分") is None:
                    item["评分"] = score_map[slug]
                    updated += 1
            continue

        try:
            rec = build_record(slug, score_map)
        except Exception:
            continue

        info = listing.get(slug)
        if info:
            if info.get("name"):
                rec["中文名称"] = info["name"]
            if info.get("tagline") and (not rec.get("概览") or rec.get("概览") == "—"):
                rec["概览"] = info["tagline"]

        data.append(rec)
        added += 1

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8-sig")
    sys.stdout.write(f"added={added}, updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
