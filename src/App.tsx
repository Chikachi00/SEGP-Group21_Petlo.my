import { Routes, Route } from "react-router";
import Navbar from "./components/Navbar";
import VideoListPage from "./pages/VideoListPage";
import ResultPage from "./pages/ResultPage";
import HistoryPage from "./pages/HistoryPage";


export default function App() {
  return (
    <>
      <Navbar />
      <main>
        <Routes>
          <Route path="/" element={<VideoListPage />} />
          <Route path="/sessions/:id" element={<ResultPage />} />
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </main>
    </>
  );
}