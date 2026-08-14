import { useEffect, useState } from "react";
import { T, SERIF } from "../theme.js";

/** 영상 목록 하단에 조용히 붙는 한 마디 + 돌아가기. 프로토타입 그대로. */
export function Closing({ text, onBack }) {
  return (
    <div style={{ marginTop: 32, textAlign: "center" }}>
      <div style={{ fontFamily: SERIF, fontSize: 14.5, color: T.muted, lineHeight: 1.8 }}>
        {text}
      </div>
      <button
        onClick={onBack}
        style={{
          marginTop: 26,
          background: "none",
          border: "none",
          color: "#ffffff40",
          fontSize: 12.5,
        }}
      >
        다시 적어보기
      </button>
    </div>
  );
}

/** 빈 입력·분류 실패 안내. 오류가 아니라 초대처럼 보이게 한다. */
export function Msg({ title, sub, onBack, back = "돌아가기" }) {
  return (
    <div className="rise" style={{ textAlign: "center", paddingTop: 60 }}>
      <div style={{ fontFamily: SERIF, fontSize: 19, color: T.mist, lineHeight: 1.7 }}>
        {title}
      </div>
      <div style={{ fontSize: 13.5, color: T.muted, marginTop: 12 }}>{sub}</div>
      <button
        onClick={onBack}
        style={{
          marginTop: 30,
          padding: "11px 24px",
          borderRadius: 3,
          border: `1px solid ${T.jade}4d`,
          background: "transparent",
          color: T.jade,
          fontSize: 13,
        }}
      >
        {back}
      </button>
    </div>
  );
}

/**
 * 위기 안내 블록 — 상담 안내가 화면 최상단·최대 강조로 항상 먼저 온다.
 * 영상은 이 블록 아래에 놓인다 (taxonomy.yaml content_policy.placement).
 */
export function CrisisBlock({ message, resources }) {
  return (
    <div
      style={{
        border: `1px solid ${T.sand}4d`,
        background: `${T.sand}0f`,
        borderRadius: 4,
        padding: "22px 20px",
      }}
    >
      <div style={{ fontFamily: SERIF, fontSize: 17, lineHeight: 1.75, color: T.mist }}>
        {message}
      </div>
      <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 9 }}>
        {resources.map((resource) => (
          <a
            key={resource.number}
            href={`tel:${resource.number}`}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "12px 15px",
              border: `1px solid ${T.sand}40`,
              borderRadius: 3,
              textDecoration: "none",
            }}
          >
            <span style={{ fontSize: 13.5, color: T.mist }}>{resource.name}</span>
            <span
              style={{
                fontFamily: SERIF,
                fontSize: 18,
                color: T.sand,
                letterSpacing: "0.04em",
              }}
            >
              {resource.number}
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}


/**
 * 결과 화면의 "다시 적기" — 라벨 줄 오른쪽 끝에 붙는 텍스트.
 *
 * 버튼처럼 보이지 않게 한다. 테두리·배경 없이 라벨과 같은 크기·색으로 두어,
 * 같은 줄의 오른쪽 끝에 놓인 또 하나의 라벨처럼 읽히게 하는 것이 목적이다.
 * (하단의 "다시 적어보기"는 그대로 둔다 — 마무리 문구 뒤에 오는 마침표 역할이다)
 */
export function InlineRestart({ onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "none",
        border: "none",
        padding: 0,
        fontSize: 11.5,
        letterSpacing: "0.2em",
        color: T.muted,
        opacity: 0.75,
      }}
    >
      다시 적기
    </button>
  );
}

/**
 * 스크롤하면 우하단에 나타나는 "다시 적기".
 *
 * 결과가 길면 하단의 "다시 적어보기"까지 내려가야만 돌아갈 수 있었다.
 * 처음부터 떠 있으면 화면을 방해하므로, 스크롤을 시작한 뒤에만 조용히 나타난다.
 * 최상단으로 돌아가면 다시 사라진다 — 그 자리에는 라벨 줄의 InlineRestart가 있다.
 */
const REVEAL_AFTER_PX = 100;

export function FloatingRestart({ onClick, reducedMotion }) {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const onScroll = () => setShown(window.scrollY > REVEAL_AFTER_PX);
    onScroll(); // 이미 스크롤된 상태로 들어올 수 있다
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // reduced-motion이면 페이드를 쓰지 않는다. 나타나고 사라지는 것 자체는 유지한다.
  if (reducedMotion && !shown) return null;

  return (
    <button
      onClick={onClick}
      aria-hidden={!shown}
      tabIndex={shown ? 0 : -1}
      style={{
        position: "fixed",
        right: 20,
        bottom: 24,
        padding: "10px 16px",
        borderRadius: 99,
        border: `1px solid ${T.jade}33`,
        background: `${T.ink}d9`,
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        color: T.muted,
        fontSize: 12.5,
        letterSpacing: "0.04em",
        opacity: shown ? 1 : 0,
        pointerEvents: shown ? "auto" : "none",
        transition: reducedMotion ? "none" : "opacity .3s ease",
      }}
    >
      다시 적기
    </button>
  );
}
