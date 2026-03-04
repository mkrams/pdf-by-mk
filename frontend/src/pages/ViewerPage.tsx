import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { useAnalysis } from '../hooks/useAnalysis';
import type { ChangeItem, ProgressEvent } from '../types';

// ── Category & Impact colors ─────────────────────────────────────

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
const IMP_COLORS: Record<string, string> = {
  CRITICAL: 'bg-red-900 text-red-200',
  HIGH: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  MEDIUM: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  LOW: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
};

function Badge({ text, colors }: { text: string; colors: string }) {
  return <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${colors}`}>{text}</span>;
}

// ── Miami Vice Sun Animation ────────────────────────────────────

function MiamiSun({ percent }: { percent: number }) {
  // Sun travels across the sky: 0% = left horizon (sunrise), 50% = top (noon), 100% = right horizon (sunset)
  // Map percent to a position on an arc
  const t = percent / 100;
  // x goes from 10% to 90%
  const x = 10 + t * 80;
  // y follows a parabola: highest at t=0.5
  const y = 85 - (1 - 4 * (t - 0.5) * (t - 0.5)) * 70;

  // Sky color transitions: night → dawn → day → dusk → night
  const skyColors = t < 0.15
    ? 'rgba(10,0,26,1)' // night
    : t < 0.3
    ? `rgba(${Math.round(26 + (t - 0.15) / 0.15 * 20)},${Math.round(5 + (t - 0.15) / 0.15 * 10)},${Math.round(51 + (t - 0.15) / 0.15 * 30)},1)` // dawn
    : t < 0.7
    ? 'rgba(45,15,80,1)' // day (still purple-ish, Miami Vice style)
    : t < 0.85
    ? `rgba(${Math.round(45 - (t - 0.7) / 0.15 * 20)},${Math.round(15 - (t - 0.7) / 0.15 * 10)},${Math.round(80 - (t - 0.7) / 0.15 * 30)},1)` // dusk
    : 'rgba(10,0,26,1)'; // night again

  // Sun glow intensity
  const glowIntensity = t < 0.1 ? t / 0.1 : t > 0.9 ? (1 - t) / 0.1 : 1;

  return (
    <svg viewBox="0 0 100 100" className="absolute inset-0 w-full h-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id="sunGradAnim" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ff2d95" />
          <stop offset="100%" stopColor="#ffb347" />
        </linearGradient>
        <radialGradient id="sunGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(255,45,149,0.4)" />
          <stop offset="100%" stopColor="rgba(255,45,149,0)" />
        </radialGradient>
      </defs>
      {/* Sky background */}
      <rect width="100" height="100" fill={skyColors} />
      {/* Stars (visible at low percent) */}
      {(t < 0.2 || t > 0.8) && (
        <g opacity={t < 0.2 ? 1 - t / 0.2 : (t - 0.8) / 0.2}>
          {[
            [15, 20], [30, 12], [50, 8], [70, 15], [85, 22],
            [20, 35], [40, 28], [60, 18], [80, 30], [45, 40],
            [10, 45], [90, 38], [25, 50], [75, 45],
          ].map(([sx, sy], i) => (
            <circle key={i} cx={sx} cy={sy} r={0.3 + (i % 3) * 0.2} fill="white" opacity={0.5 + (i % 3) * 0.2} />
          ))}
        </g>
      )}
      {/* Sun glow */}
      <circle cx={x} cy={y} r={12} fill="url(#sunGlow)" opacity={glowIntensity * 0.6} />
      {/* Sun */}
      <circle cx={x} cy={y} r={5} fill="url(#sunGradAnim)" opacity={glowIntensity} />
      {/* Horizontal lines through sun */}
      {[0, 1.5, 2.7, 3.6, 4.3, 4.8].map((offset, i) => (
        <rect key={i} x={x - 5} y={y + offset - 2.5} width={10} height={0.5}
          fill="rgba(20,0,40,0.5)" opacity={glowIntensity} />
      ))}
      {/* Water / horizon */}
      <rect x="0" y="85" width="100" height="15" fill="rgba(0,0,20,0.8)" />
      {/* Water reflection */}
      <ellipse cx={x} cy="88" rx={6 * glowIntensity} ry={2} fill="rgba(255,45,149,0.15)" opacity={glowIntensity} />
      {/* Buildings silhouette */}
      <g fill="rgba(10,0,26,0.95)">
        <rect x="5" y="70" width="6" height="15" />
        <rect x="12" y="62" width="8" height="23" />
        <rect x="21" y="72" width="5" height="13" />
        <rect x="27" y="55" width="7" height="30" />
        <rect x="35" y="65" width="5.5" height="20" />
        <rect x="42" y="58" width="9" height="27" />
        <rect x="52" y="48" width="8" height="37" />
        <rect x="61" y="60" width="7" height="25" />
        <rect x="69" y="68" width="6" height="17" />
        <rect x="76" y="55" width="8.5" height="30" />
        <rect x="85" y="65" width="5" height="20" />
        <rect x="91" y="70" width="7" height="15" />
      </g>
      {/* Palm tree silhouettes */}
      <g fill="rgba(5,0,15,0.9)">
        <rect x="17" y="64" width="1" height="21" rx="0.5" />
        <ellipse cx="14" cy="63" rx="5" ry="1.2" transform="rotate(-20 14 63)" />
        <ellipse cx="20" cy="62" rx="4.5" ry="1" transform="rotate(15 20 62)" />
        <rect x="82" y="66" width="1" height="19" rx="0.5" />
        <ellipse cx="79" cy="65" rx="4.5" ry="1.1" transform="rotate(-18 79 65)" />
        <ellipse cx="85" cy="64.5" rx="4" ry="1" transform="rotate(20 85 64.5)" />
      </g>
      {/* Retro grid on water */}
      <g stroke="rgba(0,229,255,0.08)" strokeWidth="0.2" fill="none">
        {[88, 91, 94, 97].map(gy => (
          <line key={gy} x1="0" y1={gy} x2="100" y2={gy} />
        ))}
        {[10, 20, 30, 40, 50, 60, 70, 80, 90].map(gx => (
          <line key={gx} x1={gx} y1="85" x2={gx < 50 ? gx - 10 : gx + 10} y2="100" />
        ))}
      </g>
    </svg>
  );
}

// ── Progress Monitor (Miami Vice style) ─────────────────────────

function ProgressMonitor({ events, error }: { events: ProgressEvent[]; error?: string | null }) {
  const latest = events[events.length - 1];
  const pct = latest?.percent || 0;
  const [elapsed, setElapsed] = useState(0);
  const logRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const turnMatch = latest?.message?.match(/Turn (\d+)\/(\d+)/);
  const tokenMatch = latest?.message?.match(/([\d,]+) tokens/);
  const currentTurn = turnMatch ? parseInt(turnMatch[1]) : 0;
  const maxTurns = turnMatch ? parseInt(turnMatch[2]) : 15;
  const tokens = tokenMatch ? tokenMatch[1] : '0';

  return (
    <div className="flex-1 flex flex-col relative overflow-hidden"
      style={{ background: 'linear-gradient(180deg, #0a001a 0%, #1a0533 50%, #0a001a 100%)' }}>

      {/* Animated sun background */}
      <MiamiSun percent={pct} />

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
                  <div className="text-[10px] text-white/30 uppercase tracking-wider">AI Turns</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-mono font-bold" style={{ color: '#ffb347' }}>
                    {tokens}
                  </div>
                  <div className="text-[10px] text-white/30 uppercase tracking-wider">Tokens</div>
                </div>
              </div>

              {/* Neon progress bar */}
              <div className="w-full rounded-full h-2 mb-3"
                style={{ background: 'rgba(255,255,255,0.05)' }}>
                <div className="h-2 rounded-full transition-all duration-700 ease-out"
                  style={{
                    width: `${Math.max(pct, 2)}%`,
                    background: 'linear-gradient(90deg, #ff2d95, #d926ff, #00e5ff)',
                    boxShadow: '0 0 12px rgba(255,45,149,0.5), 0 0 24px rgba(0,229,255,0.3)',
                  }} />
              </div>

              {/* Current action */}
              <div className="text-center text-sm mb-6" style={{ color: 'rgba(255,255,255,0.5)' }}>
                {latest?.message?.replace(/^\[[\d:]+\]\s*Turn \d+\/\d+\s*\|\s*[\d,]+ tokens\s*\|\s*/, '') || 'Connecting to the engine...'}
              </div>

              {/* Activity log */}
              <div ref={logRef} className="rounded-xl p-3 max-h-36 overflow-y-auto"
                style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.05)' }}>
                {events.length === 0 ? (
                  <div className="text-[11px] py-0.5 font-mono animate-pulse" style={{ color: 'rgba(0,229,255,0.5)' }}>
                    Warming up the AI engine...
                  </div>
                ) : events.map((ev, i) => (
                  <div key={i} className="text-[11px] py-0.5 font-mono flex gap-2">
                    <span style={{ color: 'rgba(255,45,149,0.5)' }} className="min-w-[3ch] text-right">{ev.percent}%</span>
                    <span style={{ color: 'rgba(255,255,255,0.1)' }}>|</span>
                    <span style={{ color: 'rgba(255,255,255,0.4)' }}>{ev.message}</span>
                  </div>
                ))}
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
  changes, selectedId, onSelect, search, onSearch, catFilter, onCatFilter, impFilter, onImpFilter,
}: {
  changes: ChangeItem[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  search: string; onSearch: (s: string) => void;
  catFilter: string; onCatFilter: (s: string) => void;
  impFilter: string; onImpFilter: (s: string) => void;
}) {
  const cats = useMemo(() => [...new Set(changes.map(c => c.category))].sort(), [changes]);
  const imps = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

  const filtered = useMemo(() => changes.filter(c => {
    if (catFilter && c.category !== catFilter) return false;
    if (impFilter && c.impact_level !== impFilter) return false;
    if (search && !`${c.title} ${c.description} ${c.section}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }), [changes, catFilter, impFilter, search]);

  return (
    <div className="w-72 min-w-[260px] border-r border-gray-200 dark:border-gray-700 flex flex-col bg-white dark:bg-gray-900 shrink-0">
      <div className="p-2 border-b border-gray-200 dark:border-gray-700 space-y-1">
        <input type="text" value={search} onChange={e => onSearch(e.target.value)}
          placeholder="Search changes..." className="w-full px-2 py-1.5 text-xs border rounded bg-gray-50 dark:bg-gray-800 dark:text-gray-200 dark:border-gray-600" />
        <div className="flex gap-1">
          <select value={catFilter} onChange={e => onCatFilter(e.target.value)}
            className="flex-1 text-xs px-1 py-1 border rounded bg-gray-50 dark:bg-gray-800 dark:text-gray-200 dark:border-gray-600">
            <option value="">All Categories</option>
            {cats.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={impFilter} onChange={e => onImpFilter(e.target.value)}
            className="flex-1 text-xs px-1 py-1 border rounded bg-gray-50 dark:bg-gray-800 dark:text-gray-200 dark:border-gray-600">
            <option value="">All Impacts</option>
            {imps.map(i => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>
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
              <Badge text={c.impact_level} colors={IMP_COLORS[c.impact_level] || ''} />
              <span className="text-[10px] text-gray-400">{'\u00A7'}{c.section}</span>
            </div>
          </div>
        ))}
        {filtered.length === 0 && <div className="p-4 text-sm text-gray-400 text-center">No changes match filters</div>}
      </div>
    </div>
  );
}

