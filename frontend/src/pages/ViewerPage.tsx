import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { useAnalysis } from '../hooks/useAnalysis';
import type { ChangeItem, ProgressEvent } from '../types';

const API = import.meta.env.VITE_API_URL || '';

// ── Category colors ─────────────────────────────────────────────

const CAT_COLORS: Record<string, string> = {
  NEW: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  MODIFIED: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  REMOVED: 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
  STRUCTURAL: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
};
const CAT_BORDER: Record<string, string> = {
  NEW: 'border-orange-400',
  MODIFIED: 'border-blue-400',
  REMOVED: 'border-gray-400',
  STRUCTURAL: 'border-purple-400',
};

function Badge({ text, colors }: { text: string; colors: string }) {
  return <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${colors}`}>{text}</span>;
}

// ── Progress Monitor (Miami Vice style, static background) ──────

function ProgressMonitor({ events, error }: { events: ProgressEvent[]; error?: string | null }) {
  const latest = events[events.length - 1];
  const startRef = useRef(Date.now());
  const [now, setNow] = useState(Date.now());
  const logRef = React.useRef<HTMLDivElement>(null);

  // Continuous timer — ticks every second, never resets
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  // Elapsed from local clock — continuous, never jumps
  const elapsedSecs = Math.floor((now - startRef.current) / 1000);
  const mins = Math.floor(elapsedSecs / 60);
  const secs = elapsedSecs % 60;
  const currentTurn = latest?.turn || 0;
  const maxTurns = latest?.max_turns || 20;
  const tokens = latest?.tokens || 0;
  const tokensStr = tokens > 0 ? tokens.toLocaleString() : '0';

  // Progress bar: based on elapsed time (typical analysis is 3-7 min)
  const timePct = Math.min(90, Math.round((elapsedSecs / 360) * 90));
  const pct = latest?.stage === 'complete' ? 100 : Math.max(timePct, latest?.percent || 0);

  return (
    <div className="flex-1 flex flex-col relative overflow-hidden"
      style={{ background: 'linear-gradient(180deg, #0a001a 0%, #1a0533 40%, #2d0a4e 70%, #1a0a3e 100%)' }}>

      {/* Static Miami Vice skyline background */}
      <svg viewBox="0 0 1200 400" className="absolute bottom-0 left-0 w-full" preserveAspectRatio="xMidYMax slice" style={{ opacity: 0.25 }}>
        <defs>
          <linearGradient id="sunGradP" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ff2d95" />
            <stop offset="100%" stopColor="#ffb347" />
          </linearGradient>
        </defs>
        <circle cx="600" cy="320" r="120" fill="url(#sunGradP)" opacity="0.5" />
        {[240, 260, 275, 288, 298, 306, 312, 317].map((y, i) => (
          <rect key={i} x="480" y={y} width="240" height="3" fill="rgba(20,0,40,0.5)" />
        ))}
        <g fill="#1a0a2e">
          <rect x="50" y="180" width="60" height="220" />
          <rect x="120" y="140" width="80" height="260" />
          <rect x="210" y="200" width="50" height="200" />
          <rect x="270" y="100" width="70" height="300" />
          <rect x="350" y="160" width="55" height="240" />
          <rect x="420" y="120" width="90" height="280" />
          <rect x="560" y="60" width="80" height="340" />
          <rect x="660" y="130" width="70" height="270" />
          <rect x="740" y="170" width="60" height="230" />
          <rect x="810" y="110" width="85" height="290" />
          <rect x="905" y="190" width="55" height="210" />
          <rect x="970" y="150" width="70" height="250" />
          <rect x="1050" y="200" width="60" height="200" />
          <rect x="1120" y="170" width="80" height="230" />
        </g>
        <rect x="0" y="390" width="1200" height="10" fill="#0d0520" />
      </svg>

      {/* Content overlay */}
      <div className="relative z-10 flex-1 flex flex-col items-center justify-center p-8">
        <div className="max-w-lg w-full">
          {error ? (
            <div className="text-center backdrop-blur-md rounded-2xl p-8"
              style={{ background: 'rgba(15,5,30,0.75)', border: '1px solid rgba(255,45,149,0.3)' }}>
              <h2 className="text-2xl font-black italic mb-3"
                style={{
                  background: 'linear-gradient(135deg, #ff2d95, #ff6fb5)',
                  WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                }}>Analysis Failed</h2>
              <p className="text-white/50 text-sm mb-6 max-w-sm mx-auto break-words">{error}</p>
              <button onClick={() => window.location.href = '/'}
                className="px-8 py-3 font-bold text-white rounded-xl text-sm uppercase tracking-widest"
                style={{
                  background: 'linear-gradient(135deg, #ff2d95, #d926ff, #00e5ff)',
                  boxShadow: '0 0 30px rgba(255,45,149,0.4)',
                }}>
                Try Again
              </button>
            </div>
          ) : (
            <div className="backdrop-blur-md rounded-2xl p-8"
              style={{ background: 'rgba(15,5,30,0.65)', border: '1px solid rgba(255,255,255,0.08)',
                boxShadow: '0 0 60px rgba(255,45,149,0.1), 0 25px 50px rgba(0,0,0,0.5)' }}>

              <h2 className="text-3xl font-black italic mb-1 text-center"
                style={{
                  background: 'linear-gradient(135deg, #ff2d95 0%, #ff6fb5 30%, #00e5ff 70%, #00b8d4 100%)',
                  WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                  filter: 'drop-shadow(0 0 20px rgba(255,45,149,0.3))',
                }}>
                Analyzing...
              </h2>
              <p className="text-white/30 text-xs text-center mb-6 tracking-widest uppercase">
                You can close this tab — analysis continues on the server
              </p>

              {/* Stats row */}
              <div className="flex justify-center gap-6 mb-6">
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold" style={{ color: '#ff2d95' }}>
                    {mins}:{secs.toString().padStart(2, '0')}
                  </div>
                  <div className="text-[10px] text-white/30 uppercase tracking-wider">Elapsed</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold" style={{ color: '#00e5ff' }}>
                    {currentTurn}<span style={{ color: 'rgba(255,255,255,0.2)' }}>/{maxTurns}</span>
                  </div>
                  <div className="text-[10px] text-white/30 uppercase tracking-wider">AI Steps</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold" style={{ color: '#ffb347' }}>
                    {tokensStr}
                  </div>
                  <div className="text-[10px] text-white/30 uppercase tracking-wider">Tokens</div>
                </div>
              </div>

              {/* Neon progress bar — time-based, smooth */}
              <div className="w-full rounded-full h-2 mb-3"
                style={{ background: 'rgba(255,255,255,0.05)' }}>
                <div className="h-2 rounded-full transition-all duration-1000 ease-out"
                  style={{
                    width: `${Math.max(pct, 2)}%`,
                    background: 'linear-gradient(90deg, #ff2d95, #d926ff, #00e5ff)',
                    boxShadow: '0 0 12px rgba(255,45,149,0.5), 0 0 24px rgba(0,229,255,0.3)',
                  }} />
              </div>

              {/* Current action — human readable */}
              <div className="text-center text-sm mb-6" style={{ color: 'rgba(255,255,255,0.5)' }}>
                {latest?.message || 'Connecting to the engine...'}
              </div>

              {/* Activity log */}
              <div ref={logRef} className="rounded-xl p-3 max-h-36 overflow-y-auto"
                style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.05)' }}>
                {events.length === 0 ? (
                  <div className="text-[11px] py-0.5 font-mono animate-pulse" style={{ color: 'rgba(0,229,255,0.5)' }}>
                    Warming up the AI engine...
                  </div>
                ) : events.map((ev, i) => {
                  const evMins = Math.floor((ev.elapsed || 0) / 60);
                  const evSecs = (ev.elapsed || 0) % 60;
                  return (
                    <div key={i} className="text-[11px] py-0.5 font-mono flex gap-2">
                      <span style={{ color: 'rgba(255,45,149,0.5)' }} className="min-w-[4ch] text-right shrink-0">
                        {evMins}:{evSecs.toString().padStart(2, '0')}
                      </span>
                      <span style={{ color: 'rgba(255,255,255,0.1)' }}>|</span>
                      <span style={{ color: 'rgba(255,255,255,0.4)' }}>{ev.message}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Change List (left panel) ─────────────────────────────────────

function ChangeList({
  changes, selectedId, onSelect, search, onSearch, catFilter, onCatFilter,
}: {
  changes: ChangeItem[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  search: string; onSearch: (s: string) => void;
  catFilter: string; onCatFilter: (s: string) => void;
}) {
  const cats = useMemo(() => [...new Set(changes.map(c => c.category))].sort(), [changes]);

  const filtered = useMemo(() => changes.filter(c => {
    if (catFilter && c.category !== catFilter) return false;
    if (search && !`${c.title} ${c.description} ${c.section}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [changes, catFilter, search]);

  return (
    <div className="w-72 min-w-[260px] border-r border-gray-200 dark:border-gray-700 flex flex-col bg-white dark:bg-gray-900 shrink-0">
      <div className="p-2 border-b border-gray-200 dark:border-gray-700 space-y-1">
        <input type="text" value={search} onChange={e => onSearch(e.target.value)}
          placeholder="Search changes..." className="w-full px-2 py-1.5 text-xs border rounded bg-gray-50 dark:bg-gray-800 dark:text-gray-200 dark:border-gray-600" />
        <select value={catFilter} onChange={e => onCatFilter(e.target.value)}
          className="w-full text-xs px-1 py-1 border rounded bg-gray-50 dark:bg-gray-800 dark:text-gray-200 dark:border-gray-600">
          <option value="">All Categories</option>
          {cats.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.map(c => (
          <div key={c.id} onClick={() => onSelect(c.id)}
            className={`px-3 py-2 border-b border-gray-100 dark:border-gray-800 cursor-pointer transition-colors
              ${c.id === selectedId ? 'bg-blue-50 dark:bg-blue-900/30 border-l-[3px] border-l-blue-500' : 'hover:bg-gray-50 dark:hover:bg-gray-800'}`}>
            <div className="flex items-start gap-1.5">
              <span className="text-[10px] font-bold text-gray-400 mt-0.5">#{c.id}</span>
              <span className="text-xs font-medium text-gray-800 dark:text-gray-200 leading-tight">{c.title}</span>
            </div>
            <div className="flex gap-1 mt-1">
              <Badge text={c.category} colors={CAT_COLORS[c.category] || ''} />
              <span className="text-[10px] text-gray-400">{'\u00A7'}{c.section}</span>
            </div>
          </div>
        ))}
        {filtered.length === 0 && <div className="p-4 text-sm text-gray-400 text-center">No changes match filters</div>}
      </div>
    </div>
  );
}

