from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict
from urllib.request import Request, urlopen

from flask import Flask, abort, redirect, render_template, request, url_for

WindowsSupport = Optional[bool | Literal["wsl2"]]


class ClawRecord(TypedDict, total=False):
    id: str
    中文名称: str
    是否开源: Optional[bool]
    供应商: Optional[str]
    评分: Optional[float]
    部署形态: str
    概览: str
    优点: list[str]
    缺点: list[str]
    部署便捷性: str
    扩展性: str
    安全性: str
    生态成熟度: str
    可玩性: str
    维护成本: str
    大模型支持范围: list[str]
    logo: str
    编程语言: Optional[str]
    git仓库地址: Optional[str]
    是否支持本地部署: Optional[bool]
    是否支持多模态大模型: Optional[bool]
    是否支持windows原生部署: WindowsSupport
    是否支持原生web界面: Optional[bool]
    web界面说明: Optional[str]
    github_stars: Optional[int]
    github_forks: Optional[int]
    github_open_issues: Optional[int]
    github_license: Optional[str]
    github_created_at: Optional[str]
    github_last_pushed_at: Optional[str]
    github_release_count: Optional[int]
    github_release频率: Optional[str]
    许可源码说明: Optional[str]


FilterValue = Literal["all", "true", "false", "unknown", "wsl2"]


@dataclass(frozen=True)
class FilterSpec:
    key: str
    label: str
    query_param: str


FILTERS: list[FilterSpec] = [
    FilterSpec(key="是否开源", label="是否开源", query_param="oss"),
    FilterSpec(key="是否支持本地部署", label="是否支持本地部署", query_param="local"),
    FilterSpec(key="是否支持多模态大模型", label="是否支持多模态大模型", query_param="multimodal"),
    FilterSpec(key="是否支持windows原生部署", label="是否支持Windows原生部署", query_param="windows"),
    FilterSpec(key="是否支持原生web界面", label="Web 界面", query_param="webui"),
]


def parse_filter_value(raw: str | None) -> FilterValue:
    if raw in (None, "", "all"):
        return "all"
    raw = raw.lower()
    if raw in ("true", "false", "unknown", "wsl2"):
        return raw  # type: ignore[return-value]
    return "all"


def match_tri_state(value: Any, filter_value: FilterValue) -> bool:
    if filter_value == "all":
        return True
    if filter_value == "unknown":
        return value is None
    if filter_value == "wsl2":
        return isinstance(value, str) and value.lower() == "wsl2"
    if filter_value == "true":
        return value is True
    if filter_value == "false":
        return value is False
    return True


def format_tri_state(value: Any) -> str:
    if isinstance(value, str) and value.lower() == "wsl2":
        return "WSL2"
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "未知"


def tri_state_class(value: Any) -> str:
    if isinstance(value, str) and value.lower() == "wsl2":
        return "wsl2"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def format_number(n: int | float | None) -> str:
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


class VendorResolver:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._fetched_at: float | None = None

    def _should_refresh(self) -> bool:
        if self._fetched_at is None:
            return True
        return (time.time() - self._fetched_at) > 3600

    def _fetch(self) -> None:
        req = Request(
            "https://bestclaw.io/zh",
            headers={"User-Agent": "claws-web"},
        )
        with urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        pattern = re.compile(
            r'(?s)<p class="text-foreground truncate text-sm font-semibold">(?P<name>[^<]+)</p>.*?'
            r'<p class="text-muted-foreground truncate text-xs">(?P<vendor>[^<]+)</p>.*?'
            r'<a href="/agents/(?P<slug>[^"]+)"[^>]*>\s*Read Review\s*</a>'
        )
        cache: dict[str, str] = {}
        for match in pattern.finditer(html):
            slug = match.group("slug").strip()
            vendor = unescape(match.group("vendor")).strip()
            if not slug or not vendor:
                continue
            if vendor.startswith("<") and vendor.endswith(">"):
                continue
            if slug not in cache:
                cache[slug] = vendor
        self._cache = cache
        self._fetched_at = time.time()

    def get_map(self) -> dict[str, str]:
        if self._should_refresh():
            try:
                self._fetch()
            except Exception:
                self._cache = self._cache or {}
                self._fetched_at = self._fetched_at or time.time()
        return dict(self._cache)


