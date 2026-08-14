#!/usr/bin/env python
"""taxonomy.yaml → app/src/data/taxonomy.json (빌드 시점 변환).

앱이 YAML 파서를 번들에 넣지 않도록 빌드 전에 JSON으로 바꾼다.
`npm run build`/`npm run dev`의 prebuild 훅에서 자동 실행된다.

앱에 필요한 것만 담는다. 배치 전용 필드(search_queries, blocklist_tiers,
channel_allowlist 등)는 앱에서 쓰지 않으므로 제외한다 — 번들 크기 문제이기도 하지만,
그보다 검색어·화이트리스트가 클라이언트로 나가야 할 이유가 없다.

생성물은 커밋하지 않는다 (app/src/data/taxonomy.json은 .gitignore).
taxonomy.yaml이 단일 소스이고, 사본이 저장소에 두 개 있으면 반드시 어긋난다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "taxonomy.yaml"
DEFAULT_OUT = ROOT / "app" / "src" / "data" / "taxonomy.json"

# 세분류에서 앱이 쓰는 필드. search_queries는 배치 전용이라 뺀다.
SUB_FIELDS = ("id", "label", "tone", "keywords", "empathy_messages", "closing_messages")


def build_payload(raw: dict) -> dict:
    meta = raw["meta"]
    ui = raw["ui"]
    safety = raw["safety"]
    crisis = safety["crisis_response"]

    categories = []
    for category in raw["categories"]:
        subs = []
        for sub in category["subcategories"]:
            missing = [f for f in ("id", "label", "keywords") if not sub.get(f)]
            if missing:
                raise SystemExit(f"{sub.get('id', '?')}: 필수 필드 누락 — {missing}")
            subs.append({f: sub.get(f) for f in SUB_FIELDS})
        categories.append(
            {"id": category["id"], "label": category["label"], "subcategories": subs}
        )

    return {
        "version": meta["version"],
        "ui": {
            "placeholders": ui["placeholders"]["items"],
            "entry_greetings": {
                k: v
                for k, v in ui["entry_greetings"].items()
                if k in ("morning", "afternoon", "evening", "night")
            },
            # 로딩 지연은 여기 한 곳에서만 읽는다. 코드에 상수로 복제하지 않는다.
            "loading": {
                "min_duration_ms": ui["loading"]["min_duration_ms"],
                "messages": ui["loading"]["messages"],
            },
            "empty_input": ui["empty_input"]["items"],
            "no_match": ui["no_match"]["message"],
            "select_mode": {
                k: v for k, v in ui["select_mode"].items() if k != "rule"
            },
            "revisit": {
                k: v
                for k, v in ui["revisit"].items()
                if k in ("first_visit", "same_day", "recent", "long_absence")
            },
        },
        "safety": {
            "crisis_keywords": safety["crisis_keywords"],
            "message": _clean(crisis["message"]),
            "resources": crisis["resources"],
            "closing_messages": crisis["content_policy"]["closing_messages"],
            "framing_note": _clean(crisis["content_policy"]["framing"]),
        },
        "categories": categories,
    }


def _clean(text: str) -> str:
    """YAML 블록 스칼라의 줄바꿈을 화면용 한 문단으로 붙인다."""
    return " ".join(str(text).split())


def main(argv: list[str]) -> int:
    # npm이 띄운 셸은 Windows 기본 인코딩(cp949)이라 한글·기호 출력이 깨진다.
    # 다른 배치 스크립트와 같은 방식으로 UTF-8에 고정한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    src = Path(argv[1]) if len(argv) > 1 else DEFAULT_SRC
    out = Path(argv[2]) if len(argv) > 2 else DEFAULT_OUT

    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    payload = build_payload(raw)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    subs = sum(len(c["subcategories"]) for c in payload["categories"])
    keywords = sum(
        len(s["keywords"]) for c in payload["categories"] for s in c["subcategories"]
    )
    size = out.stat().st_size
    print(
        f"{out.relative_to(ROOT)} 생성 — 대분류 {len(payload['categories'])}개 / "
        f"세분류 {subs}개 / 키워드 {keywords}개 / "
        f"위기 키워드 {len(payload['safety']['crisis_keywords'])}개 / {size:,} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