// ── PDF Page Viewer (right panel) ─────────────────────────────────
// Renders actual PDF pages as images from the backend.
// Scrolls to and highlights the page containing the selected change.

function PdfPageViewer({
  jobId, changes, selectedId, onSelect, viewMode, totalPages, navToPage,
}: {
  jobId: string;
  changes: ChangeItem[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  viewMode: 'old' | 'new';
  totalPages: number;
  navToPage?: { page: number; ts: number } | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set());
  const [visibleRange, setVisibleRange] = useState<[number, number]>([1, 3]);

  // Get the page for the selected change
  const selectedChange = changes.find(c => c.id === selectedId);
  const targetPage = selectedChange
    ? (viewMode === 'old' ? selectedChange.old_page : selectedChange.new_page) || 0
    : 0;

  // Build page → changes mapping
  const changesByPage = useMemo(() => {
    const map = new Map<number, ChangeItem[]>();
    for (const c of changes) {
      const pg = viewMode === 'old' ? (c.old_page || 0) : (c.new_page || 0);
      if (pg > 0) {
        if (!map.has(pg)) map.set(pg, []);
        map.get(pg)!.push(c);
      }
    }
    return map;
  }, [changes, viewMode]);

  // Scroll to target page when selection changes
  useEffect(() => {
    if (targetPage > 0) {
      const el = pageRefs.current.get(targetPage);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      setVisibleRange([Math.max(1, targetPage - 1), Math.min(totalPages, targetPage + 2)]);
    }
  }, [targetPage, totalPages]);

  // Respond to explicit navigation (clicking OLD/NEW text boxes)
  useEffect(() => {
    if (navToPage && navToPage.page > 0) {
      // Ensure pages are loaded first, then scroll after a tick
      setVisibleRange([Math.max(1, navToPage.page - 1), Math.min(totalPages, navToPage.page + 2)]);
      setTimeout(() => {
        const el = pageRefs.current.get(navToPage.page);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }, 100);
    }
  }, [navToPage, totalPages]);

  // Observe scroll to determine visible pages (lazy loading)
  useEffect(() => {
    if (!containerRef.current || totalPages === 0) return;
    const container = containerRef.current;

    const handleScroll = () => {
      const rect = container.getBoundingClientRect();
      let minPage = totalPages;
      let maxPage = 1;
      pageRefs.current.forEach((el, pg) => {
        const r = el.getBoundingClientRect();
        if (r.bottom > rect.top && r.top < rect.bottom) {
          minPage = Math.min(minPage, pg);
          maxPage = Math.max(maxPage, pg);
        }
      });
      // Load 2 pages before and after visible range
      setVisibleRange([Math.max(1, minPage - 2), Math.min(totalPages, maxPage + 2)]);
    };

    container.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll(); // initial
    return () => container.removeEventListener('scroll', handleScroll);
  }, [totalPages]);

  // Pages to actually render (visible range + target page neighborhood)
  const pagesToRender = useMemo(() => {
    const pages = new Set<number>();
    for (let p = visibleRange[0]; p <= visibleRange[1]; p++) pages.add(p);
    if (targetPage > 0) {
      pages.add(Math.max(1, targetPage - 1));
      pages.add(targetPage);
      pages.add(Math.min(totalPages, targetPage + 1));
    }
    // Always load first few pages
    for (let p = 1; p <= Math.min(3, totalPages); p++) pages.add(p);
    return pages;
  }, [visibleRange, targetPage, totalPages]);

  if (totalPages === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        No PDF pages available
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto bg-gray-200 dark:bg-gray-950">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-600 font-bold px-3 py-2 sticky top-0 z-20 bg-gray-200 dark:bg-gray-950 border-b border-gray-300 dark:border-gray-800">
        {viewMode === 'old' ? 'Old Document' : 'New Document'} — {totalPages} pages
      </div>
      <div className="space-y-2 p-2">
        {Array.from({ length: totalPages }, (_, i) => i + 1).map(pageNum => {
          const shouldLoad = pagesToRender.has(pageNum);
          const pageChanges = changesByPage.get(pageNum) || [];
          const hasSelectedChange = pageChanges.some(c => c.id === selectedId);

          return (
            <div
              key={pageNum}
              ref={el => { if (el) pageRefs.current.set(pageNum, el); }}
              className={`relative ${hasSelectedChange ? 'ring-2 ring-blue-500 rounded-lg' : ''}`}
            >
              {/* Page number label */}
              <div className="absolute top-1 left-1 z-10 bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded font-mono">
                p.{pageNum}
              </div>

              {/* Change indicators on the page */}
              {pageChanges.length > 0 && (
                <div className="absolute top-1 right-1 z-10 flex gap-1">
                  {pageChanges.map(c => (
                    <button
                      key={c.id}
                      onClick={() => onSelect(c.id)}
                      className={`text-[9px] font-bold px-1.5 py-0.5 rounded cursor-pointer transition-all
                        ${c.id === selectedId
                          ? 'bg-blue-500 text-white shadow-lg scale-110'
                          : 'bg-black/60 text-white hover:bg-blue-600'
                        }`}
                      title={`#${c.id}: ${c.title}`}
                    >
                      #{c.id}
                    </button>
                  ))}
                </div>
              )}

              {/* The actual PDF page image */}
              {shouldLoad ? (
                <PageImage jobId={jobId} which={viewMode} pageNum={pageNum} />
              ) : (
                <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm" style={{ height: 800 }}>
                  <div className="flex items-center justify-center h-full text-gray-400 text-xs">
                    Page {pageNum}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Single page image component with loading state
function PageImage({ jobId, which, pageNum }: { jobId: string; which: string; pageNum: number }) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(false);
    const url = `${API}/api/analyze/${jobId}/page/${which}/${pageNum}`;
    // Use fetch to load as blob for better caching control
    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then(blob => {
        setSrc(URL.createObjectURL(blob));
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });

    return () => {
      if (src) URL.revokeObjectURL(src);
    };
  }, [jobId, which, pageNum]);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm animate-pulse" style={{ height: 800 }}>
        <div className="flex items-center justify-center h-full text-gray-400 text-xs">
          Loading page {pageNum}...
        </div>
      </div>
    );
  }

  if (error || !src) {
    return (
      <div className="bg-red-50 dark:bg-red-950/30 rounded-lg shadow-sm" style={{ height: 200 }}>
        <div className="flex items-center justify-center h-full text-red-400 text-xs">
          Failed to load page {pageNum}
        </div>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={`Page ${pageNum}`}
      className="w-full rounded-lg shadow-sm"
      style={{ background: 'white' }}
    />
  );
}


// ── Main Viewer Page ─────────────────────────────────────────────

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { progress, result, isComplete, error } = useAnalysis(jobId || null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('');
  const [viewMode, setViewMode] = useState<'old' | 'new'>('new');
  const [dark, setDark] = useState(true);
  // Navigate-to-page trigger: bumped each time user clicks OLD/NEW text boxes
  const [navToPage, setNavToPage] = useState<{ page: number; ts: number } | null>(null);

  const changes = result?.changes || [];
  const totalPages = viewMode === 'old' ? (result?.old_pages || 0) : (result?.new_pages || 0);

  // Handler: click OLD/NEW text box → switch doc + scroll to page
  const navigateToDocPage = useCallback((which: 'old' | 'new', page: number | undefined) => {
    if (!page) return;
    setViewMode(which);
    setNavToPage({ page, ts: Date.now() });
  }, []);

  // Debug logging
  useEffect(() => {
    console.log('[ViewerPage] State:', {
      hasResult: !!result,
      isComplete,
      error,
      changesCount: changes.length,
      oldPages: result?.old_pages,
      newPages: result?.new_pages,
    });
  }, [result, isComplete, error, changes.length]);

  // Select first change when results arrive
  useEffect(() => {
    if (changes.length && !selectedId) {
      setSelectedId(changes[0].id);
    }
  }, [changes.length]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      const idx = changes.findIndex(c => c.id === selectedId);
      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault();
        if (idx < changes.length - 1) setSelectedId(changes[idx + 1].id);
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault();
        if (idx > 0) setSelectedId(changes[idx - 1].id);
      } else if (e.key === '1') setViewMode('old');
      else if (e.key === '2') setViewMode('new');
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [changes, selectedId]);

  const selectedChange = changes.find(c => c.id === selectedId) || null;

  if (!jobId) return <div className="p-8">No job ID</div>;

  // Determine what to show
  const hasResults = result && changes.length > 0;

  return (
    <div className={`h-screen flex flex-col ${dark ? 'dark' : ''}`}>
      {/* Header */}
      <div className="bg-gradient-to-r from-slate-800 to-blue-800 text-white px-4 py-2 flex items-center gap-4 shrink-0">
        <h1 className="text-sm font-bold whitespace-nowrap cursor-pointer"
          onClick={() => window.location.href = '/'}
          style={{
            background: 'linear-gradient(135deg, #ff2d95, #00e5ff)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>
          PDF by MK
        </h1>
        {result && (
          <div className="flex gap-2 text-[10px]">
            <span className="bg-white/15 px-2 py-0.5 rounded-full">{result.total_changes} changes</span>
            {Object.entries(result.by_category || {}).map(([k, v]) => (
              <span key={k} className="bg-white/10 px-2 py-0.5 rounded-full">{k}: {v}</span>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2 text-[10px]">
          <span className="opacity-50">{'\u2191\u2193'} nav {'\u00B7'} 1/2 doc</span>
          <button onClick={() => setDark(!dark)} className="bg-white/20 px-2 py-0.5 rounded text-[10px]">
            {dark ? 'Light' : 'Dark'}
          </button>
        </div>
      </div>

      {/* Main content */}
      {hasResults ? (
        <div className="flex flex-1 overflow-hidden bg-white dark:bg-gray-950">
          {/* Left: change list */}
          <ChangeList
            changes={changes}
            selectedId={selectedId}
            onSelect={setSelectedId}
            search={search} onSearch={setSearch}
            catFilter={catFilter} onCatFilter={setCatFilter}
          />

          {/* Center: change detail */}
          <div className="flex-1 overflow-y-auto border-r border-gray-200 dark:border-gray-700">
            {selectedChange ? (
              <div className="p-4 bg-gray-50 dark:bg-gray-950">
                <div className="mb-3">
                  <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">#{selectedChange.id}: {selectedChange.title}</h2>
                  <div className="flex gap-2 mt-1 flex-wrap">
                    <Badge text={selectedChange.category} colors={CAT_COLORS[selectedChange.category] || ''} />
                    {selectedChange.manifest_item && selectedChange.manifest_item !== '[not in manifest]' && (
                      <Badge text={`Manifest: ${selectedChange.manifest_item}`} colors="bg-blue-100 text-blue-700" />
                    )}
                    <span className="text-xs text-gray-400">{'\u00A7'}{selectedChange.section}</span>
                    {selectedChange.old_page && <span className="text-[10px] text-gray-400">Old p.{selectedChange.old_page}</span>}
                    {selectedChange.new_page && <span className="text-[10px] text-gray-400">New p.{selectedChange.new_page}</span>}
                  </div>
                </div>

                <div className="text-sm text-gray-600 dark:text-gray-400 mb-3 p-2 bg-white dark:bg-gray-900 rounded border border-gray-200 dark:border-gray-700">
                  {selectedChange.description}
                </div>

                {selectedChange.verification_status && selectedChange.verification_status !== 'N/A' && (
                  <div className="mb-3 p-2 rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800">
                    <div className="text-xs font-bold mb-1 text-gray-700 dark:text-gray-200">
                      {selectedChange.verification_status.includes('CONFIRMED') ? '\u2713' : '\u26A0'}{' '}
                      Verification
                    </div>
                    <div className={`text-xs font-semibold ${selectedChange.verification_status.includes('CONFIRMED') ? 'text-green-600 dark:text-green-400' : 'text-amber-600 dark:text-amber-400'}`}>
                      {selectedChange.verification_status}
                    </div>
                    {selectedChange.verification_conclusion && (
                      <div className="text-[11px] text-gray-600 dark:text-gray-300 mt-1">{selectedChange.verification_conclusion}</div>
                    )}
                  </div>
                )}

                {/* Side-by-side old/new — click to navigate PDF viewer */}
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div
                    className={`p-3 rounded-lg text-sm whitespace-pre-wrap bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-gray-800 dark:text-red-200 transition-all ${selectedChange.old_page ? 'cursor-pointer hover:ring-2 hover:ring-red-400/50' : ''}`}
                    onClick={() => navigateToDocPage('old', selectedChange.old_page || undefined)}
                    title={selectedChange.old_page ? `Click to view page ${selectedChange.old_page} in old document` : undefined}
                  >
                    <div className="text-[11px] font-bold text-red-700 dark:text-red-400 mb-1 flex items-center gap-1">
                      OLD {selectedChange.old_page && <span className="opacity-60 font-normal">p.{selectedChange.old_page} {'\u2197'}</span>}
                    </div>
                    {selectedChange.old_text || <em className="text-gray-400">[Not applicable]</em>}
                  </div>
                  <div
                    className={`p-3 rounded-lg text-sm whitespace-pre-wrap bg-green-50 dark:bg-green-950/40 border border-green-200 dark:border-green-800 text-gray-800 dark:text-green-200 transition-all ${selectedChange.new_page ? 'cursor-pointer hover:ring-2 hover:ring-green-400/50' : ''}`}
                    onClick={() => navigateToDocPage('new', selectedChange.new_page || undefined)}
                    title={selectedChange.new_page ? `Click to view page ${selectedChange.new_page} in new document` : undefined}
                  >
                    <div className="text-[11px] font-bold text-green-700 dark:text-green-400 mb-1 flex items-center gap-1">
                      NEW {selectedChange.new_page && <span className="opacity-60 font-normal">p.{selectedChange.new_page} {'\u2197'}</span>}
                    </div>
                    {selectedChange.new_text || <em className="text-gray-400">[Not applicable]</em>}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center h-full text-gray-400 dark:text-gray-600">
                Select a change to view details
              </div>
            )}
          </div>

          {/* Right: actual PDF page viewer — ~40% of screen */}
          <div className="flex flex-col shrink-0" style={{ width: '40%', minWidth: 400 }}>
            <div className="flex border-b border-gray-200 dark:border-gray-700">
              {(['old', 'new'] as const).map(tab => (
                <button key={tab} onClick={() => setViewMode(tab)}
                  className={`flex-1 py-2 text-xs font-medium text-center transition-colors
                    ${viewMode === tab
                      ? 'bg-white dark:bg-gray-900 border-b-2 border-blue-500 text-blue-600'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-500 hover:text-gray-700'
                    }`}>
                  {tab === 'old' ? `Old (${result?.old_pages || '?'}p)` : `New (${result?.new_pages || '?'}p)`}
                </button>
              ))}
            </div>
            <PdfPageViewer
              jobId={jobId}
              changes={changes}
              selectedId={selectedId}
              onSelect={setSelectedId}
              viewMode={viewMode}
              totalPages={totalPages}
              navToPage={navToPage}
            />
          </div>
        </div>
      ) : isComplete && error ? (
        <ProgressMonitor events={progress} error={error} />
      ) : isComplete && result ? (
        /* Analysis completed but 0 changes — show a message */
        <div className="flex-1 flex items-center justify-center"
          style={{ background: 'linear-gradient(180deg, #0a001a 0%, #1a0533 50%, #0a001a 100%)' }}>
          <div className="text-center backdrop-blur-md rounded-2xl p-8"
            style={{ background: 'rgba(15,5,30,0.75)', border: '1px solid rgba(0,229,255,0.3)' }}>
            <h2 className="text-2xl font-black italic mb-3"
              style={{
                background: 'linear-gradient(135deg, #00e5ff, #00b8d4)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              }}>No Changes Found</h2>
            <p className="text-white/40 text-sm mb-6">The AI agent completed analysis but found no differences between the documents.</p>
            <button onClick={() => window.location.href = '/'}
              className="px-8 py-3 font-bold text-white rounded-xl text-sm uppercase tracking-widest"
              style={{
                background: 'linear-gradient(135deg, #ff2d95, #d926ff, #00e5ff)',
                boxShadow: '0 0 30px rgba(255,45,149,0.4)',
              }}>
              Try Again
            </button>
          </div>
        </div>
      ) : isComplete ? (
        <div className="flex-1 flex items-center justify-center"
          style={{ background: 'linear-gradient(180deg, #0a001a 0%, #1a0533 50%, #0a001a 100%)' }}>
          <div className="text-center backdrop-blur-md rounded-2xl p-8"
            style={{ background: 'rgba(15,5,30,0.75)', border: '1px solid rgba(255,255,255,0.1)' }}>
            <p className="text-white/40 mb-4">Analysis complete but results couldn't be loaded.</p>
            <button onClick={() => window.location.reload()}
              className="px-6 py-2 mr-3 font-bold text-white rounded-lg text-sm"
              style={{ background: 'linear-gradient(135deg, #00e5ff, #00b8d4)' }}>
              Refresh
            </button>
            <button onClick={() => window.location.href = '/'}
              className="px-6 py-2 font-bold text-white/60 rounded-lg text-sm"
              style={{ background: 'rgba(255,255,255,0.1)' }}>
              Start Over
            </button>
          </div>
        </div>
      ) : (
        <ProgressMonitor events={progress} error={error} />
      )}
    </div>
  );
}