class ScoreResolver:
    def __init__(self) -> None:
        self._cache: dict[str, float] = {}
        self._fetched_at: float | None = None

    def _should_refresh(self) -> bool:
        if self._fetched_at is None:
            return True
        return (time.time() - self._fetched_at) > 3600

    def _fetch(self) -> None:
        def fetch_html(url: str) -> str:
            req = Request(url, headers={"User-Agent": "claws-web"})
            with urlopen(req, timeout=6) as resp:
                return resp.read().decode("utf-8", errors="ignore")

        def parse_scores(html: str) -> dict[str, float]:
            cache: dict[str, float] = {}
            for m in re.finditer(r'href="/(?:zh/)?agents/(?P<slug>[^"]+)"', html):
                slug = m.group("slug").strip()
                if not slug or slug in cache:
                    continue
                frag = html[m.start() : min(len(html), m.start() + 3200)]
                m2 = re.search(r'tabular-nums">(?P<score>[0-9.]+)</span>', frag)
                if not m2:
                    continue
                try:
                    cache[slug] = float(m2.group("score"))
                except ValueError:
                    continue
            return cache

        cache: dict[str, float] = {}
        try:
            rankings_html = fetch_html("https://bestclaw.io/zh/rankings")
            cache.update(parse_scores(rankings_html))
        except Exception:
            pass

        try:
            home_html = fetch_html("https://bestclaw.io/zh")
            cache.update(parse_scores(home_html))
        except Exception:
            pass
        self._cache = cache
        self._fetched_at = time.time()

    def get_map(self) -> dict[str, float]:
        if self._should_refresh() or not self._cache:
            try:
                self._fetch()
            except Exception:
                self._cache = self._cache or {}
                self._fetched_at = self._fetched_at or time.time()
        return dict(self._cache)



KNOWN_VENDORS: dict[str, str] = {
    "arkclaw": "火山引擎",
    "copaw": "阿里通义",
    "duclaw": "百度",
    "lobsterai": "网易有道",
    "maxclaw": "MiniMax",
    "openclaw-launch": "OpenClaw Launch",
    "openclaw": "OpenClaw",
    "nanoclaw": "NanoClaw",
    "zeroclaw": "ZeroClaw",
    "picoclaw": "PicoClaw",
}


def vendor_for(item: ClawRecord, vendor_map: dict[str, str]) -> str | None:
    if item.get("供应商"):
        return item.get("供应商")
    claw_id = item.get("id")
    if claw_id and claw_id in vendor_map:
        v = vendor_map[claw_id]
        if v.startswith("<") and v.endswith(">"):
            return None
        return v
    repo = item.get("git仓库地址")
    if repo and isinstance(repo, str):
        m = re.match(r"^https://github\.com/([^/]+)/([^/]+)$", repo.strip("/"))
        if m:
            return m.group(1)
    if claw_id and claw_id in KNOWN_VENDORS:
        return KNOWN_VENDORS[claw_id]
    return None


def score_for(item: ClawRecord, score_map: dict[str, float]) -> float | None:
    if item.get("评分") is not None:
        try:
            return float(item.get("评分"))  # type: ignore[arg-type]
        except Exception:
            return None
    claw_id = item.get("id")
    if claw_id and claw_id in score_map:
        return score_map[claw_id]
    return None


