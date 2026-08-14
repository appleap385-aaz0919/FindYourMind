import { useEffect, useState } from "react";
import { T, SERIF } from "../theme.js";

/**
 * 오프라인 위로 경로 — 4-7-8 호흡 가이드.
 *
 * ⚠ 노출 조건: 오프라인일 때만. 온라인에서는 어떤 카테고리에서도 노출하지 않는다.
 *   영상 추천이 이 서비스의 본 기능이고, 대체재가 상시 노출되면 본 기능이 흐려진다.
 *   (PLAN.md Phase 3 "[확정] 오프라인 전용")
 *
 * 문구 규칙: "영상 대신"이라는 표현을 쓰지 않는다. 아쉬움을 강조하지 않고
 *   그 자체로 완결된 제안처럼 보이게 한다.
 */

const CYCLE = [
  { key: "in", label: "들이쉬기", seconds: 4 },
  { key: "hold", label: "멈춤", seconds: 7 },
  { key: "out", label: "내쉬기", seconds: 8 },
];

const EASE_NOTES = [
  "어깨를 한 번 내려놓아요",
  "시선을 조금 멀리 두어요",
  "턱에 힘이 들어가 있진 않은지 살펴봐요",
];

export function BreathingGuide({ reducedMotion }) {
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(0);
  const [remaining, setRemaining] = useState(CYCLE[0].seconds);

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => {
      setRemaining((left) => {
        if (left > 1) return left - 1;
        setStep((current) => {
          const next = (current + 1) % CYCLE.length;
          setRemaining(CYCLE[next].seconds);
          return next;
        });
        return CYCLE[(step + 1) % CYCLE.length].seconds;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [running, step]);

  const phase = CYCLE[step];

  return (
    <div
      style={{
        marginTop: 30,
        padding: "22px 20px",
        border: `1px solid ${T.jade}33`,
        borderRadius: 4,
        background: `${T.jade}0d`,
        textAlign: "center",
      }}
    >
      <div style={{ fontFamily: SERIF, fontSize: 16, color: T.mist, lineHeight: 1.75 }}>
        잠시 같이 숨을 골라볼까요
      </div>

      {!running ? (
        <>
          <div style={{ fontSize: 12.5, color: T.muted, marginTop: 10, lineHeight: 1.8 }}>
            {EASE_NOTES[Math.floor(Math.random() * EASE_NOTES.length)]}
          </div>
          <button
            onClick={() => {
              setStep(0);
              setRemaining(CYCLE[0].seconds);
              setRunning(true);
            }}
            style={{
              marginTop: 18,
              padding: "11px 24px",
              borderRadius: 3,
              border: `1px solid ${T.jade}4d`,
              background: "transparent",
              color: T.jade,
              fontSize: 13,
            }}
          >
            시작하기
          </button>
        </>
      ) : (
        <>
          <div
            style={{
              margin: "22px auto 0",
              width: 110,
              height: 110,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${T.jade}66 0%, ${T.jade}00 70%)`,
              // 애니메이션이 아니라 단계에 맞춰 크기를 바꾼다.
              // reduced-motion이면 전환 자체를 끄고 숫자만 남긴다.
              transform: phase.key === "out" ? "scale(0.82)" : "scale(1.12)",
              transition: reducedMotion ? "none" : "transform 1.2s ease-in-out",
            }}
          />
          <div style={{ marginTop: 20, fontSize: 15, color: T.mist, letterSpacing: "0.05em" }}>
            {phase.label}
          </div>
          <div style={{ fontFamily: SERIF, fontSize: 26, color: T.jade, marginTop: 6 }}>
            {remaining}
          </div>
          <button
            onClick={() => setRunning(false)}
            style={{
              marginTop: 20,
              background: "none",
              border: "none",
              color: "#ffffff40",
              fontSize: 12.5,
            }}
          >
            그만하기
          </button>
        </>
      )}
    </div>
  );
}
