import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useAnalysis, getPdfUrl } from '../hooks/useAnalysis';
import type { ChangeItem, ProgressEvent } from '../types';

// ── Category & Impact colors ─────────────────────────────────────

const CAT_COLORS: Record<string, string> = {
  NEW: 'bg-orange-100 text-orange-700',
  MODIFIED: 'bg-blue-100 text-blue-700',
  REMOVED: 'bg-gray-200 text-gray-600',
  STRUCTURAL: 'bg-purple-100 text-purple-700',
};
const IMP_COLORS: Record<string, string> = {
  CRITICAL: 'bg-red-900 text-red-200',
  HIGH: 'bg-red-100 text-red-700',
  MEDIUM: 'bg-amber-100 text-amber-700',
  LOW: 'bg-green-100 text-green-700',
};

function Badge({ text, colors }: { text: string; colors: string }) {
  return <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${colors}`}>{text}</span>;
}

// ── Progress Monitor ─────────────────────────────────────────────

function ProgressMonitor({ events, error }: { events: ProgressEvent[]; error?: string | null }) {
  const latest = events[events.length - 1];
  const pct = latest?.percent || 0;
  const [elapsed, setElapsed] = useState(0);
  const logRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(t);
  }, []);

  // Auto-scroll log to bottom
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [events]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;

  // Parse turn/token info from latest message (format: "[0:12] Turn 3/15 | 12,345 tokens | ...")
  const turnMatch = latest?.message?.match(/Turn (\d+)\/(\d+)/);
  const tokenMatch = latest?.message?.match(/([\d,]+) tokens/);
  const currentTurn = turnMatch ? parseInt(turnMatch[1]) : 0;
  const maxTurns = turnMatch ? parseInt(turnMatch[2]) : 15;
  const tokens = tokenMatch ? tokenMatch[1] : '0';

  // Pulse animation when no events for a while
  const isStale = events.length > 0 && elapsed > 5 && !error;

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 bg-slate-900 text-white">
      <div className="max-w-lg w-full">
        {error ? (
          <>
            <div className="text-center mb-6">
              <div className="text-4xl mb-3">⚠️</div>
              <h2 className="text-xl font-bold text-red-400 mb-2">Analysis Failed</h2>
              <p className="text-slate-400 text-sm mb-4 max-w-sm mx-auto break-words">{error}</p>
              <button onClick={() => window.location.href = '/'}
                className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium">
                Try Again
              </button>
            </div>
            {events.length > 0 && (
              <div ref={logRef} className="bg-slate-800/60 rounded-lg p-3 max-h-32 overflow-y-auto border border-slate-700">
                {events.map((ev, i) => (
                  <div key={i} className="text-[11px] text-slate-500 py-0.5 font-mono">{ev.message}</div>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <h2 className="text-2xl font-bold mb-2 text-center">Analyzing Documents...</h2>
            <p className="text-slate-400 text-xs text-center mb-6">You can close this tab — analysis continues on the server</p>

            {/* Stats bar */}
            <div className="flex justify-center gap-6 mb-6">
              <div className="text-center">
                <div className="text-2xl font-mono font-bold text-blue-400">{mins}:{secs.toString().padStart(2, '0')}</div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">Elapsed</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-mono font-bold text-emerald-400">{currentTurn}<span className="text-slate-600">/{maxTurns}</span></div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">AI Turns</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-mono font-bold text-amber-400">{tokens}</div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">Tokens</div>
              </div>
            </div>

            {/* Progress bar */}
            <div className="w-full bg-slate-700 rounded-full h-2.5 mb-3">
              <div className={`bg-blue-500 h-2.5 rounded-full transition-all duration-700 ease-out ${isStale && pct < 100 ? 'animate-pulse' : ''}`}
                style={{ width: `${Math.max(pct, 2)}%` }} />
            </div>
            <div className="text-center text-slate-400 text-xs mb-6">
              {latest?.message?.replace(/^\[[\d:]+\]\s*Turn \d+\/\d+\s*\|\s*[\d,]+ tokens\s*\|\s*/, '') || 'Connecting...'}
            </div>

            {/* Event log */}
            <div ref={logRef} className="bg-slate-800/60 rounded-lg p-3 max-h-48 overflow-y-auto border border-slate-700">
              {events.length === 0 ? (
                <div className="text-[11px] text-slate-500 py-0.5 font-mono animate-pulse">Waiting for agent...</div>
              ) : events.map((ev, i) => (
                <div key={i} className="text-[11px] text-slate-400 py-0.5 font-mono flex gap-2">
                  <span className="text-blue-500/60 min-w-[3ch] text-right">{ev.percent}%</span>
                  <span className="text-slate-500">│</span>
                  <span>{ev.message}</span>
                </div>
              ))}
            </div>
          </>
        )}
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
    <div className="w-80 min-w-[280px] border-r border-gray-200 dark:border-gray-700 flex flex-col bg-white dark:bg-gray-900">
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
              ${c.id === selectedId ? 'bg-blue-50 dark:bg-blue-900/30 border-l-3 border-l-blue-500' : 'hover:bg-gray-50 dark:hover:bg-gray-800'}`}>
            <div className="flex items-start gap-1.5">
              <span className="text-[10px] font-bold text-gray-400 mt-0.5">#{c.id}</span>
              <span className="text-xs font-medium text-gray-800 dark:text-gray-200 leading-tight">{c.title}</span>
            </div>
            <div className="flex gap-1 mt-1">
              <Badge text={c.category} colors={CAT_COLORS[c.category] || ''} />
              <Badge text={c.impact_level} colors={IMP_COLORS[c.impact_level] || ''} />
              <span className="text-[10px] text-gray-400">§{c.section}</span>
            </div>
          </div>
        ))}
        {filtered.length === 0 && <div className="p-4 text-sm text-gray-400 text-center">No changes match filters</div>}
      </div>
    </div>
  );
}