class DataStore:
    def __init__(self, json_path: Path) -> None:
        self._json_path = json_path
        self._mtime: float | None = None
        self._items: list[ClawRecord] = []
        self._by_id: dict[str, ClawRecord] = {}

    def _load(self) -> None:
        if not self._json_path.exists():
            self._items = []
            self._by_id = {}
            self._mtime = None
            return

        mtime = self._json_path.stat().st_mtime
        if self._mtime is not None and mtime == self._mtime:
            return

        content = self._json_path.read_text(encoding="utf-8-sig")
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("claws-info.json must be a JSON array")

        items: list[ClawRecord] = []
        by_id: dict[str, ClawRecord] = {}
        for raw in data:
            if not isinstance(raw, dict):
                continue
            if "id" not in raw or not isinstance(raw["id"], str):
                continue
            record = raw  # type: ignore[assignment]
            items.append(record)
            by_id[record["id"]] = record

        self._items = items
        self._by_id = by_id
        self._mtime = mtime

    def all(self) -> list[ClawRecord]:
        self._load()
        return list(self._items)

    def get(self, claw_id: str) -> ClawRecord | None:
        self._load()
        return self._by_id.get(claw_id)

    def update(self, claw_id: str, updates: dict[str, Any]) -> ClawRecord | None:
        self._load()
        item = self._by_id.get(claw_id)
        if item is None:
            return None

        for key, value in updates.items():
            if key == "id":
                continue
            item[key] = value  # type: ignore[literal-required]

        tmp_path = self._json_path.with_suffix(self._json_path.suffix + ".tmp")
        payload = json.dumps(self._items, ensure_ascii=False, indent=4)
        tmp_path.write_text(payload, encoding="utf-8-sig")
        os.replace(str(tmp_path), str(self._json_path))
        self._mtime = self._json_path.stat().st_mtime
        return item


def parse_optional_bool(raw: str | None) -> Optional[bool]:
    if raw is None:
        return None
    raw = raw.strip().lower()
    if raw == "true":
        return True
    if raw == "false":
        return False
    return None


def parse_windows_support(raw: str | None) -> WindowsSupport:
    if raw is None:
        return None
    raw = raw.strip().lower()
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw == "wsl2":
        return "wsl2"
    return None


def parse_string_list(raw: str | None) -> list[str]:
    if raw is None:
        return []
    lines = [line.strip() for line in raw.splitlines()]
    return [line for line in lines if line]


