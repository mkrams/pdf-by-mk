import { useState, useEffect, useRef, useCallback } from 'react';
import type { AnalysisResult, ProgressEvent } from '../types';

const API = import.meta.env.VITE_API_URL || '';

export function useAnalysis(jobId: string | null) {
  const [progress, setProgress] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  // Use refs for poll interval to avoid stale closures
  const isCompleteRef = useRef(false);
  const errorRef = useRef<string | null>(null);

  // Keep refs in sync with state
  useEffect(() => { isCompleteRef.current = isComplete; }, [isComplete]);
  useEffect(() => { errorRef.current = error; }, [error]);

  const fetchResult = useCallback(async (id: string): Promise<boolean> => {
    try {
      console.log(`[useAnalysis] Fetching result for ${id}...`);
      const res = await fetch(`${API}/api/analyze/${id}/result`);
      console.log(`[useAnalysis] Response status: ${res.status}`);
      if (!res.ok) {
        console.log(`[useAnalysis] Response not OK, returning false`);
        return false;
      }
      const data = await res.json();
      console.log(`[useAnalysis] Result data:`, {
        status: data.status,
        changesCount: data.changes?.length,
        totalChanges: data.total_changes,
        hasError: !!data.error,
        keys: Object.keys(data),
      });

      if (data.status === 'completed') {
        // Ensure changes array exists
        if (!data.changes) {
          console.warn(`[useAnalysis] Result has status=completed but no changes array!`);
          data.changes = [];
        }
        setResult(data);
        setIsComplete(true);
        console.log(`[useAnalysis] Set result with ${data.changes.length} changes`);
        return true;
      } else if (data.status === 'failed') {
        setError(data.error || 'Analysis failed');
        setIsComplete(true);
        console.log(`[useAnalysis] Analysis failed: ${data.error}`);
        return true;
      }
      console.log(`[useAnalysis] Status is '${data.status}', still processing`);
    } catch (err) {
      console.error(`[useAnalysis] fetchResult error:`, err);
    }
    return false;
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;

    // First check if result already exists (tab reopened / analysis done)
    fetchResult(jobId).then(done => {
      if (cancelled) return;
      if (done) {
        console.log(`[useAnalysis] Result already available, skipping SSE`);
        return;
      }

      // Not finished yet — connect SSE for live progress
      console.log(`[useAnalysis] Connecting SSE for ${jobId}`);
      const es = new EventSource(`${API}/api/analyze/${jobId}/progress`);
      esRef.current = es;

      es.addEventListener('progress', (e) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(e.data) as ProgressEvent;
          setProgress((prev) => [...prev, data]);
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
        // Fetch the full result
        const fetched = await fetchResult(jobId);
        console.log(`[useAnalysis] Post-SSE-complete fetchResult: ${fetched}`);
        if (!fetched) {
          // Retry once after a short delay
          console.log(`[useAnalysis] First fetch failed, retrying in 2s...`);
          await new Promise(r => setTimeout(r, 2000));
          const retried = await fetchResult(jobId);
          console.log(`[useAnalysis] Retry fetchResult: ${retried}`);
          if (!retried) {
            setError('Analysis completed but failed to load results. Please refresh the page.');
            setIsComplete(true);
          }
        }
      });

      // Listen for "failed" named event
      es.addEventListener('failed', (e) => {
        if (cancelled) return;
        console.log(`[useAnalysis] SSE failed event received`);
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

      // Built-in error handler
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

  return { progress, result, isComplete, error };
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
