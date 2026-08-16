#!/usr/bin/env python
"""채널 차단 목록 검증 — 네트워크 호출 없음.

    python scripts/blocklist_test.py

이 필터가 존재하는 이유가 "제목으로는 못 잡는다"이므로, 그 전제 자체를 고정한다.
실제로 걸러낸 제목들을 넣어 두고 blocklist 용어에 걸리지 않는지 확인한다 —
만약 어느 날 걸리게 된다면 채널 차단 대신 용어로 막는 편이 낫다는 뜻이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.channel_blocklist import load_channel_blocklist
from lib.filters import apply_filters
from lib.normalize import matched_terms
from lib.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[1]
EXIT_OK, EXIT_FAIL = 0, 1

# 실제로 걸러낸 제목들 (2026-08-15 배치 sadness.sorrow)
BLOCKED_TITLES = [
    "동창회에 남편을 데려갔는데,선생님은 그를 보자마자 물컵을 떨어뜨리며 벌벌 떨었습니다",
    "내가 서울대에 합격하자, 새아버지는 나를 위해 갈비찜을 한 냄비 만들어 주셨다",
    "딸의 부탁으로 미국에 가 손주를 돌보고 있었습니다 그런데 아이가 목욕하던 중",
    "신혼 이틀 만에 여자 절친과 출국한 남편… 하지만 돌아온 집은 이미 달라져 있었습니다",
]

BLOCKED_ID = "UCEfLzRHtNtSaXTUc45XV5ww"  # Emotional Road


def _video(video_id: str, title: str, channel_id: str) -> dict:
    return {
        "id": video_id,
        "status": {"privacyStatus": "public", "uploadStatus": "processed"},
        "snippet": {
            "title": title,
            "channelTitle": "테스트 채널",
            "channelId": channel_id,
            "publishedAt": "2026-08-15T00:00:00Z",
        },
        "contentDetails": {"duration": "PT10M"},
        "statistics": {"commentCount": "1"},
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    failures: list[str] = []
    tax = load_taxonomy(ROOT / "taxonomy.yaml")
    blocklist = load_channel_blocklist(ROOT / "channel_blocklist.yaml")
    terms = [t for group in tax.blocklist_for("sadness").values() for t in group]

    print("차단 목록")
    print("-" * 76)
    for channel in blocklist.channels:
        print(f"   {channel.channel_name:<20} {channel.channel_id}  ({channel.added_by})")
    if not blocklist.channels:
        print("X  비어 있다")
        failures.append("빈 목록")

    # 이 필터의 존재 이유 — 제목으로는 잡히지 않는다
    print("\n제목 blocklist로는 잡히지 않는다 (이 필터가 필요한 이유)")
    print("-" * 76)
    for title in BLOCKED_TITLES:
        hits = matched_terms(title, terms)
        ok = not hits
        print(f"{'   ' if ok else 'X  '}{title[:46]}  {hits or ''}")
        if not ok:
            # 걸린다면 채널 차단보다 용어 쪽이 낫다는 신호다
            failures.append(f"제목으로 잡힘: {title[:20]}")

    # 채널로는 잡힌다
    print("\n채널로는 잡힌다")
    print("-" * 76)
    items = [_video(f"v{i}", t, BLOCKED_ID) for i, t in enumerate(BLOCKED_TITLES)]
    items.append(_video("ok1", "잔잔한 피아노 연주 3시간", "UCsomethingelse00000000"))

    kept, stats = apply_filters(
        items, tax.blocklist_for("sadness"), min_seconds=180,
        blocked_channel_ids=blocklist.ids,
    )
    print(f"   후보 {stats.considered} → 확보 {stats.kept}")
    print(f"   차단채널 제거 {stats.dropped_blocked_channel}건  {dict(stats.blocked_channels)}")
    if stats.dropped_blocked_channel != len(BLOCKED_TITLES):
        print("X  차단 건수가 맞지 않는다")
        failures.append("차단 건수")
    if len(kept) != 1 or kept[0].video_id != "ok1":
        print("X  차단되지 않아야 할 영상이 걸렸다")
        failures.append("무관한 영상 차단")

    # 목록을 비우면 그대로 통과해야 한다 (필터가 실제로 이 목록을 본다는 확인)
    kept2, stats2 = apply_filters(
        items, tax.blocklist_for("sadness"), min_seconds=180, blocked_channel_ids=None
    )
    print(f"\n   차단 목록 없이: 확보 {stats2.kept}건 (목록이 실제로 쓰인다면 {stats.kept}보다 커야 한다)")
    if stats2.kept <= stats.kept:
        print("X  차단 목록이 결과에 영향을 주지 않는다")
        failures.append("목록 미적용")

    print("\n" + "=" * 76)
    if failures:
        print(f"실패 {len(failures)}건: {', '.join(failures)}")
        return EXIT_FAIL
    print("전부 통과")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
