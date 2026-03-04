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
  const isStale = events.length > 0 && elapsed > 5 && !error;

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 bg-slate-900 text-white">
      <div className="max-w-lg w-full">
        {error ? (
          <>
            <div className="text-center mb-6">
              <h2 className="text-xl font-bold text-red-400 mb-2">Analysis Failed</h2>
              <p className="text-slate-400 text-sm mb-4 max-w-sm mx-auto break-words">{error}</p>
              <button onClick={() => window.location.href = '/'}
                className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium">
                Try Again
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 className="text-2xl font-bold mb-2 text-center">Analyzing Documents...</h2>
            <p className="text-slate-400 text-xs text-center mb-6">You can close this tab — analysis continues on the server</p>
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
            <div className="w-full bg-slate-700 rounded-full h-2.5 mb-3">
              <div className={`bg-blue-500 h-2.5 rounded-full transition-all duration-700 ease-out ${isStale && pct < 100 ? 'animate-pulse' : ''}`}
                style={{ width: `${Math.max(pct, 2)}%` }} />
            </div>
            <div className="text-center text-slate-400 text-xs mb-6">
              {latest?.message?.replace(/^\[[\d:]+\]\s*Turn \d+\/\d+\s*\|\s*[\d,]+ tokens\s*\|\s*/, '') || 'Connecting...'}
            </div>
            <div ref={logRef} className="bg-slate-800/60 rounded-lg p-3 max-h-48 overflow-y-auto border border-slate-700">
              {events.length === 0 ? (
                <div className="text-[11px] text-slate-500 py-0.5 font-mono animate-pulse">Waiting for agent...</div>
              ) : events.map((ev, i) => (
                <div key={i} className="text-[11px] text-slate-400 py-0.5 font-mono flex gap-2">
                  <span className="text-blue-500/60 min-w-[3ch] text-right">{ev.percent}%</span>
                  <span className="text-slate-500">|</span>
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
      } else if (e.key === '1') setViewMode('old');
      else if (e.key === '2') setViewMode('new');
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [result, selectedId]);

  const selectedChange = result?.changes.find(c => c.id === selectedId) || null;

  if (!jobId) return <div className="p-8">No job ID</div>;

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
            {Object.entries(result.by_impact).map(([k, v]) => (
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
      {result ? (
        <div className="flex flex-1 overflow-hidden bg-white dark:bg-gray-950">
          {/* Left: change list */}
          <ChangeList
            changes={result.changes}
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
              changes={result.changes}
              selectedId={selectedId}
              onSelect={setSelectedId}
              viewMode={viewMode}
            />
          </div>
        </div>
      ) : isComplete && error ? (
        <ProgressMonitor events={progress} error={error} />
      ) : isComplete ? (
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
        <ProgressMonitor events={progress} error={error} />
      )}
    </div>
  );
}
