import { lazy, Suspense } from "react";
import { useApiMode } from "../config/apiMode.ts";
import { Routes, Route } from "react-router";
import Navbar from "../components/layout/Navbar";
import HistoryPage from "../features/sessions/pages/HistoryPage";
import ResultPage from "../features/sessions/pages/ResultPage";
import VideoListPage from "../features/sessions/pages/VideoListPage";
import UploadPage from "../features/videos/pages/UploadPage";

const LiveUploadPage = lazy(() => import("../features/videos/pages/LiveUploadPage"));
const LiveVideoListPage = lazy(() => import("../features/sessions/pages/LiveVideoListPage"));
const LiveResultPage = lazy(() => import("../features/sessions/pages/LiveResultPage"));
const LiveHistoryPage = lazy(() => import("../features/sessions/pages/LiveHistoryPage"));

export default function App() {
  return (
    <>
      <Navbar />
      <main>
        <Suspense fallback={<p role="status">Loading page…</p>}>
        <Routes>
          <Route path="/" element={useApiMode ? <LiveVideoListPage /> : <VideoListPage />} />
          <Route path="/upload" element={useApiMode ? <LiveUploadPage /> : <UploadPage />} />
          <Route path="/sessions/:id" element={useApiMode ? <LiveResultPage /> : <ResultPage />} />
          <Route path="/history" element={useApiMode ? <LiveHistoryPage /> : <HistoryPage />} />
        </Routes>
        </Suspense>
      </main>
    </>
  );
}