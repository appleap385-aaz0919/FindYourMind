import { useState } from "react";
import { T } from "../theme.js";
import { formatDuration, thumbnailUrl, watchUrl } from "../lib/videos.js";
import { openVideo } from "../lib/offline.js";

/**
 * 영상 카드 목록.
 *
 * 프로토타입의 카드 형태(76×46 썸네일 자리, 13px 간격, 제목+부제 2줄)를 유지하고
 * 안쪽 내용만 실제 데이터로 채운다.
 *
 * 오프라인이면 카드를 흐리게 하고 위에 한 줄 안내를 둔다.
 * 탭했는데 아무 일도 일어나지 않는 상황을 만들지 않기 위한 것이다 (PLAN.md).
 */
export function Videos({ list, online }) {
  // 삭제된 영상은 썸네일이 404가 난다. 그 카드만 조용히 숨긴다 — 빈 자리를 남기지 않는다.
  const [hidden, setHidden] = useState(() => new Set());
  const visible = list.filter((v) => !hidden.has(v.videoId));

  if (visible.length === 0) return null;

  return (
    <div>
      {!online && (
        <div
          style={{
            fontSize: 12.5,
            color: T.muted,
            lineHeight: 1.7,
            marginBottom: 12,
            padding: "10px 12px",
            border: `1px solid #ffffff14`,
            borderRadius: 3,
          }}
        >
          지금은 연결이 없어 영상을 열 수 없어요. 목록은 저장해둘게요
        </div>
      )}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          opacity: online ? 1 : 0.45,
        }}
      >
        {visible.map((video) => (
          <div
            key={video.videoId}
            className="vcard"
            role="button"
            tabIndex={online ? 0 : -1}
            aria-disabled={!online}
            onClick={() => online && openVideo(watchUrl(video.videoId))}
            onKeyDown={(event) => {
              if (!online) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openVideo(watchUrl(video.videoId));
              }
            }}
            style={{
              display: "flex",
              gap: 13,
              alignItems: "center",
              border: "1px solid #ffffff14",
              borderRadius: 4,
              padding: 10,
              cursor: online ? "pointer" : "default",
            }}
          >
            <div
              style={{
                width: 76,
                height: 46,
                borderRadius: 2,
                flexShrink: 0,
                overflow: "hidden",
                position: "relative",
                background: `linear-gradient(135deg, ${T.jade}2e, ${T.plum})`,
              }}
            >
              <img
                src={thumbnailUrl(video.videoId)}
                alt=""
                loading="lazy"
                onError={() =>
                  setHidden((previous) => new Set(previous).add(video.videoId))
                }
                style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
              />
              {video.duration && (
                <span
                  style={{
                    position: "absolute",
                    right: 3,
                    bottom: 3,
                    padding: "1px 4px",
                    borderRadius: 2,
                    background: "#000000a6",
                    color: T.mist,
                    fontSize: 9.5,
                    letterSpacing: "0.02em",
                  }}
                >
                  {formatDuration(video.duration)}
                </span>
              )}
            </div>

            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontSize: 14,
                  color: T.mist,
                  lineHeight: 1.45,
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                }}
              >
                {video.title}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: T.muted,
                  marginTop: 4,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {video.channel}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