// ── Document Map (right panel) ───────────────────────────────────
// Shows all changes organized by page, with the selected one highlighted.
// Clicking a change here also selects it. Auto-scrolls to the selected change.

function DocumentMap({
  changes, selectedId, onSelect, viewMode,
}: {
  changes: ChangeItem[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  viewMode: 'old' | 'new';
}) {
  const selectedRef = useRef<HTMLDivElement>(null);

  // Group changes by page
  const byPage = useMemo(() => {
    const map = new Map<number, ChangeItem[]>();
    for (const c of changes) {
      const pg = viewMode === 'old' ? (c.old_page || 0) : (c.new_page || 0);
      if (!map.has(pg)) map.set(pg, []);
      map.get(pg)!.push(c);
    }
    return [...map.entries()].sort((a, b) => a[0] - b[0]);
  }, [changes, viewMode]);

  // Auto-scroll to selected change
  useEffect(() => {
    if (selectedRef.current) {
      selectedRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [selectedId]);

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-950 p-3">
      <div className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-600 mb-2 font-bold px-1">
        {viewMode === 'old' ? 'Old Document' : 'New Document'} — {changes.length} annotations
      </div>
      {byPage.map(([page, pageChanges]) => (
        <div key={page} className="mb-3">
          <div className="text-[10px] font-bold text-gray-400 dark:text-gray-600 px-1 mb-1 sticky top-0 bg-gray-50 dark:bg-gray-950 py-1 z-10">
            {page === 0 ? 'Page unknown' : `Page ${page}`}
          </div>
          <div className="space-y-1.5">
            {pageChanges.map(c => {
              const isSelected = c.id === selectedId;
              const text = viewMode === 'old' ? c.old_text : c.new_text;
              return (
                <div
                  key={c.id}
                  ref={isSelected ? selectedRef : undefined}
                  onClick={() => onSelect(c.id)}
                  className={`rounded-lg p-2.5 cursor-pointer transition-all border-l-[3px] ${CAT_BORDER[c.category] || 'border-gray-300'}
                    ${isSelected
                      ? 'bg-white dark:bg-gray-800 shadow-md ring-2 ring-blue-400/50'
                      : 'bg-white/60 dark:bg-gray-900/60 hover:bg-white dark:hover:bg-gray-800 hover:shadow-sm'
                    }`}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-[10px] font-bold text-gray-400">#{c.id}</span>
                    <Badge text={c.category} colors={CAT_COLORS[c.category] || ''} />
                    <Badge text={c.impact_level} colors={IMP_COLORS[c.impact_level] || ''} />
                  </div>
                  <div className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-1">{c.title}</div>
                  {text ? (
                    <div className={`text-[11px] leading-relaxed p-2 rounded font-mono whitespace-pre-wrap max-h-24 overflow-hidden
                      ${viewMode === 'old'
                        ? 'bg-red-50 dark:bg-red-950/30 text-red-900 dark:text-red-200'
                        : 'bg-green-50 dark:bg-green-950/30 text-green-900 dark:text-green-200'
                      }`}>
                      {text}
                    </div>
                  ) : (
                    <div className="text-[11px] text-gray-400 italic">
                      {c.category === 'NEW' ? 'New addition' : c.category === 'REMOVED' ? 'Removed from document' : 'No text excerpt'}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}


// ── Main Viewer Page ─────────────────────────────────────────────

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { progress, result, isComplete, error } = useAnalysis(jobId || null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('');
  const [impFilter, setImpFilter] = useState('');
  const [viewMode, setViewMode] = useState<'old' | 'new'>('new');
  const [dark, setDark] = useState(true);

  const changes = result?.changes || [];

  // Debug logging
  useEffect(() => {
    console.log('[ViewerPage] State:', {
      hasResult: !!result,
      isComplete,
      error,
      changesCount: changes.length,
      resultKeys: result ? Object.keys(result) : [],
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
        <h1 className="text-sm font-bold whitespace-nowrap"
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
            {Object.entries(result.by_impact || {}).map(([k, v]) => (
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
            impFilter={impFilter} onImpFilter={setImpFilter}
          />

          {/* Center: change detail */}
          <div className="flex-1 overflow-y-auto border-r border-gray-200 dark:border-gray-700">
            {selectedChange ? (
              <div className="p-4 bg-gray-50 dark:bg-gray-950">
                <div className="mb-3">
                  <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">#{selectedChange.id}: {selectedChange.title}</h2>
                  <div className="flex gap-2 mt-1 flex-wrap">
                    <Badge text={selectedChange.category} colors={CAT_COLORS[selectedChange.category] || ''} />
                    <Badge text={selectedChange.impact_level} colors={IMP_COLORS[selectedChange.impact_level] || ''} />
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
                  <div className="mb-3 p-2 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
                    <div className="text-xs font-bold mb-1">
                      {selectedChange.verification_status.includes('CONFIRMED') ? '\u2713' : '\u26A0'}{' '}
                      Verification
                    </div>
                    <div className={`text-xs font-semibold ${selectedChange.verification_status.includes('CONFIRMED') ? 'text-green-600' : 'text-amber-600'}`}>
                      {selectedChange.verification_status}
                    </div>
                    {selectedChange.verification_conclusion && (
                      <div className="text-[11px] text-gray-500 mt-1">{selectedChange.verification_conclusion}</div>
                    )}
                  </div>
                )}

                {/* Side-by-side old/new */}
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div className="p-3 rounded-lg text-sm whitespace-pre-wrap bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-gray-800 dark:text-red-200">
                    <div className="text-[11px] font-bold text-red-700 dark:text-red-400 mb-1">
                      OLD {selectedChange.old_page && <span className="opacity-60 font-normal">p.{selectedChange.old_page}</span>}
                    </div>
                    {selectedChange.old_text || <em className="text-gray-400">[Not applicable]</em>}
                  </div>
                  <div className="p-3 rounded-lg text-sm whitespace-pre-wrap bg-green-50 dark:bg-green-950/40 border border-green-200 dark:border-green-800 text-gray-800 dark:text-green-200">
                    <div className="text-[11px] font-bold text-green-700 dark:text-green-400 mb-1">
                      NEW {selectedChange.new_page && <span className="opacity-60 font-normal">p.{selectedChange.new_page}</span>}
                    </div>
                    {selectedChange.new_text || <em className="text-gray-400">[Not applicable]</em>}
                  </div>
                </div>

                <div className="text-xs text-gray-500"><b>Impact:</b> {selectedChange.impact}</div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center h-full text-gray-400 dark:text-gray-600">
                Select a change to view details
              </div>
            )}
          </div>

          {/* Right: document map with annotations */}
          <div className="w-[380px] min-w-[320px] flex flex-col shrink-0">
            <div className="flex border-b border-gray-200 dark:border-gray-700">
              {(['old', 'new'] as const).map(tab => (
                <button key={tab} onClick={() => setViewMode(tab)}
                  className={`flex-1 py-2 text-xs font-medium text-center transition-colors
                    ${viewMode === tab
                      ? 'bg-white dark:bg-gray-900 border-b-2 border-blue-500 text-blue-600'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-500 hover:text-gray-700'
                    }`}>
                  {tab === 'old' ? 'Old Document' : 'New Document'}
                </button>
              ))}
            </div>
            <DocumentMap
              changes={changes}
              selectedId={selectedId}
              onSelect={setSelectedId}
              viewMode={viewMode}
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
