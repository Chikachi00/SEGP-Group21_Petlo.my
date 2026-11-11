import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import PawLogo from '../../../components/PawLogo';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type Theme = 'dark' | 'light';

function ThemeButton({ theme, onToggleTheme }: { theme: Theme; onToggleTheme: () => void }) {
  return <button type="button" className="theme-toggle" onClick={onToggleTheme} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} title={theme === 'dark' ? 'Light mode' : 'Dark mode'}>{theme === 'dark' ? '☀' : '☾'}</button>;
}

type Session = {
  id: string;
  date: string;
  throws: number;
  catches: number;
};

const initialSessions: Session[] = [
  { id: 's_001', date: '2026-10-12', throws: 8, catches: 4 },
  { id: 's_002', date: '2026-10-15', throws: 12, catches: 9 },
  { id: 's_003', date: '2026-10-18', throws: 10, catches: 8 },
];
const rate = (s: Session) => (s.throws ? Math.round((s.catches / s.throws) * 100) : 0);

// Only s_001 has a demonstrated event timeline in the existing ResultPage.
const demoEvents = [
  { time: '00:05', label: 'Catch' },
  { time: '00:18', label: 'Failure' },
  { time: '00:31', label: 'Catch' },
  { time: '00:47', label: 'Indetermination' },
];

function SearchIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.7" /><path d="m16 16 5 5" /></svg>;
}
function UploadIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 16V3m0 0L7 8m5-5 5 5" /><path d="M4 15v5h16v-5" /></svg>;
}
function TrendIcon() {
  return <svg viewBox="0 0 28 28" fill="currentColor" aria-hidden="true"><rect x="3" y="17" width="5" height="8" rx="1"/><rect x="11.5" y="11" width="5" height="14" rx="1"/><rect x="20" y="4" width="5" height="21" rx="1"/></svg>;
}
function TargetIcon() {
  return <svg viewBox="0 0 54 54" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="24" cy="30" r="18"/><circle cx="24" cy="30" r="10"/><path d="m24 30 21-21M36 9h9v9"/></svg>;
}

