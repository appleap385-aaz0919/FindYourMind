# FindYourMind

마음 상태를 자연어로 적으면 감정을 분류해, 지금 곁에 두면 좋을 유튜브 영상을 조용히 건네는 PWA입니다.

**운영 서버도, 로그인도, 운영 중 AI API 호출도 없습니다.** 감정 분류는 브라우저 안에서 끝나고, 영상 목록은 매일 한 번 GitHub Actions가 만들어 정적 파일로 배포합니다. 사용자가 무엇을 입력했는지는 디바이스 밖으로 나가지 않습니다.

## 어떻게 동작하나

```
[GitHub Actions — 매일 1회 cron]
   └─ YouTube Data API v3 검색 (세분류별 검색어 세트)
   └─ 필터·검증 → videos.json 생성
   └─ gh-pages 배포
            │
            ▼  앱은 version.json으로 버전만 비교하고, 바뀐 날만 내려받는다
[PWA (React)]
   ├─ 감정 입력 — 자연어 텍스트 또는 대분류 → 세분류 선택
   ├─ 온디바이스 분류 — 키워드 사전 단독 (커버리지 98.6%), 못 알아들으면 선택 UI
   │                    ※ TF.js 모델은 검토 후 보류 (PLAN.md Phase 2)
   ├─ IndexedDB — videos.json 캐시
   └─ 클릭 → youtube.com에서 열기
```

**앱은 YouTube API를 직접 호출하지 않습니다.** API 키는 GitHub Actions Secrets(`YOUTUBE_API_KEY`)에만 존재하며, 저장소와 배포 산출물 어디에도 들어가지 않습니다.

## 감정 체계

대분류 9개 × 세분류 2~3개 = **세분류 24개**. 전부 [`taxonomy.yaml`](taxonomy.yaml) 한 곳에서 정의합니다 — 검색어, 공감 문구, 마무리 문구, blocklist 계층까지 포함입니다.

| 대분류 | 세분류 |
|---|---|
| 불안 | 초조 · 걱정 · 긴장 |
| 분노 | 짜증 · 억울함 · 격분 |
| 답답함 | 막막함 · 진전 없음 · 억눌림 |
| 우울 | 슬픔 · 외로움 · 상실감 |
| 지침/무기력 | 번아웃 · 피로 · 의욕 없음 |
| 기쁨 | 뿌듯함 · 즐거움 · 감사 |
| 설렘 | 기대 · 두근거림 |
| 평온 | 여유 · 안정 |
| 심심함 | 지루함 · 새로운 자극 |

### 위기 카테고리는 다르게 다룹니다

자·타해나 죽음이 감지되는 입력에는 **상담 안내가 화면 최상단에 항상 먼저** 나오고, 영상은 그 아래에 조용히 놓입니다. "추천"이라는 말을 쓰지 않고, 자동재생도 하지 않습니다.

이 카테고리의 영상 풀에는 3중 가드레일이 걸려 있습니다.

1. **검색어 자체를 제한** — `forbidden_query_patterns`를 위반하는 질의는 API를 부르기 전에 배치를 실패시킵니다.
2. **채널 화이트리스트** — 사람이 승인한 채널만 씁니다 ([`channel_allowlist.yaml`](channel_allowlist.yaml)). 채널을 라운드로빈으로 순회해 한 채널이 3건을 넘지 않게 하고, 순회 시작점은 매일 회전시켜 특정 채널이 구조적으로 배제되지 않게 합니다.
3. **blocklist 3계층 전부 적용** — 가장 좁고 조용한 풀입니다.

확보량이 12건에 못 미치면 **필터를 완화하지 않고 직전 결과를 유지합니다.** 안전 기준을 낮춰서 개수를 채우는 선택은 하지 않습니다.

## 저장소 구조