// ── Change Detail (center panel) ─────────────────────────────────

function ChangeDetail({
  change, jobId, onViewPdf,
}: {
  change: ChangeItem | null;
  jobId: string;
  onViewPdf: (which: 'old' | 'new', page: number | null) => void;
}) {
  if (!change) return (
    <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-600">
      Select a change to view details
    </div>
  );

  const c = change;

  return (
    <div className="flex-1 overflow-y-auto p-4 bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <div className="mb-3">
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">#{c.id}: {c.title}</h2>
        <div className="flex gap-2 mt-1 flex-wrap">
          <Badge text={c.category} colors={CAT_COLORS[c.category] || ''} />
          <Badge text={c.impact_level} colors={IMP_COLORS[c.impact_level] || ''} />
          {c.manifest_item && c.manifest_item !== '[not in manifest]' && (
            <Badge text={`Manifest: ${c.manifest_item}`} colors="bg-blue-100 text-blue-700" />
          )}
          <span className="text-xs text-gray-400">§{c.section}</span>
        </div>
      </div>

      {/* Description */}
      <div className="text-sm text-gray-600 dark:text-gray-400 mb-3 p-2 bg-white dark:bg-gray-900 rounded border border-gray-200 dark:border-gray-700">
        {c.description}
      </div>

      {/* Verification */}
      {c.verification_status && c.verification_status !== 'N/A' && (
        <div className="mb-3 p-2 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <div className="text-xs font-bold mb-1">
            {c.verification_status.includes('CONFIRMED') ? '✓' : '⚠'}{' '}
            {c.verification_status.includes('REMOVED') ? 'Full-Document Removal Verification' : 'Full-Document Verification'}
          </div>
          <div className={`text-xs font-semibold ${c.verification_status.includes('CONFIRMED') ? 'text-green-600' : 'text-amber-600'}`}>
            {c.verification_status}
          </div>
          {c.verification_conclusion && (
            <div className="text-[11px] text-gray-500 mt-1">{c.verification_conclusion}</div>
          )}
          {c.verification_keywords && c.verification_keywords.length > 0 && (
            <div className="text-[10px] text-gray-400 mt-1 p-1 bg-gray-50 dark:bg-gray-800 rounded">
              <b>Keywords searched:</b> {c.verification_keywords.map(k => <code key={k} className="bg-gray-200 dark:bg-gray-700 px-1 rounded mx-0.5">{k}</code>)}
            </div>
          )}
        </div>
      )}

      {/* Old/New comparison */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div
          className={`p-3 rounded-lg text-sm whitespace-pre-wrap bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-gray-800 dark:text-red-200 ${c.old_page ? 'cursor-pointer hover:shadow-md transition-shadow' : ''}`}
          onClick={() => c.old_page && onViewPdf('old', c.old_page)}
          title={c.old_page ? `Click to view in Old PDF (p.${c.old_page})` : ''}
        >
          <div className="text-[11px] font-bold text-red-700 dark:text-red-400 mb-1 flex justify-between">
            <span>OLD</span>
            {c.old_page && <span className="opacity-60">p.{c.old_page} →</span>}
          </div>
          {c.old_text || <em className="text-gray-400">[Not applicable]</em>}
        </div>
        <div
          className={`p-3 rounded-lg text-sm whitespace-pre-wrap bg-green-50 dark:bg-green-950/40 border border-green-200 dark:border-green-800 text-gray-800 dark:text-green-200 ${c.new_page ? 'cursor-pointer hover:shadow-md transition-shadow' : ''}`}
          onClick={() => c.new_page && onViewPdf('new', c.new_page)}
          title={c.new_page ? `Click to view in New PDF (p.${c.new_page})` : ''}
        >
          <div className="text-[11px] font-bold text-green-700 dark:text-green-400 mb-1 flex justify-between">
            <span>NEW</span>
            {c.new_page && <span className="opacity-60">p.{c.new_page} →</span>}
          </div>
          {c.new_text || <em className="text-gray-400">[Not applicable]</em>}
        </div>
      </div>

      <div className="text-xs text-gray-500 dark:text-gray-500">
        <b>Impact:</b> {c.impact}
      </div>
    </div>
  );
}

// ── PDF Viewer (right panel) ─────────────────────────────────────

function PdfViewer({
  jobId, activeTab, page, onTabChange,
}: {
  jobId: string;
  activeTab: 'old' | 'new';
  page: number | null;
  onTabChange: (tab: 'old' | 'new') => void;
}) {
  const url = getPdfUrl(jobId, activeTab) + (page ? `#page=${page}` : '');
  return (
    <div className="w-[420px] min-w-[300px] flex flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
      <div className="flex border-b border-gray-200 dark:border-gray-700">
        {(['old', 'new'] as const).map(tab => (
          <button key={tab} onClick={() => onTabChange(tab)}
            className={`flex-1 py-2 text-xs font-medium text-center transition-colors
              ${activeTab === tab ? 'bg-white dark:bg-gray-900 border-b-2 border-blue-500 text-blue-600' : 'bg-gray-100 dark:bg-gray-800 text-gray-500'}`}>
            {tab === 'old' ? 'Old Version' : 'New Version'}
          </button>
        ))}
      </div>
      <iframe key={url} src={url} className="flex-1 border-0 w-full" title="PDF Viewer" />
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
  const [pdfTab, setPdfTab] = useState<'old' | 'new'>('new');
  const [pdfPage, setPdfPage] = useState<number | null>(null);
  const [dark, setDark] = useState(true);

  // Select first change when results arrive
  useEffect(() => {
    if (result?.changes.length && !selectedId) {
      setSelectedId(result.changes[0].id);
    }
  }, [result]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      const changes = result?.changes || [];
      const idx = changes.findIndex(c => c.id === selectedId);
      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault();
        if (idx < changes.length - 1) setSelectedId(changes[idx + 1].id);
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault();
        if (idx > 0) setSelectedId(changes[idx - 1].id);
      } else if (e.key === '1') setPdfTab('old');
      else if (e.key === '2') setPdfTab('new');
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [result, selectedId]);

  const handleViewPdf = useCallback((which: 'old' | 'new', page: number | null) => {
    setPdfTab(which);
    setPdfPage(page);
  }, []);

  const selectedChange = result?.changes.find(c => c.id === selectedId) || null;

  if (!jobId) return <div className="p-8">No job ID</div>;

  return (
    <div className={`h-screen flex flex-col ${dark ? 'dark' : ''}`}>
      {/* Header */}
      <div className="bg-gradient-to-r from-slate-800 to-blue-800 text-white px-4 py-2 flex items-center gap-4 shrink-0">
        <h1 className="text-sm font-bold whitespace-nowrap">PDF by MK</h1>
        {result && (
          <div className="flex gap-2 text-[10px]">
            <span className="bg-white/15 px-2 py-0.5 rounded-full">{result.total_changes} changes</span>
            {Object.entries(result.by_impact).map(([k, v]) => (
              <span key={k} className="bg-white/10 px-2 py-0.5 rounded-full">{k}: {v}</span>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2 text-[10px]">
          <span className="opacity-50">↑↓ nav · 1/2 PDF</span>
          <button onClick={() => setDark(!dark)} className="bg-white/20 px-2 py-0.5 rounded text-[10px]">
            {dark ? 'Light' : 'Dark'}
          </button>
        </div>
      </div>

      {/* Main content */}
      {result ? (
        /* Analysis complete with results — show the 3-panel viewer */
        <div className="flex flex-1 overflow-hidden bg-white dark:bg-gray-950">
          <ChangeList
            changes={result.changes}
            selectedId={selectedId}
            onSelect={setSelectedId}
            search={search} onSearch={setSearch}
            catFilter={catFilter} onCatFilter={setCatFilter}
            impFilter={impFilter} onImpFilter={setImpFilter}
          />
          <ChangeDetail change={selectedChange} jobId={jobId} onViewPdf={handleViewPdf} />
          <PdfViewer jobId={jobId} activeTab={pdfTab} page={pdfPage} onTabChange={setPdfTab} />
        </div>
      ) : isComplete && error ? (
        /* Failed — show error in progress monitor */
        <ProgressMonitor events={progress} error={error} />
      ) : isComplete ? (
        /* Complete but no result (shouldn't happen, fallback) */
        <div className="flex-1 flex items-center justify-center text-gray-400">
          <div className="text-center">
            <p className="mb-2">Analysis complete but no results available.</p>
            <button onClick={() => window.location.href = '/'}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm">
              Start New Analysis
            </button>
          </div>
        </div>
      ) : (
        /* Still processing — show progress monitor */
        <ProgressMonitor events={progress} error={error} />
      )}
    </div>
  );
}