export default function Dashboard({ theme, onToggleTheme }: { theme: Theme; onToggleTheme: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [sessions] = useState<Session[]>(initialSessions);
  const [active, setActive] = useState('Dashboard');
  const [selected, setSelected] = useState<Session | null>(null);
  const [drawerClosing, setDrawerClosing] = useState(false);
  const drawerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewButtonRef = useRef<HTMLButtonElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const tableRef = useRef<HTMLElement>(null);
  const trendRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!selected) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closePreview();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [selected]);

  useEffect(() => () => {
    if (drawerTimer.current) clearTimeout(drawerTimer.current);
  }, []);

  function openPreview(session: Session, button: HTMLButtonElement) {
    if (drawerTimer.current) clearTimeout(drawerTimer.current);
    previewButtonRef.current = button;
    setDrawerClosing(false);
    setSelected(session);
  }

  function closePreview() {
    if (!selected || drawerClosing) return;
    setDrawerClosing(true);
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    drawerTimer.current = setTimeout(() => {
      setSelected(null);
      setDrawerClosing(false);
      previewButtonRef.current?.focus();
    }, reducedMotion ? 0 : 300);
  }

  const filtered = useMemo(() => sessions.filter((s) => {
    const text = `${s.id} ${s.date} ${s.throws} ${s.catches} ${rate(s)}%`.toLowerCase();
    return text.includes(query.trim().toLowerCase());
  }), [query, sessions]);
  const chartData = sessions.map((s) => ({ name: s.id, catchRate: rate(s) }));
  const difference = chartData.length > 1 ? chartData[chartData.length - 1].catchRate - chartData[0].catchRate : 0;

  const goTo = (page: string) => {
    setActive(page);
    if (page === 'Dashboard') window.scrollTo({ top: 0, behavior: 'smooth' });
    if (page === 'Sessions') tableRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (page === 'History') trendRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  return <div className="site">
    <header className="topbar">
      <div className="topbar-inner">
        <button className="brand" onClick={() => goTo('Dashboard')} aria-label="Go to dashboard"><PawLogo/><span className="brand-divider"/><span>Disc Dog Tracker</span></button>
        <label className="search-box"><SearchIcon/><input value={query} onChange={(e) => setQuery(e.target.value)} type="search" placeholder="Search by serial number, date, or keyword..." aria-label="Search sessions" /></label>
        <nav className="nav" aria-label="Main navigation">{['Dashboard','Sessions','History'].map((item) => <button key={item} className={active === item ? 'nav-active' : ''} onClick={() => item === 'History' ? navigate('/history') : goTo(item)}>{item}</button>)}</nav>
        <ThemeButton theme={theme} onToggleTheme={onToggleTheme} />
        <button className="header-upload" onClick={() => navigate('/upload')}><UploadIcon/> Upload Video</button>
      </div>
    </header>

    <main className="main">
      <section className="hero" aria-labelledby="hero-title">
        <img className="hero-dog" src="/hero-dog.png" alt="Black and white dog jumping toward a red flying disc" />
        <div className="hero-copy">
          <div className="eyebrow"><span/>DISC DOG TRAINING ANALYTICS</div>
          <h1 id="hero-title">Track Every Throw.<br/>Improve Every Catch.</h1>
          <p>Review your training sessions, measure catch rate, and<br className="desktop-break"/> visualize your progress over time.</p>
          <div className="hero-actions"><button className="primary-button" onClick={() => navigate('/upload')}><span className="play-icon">▶</span>Upload Training Video</button><button className="history-link" onClick={() => goTo('History')}>View Session History <span>→</span></button></div>
        </div>
      </section>

      <div className="dashboard-grid">
        <section className="panel sessions-panel" ref={tableRef} aria-labelledby="sessions-title">
          <h2 id="sessions-title">Training Sessions</h2><p className="panel-description">Review your training sessions, throw by throw.</p>
          <div className="table-scroll"><table><thead><tr><th>SERIAL NUMBER</th><th>DATE</th><th>THROWS</th><th>CATCHES</th><th>CATCH RATE</th><th>ACTION</th></tr></thead><tbody>
            {filtered.map((s) => <tr key={s.id}><td>{s.id}</td><td>{s.date}</td><td>{s.throws}</td><td>{s.catches}</td><td>{rate(s)}%</td><td><div className="session-actions">
              <button className="check-button" onClick={() => navigate(`/sessions/${s.id}`)}>Check</button>
              <button className="preview-button" onClick={(e) => openPreview(s, e.currentTarget)} aria-label={`Preview session ${s.id}`}>Preview</button>
            </div></td></tr>)}
            {filtered.length === 0 && <tr><td colSpan={6} className="no-results">No matching sessions found.</td></tr>}
          </tbody></table></div>
        </section>
        <div className="right-column">
          <section className="panel trend-panel" ref={trendRef} aria-labelledby="trend-title"><div className="panel-title-row"><TrendIcon/><div><h2 id="trend-title">Catch Rate Trend</h2><p>Your recent training performance</p></div></div>
            <div className="chart-container"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 10, right: 14, bottom: 0, left: -16 }}><defs><linearGradient id="catchGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#a0cce8" stopOpacity={0.28}/><stop offset="100%" stopColor="#a0cce8" stopOpacity={0.05}/></linearGradient></defs><CartesianGrid stroke={theme === 'dark' ? "#ffffff" : "#8296af"} strokeOpacity={theme === 'dark' ? 0.12 : 0.24} vertical={false} strokeDasharray="3 3"/><XAxis dataKey="name" tick={{ fill: theme === 'dark' ? '#f1f5fc' : '#263e59', fontSize: 13 }} axisLine={{ stroke: theme === 'dark' ? '#dfe8f4' : '#9db0c5' }} tickLine={false} tickMargin={9}/><YAxis domain={[0,100]} ticks={[0,20,40,60,80,100]} tickFormatter={v=>`${v}%`} tick={{ fill: theme === 'dark' ? '#f1f5fc' : '#263e59', fontSize: 13 }} axisLine={{ stroke: theme === 'dark' ? '#dfe8f4' : '#9db0c5' }} tickLine={false}/><Tooltip formatter={(v) => [`${v}%`, 'Catch rate']} contentStyle={{background:theme === 'dark' ? '#132a43' : '#ffffff',color:theme === 'dark' ? 'white' : '#142d4b',border:'1px solid #6a8199',borderRadius:8}}/><Area type="linear" dataKey="catchRate" stroke={theme === 'dark' ? "#f4f8ff" : "#1268b3"} strokeWidth={2.6} fill="url(#catchGradient)" dot={{r:5,fill:theme === 'dark' ? '#f4f8ff' : '#1268b3',stroke:theme === 'dark' ? '#f4f8ff' : '#1268b3'}} activeDot={{r:7}} /></AreaChart></ResponsiveContainer></div>
          </section>
          <section className="panel insight-panel"><TargetIcon/><div><h3>Keep Improving</h3><p>Your catch rate {difference >= 0 ? 'increased' : 'decreased'} by {Math.abs(difference)} percentage points from your first to latest session.</p></div></section>
        </div>
      </div>
    </main>

    {selected && <div className={`quick-overlay${drawerClosing ? ' is-closing' : ''}`} onClick={closePreview}>
      <aside className="quick-drawer" role="dialog" aria-modal="true" aria-labelledby="quick-title" onClick={(e) => e.stopPropagation()}>
        <div className="quick-header"><div><span className="quick-eyebrow">TRAINING ANALYTICS</span><h2 id="quick-title">Session Details</h2><p>{selected.id} · {selected.date}</p></div>
          <button ref={closeButtonRef} type="button" className="quick-close" aria-label="Close session preview" onClick={closePreview}>×</button>
        </div>
        <div className="quick-stats">
          <div className="quick-stat"><span>Total Throws</span><strong>{selected.throws}</strong></div>
          <div className="quick-stat"><span>Successful Catches</span><strong>{selected.catches}</strong></div>
          <div className="quick-stat"><span>Catch Rate</span><strong>{rate(selected)}%</strong></div>
          <div className="quick-stat"><span>Missed Throws</span><strong>{Math.max(0, selected.throws - selected.catches)}</strong></div>
        </div>
        <div className="quick-section"><h3>Catch Performance</h3><p>Catch success across this demo training session.</p><div className="quick-rate-row"><span>Success rate</span><strong>{rate(selected)}%</strong></div><div className="quick-progress"><div className="quick-progress-fill" style={{ width: `${rate(selected)}%` }}/></div></div>
        <div className="quick-section"><h3>Event Timeline</h3><p>Demonstration event preview</p>
          {selected.id === 's_001' ? <div className="quick-events">{demoEvents.map((event) => <div key={event.time}><span>{event.time}</span><strong>{event.label}</strong></div>)}</div> : <p className="quick-empty">No event timestamps available for this demo session.</p>}
        </div>
        <div className="quick-footer"><button type="button" className="quick-view" onClick={() => navigate(`/sessions/${selected.id}`)}>View Full Analysis →</button></div>
      </aside>
    </div>}
  </div>;
}