| 경로 | 역할 |
|---|---|
| [`taxonomy.yaml`](taxonomy.yaml) | 감정 체계·검색어·문구·blocklist·위기 정책의 **단일 소스**. 여기 없는 정책은 코드 어디에도 없어야 합니다. |
| [`channel_allowlist.yaml`](channel_allowlist.yaml) | 위기 카테고리 채널 화이트리스트. 변경 시 이유를 `note`와 커밋 메시지에 남깁니다. |
| `scripts/build_videos.py` | 일일 배치. `videos.json`·`version.json`·`build_report.json` 생성 |
| `scripts/check_channels.py` | 화이트리스트 채널 정기 점검 (삭제·휴면·성향 변화 감지) |
| `scripts/suggest_channels.py` | 화이트리스트 후보 수집 — **일회성 도구**, 배치에 넣지 않습니다 |
| `scripts/lib/` | 공용 모듈 — `taxonomy` · `allowlist` · `filters` · `normalize` · `quota` · `youtube` · `alerts` |
| `.github/workflows/build.yml` | 매일 UTC 08:30 배치 (YouTube 쿼터 리셋 직후) |
| `emotion-prototype.jsx` | Phase 0.5 UI 프로토타입. 분류 로직은 Phase 3에 그대로 이식합니다 |

`dist/`는 배치 산출물이라 커밋하지 않습니다 — gh-pages로 배포됩니다.

## 실행

```bash
pip install -r scripts/requirements.txt

# API 키 없이 전 과정 검증 (쿼터 0)
python scripts/build_videos.py --dry-run

# 실제 API를 소량으로 먼저 확인 — 산출물은 videos.partial.json, 배포 대상 아님
export YOUTUBE_API_KEY="..."
python scripts/build_videos.py --only anxiety.restless,safety.crisis

# 전체 배치 (약 7,900 units)
python scripts/build_videos.py --previous dist/videos.json
```

종료 코드: `0` 성공 · `1` 일반 오류(1회 재시도) · `2` 쿼터 중단(재시도 안 함).

**실패해도 부분 결과를 쓰지 않습니다.** 모든 처리가 끝난 뒤 `tmp → os.replace`로 한 번에 교체하므로, 빌드가 깨지면 직전 `videos.json`이 그대로 유지됩니다.

## 쿼터

일일 한도 10,000 units, 하드캡 9,800. 실행 전에 예상 소모량을 산정해 넘으면 **API를 한 번도 부르지 않고** 중단합니다.

| 항목 | units |
|---|---:|
| 일반 24 세분류 × 쿼리 3개(4개 중 로테이션) | 7,200 |
| 위기 전용 검색 6개 | 600 |
| 화이트리스트 조회 | 11 |
| 영상 검증 (`videos.list`) | 약 100 |
| **합계** | **약 7,900** |

## 문서

- **[PLAN.md](PLAN.md)** — 개발 계획서. 목표·제약·아키텍처·Phase 0~5 로드맵과 각 결정의 근거
- **[OPERATIONS.md](OPERATIONS.md)** — 운영 문서. 정기 체크리스트, 자동 Issue 대응, 화이트리스트·채널 차단 절차, 배포 구조, 쿼터 관리, 장애 대응
- **[HANDOFF.md](HANDOFF.md)** — 작업 인수인계. 지금 무엇이 걸려 있는지, 어떤 판단으로 그렇게 됐는지. **이어서 작업한다면 여기부터**

운영을 인수인계받으셨다면 **OPERATIONS.md의 "최소 안전선"부터** 읽으시면 됩니다. 자동화가 대신해줄 수 없는 것 — 썸네일과 실제 영상 내용 판단, 채널 성향의 미묘한 변화, 새로운 위험 표현 — 이 무엇인지 적혀 있습니다.

## 기여

`channel_allowlist.yaml`을 바꿀 때는 **누가 왜 바꿨는지가 남아야 합니다.**
채널마다 `note`에 검토 근거를, 제외한 채널은 파일 주석에 사유를, 커밋 메시지에는
채널명과 검토 근거를 적습니다. 담당자가 2명 이상이 되면 PR 필수로 전환합니다
(PLAN.md Phase 4.5 "변경 추적").
