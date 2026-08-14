"""YouTube Data API v3 클라이언트.

실제 클라이언트(YouTubeClient)와 드라이런 클라이언트(DryRunClient)가 같은 인터페이스를
제공한다. 배치 로직은 둘을 구분하지 않으므로, API 키 없이도 필터·가드레일·쿼터 계산이
실제와 동일한 경로로 검증된다.

모든 호출은 QuotaBudget에 비용을 먼저 청구한다. 드라이런도 마찬가지로 청구해서
"실제로 돌렸다면 얼마나 썼을지"를 그대로 보여준다.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Sequence
from typing import Any, Protocol

import requests

from lib.quota import QuotaBudget, QuotaExceeded

logger = logging.getLogger(__name__)

API_ROOT = "https://www.googleapis.com/youtube/v3"
BATCH_SIZE = 50  # videos.list / channels.list가 한 번에 받는 id 개수
SEARCH_MAX_RESULTS = 50  # search.list는 개수와 무관하게 100 units — 최대로 받는다
REQUEST_TIMEOUT = 30
TRANSIENT_RETRY = 1  # 일시적 오류에 한해 1회만. 무한 재시도는 쿼터를 이중 소모한다.


class YouTubeError(RuntimeError):
    """API 호출 실패 (쿼터 외 사유)."""


class Client(Protocol):
    """배치가 의존하는 최소 인터페이스."""

    def search(self, query: str) -> list[str]: ...
    def search_items(self, query: str) -> list[dict[str, Any]]: ...
    def videos(self, video_ids: Sequence[str]) -> list[dict[str, Any]]: ...
    def channels(self, channel_ids: Sequence[str]) -> list[dict[str, Any]]: ...
    def playlist_items(self, playlist_id: str, limit: int) -> list[str]: ...


def chunked(items: Sequence[str], size: int = BATCH_SIZE) -> list[Sequence[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class YouTubeClient:
    """실제 API 클라이언트."""

    def __init__(self, api_key: str, budget: QuotaBudget) -> None:
        if not api_key:
            raise YouTubeError(
                "API 키가 없다. --dry-run으로 실행하거나 YOUTUBE_API_KEY를 설정한다."
            )
        self._key = api_key
        self._budget = budget
        self._session = requests.Session()

    # --- 검색 ---------------------------------------------------------------
    def search_items(self, query: str) -> list[dict[str, Any]]:
        """검색 결과 원본 항목을 관련도 순서 그대로 반환한다.

        safeSearch=strict는 API가 제공하는 무료 1차 방어선이라 항상 켠다.
        길이 필터(videoDuration)는 쓰지 않는다 — 이유는 filters.py 상단 참조.

        snippet에 channelId/channelTitle이 들어 있어, 채널 집계를 하려는 호출자는
        추가 쿼터 없이 여기서 바로 얻을 수 있다 (suggest_channels.py).
        """
        self._budget.charge("search.list")
        payload = self._get(
            "search",
            {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": SEARCH_MAX_RESULTS,
                "regionCode": "KR",
                "relevanceLanguage": "ko",
                "safeSearch": "strict",
                "order": "relevance",
            },
        )
        return [
            item for item in payload.get("items", []) if item.get("id", {}).get("videoId")
        ]

    def search(self, query: str) -> list[str]:
        """검색 결과 videoId만 반환한다."""
        return [item["id"]["videoId"] for item in self.search_items(query)]

    # --- 검증 ---------------------------------------------------------------
    def videos(self, video_ids: Sequence[str]) -> list[dict[str, Any]]:
        """영상 상세. 응답에서 빠진 id는 삭제된 영상이다 (1 unit / 50건)."""
        items: list[dict[str, Any]] = []
        for batch in chunked(list(video_ids)):
            self._budget.charge("videos.list")
            payload = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,status,statistics",
                    "id": ",".join(batch),
                    "maxResults": BATCH_SIZE,
                },
            )
            items.extend(payload.get("items", []))
        return items

    # --- 채널 ---------------------------------------------------------------
    def channels(self, channel_ids: Sequence[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for batch in chunked(list(channel_ids)):
            self._budget.charge("channels.list")
            payload = self._get(
                "channels",
                {
                    "part": "snippet,contentDetails,statistics",
                    "id": ",".join(batch),
                    "maxResults": BATCH_SIZE,
                },
            )
            items.extend(payload.get("items", []))
        return items

    def playlist_items(self, playlist_id: str, limit: int) -> list[str]:
        """uploads 재생목록에서 최신 videoId를 읽는다 (채널당 1 unit)."""
        self._budget.charge("playlistItems.list")
        payload = self._get(
            "playlistItems",
            {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": min(limit, BATCH_SIZE),
            },
        )
        return [
            item["contentDetails"]["videoId"]
            for item in payload.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]

    # --- HTTP ---------------------------------------------------------------
    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "key": self._key}
        url = f"{API_ROOT}/{endpoint}"
        last_error: Exception | None = None

        for attempt in range(TRANSIENT_RETRY + 1):
            try:
                response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("%s 네트워크 오류 (%d회차): %s", endpoint, attempt + 1, exc)
                time.sleep(2)
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code == 403 and _is_quota_error(response):
                raise QuotaExceeded(
                    f"API가 쿼터 초과를 반환했다 ({endpoint}). "
                    "재시도하지 않고 중단한다 — 재실행은 다음 리셋 이후에."
                )
            if 500 <= response.status_code < 600:
                last_error = YouTubeError(f"{endpoint} HTTP {response.status_code}")
                logger.warning("%s 서버 오류 %s (%d회차)", endpoint, response.status_code, attempt + 1)
                time.sleep(2)
                continue

            raise YouTubeError(
                f"{endpoint} HTTP {response.status_code}: {response.text[:300]}"
            )

        raise YouTubeError(f"{endpoint} 호출 실패: {last_error}")


def _is_quota_error(response: requests.Response) -> bool:
    try:
        errors = response.json().get("error", {}).get("errors", [])
    except ValueError:
        return False
    return any(e.get("reason") in {"quotaExceeded", "dailyLimitExceeded"} for e in errors)


# =============================================================================
# 드라이런
# =============================================================================


class DryRunClient:
    """API를 호출하지 않고 결정적인 가짜 응답을 만든다.

    필터가 실제로 동작하는지 눈으로 확인할 수 있도록, 걸러져야 마땅한 후보를
    의도적으로 섞는다. 비율은 videoId 해시로 결정되므로 실행할 때마다 같다.

        버킷  0-19 (20%) : 3분 미만 (Shorts)
        버킷 20-29 (10%) : 제목에 blocklist 용어 포함
        버킷 30-33  (4%) : 삭제됨 — videos.list 응답에서 아예 빠진다
        버킷 34-37  (4%) : 비공개
        버킷 38-41  (4%) : 국내 차단
        나머지     (58%) : 정상

    또한 8건마다 공용 시드를 써서 서로 다른 쿼리가 같은 videoId를 반환하게 만든다
    (중복 제거 로직 검증용).
    """

    def __init__(self, budget: QuotaBudget, blocklist_pool: Sequence[str]) -> None:
        self._budget = budget
        self._pool = list(blocklist_pool) or ["자살"]

    def search_items(self, query: str) -> list[dict[str, Any]]:
        self._budget.charge("search.list")
        items = []
        for i in range(SEARCH_MAX_RESULTS):
            vid = self._video_id(query, i)
            items.append(
                {
                    "id": {"videoId": vid},
                    "snippet": {
                        "title": f"[dry-run] 잔잔한 영상 {vid[:5]}",
                        "channelId": _fake_channel_id(vid),
                        "channelTitle": _fake_channel_title(vid),
                    },
                }
            )
        return items

    def search(self, query: str) -> list[str]:
        return [item["id"]["videoId"] for item in self.search_items(query)]

    def videos(self, video_ids: Sequence[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for batch in chunked(list(video_ids)):
            self._budget.charge("videos.list")
            for vid in batch:
                item = self._video_item(vid)
                if item is not None:  # None = 삭제된 영상 (응답에서 누락)
                    items.append(item)
        return items

    def channels(self, channel_ids: Sequence[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for batch in chunked(list(channel_ids)):
            self._budget.charge("channels.list")
            for cid in batch:
                # 해시 끝자리가 0이면 삭제된 채널로 취급해 헬스체크 경보를 검증한다.
                if _bucket(cid) % 10 == 0:
                    continue
                items.append(
                    {
                        "id": cid,
                        "snippet": {
                            # id에서 구분되는 부분을 쓴다 (끝자리는 패딩이라 전부 같다)
                            "title": f"[dry-run] 채널 {cid[2:10]}",
                            "publishedAt": "2020-01-01T00:00:00Z",
                        },
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": f"UU{cid[2:]}"}
                        },
                        "statistics": {
                            "subscriberCount": str(1000 * (_bucket(cid) + 1)),
                            "videoCount": str(50 + _bucket(cid)),
                        },
                    }
                )
        return items

    def playlist_items(self, playlist_id: str, limit: int) -> list[str]:
        self._budget.charge("playlistItems.list")
        return [self._video_id(playlist_id, i) for i in range(limit)]

    # --- 생성기 -------------------------------------------------------------
    @staticmethod
    def _video_id(seed: str, index: int) -> str:
        # 8건마다 공용 시드 → 서로 다른 쿼리에서 같은 id가 나온다 (중복 제거 검증)
        material = f"shared:{index % 7}" if index % 8 == 0 else f"{seed}:{index}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:11]

    def _video_item(self, video_id: str) -> dict[str, Any] | None:
        bucket = _bucket(video_id)
        if 30 <= bucket <= 33:
            return None  # 삭제됨

        title = f"[dry-run] 잔잔한 영상 {video_id[:5]}"
        privacy = "public"
        duration = "PT12M34S"
        region: dict[str, Any] = {}

        if bucket < 20:
            duration = f"PT{30 + bucket * 7}S"  # 30~163초
        elif bucket < 30:
            # 버킷(20~29)을 그대로 인덱스로 쓰면 용어 풀의 앞쪽(tier_a)에 영원히 닿지 않는다.
            # 서로소인 7을 곱해 풀 전체에 흩어지게 한다 — 세 계층이 모두 검증된다.
            term = self._pool[(bucket * 7) % len(self._pool)]
            title = f"[dry-run] {term} 이야기 {video_id[:5]}"
        elif bucket < 38:
            privacy = "private"
        elif bucket < 42:
            region = {"regionRestriction": {"blocked": ["KR"]}}

        statistics: dict[str, str] = {"viewCount": str(1000 + bucket)}
        if bucket % 3 != 0:  # 3의 배수는 댓글 사용 중지로 둔다
            statistics["commentCount"] = str(bucket)

        return {
            "id": video_id,
            "snippet": {
                "title": title,
                "description": "드라이런 생성 데이터입니다.",
                "channelTitle": _fake_channel_title(video_id),
                "channelId": _fake_channel_id(video_id),
                "publishedAt": "2026-08-01T00:00:00Z",
                "tags": ["dryrun"],
            },
            "contentDetails": {"duration": duration, **region},
            "status": {"privacyStatus": privacy, "uploadStatus": "processed"},
            "statistics": statistics,
        }


def _bucket(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16) % 100


# 드라이런에서 영상이 소수의 채널에 몰리도록 채널 풀을 좁게 잡는다.
# 채널마다 영상이 1건씩이면 채널 집계(suggest_channels.py)를 검증할 수 없다.
DRY_RUN_CHANNEL_POOL = 12


def _fake_channel_id(video_id: str) -> str:
    """videoId → 소수의 고정 채널 중 하나. search와 videos가 같은 값을 내야 한다."""
    index = int(hashlib.sha256(video_id.encode("utf-8")).hexdigest(), 16) % DRY_RUN_CHANNEL_POOL
    return f"UCDRYRUN{index:02d}" + "0" * 14


def _fake_channel_title(video_id: str) -> str:
    index = int(hashlib.sha256(video_id.encode("utf-8")).hexdigest(), 16) % DRY_RUN_CHANNEL_POOL
    return f"[dry-run] 채널 {index:02d}"
