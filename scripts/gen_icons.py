#!/usr/bin/env python
"""앱 아이콘 생성 — SVG 원본과 PNG를 같은 파라미터에서 함께 만든다.

    python scripts/gen_icons.py

왜 이렇게 만드나
    SVG를 래스터라이즈하려면 cairosvg·sharp·rsvg 같은 네이티브 의존성이 필요한데,
    아이콘 하나 때문에 빌드 체인에 그걸 들이는 건 과하다.
    대신 도형이 원형 그라데이션 두 개뿐이라 정의를 파라미터로 한 번만 적고,
    SVG와 PNG를 각각 그 정의에서 생성한다. 사본이 아니라 같은 출처에서 나오므로
    둘이 어긋날 수 없다. SVG는 디자인 원본이자 나중에 손볼 지점이다.

디자인 (앱 톤과 맞춘다 — src/theme.js)
    배경  자정 청록-자주. 위쪽 plum(#221A28) → 아래 ink(#141E24) → inkDeep 가장자리.
          앱 배경의 radial-gradient(120% 90% at 50% 0%)를 옮긴 것이다.
    중앙  호흡하는 빛. jade(#7FB3A3) 가우시안 글로우. 글자·도형 없음.

밝기가 왜 중요한가
    이전 아이콘은 88%가 거의 검정(평균 밝기 29.8/255)이라 홈 화면에서
    빈 회색 사각형처럼 보였다. 파일이 깨진 게 아니라 디자인이 안 보였던 것이다.
    작은 크기에서 읽히려면 글로우가 충분히 넓고 밝아야 한다.
    --report로 밝기 분포를 확인할 수 있다.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "app" / "public" / "icons"

# --- 색 (app/src/theme.js와 같은 값) -----------------------------------------
PLUM = (0x22, 0x1A, 0x28)
INK = (0x14, 0x1E, 0x24)
INK_DEEP = (0x0B, 0x12, 0x16)
JADE = (0x7F, 0xB3, 0xA3)
MIST = (0xE9, 0xEE, 0xEA)

# --- 글로우 형태 -------------------------------------------------------------
# 빛은 두 겹으로 만든다. 한 겹짜리 가우시안은 핵이 없어 뿌연 얼룩으로 읽히고,
# 홈 화면 크기(약 40px)로 줄면 형태가 사라진다.
#   halo — 넓고 옅게 퍼지는 바깥 빛
#   core — 좁고 밝은 중심. 이게 있어야 "빛"으로 읽힌다.
# sigma는 반지름(size/2) 대비 비율, peak는 혼합 강도(1.0이면 그 색 그대로).
HALO_SIGMA, HALO_PEAK = 0.36, 0.78
CORE_SIGMA, CORE_PEAK = 0.18, 1.00

# 중심은 순수 jade보다 한 톤 밝게 — 색이 아니라 빛으로 보이게 하는 장치다.
CORE_TINT = 0.35  # mist를 섞는 비율

# 마스커블은 안드로이드가 바깥을 잘라낸다(안전 영역 = 중앙 80%).
# 두 겹 모두 안쪽으로 모아 잘려도 형태가 유지되게 한다.
MASKABLE_SCALE = 0.66

SIZES = {
    "icon-180.png": (180, 1.0),  # iOS apple-touch-icon
    "icon-192.png": (192, 1.0),
    "icon-512.png": (512, 1.0),
    "icon-maskable-512.png": (512, MASKABLE_SCALE),
}


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def background(nx: float, ny: float) -> tuple[int, int, int]:
    """앱 배경과 같은 방향의 그라데이션 — 위쪽이 자주, 아래·가장자리가 어두운 청록.

    nx, ny는 -0.5~0.5로 정규화한 좌표.
    """
    # 위 중앙(0, -0.5)에서의 거리로 섞는다. 앱의 `at 50% 0%`와 같은 기준점.
    d = math.hypot(nx * 1.15, ny + 0.5) / 1.15
    if d < 0.45:
        return _mix(PLUM, INK, d / 0.45)
    return _mix(INK, INK_DEEP, (d - 0.45) / 0.75)


def render(size: int, scale: float = 1.0) -> Image.Image:
    """scale은 글로우 전체를 안쪽으로 모으는 배율(마스커블용)."""
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    core_color = _mix(JADE, MIST, CORE_TINT)
    halo_denom = 2 * (HALO_SIGMA * scale) ** 2
    core_denom = 2 * (CORE_SIGMA * scale) ** 2

    for y in range(size):
        ny = (y + 0.5) / size - 0.5
        for x in range(size):
            nx = (x + 0.5) / size - 0.5
            d_sq = (nx * nx + ny * ny) / 0.25  # 반지름 기준 정규화 거리의 제곱

            color = background(nx, ny)
            color = _mix(color, JADE, HALO_PEAK * math.exp(-d_sq / halo_denom))
            color = _mix(color, core_color, CORE_PEAK * math.exp(-d_sq / core_denom))
            pixels[x, y] = color
    return image


def svg_source() -> str:
    """디자인 원본. 래스터와 같은 색·같은 구성이며, 편집은 여기서 시작한다.

    가우시안을 SVG의 radialGradient stop으로 근사한다 — 뷰어마다 보간이 조금씩
    다르므로 픽셀 단위로 같지는 않다. 배포에 나가는 것은 PNG이고,
    이 파일은 디자인 원본·확대용이다.
    """
    def ramp(sigma: float, peak: float, color: str) -> str:
        rows = []
        for offset in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0):
            alpha = peak * math.exp(-(offset**2) / (2 * sigma**2))
            rows.append(
                f'      <stop offset="{offset * 100:.0f}%" '
                f'stop-color="{color}" stop-opacity="{alpha:.3f}" />'
            )
        return chr(10).join(rows)

    core_hex = "#%02X%02X%02X" % _mix(JADE, MIST, CORE_TINT)
    halo_stops = ramp(HALO_SIGMA, HALO_PEAK, "#7FB3A3")
    core_stops = ramp(CORE_SIGMA, CORE_PEAK, core_hex)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <!-- FindYourMind 앱 아이콘 — scripts/gen_icons.py가 PNG와 함께 생성한다.
       색은 app/src/theme.js와 같다. 글자·도형 없이 배경 + 호흡하는 빛뿐이다. -->
  <defs>
    <radialGradient id="bg" cx="50%" cy="0%" r="115%">
      <stop offset="0%" stop-color="#221A28" />
      <stop offset="45%" stop-color="#141E24" />
      <stop offset="100%" stop-color="#0B1216" />
    </radialGradient>
    <radialGradient id="halo" cx="50%" cy="50%" r="50%">
{halo_stops}
    </radialGradient>
    <radialGradient id="core" cx="50%" cy="50%" r="50%">
{core_stops}
    </radialGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg)" />
  <rect width="512" height="512" fill="url(#halo)" />
  <rect width="512" height="512" fill="url(#core)" />
</svg>
"""


def report(image: Image.Image, name: str) -> None:
    pixels = list(image.getdata())
    lum = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels]
    dark = sum(1 for value in lum if value < 60) * 100 / len(lum)
    print(
        f"    평균 밝기 {sum(lum) / len(lum):5.1f}  "
        f"최대 {max(lum):5.1f}  거의 검정 {dark:4.1f}%"
    )


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    show_report = "--report" in argv

    svg_path = OUT_DIR / "icon.svg"
    svg_path.write_text(svg_source(), encoding="utf-8")
    print(f"  {svg_path.relative_to(ROOT)}  ({svg_path.stat().st_size:,} bytes) — 디자인 원본")

    for name, (size, scale) in SIZES.items():
        image = render(size, scale)
        path = OUT_DIR / name
        image.save(path, "PNG", optimize=True)
        print(f"  {path.relative_to(ROOT)}  {size}x{size}  ({path.stat().st_size:,} bytes)")
        if show_report:
            report(image, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
