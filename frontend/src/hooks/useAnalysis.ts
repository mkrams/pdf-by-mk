import { useState, useEffect, useRef, useCallback } from 'react';
import type { AnalysisResult, ProgressEvent, ChangeItem, CandidateSummary } from '../types';

const API = import.meta.env.VITE_API_URL || '';

export function useAnalysis(jobId: string | null) {
  const [progress, setProgress] = useState<ProgressEvent[]>([]);
  const [streamingChanges, setStreamingChanges] = useState<ChangeItem[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageCounts, setPageCounts] = useState<{ old: number; new: number }>({ old: 0, new: 0 });
  const [candidates, setCandidates] = useState<CandidateSummary[]>([]);
  const [analyzedCandidateIds, setAnalyzedCandidateIds] = useState<Set<string>>(new Set());
  const [rejectedCandidateIds, setRejectedCandidateIds] = useState<Set<string>>(new Set());
  const [analysisProgress, setAnalysisProgress] = useState<{ analyzed: number; total: number }>({ analyzed: 0, total: 0 });
  const [activeCandidateId, setActiveCandidateId] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const isCompleteRef = useRef(false);
  const errorRef = useRef<string | null>(null);

  useEffect(() => { isCompleteRef.current = isComplete; }, [isComplete]);
  useEffect(() => { errorRef.current = error; }, [error]);

  const fetchResult = useCallback(async (id: string): Promise<boolean> => {
    try {
      console.log(`[useAnalysis] Fetching result for ${id}...`);
      const res = await fetch(`${API}/api/analyze/${id}/result`);
      console.log(`[useAnalysis] Response status: ${res.status}`);
      if (!res.ok) return false;
      const data = await res.json();
      console.log(`[useAnalysis] Result data:`, {
        status: data.status,
        changesCount: data.changes?.length,
        totalChanges: data.total_changes,
      });

      if (data.status === 'completed') {
        if (!data.changes) data.changes = [];
        setResult(data);
        setIsComplete(true);
        console.log(`[useAnalysis] Set result with ${data.changes.length} changes`);
        return true;
      } else if (data.status === 'failed') {
        setError(data.error || 'Analysis failed');
        setIsComplete(true);
        return true;
      }
    } catch (err) {
      console.error(`[useAnalysis] fetchResult error:`, err);
    }
    return false;
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;

    fetchResult(jobId).then(done => {
      if (cancelled) return;
      if (done) {
        console.log(`[useAnalysis] Result already available, skipping SSE`);
        return;
      }

      console.log(`[useAnalysis] Connecting SSE for ${jobId}`);
      const es = new EventSource(`${API}/api/analyze/${jobId}/progress`);
      esRef.current = es;

      es.addEventListener('progress', (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(e.data) as ProgressEvent;
          setProgress((prev) => [...prev, data]);
          // Pick up page counts as soon as they arrive
          if (data.old_pages_count && data.new_pages_count) {
            setPageCounts({ old: data.old_pages_count, new: data.new_pages_count });
          }
        } catch {}
      });

      // Listen for full candidate list from orchestrator
      es.addEventListener('candidates_list', (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(e.data);
          console.log(`[useAnalysis] Received ${data.candidates?.length || 0} candidates`);
          setCandidates(data.candidates || []);
          setAnalysisProgress({ analyzed: 0, total: data.total || 0 });
        } catch {}
      });

      // Listen for candidate analysis starting
      es.addEventListener('candidate_started', (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(e.data);
          setActiveCandidateId(data.candidate_id || null);
        } catch {}
      });

      // Listen for candidate analysis completion
      es.addEventListener('candidate_analyzed', (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(e.data);
          // had_change: true = accepted, false = rejected, null = uncertain (pending pass 2)
          if (data.had_change !== null) {
            setAnalyzedCandidateIds(prev => new Set([...prev, data.candidate_id]));
          }
          if (data.had_change === false) {
            setRejectedCandidateIds(prev => new Set([...prev, data.candidate_id]));
          }
          setAnalysisProgress({ analyzed: data.analyzed_count || 0, total: data.total_candidates || 0 });
        } catch {}
      });

      // Listen for individual changes streaming in
      es.addEventListener('change_found', (e) => {
        if (cancelled) return;
        try {
          const change = JSON.parse(e.data) as ChangeItem;
          console.log(`[useAnalysis] Change found: #${change.id} ${change.section}`);
          setStreamingChanges((prev) => [...prev, change]);
        } catch {}
      });

      es.addEventListener('complete', async (e) => {
        if (cancelled) return;
        console.log(`[useAnalysis] SSE complete event received`);
        try {
          const data = JSON.parse(e.data);
          setProgress((prev) => [...prev, {
            stage: 'complete', percent: 100,
            message: data.message || `Complete: ${data.total_changes || 0} changes found`,
          }]);
        } catch {}
        es.close();
        esRef.current = null;
        const fetched = await fetchResult(jobId);
        if (!fetched) {
          console.log(`[useAnalysis] First fetch failed, retrying in 2s...`);
          await new Promise(r => setTimeout(r, 2000));
          const retried = await fetchResult(jobId);
          if (!retried) {
            setError('Analysis completed but failed to load results. Please refresh the page.');
            setIsComplete(true);
          }
        }
      });

      es.addEventListener('failed', (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(e.data);
          setError(data.error || 'Analysis failed');
          setIsComplete(true);
        } catch {
          setError('Analysis failed');
          setIsComplete(true);
        }
        es.close();
        esRef.current = null;
      });

      es.addEventListener('error', () => {
        if (cancelled) return;
        console.log(`[useAnalysis] SSE error, readyState=${es.readyState}`);
        if (es.readyState === EventSource.CLOSED) {
          fetchResult(jobId);
        }
      });
    });

    // Poll every 6s as fallback
    const poll = setInterval(() => {
      if (!isCompleteRef.current && !errorRef.current) {
        fetchResult(jobId).then(done => {
          if (done && esRef.current) {
            console.log(`[useAnalysis] Poll found completion, closing SSE`);
            esRef.current.close();
            esRef.current = null;
          }
        });
      }
    }, 6000);

    return () => {
      cancelled = true;
      esRef.current?.close();
      esRef.current = null;
      clearInterval(poll);
    };
  }, [jobId, fetchResult]);

  return { progress, streamingChanges, result, isComplete, error, pageCounts, candidates, analyzedCandidateIds, rejectedCandidateIds, analysisProgress, activeCandidateId };
}

export async function startAnalysis(
  oldPdf: File,
  newPdf: File,
  oldLabel: string,
  newLabel: string,
  apiKey?: string,
): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('old_pdf', oldPdf);
  form.append('new_pdf', newPdf);
  form.append('old_label', oldLabel);
  form.append('new_label', newLabel);
  if (apiKey) form.append('api_key', apiKey);

  const res = await fetch(`${API}/api/analyze`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export function getPdfUrl(jobId: string, which: 'old' | 'new') {
  return `${API}/api/analyze/${jobId}/pdf/${which}`;
}
