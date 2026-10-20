import { Routes, Route } from "react-router";
import Navbar from "../components/layout/Navbar";
import HistoryPage from "../features/sessions/pages/HistoryPage";
import ResultPage from "../features/sessions/pages/ResultPage";
import VideoListPage from "../features/sessions/pages/VideoListPage";
import UploadPage from "../features/videos/pages/UploadPage";

export default function App() {
  return (
    <>
      <Navbar />
      <main>
        <Routes>
          <Route path="/" element={<VideoListPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/sessions/:id" element={<ResultPage />} />
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </main>
    </>
  );
}