def create_app() -> Flask:
    app = Flask(__name__)
    data_path = Path(__file__).resolve().parent / "claws-info.json"
    store = DataStore(data_path)
    vendor_resolver = VendorResolver()
    score_resolver = ScoreResolver()

    @app.get("/")
    def index() -> str:
        # 默认筛选：是否开源 = true
        raw_oss = request.args.get("oss")
        if raw_oss is None or raw_oss == "":
            raw_oss = "true"

        filters: dict[str, FilterValue] = {}
        for spec in FILTERS:
            if spec.query_param == "oss":
                filters[spec.query_param] = parse_filter_value(raw_oss)
            else:
                filters[spec.query_param] = parse_filter_value(request.args.get(spec.query_param))

        items = store.all()
        filtered: list[ClawRecord] = []
        for item in items:
            ok = True
            for spec in FILTERS:
                fv = filters[spec.query_param]
                ok = ok and match_tri_state(item.get(spec.key), fv)
            if ok:
                filtered.append(item)

        vendor_map = vendor_resolver.get_map()
        score_map = score_resolver.get_map()

        # 排序：开源项目按 stars 降序排在前面，闭源/未知排在后面
        def sort_key(x: ClawRecord) -> tuple[int, int]:
            is_oss = 0 if x.get("是否开源") is True else 1  # 开源=0 排前面
            stars = x.get("github_stars") or 0
            return (is_oss, -stars)  # stars 降序

        filtered.sort(key=sort_key)

        return render_template(
            "list.html",
            items=filtered,
            filters=filters,
            filter_specs=FILTERS,
            format_tri_state=format_tri_state,
            tri_state_class=tri_state_class,
            format_number=format_number,
            vendor_map=vendor_map,
            vendor_for=vendor_for,
            score_map=score_map,
            score_for=score_for,
            total=len(items),
            count=len(filtered),
        )

    @app.get("/claw/<claw_id>")
    def detail(claw_id: str) -> str:
        item = store.get(claw_id)
        if item is None:
            abort(404)
        vendor_map = vendor_resolver.get_map()
        return render_template(
            "detail.html",
            item=item,
            format_tri_state=format_tri_state,
            tri_state_class=tri_state_class,
            format_number=format_number,
            vendor_map=vendor_map,
            vendor_for=vendor_for,
        )

    @app.get("/claw/<claw_id>/edit")
    def edit(claw_id: str) -> str:
        item = store.get(claw_id)
        if item is None:
            abort(404)
        vendor_map = vendor_resolver.get_map()
        return render_template(
            "edit.html",
            item=item,
            format_tri_state=format_tri_state,
            tri_state_class=tri_state_class,
            vendor_map=vendor_map,
            vendor_for=vendor_for,
        )

    @app.post("/claw/<claw_id>/edit")
    def save_edit(claw_id: str) -> Any:
        current = store.get(claw_id)
        if current is None:
            abort(404)

        updates: dict[str, Any] = {}

        def set_optional_str(key: str, form_key: str) -> None:
            raw = request.form.get(form_key)
            if raw is None:
                return
            value = raw.strip()
            updates[key] = value if value else None

        def set_str(key: str, form_key: str) -> None:
            raw = request.form.get(form_key)
            if raw is None:
                return
            updates[key] = raw.strip()

        def set_opt_bool(key: str, form_key: str) -> None:
            raw = request.form.get(form_key)
            updates[key] = parse_optional_bool(raw)

        def set_list(key: str, form_key: str) -> None:
            updates[key] = parse_string_list(request.form.get(form_key))

        set_str("中文名称", "中文名称")
        set_optional_str("供应商", "供应商")
        set_optional_str("logo", "logo")
        set_optional_str("编程语言", "编程语言")
        set_optional_str("git仓库地址", "git仓库地址")
        set_optional_str("web界面说明", "web界面说明")
        set_optional_str("github_license", "github_license")
        set_optional_str("github_created_at", "github_created_at")
        set_optional_str("github_last_pushed_at", "github_last_pushed_at")
        set_optional_str("github_release频率", "github_release频率")
        set_optional_str("许可源码说明", "许可源码说明")

        # GitHub numeric fields
        for num_key in ("github_stars", "github_forks", "github_open_issues", "github_release_count"):
            raw_val = request.form.get(num_key)
            if raw_val is not None:
                raw_val = raw_val.strip()
                updates[num_key] = int(raw_val) if raw_val else None

        set_opt_bool("是否开源", "是否开源")
        set_opt_bool("是否支持本地部署", "是否支持本地部署")
        set_opt_bool("是否支持多模态大模型", "是否支持多模态大模型")
        set_opt_bool("是否支持原生web界面", "是否支持原生web界面")
        updates["是否支持windows原生部署"] = parse_windows_support(
            request.form.get("是否支持windows原生部署")
        )

        set_str("部署形态", "部署形态")
        set_str("概览", "概览")
        set_list("优点", "优点")
        set_list("缺点", "缺点")
        set_str("部署便捷性", "部署便捷性")
        set_str("扩展性", "扩展性")
        set_str("安全性", "安全性")
        set_str("生态成熟度", "生态成熟度")
        set_str("可玩性", "可玩性")
        set_str("维护成本", "维护成本")
        set_list("大模型支持范围", "大模型支持范围")
        set_list("通信渠道支持范围", "通信渠道支持范围")

        updated = store.update(claw_id, updates)
        if updated is None:
            abort(404)

        return redirect(url_for("detail", claw_id=claw_id), code=303)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/favicon.ico")
    def favicon() -> Any:
        return redirect("https://bestclaw.io/favicon.ico", code=302)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
