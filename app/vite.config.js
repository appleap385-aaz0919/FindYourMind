import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages는 https://<user>.github.io/FindYourMind/ 하위에 서빙한다.
// base를 맞추지 않으면 자산 경로가 루트로 잡혀 전부 404가 난다.
const BASE = "/FindYourMind/";

export default defineConfig({
  base: BASE,
  plugins: [react()],
  define: {
    // 데이터는 앱과 같은 오리진의 data/ 하위에 배치가 따로 배포한다.
    // (앱 워크플로·데이터 워크플로 양쪽 keep_files: true — PLAN.md Phase 1)
    __DATA_BASE__: JSON.stringify(`${BASE}data/`),
  },
  build: {
    outDir: "dist",
    // 시드 JSON이 130KB라 기본 경고선(500KB)에 걸리진 않지만 명시해 둔다.
    chunkSizeWarningLimit: 700,
  },
});
