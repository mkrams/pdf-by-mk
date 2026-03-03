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
      const res = await fetch(`${API}/api/analyze/${id}/result`);
      if (!res.ok) return false;
      const data = await res.json();
      if (data.status === 'completed') {
        setResult(data);
        setIsComplete(true);
        return true;
      } else if (data.status === 'failed') {
        setError(data.error || 'Analysis failed');
        setIsComplete(true);  // Mark complete so we don't show progress bar
        return true;
      }
    } catch {
      // Network error — don't set error state, just return false
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
        // Already finished — don't connect SSE at all
        return;
      }

      // Not finished yet — connect SSE for live progress
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
        await fetchResult(jobId);
      });

      // Listen for "failed" named event (backend sends event: failed)
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

      // Built-in error handler — fires on network issues or when server closes
      es.addEventListener('error', () => {
        if (cancelled) return;
        if (es.readyState === EventSource.CLOSED) {
          // Connection was closed by server — try fetching result
          fetchResult(jobId);
        }
        // If CONNECTING, EventSource will auto-reconnect (that's fine)
      });
    });

    // Poll every 8s as fallback (handles tab reopen, SSE drops)
    const poll = setInterval(() => {
      // Use refs to avoid stale closure
      if (!isCompleteRef.current && !errorRef.current) {
        fetchResult(jobId).then(done => {
          if (done && esRef.current) {
            // If poll found it's done, close SSE
            esRef.current.close();
            esRef.current = null;
          }
        });
      }
    }, 8000);

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
