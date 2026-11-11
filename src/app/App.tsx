import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useApiMode } from "../config/apiMode.ts";
import { Routes, Route, useLocation } from "react-router";
import Navbar from "../components/layout/Navbar";
import Dashboard from "../features/sessions/pages/Dashboard";

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

type Theme = "dark" | "light";

export default function App() {
  const { pathname } = useLocation();
  const showDashboard = !useApiMode && pathname === "/";
  const [theme, setTheme] = useState<Theme>(() => {
    try { return localStorage.getItem("disc-dog-theme") === "light" ? "light" : "dark"; }
    catch { return "dark"; }
  });
  const transitionRunning = useRef(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("disc-dog-theme", theme); } catch { /* storage disabled */ }
  }, [theme]);

  function toggleTheme() {
    if (transitionRunning.current) return;
    const nextTheme: Theme = theme === "dark" ? "light" : "dark";
    const applyTheme = () => flushSync(() => {
      document.documentElement.dataset.theme = nextTheme;
      setTheme(nextTheme);
    });
    const viewDoc = document as Document & {
      startViewTransition?: (callback: () => void) => { finished: Promise<void> };
    };
    if (!viewDoc.startViewTransition || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      applyTheme();
      return;
    }
    transitionRunning.current = true;
    document.documentElement.classList.add("theme-transitioning");
    const cleanup = () => {
      document.documentElement.classList.remove("theme-transitioning");
      transitionRunning.current = false;
    };
    try { void viewDoc.startViewTransition(applyTheme).finished.then(cleanup, cleanup); }
    catch { cleanup(); applyTheme(); }
  }

  return (
    <>
      {!showDashboard && <Navbar />}
      <div className={showDashboard ? "dashboard-route" : "app-route"}>
        <Suspense fallback={<p role="status">Loading page…</p>}>
          <Routes>
            <Route path="/" element={useApiMode ? <VideoListPage /> : <Dashboard theme={theme} onToggleTheme={toggleTheme} />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/sessions/:id" element={<ResultPage />} />
            <Route path="/sessions/:id/analysis" element={<AnalysisPage />} />
            <Route path="/history" element={<HistoryPage />} />
          </Routes>
        </Suspense>
      </div>
      {!showDashboard && (
        <div className="subpage-theme-toggle">
          <button type="button" className="theme-toggle" onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </div>
      )}
    </>
  );
}
