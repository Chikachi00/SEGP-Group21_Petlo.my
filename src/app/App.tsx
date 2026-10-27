import { lazy, Suspense } from "react";
import { useApiMode } from "../config/apiMode.ts";
import { Routes, Route } from "react-router";
import Navbar from "../components/layout/Navbar";

// Load only the selected mode and route. In particular, charts should not be
// downloaded and parsed when opening the video list or an analysis task.
const UploadPage = lazy(useApiMode
  ? () => import("../features/videos/pages/LiveUploadPage")
  : () => import("../features/videos/pages/UploadPage"));
const VideoListPage = lazy(useApiMode
  ? () => import("../features/sessions/pages/LiveVideoListPage")
  : () => import("../features/sessions/pages/VideoListPage"));
const ResultPage = lazy(useApiMode
  ? () => import("../features/sessions/pages/LiveResultPage")
  : () => import("../features/sessions/pages/ResultPage"));
const HistoryPage = lazy(useApiMode
  ? () => import("../features/sessions/pages/LiveHistoryPage")
  : () => import("../features/sessions/pages/HistoryPage"));
const AnalysisPage = useApiMode
  ? lazy(() => import("../features/sessions/pages/LiveAnalysisPage"))
  : ResultPage;

export default function App() {
  return (
    <>
      <Navbar />
      <main>
        <Suspense fallback={<p role="status">Loading page…</p>}>
          <Routes>
            <Route path="/" element={<VideoListPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/sessions/:id" element={<ResultPage />} />
            <Route path="/sessions/:id/analysis" element={<AnalysisPage />} />
            <Route path="/history" element={<HistoryPage />} />
          </Routes>
        </Suspense>
      </main>
    </>
  );
}
