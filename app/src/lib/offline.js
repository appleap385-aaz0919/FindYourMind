/**
 * 연결 상태 감지 + 로딩 지연.
 *
 * 오프라인은 "오류"가 아니다. 화면에 경고를 띄우지 않는다.
 * 다만 사용자가 곧 시도할 동작(영상 열기)이 불가능하므로 그것만 미리 알린다
 * (PLAN.md: "침묵이 배려인 지점과 불친절이 되는 지점을 구분한다").
 */

import { useEffect, useState } from "react";

export function useOnline() {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine !== false,
  );

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  return online;
}

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (event) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

/**
 * 최소 노출 시간을 지킨다.
 *
 * taxonomy.yaml ui.loading:
 *   분류는 실제로 수십 ms에 끝나지만 최소 노출 시간을 둔다.
 *   즉답은 기계적으로 느껴지고, 짧은 뜸이 "듣고 있다"는 감각을 만든다.
 *   분류가 min_duration_ms보다 오래 걸리면 실제 소요 시간을 사용한다(추가 지연 없음).
 *
 * prefers-reduced-motion이어도 이 지연은 그대로 유지한다.
 * 끄는 것은 애니메이션이지 뜸이 아니다 — 뜸이 만드는 감각은 움직임이 아니라 시간에서 온다.
 */
export async function withMinDuration(work, minMs) {
  const started = Date.now();
  const result = await work();
  const remaining = minMs - (Date.now() - started);
  if (remaining > 0) {
    await new Promise((resolve) => setTimeout(resolve, remaining));
  }
  return result;
}

/**
 * 유튜브 열기. 앱/브라우저 열기에 실패하면 웹 URL로 다시 시도한다
 * (PLAN.md "유튜브 앱/브라우저 열기 실패 → 웹 URL로 재시도").
 */
export function openVideo(url) {
  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (!opened) window.location.href = url;
}
