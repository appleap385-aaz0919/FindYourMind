/**
 * FindYourMind — emotion-prototype.jsx의 화면을 실제 데이터·저장소에 연결한 것.
 *
 * 프로토타입에서 유지한 것: 톤·레이아웃·인터랙션·문구, 색·간격·타이포, 호흡하는 빛.
 * 교체한 것: 샘플 영상 → videos.json, 메모리 → IndexedDB,
 *            하드코딩 감정 데이터 → taxonomy.json, 카드 → 실제 썸네일/링크.
 *
 * 제거한 것: 프로토타입 상단의 "즉답 0ms / 뜸 들이기 1000ms" 개발용 토글.
 *   비교 검수를 위한 장치였고 1000ms로 확정됐다(taxonomy.yaml ui.loading.decision).
 *   제품에 남기면 확정된 동작을 우회하는 경로가 된다.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import taxonomy from "./data/taxonomy.json";
import { T, SERIF, SANS } from "./theme.js";
import { classify, RESULT } from "./lib/classify.js";
import { getCategoryVideos, getCrisisVideos } from "./lib/videos.js";
import { loadInitialData, shouldCheck, syncInBackground } from "./lib/sync.js";
import { KEYS, setSetting } from "./lib/db.js";
import {
  greetingSlot,
  loadMessageIndexes,
  pickMessage,
  recordVisit,
  revisitSlot,
} from "./lib/messages.js";
import { useOnline, usePrefersReducedMotion, withMinDuration } from "./lib/offline.js";
import { Videos } from "./components/Videos.jsx";
import { BreathingGuide } from "./components/BreathingGuide.jsx";
import { Closing, CrisisBlock, Msg } from "./components/common.jsx";

const MIN_DURATION_MS = taxonomy.ui.loading.min_duration_ms;

export default function App() {
  const [mode, setMode] = useState("text");
  const [text, setText] = useState("");
  const [phase, setPhase] = useState("input");
  const [result, setResult] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [loadingMessage, setLoadingMessage] = useState(taxonomy.ui.loading.messages[0]);
  const [placeholder, setPlaceholder] = useState(taxonomy.ui.placeholders[0]);
  const [greeting, setGreeting] = useState("");

  // 화면을 그리는 데 쓰는 데이터. 갱신되어도 보고 있는 화면은 바꾸지 않는다.
  const [data, setData] = useState(null);
  const dataRef = useRef(null);

  const online = useOnline();
  const reducedMotion = usePrefersReducedMotion();

  // --- 시작: 캐시(없으면 시드)로 즉시 그리고, 갱신은 뒤에서 --------------------
  useEffect(() => {
    let cancelled = false;

    (async () => {
      await loadMessageIndexes();

      const [{ data: initial }, visit] = await Promise.all([
        loadInitialData(),
        recordVisit(),
      ]);
      if (cancelled) return;

      dataRef.current = initial;
      setData(initial);
      setPlaceholder(pickMessage("placeholder", taxonomy.ui.placeholders));
      setGreeting(pickGreeting(visit));

      // UI를 막지 않는다. 여기서 await하지 않고 흘려보낸다.
      if (await shouldCheck()) {
        syncInBackground(initial?.version ?? null).then((outcome) => {
          // 갱신이 끝나도 화면을 바꾸지 않는다. 다음 입력부터 새 데이터를 쓴다.
          if (!cancelled && outcome.updated && outcome.data) {
            dataRef.current = outcome.data;
          }
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // --- 분류 실행 --------------------------------------------------------------
  const show = useCallback((outcome) => {
    if (outcome.kind === RESULT.OK) {
      const id = outcome.subcategory.id;
      setResult({
        ...outcome,
        empathy: pickMessage(`empathy:${id}`, outcome.subcategory.empathy_messages),
        closing: pickMessage(`closing:${id}`, outcome.subcategory.closing_messages),
        videos: getCategoryVideos(dataRef.current, id),
      });
      void setSetting(KEYS.LAST_SUBCATEGORY_ID, id);
    } else if (outcome.kind === RESULT.CRISIS) {
      setResult({
        ...outcome,
        // ⚠ 위기 영상은 최상위 crisis 객체에서만 읽는다.
        //    categories를 순회하는 getCategoryVideos는 이 경로에 등장하지 않는다.
        videos: getCrisisVideos(dataRef.current),
        closing: pickMessage("closing:crisis", taxonomy.safety.closing_messages),
      });
    } else {
      setResult(outcome);
    }
    setPhase("result");
  }, []);

  const run = useCallback(
    async (outcome) => {
      // 빈 입력·분류 실패는 뜸을 들이지 않는다. 기다리게 할 내용이 없다.
      if (outcome.kind === RESULT.EMPTY || outcome.kind === RESULT.NO_MATCH) {
        setResult(outcome);
        setPhase("result");
        return;
      }

      setLoadingMessage(pickMessage("loading", taxonomy.ui.loading.messages));
      setPhase("loading");

      // 분류가 1000ms보다 오래 걸리면 실제 소요 시간을 쓴다(추가 지연 없음).
      // reduced-motion이어도 이 지연은 유지한다 — 끄는 건 애니메이션이지 뜸이 아니다.
      const resolved = await withMinDuration(async () => outcome, MIN_DURATION_MS);
      show(resolved);
    },
    [show],
  );

  const submitText = () => void run(classify(text, taxonomy));

  const reset = () => {
    setPhase("input");
    setText("");
    setSelectedCategory(null);
    setResult(null);
    setPlaceholder(pickMessage("placeholder", taxonomy.ui.placeholders));
  };

  const wrap = useMemo(
    () => ({
      minHeight: "100%",
      background: `radial-gradient(120% 90% at 50% 0%, ${T.plum} 0%, ${T.ink} 45%, ${T.inkDeep} 100%)`,
      color: T.mist,
      fontFamily: SANS,
      padding: "40px 22px 56px",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
    }),
    [],
  );

  return (
    <div style={wrap}>
      <style>{`
        @keyframes breathe { 0%,100%{transform:scale(1);opacity:.30} 45%{transform:scale(1.20);opacity:.55} }
        @keyframes rise { from{opacity:0;transform:translateY(10px)} to{opacity:1;transform:translateY(0)} }
        .rise{animation:rise .7s ease both}
        .orb{animation:breathe 10s ease-in-out infinite}
        @media (prefers-reduced-motion: reduce){ .orb{animation:none} .rise{animation:none} .vcard{transition:none} }
        .vcard:hover{ border-color:${T.jade}66 !important; transform:translateY(-2px) }
        .vcard{ transition:all .25s ease }
        input:focus{ outline:none; border-bottom-color:${T.jade} !important }
        button{ font-family:inherit; cursor:pointer }
        a{ -webkit-tap-highlight-color: transparent }
      `}</style>

      <div style={{ width: "100%", maxWidth: 460 }}>
        {phase === "input" && (
          <div className="rise">
            <div
              style={{
                position: "relative",
                height: 150,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                marginBottom: 8,
              }}
            >
              <div
                className="orb"
                style={{
                  position: "absolute",
                  width: 190,
                  height: 190,
                  borderRadius: "50%",
                  background: `radial-gradient(circle, ${T.jade}55 0%, ${T.jade}00 68%)`,
                }}
              />
              <div style={{ position: "relative", textAlign: "center" }}>
                <div
                  style={{
                    fontSize: 12,
                    letterSpacing: "0.22em",
                    color: T.muted,
                    marginBottom: 12,
                  }}
                >
                  오늘의 마음
                </div>
                <div style={{ fontFamily: SERIF, fontSize: 25, fontWeight: 400, lineHeight: 1.5 }}>
                  {greeting}
                </div>
              </div>
            </div>

            {mode === "text" ? (
              <div style={{ marginTop: 30 }}>
                <input
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && submitText()}
                  placeholder={placeholder}
                  aria-label="지금 마음"
                  style={{
                    width: "100%",
                    background: "transparent",
                    border: "none",
                    borderBottom: `1px solid #ffffff26`,
                    padding: "13px 2px",
                    fontSize: 16,
                    color: T.mist,
                    fontFamily: "inherit",
                  }}
                />
                <button
                  onClick={submitText}
                  style={{
                    width: "100%",
                    marginTop: 26,
                    padding: "14px",
                    borderRadius: 3,
                    border: `1px solid ${T.jade}59`,
                    background: `${T.jade}14`,
                    color: T.jade,
                    fontSize: 14,
                    letterSpacing: "0.04em",
                  }}
                >
                  마음 들여다보기
                </button>
                <button
                  onClick={() => setMode("select")}
                  style={{
                    width: "100%",
                    marginTop: 14,
                    background: "none",
                    border: "none",
                    color: T.muted,
                    fontSize: 13,
                  }}
                >
                  {taxonomy.ui.select_mode.switch_to_select}
                </button>
              </div>
            ) : (
              <div style={{ marginTop: 30 }}>
                <div style={{ fontSize: 13, color: T.muted, marginBottom: 16 }}>
                  {selectedCategory
                    ? taxonomy.ui.select_mode.step2
                    : taxonomy.ui.select_mode.step1}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {(selectedCategory ? selectedCategory.subcategories : taxonomy.categories).map(
                    (item) => (
                      <button
                        key={item.id}
                        onClick={() =>
                          selectedCategory
                            ? run({
                                kind: RESULT.OK,
                                subcategory: item,
                                category: selectedCategory,
                                hits: [],
                              })
                            : setSelectedCategory(item)
                        }
                        style={{
                          padding: "9px 15px",
                          borderRadius: 99,
                          border: `1px solid #ffffff1f`,
                          background: "transparent",
                          color: T.mist,
                          fontSize: 14,
                        }}
                      >
                        {item.label}
                      </button>
                    ),
                  )}
                </div>
                <button
                  onClick={() =>
                    selectedCategory ? setSelectedCategory(null) : setMode("text")
                  }
                  style={{
                    marginTop: 26,
                    background: "none",
                    border: "none",
                    color: T.muted,
                    fontSize: 13,
                    padding: 0,
                  }}
                >
                  {selectedCategory ? "← 다시 고르기" : taxonomy.ui.select_mode.switch_to_text}
                </button>
              </div>
            )}
          </div>
        )}

        {phase === "loading" && (
          <div
            style={{
              height: 330,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div
              className="orb"
              style={{
                width: 130,
                height: 130,
                borderRadius: "50%",
                background: `radial-gradient(circle, ${T.jade}66 0%, ${T.jade}00 70%)`,
                animationDuration: "2.6s",
              }}
            />
            <div style={{ marginTop: 26, fontSize: 14, color: T.muted, letterSpacing: "0.05em" }}>
              {loadingMessage}
            </div>
          </div>
        )}

        {phase === "result" && result?.kind === RESULT.EMPTY && (
          <Msg
            title={taxonomy.ui.empty_input[0]}
            sub={taxonomy.ui.empty_input[1]}
            onBack={reset}
          />
        )}

        {phase === "result" && result?.kind === RESULT.NO_MATCH && (
          <Msg
            title="제가 잘 못 알아들었어요"
            sub="아래에서 가까운 마음을 골라주실래요?"
            back="골라서 찾기"
            onBack={() => {
              setMode("select");
              reset();
            }}
          />
        )}

        {phase === "result" && result?.kind === RESULT.CRISIS && (
          <div className="rise">
            <CrisisBlock
              message={taxonomy.safety.message}
              resources={taxonomy.safety.resources}
            />
            <div
              style={{
                fontSize: 12.5,
                color: T.muted,
                margin: "30px 0 14px",
                letterSpacing: "0.03em",
              }}
            >
              지금 곁에 두면 좋을 것들
            </div>
            <Videos list={result.videos} online={online} />
            {!online && <BreathingGuide reducedMotion={reducedMotion} />}
            <Closing text={result.closing} onBack={reset} />
          </div>
        )}

        {phase === "result" && result?.kind === RESULT.OK && (
          <div className="rise">
            <div
              style={{
                fontSize: 11.5,
                letterSpacing: "0.2em",
                color: T.muted,
                marginBottom: 14,
              }}
            >
              {result.category.label} · {result.subcategory.label}
            </div>
            <div style={{ fontFamily: SERIF, fontSize: 20, lineHeight: 1.8, color: T.mist }}>
              {result.empathy}
            </div>
            <div style={{ height: 1, background: "#ffffff14", margin: "30px 0 22px" }} />
            <Videos list={result.videos} online={online} />
            {!online && <BreathingGuide reducedMotion={reducedMotion} />}
            <Closing text={result.closing} onBack={reset} />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 첫 화면 인사 — 방문 간격이 있으면 그쪽을, 없으면 시간대 인사를 쓴다.
 * 기록이 없으면 조용히 기본 인사로 돌아간다 (ui.revisit.limitations).
 */
function pickGreeting(visit) {
  const slot = revisitSlot(visit);
  if (slot !== "first_visit") {
    const items = taxonomy.ui.revisit[slot];
    if (items?.length) return pickMessage(`revisit:${slot}`, items);
  }
  const time = greetingSlot();
  return pickMessage(`greeting:${time}`, taxonomy.ui.entry_greetings[time]);
}
