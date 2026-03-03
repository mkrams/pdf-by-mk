import { useState, useEffect, useCallback } from 'react';
import type { AnalysisResult, ProgressEvent } from '../types';

const API = import.meta.env.VITE_API_URL || '';

export function useAnalysis(jobId: string | null) {
  const [progress, setProgress] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const es = new EventSource(`${API}/api/analyze/${jobId}/progress`);

    es.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data) as ProgressEvent;
      setProgress((prev) => [...prev, data]);
    });

    es.addEventListener('complete', async (e) => {
      const data = JSON.parse(e.data);
      setProgress((prev) => [...prev, { stage: 'complete', percent: 100, message: data.message || 'Complete' }]);
      es.close();

      // Fetch full result
      try {
        const res = await fetch(`${API}/api/analyze/${jobId}/result`);
        if (res.ok) {
          const resultData = await res.json();
          setResult(resultData);
          setIsComplete(true);
        } else {
          setError('Failed to fetch results');
        }
      } catch (err) {
        setError(String(err));
      }
    });

    es.addEventListener('error', (e) => {
      // Check if it's a real error or just SSE reconnect
      if (es.readyState === EventSource.CLOSED) {
        // Might be done - try fetching result
        fetch(`${API}/api/analyze/${jobId}/result`)
          .then(r => r.json())
          .then(data => {
            if (data.status === 'completed') {
              setResult(data);
              setIsComplete(true);
            } else if (data.status === 'failed') {
              setError(data.error || 'Analysis failed');
            }
          })
          .catch(() => {});
      }
    });

    return () => es.close();
  }, [jobId]);

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
