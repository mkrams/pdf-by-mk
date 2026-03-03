import React, { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { startAnalysis } from '../hooks/useAnalysis';

export default function UploadPage() {
  const navigate = useNavigate();
  const [oldFile, setOldFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);
  const [oldLabel, setOldLabel] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!oldFile || !newFile) { setError('Please select both PDFs'); return; }
    setLoading(true);
    setError('');
    try {
      const { job_id } = await startAnalysis(
        oldFile, newFile,
        oldLabel || oldFile.name.replace('.pdf', ''),
        newLabel || newFile.name.replace('.pdf', ''),
        apiKey || undefined,
      );
      navigate(`/analyze/${job_id}`);
    } catch (err: any) {
      setError(err.message || 'Failed to start analysis');
      setLoading(false);
    }
  };

  const DropZone = ({ label, file, onFile, side }: {
    label: string; file: File | null; onFile: (f: File) => void; side: 'old' | 'new';
  }) => {
    const [dragOver, setDragOver] = useState(false);
    const color = side === 'old' ? 'red' : 'green';
    return (
      <div
        className={`relative flex-1 border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer
          ${dragOver ? `border-${color}-400 bg-${color}-50` : 'border-gray-300 hover:border-gray-400'}
          ${file ? `border-${color}-300 bg-${color}-50/50` : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
        onClick={() => { const input = document.createElement('input'); input.type = 'file'; input.accept = '.pdf'; input.onchange = (e: any) => { if (e.target.files[0]) onFile(e.target.files[0]); }; input.click(); }}
      >
        <div className="text-4xl mb-2">{side === 'old' ? '📄' : '📄'}</div>
        <div className="font-semibold text-gray-700 mb-1">{label}</div>
        {file ? (
          <div className={`text-sm text-${color}-600 font-medium`}>{file.name} ({(file.size / 1024).toFixed(0)} KB)</div>
        ) : (
          <div className="text-sm text-gray-400">Drop PDF here or click to select</div>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">PDF by MK</h1>
          <p className="text-gray-500">AI-powered document comparison with verified change analysis</p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="flex gap-4 mb-6">
            <DropZone label="Old Version" file={oldFile} onFile={setOldFile} side="old" />
            <div className="flex items-center text-2xl text-gray-300">→</div>
            <DropZone label="New Version" file={newFile} onFile={setNewFile} side="new" />
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Old version label (optional)</label>
              <input type="text" value={oldLabel} onChange={e => setOldLabel(e.target.value)}
                placeholder={oldFile?.name.replace('.pdf', '') || 'e.g., Rev D1 2013'}
                className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">New version label (optional)</label>
              <input type="text" value={newLabel} onChange={e => setNewLabel(e.target.value)}
                placeholder={newFile?.name.replace('.pdf', '') || 'e.g., Rev E 2021'}
                className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
            </div>
          </div>

          <div className="mb-6">
            <label className="block text-xs font-medium text-gray-500 mb-1">Anthropic API Key (optional — uses server key if blank)</label>
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder="sk-ant-..."
              className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
          </div>

          {error && <div className="text-red-600 text-sm mb-4 p-3 bg-red-50 rounded-lg">{error}</div>}

          <button type="submit" disabled={loading || !oldFile || !newFile}
            className="w-full py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all">
            {loading ? 'Starting analysis...' : 'Analyze Changes'}
          </button>
        </form>

        <div className="mt-6 text-center text-xs text-gray-400">
          Powered by Claude AI. Supports any PDF document pair up to 50 pages each.
        </div>
      </div>
    </div>
  );
}
