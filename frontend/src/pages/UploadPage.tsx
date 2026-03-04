import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { startAnalysis } from '../hooks/useAnalysis';

/* ── Miami Vice SVG cityscape ──────────────────────────────────── */
function Skyline() {
  return (
    <svg viewBox="0 0 1200 400" className="absolute bottom-0 left-0 w-full" preserveAspectRatio="xMidYMax slice" style={{ opacity: 0.35 }}>
      {/* Sun */}
      <defs>
        <linearGradient id="sunGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ff2d95" />
          <stop offset="100%" stopColor="#ffb347" />
        </linearGradient>
        <linearGradient id="skyGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="transparent" />
          <stop offset="100%" stopColor="rgba(255,45,149,0.15)" />
        </linearGradient>
      </defs>
      <rect width="1200" height="400" fill="url(#skyGrad)" />
      <circle cx="600" cy="320" r="120" fill="url(#sunGrad)" opacity="0.6" />
      {/* Horizontal lines through sun */}
      {[240, 260, 275, 288, 298, 306, 312, 317].map((y, i) => (
        <rect key={i} x="480" y={y} width="240" height="3" fill="rgba(20,0,40,0.5)" />
      ))}
      {/* Buildings */}
      <rect x="50" y="180" width="60" height="220" fill="#1a0a2e" />
      <rect x="55" y="185" width="12" height="8" fill="#ff2d95" opacity="0.4" />
      <rect x="75" y="195" width="12" height="8" fill="#00e5ff" opacity="0.3" />
      <rect x="120" y="140" width="80" height="260" fill="#1a0a2e" />
      <rect x="125" y="145" width="15" height="10" fill="#ff2d95" opacity="0.5" />
      <rect x="150" y="155" width="15" height="10" fill="#00e5ff" opacity="0.4" />
      <rect x="165" y="175" width="15" height="10" fill="#ff2d95" opacity="0.3" />
      <rect x="210" y="200" width="50" height="200" fill="#120828" />
      <rect x="270" y="100" width="70" height="300" fill="#1a0a2e" />
      <rect x="275" y="105" width="14" height="10" fill="#00e5ff" opacity="0.5" />
      <rect x="305" y="125" width="14" height="10" fill="#ff2d95" opacity="0.4" />
      <rect x="350" y="160" width="55" height="240" fill="#120828" />
      <rect x="420" y="120" width="90" height="280" fill="#1a0a2e" />
      <rect x="430" y="125" width="18" height="12" fill="#ff2d95" opacity="0.6" />
      <rect x="465" y="140" width="18" height="12" fill="#00e5ff" opacity="0.4" />
      {/* Tall center tower */}
      <rect x="560" y="60" width="80" height="340" fill="#1a0a2e" />
      <rect x="575" y="65" width="50" height="8" fill="#ff2d95" opacity="0.7" />
      <rect x="580" y="85" width="14" height="10" fill="#00e5ff" opacity="0.5" />
      <rect x="610" y="95" width="14" height="10" fill="#ff2d95" opacity="0.4" />
      {/* Right side */}
      <rect x="660" y="130" width="70" height="270" fill="#120828" />
      <rect x="740" y="170" width="60" height="230" fill="#1a0a2e" />
      <rect x="810" y="110" width="85" height="290" fill="#1a0a2e" />
      <rect x="820" y="115" width="16" height="10" fill="#00e5ff" opacity="0.5" />
      <rect x="860" y="135" width="16" height="10" fill="#ff2d95" opacity="0.4" />
      <rect x="905" y="190" width="55" height="210" fill="#120828" />
      <rect x="970" y="150" width="70" height="250" fill="#1a0a2e" />
      <rect x="1050" y="200" width="60" height="200" fill="#120828" />
      <rect x="1120" y="170" width="80" height="230" fill="#1a0a2e" />
      {/* Palm trees */}
      <g transform="translate(160,250)">
        <rect x="-3" y="0" width="6" height="120" rx="3" fill="#0d0520" />
        <ellipse cx="-30" cy="-5" rx="35" ry="8" fill="#0d0520" transform="rotate(-25)" />
        <ellipse cx="25" cy="-10" rx="32" ry="7" fill="#0d0520" transform="rotate(15)" />
        <ellipse cx="-10" cy="-15" rx="30" ry="7" fill="#0d0520" transform="rotate(-40)" />
        <ellipse cx="15" cy="-20" rx="28" ry="6" fill="#0d0520" transform="rotate(35)" />
      </g>
      <g transform="translate(950,260)">
        <rect x="-3" y="0" width="6" height="110" rx="3" fill="#0d0520" />
        <ellipse cx="-28" cy="-5" rx="33" ry="7" fill="#0d0520" transform="rotate(-20)" />
        <ellipse cx="22" cy="-8" rx="30" ry="7" fill="#0d0520" transform="rotate(20)" />
        <ellipse cx="-5" cy="-18" rx="28" ry="6" fill="#0d0520" transform="rotate(-35)" />
        <ellipse cx="10" cy="-15" rx="26" ry="6" fill="#0d0520" transform="rotate(30)" />
      </g>
      <g transform="translate(1100,270)">
        <rect x="-2" y="0" width="5" height="100" rx="2" fill="#0d0520" />
        <ellipse cx="-25" cy="-5" rx="30" ry="6" fill="#0d0520" transform="rotate(-22)" />
        <ellipse cx="20" cy="-8" rx="28" ry="6" fill="#0d0520" transform="rotate(18)" />
        <ellipse cx="0" cy="-16" rx="25" ry="5" fill="#0d0520" transform="rotate(-30)" />
      </g>
      {/* Water reflection */}
      <rect x="0" y="370" width="1200" height="30" fill="rgba(0,229,255,0.08)" />
      {/* Road / ground */}
      <rect x="0" y="390" width="1200" height="10" fill="#0d0520" />
    </svg>
  );
}

/* ── Retro grid background ─────────────────────────────────────── */
function RetroGrid() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none" style={{ perspective: '400px' }}>
      <div
        className="absolute left-0 right-0 bottom-0"
        style={{
          height: '40%',
          background: `
            linear-gradient(rgba(255,45,149,0.15) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,45,149,0.15) 1px, transparent 1px)
          `,
          backgroundSize: '60px 60px',
          transform: 'rotateX(60deg)',
          transformOrigin: 'bottom',
        }}
      />
    </div>
  );
}

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
    const isOld = side === 'old';
    const accent = isOld ? '#ff2d95' : '#00e5ff';
    const accentBg = isOld ? 'rgba(255,45,149,0.1)' : 'rgba(0,229,255,0.1)';
    const accentBorder = isOld ? 'rgba(255,45,149,0.5)' : 'rgba(0,229,255,0.5)';

    return (
      <div
        className="relative flex-1 border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer backdrop-blur-sm"
        style={{
          borderColor: file ? accent : dragOver ? accent : 'rgba(255,255,255,0.15)',
          background: file ? accentBg : dragOver ? accentBg : 'rgba(255,255,255,0.03)',
        }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
        onClick={() => {
          const input = document.createElement('input');
          input.type = 'file'; input.accept = '.pdf';
          input.onchange = (e: any) => { if (e.target.files[0]) onFile(e.target.files[0]); };
          input.click();
        }}
      >
        <div className="text-4xl mb-2" style={{ filter: `drop-shadow(0 0 8px ${accent})` }}>
          {file ? '\u2705' : '\uD83D\uDCC4'}
        </div>
        <div className="font-bold text-white/90 mb-1 text-sm tracking-wide">{label}</div>
        {file ? (
          <div className="text-xs font-medium" style={{ color: accent }}>
            {file.name} ({(file.size / 1024).toFixed(0)} KB)
          </div>
        ) : (
          <div className="text-xs text-white/30">Drop PDF here or click to browse</div>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen relative overflow-hidden flex items-center justify-center p-4"
      style={{
        background: 'linear-gradient(180deg, #0a001a 0%, #1a0533 30%, #2d0a4e 60%, #1a0a3e 100%)',
      }}>

      {/* Version info — top left */}
      <div className="absolute top-3 left-4 z-20 text-[10px] font-mono text-white/20">
        v1.2.0 · {__BUILD_TIME__ || '—'}
      </div>

      {/* Background layers */}
      <RetroGrid />
      <Skyline />

      {/* Floating neon particles */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        {[...Array(6)].map((_, i) => (
          <div key={i}
            className="absolute rounded-full animate-pulse"
            style={{
              width: 3 + Math.random() * 4,
              height: 3 + Math.random() * 4,
              left: `${10 + Math.random() * 80}%`,
              top: `${10 + Math.random() * 60}%`,
              background: i % 2 === 0 ? '#ff2d95' : '#00e5ff',
              opacity: 0.3 + Math.random() * 0.3,
              animationDuration: `${2 + Math.random() * 3}s`,
              boxShadow: `0 0 ${8 + Math.random() * 12}px ${i % 2 === 0 ? '#ff2d95' : '#00e5ff'}`,
            }}
          />
        ))}
      </div>

      {/* Main card */}
      <div className="relative z-10 w-full max-w-2xl">
        <div className="rounded-2xl p-8 backdrop-blur-md"
          style={{
            background: 'rgba(15, 5, 30, 0.75)',
            border: '1px solid rgba(255,255,255,0.08)',
            boxShadow: '0 0 60px rgba(255,45,149,0.1), 0 0 120px rgba(0,229,255,0.05), 0 25px 50px rgba(0,0,0,0.5)',
          }}>

          {/* Title */}
          <div className="text-center mb-8">
            <h1 className="text-5xl font-black italic tracking-tight mb-3"
              style={{
                background: 'linear-gradient(135deg, #ff2d95 0%, #ff6fb5 30%, #00e5ff 70%, #00b8d4 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                textShadow: 'none',
                filter: 'drop-shadow(0 0 20px rgba(255,45,149,0.3))',
              }}>
              PDF by MK
            </h1>
            <p className="text-white/40 text-sm tracking-widest uppercase">
              AI-Powered Document Comparison
            </p>
          </div>

          <form onSubmit={handleSubmit}>
            {/* Drop zones */}
            <div className="flex gap-4 mb-6">
              <DropZone label="OLD VERSION" file={oldFile} onFile={setOldFile} side="old" />
              <div className="flex items-center text-2xl font-bold"
                style={{
                  background: 'linear-gradient(180deg, #ff2d95, #00e5ff)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                }}>
                &#x2192;
              </div>
              <DropZone label="NEW VERSION" file={newFile} onFile={setNewFile} side="new" />
            </div>

            {/* Labels */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-[10px] font-medium text-white/30 mb-1 uppercase tracking-wider">Old version label</label>
                <input type="text" value={oldLabel} onChange={e => setOldLabel(e.target.value)}
                  placeholder={oldFile?.name.replace('.pdf', '') || 'e.g., Rev D1 2013'}
                  className="w-full px-3 py-2 rounded-lg text-sm text-white/90 placeholder-white/20 focus:outline-none focus:ring-2"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }} />
              </div>
              <div>
                <label className="block text-[10px] font-medium text-white/30 mb-1 uppercase tracking-wider">New version label</label>
                <input type="text" value={newLabel} onChange={e => setNewLabel(e.target.value)}
                  placeholder={newFile?.name.replace('.pdf', '') || 'e.g., Rev E 2021'}
                  className="w-full px-3 py-2 rounded-lg text-sm text-white/90 placeholder-white/20 focus:outline-none focus:ring-2"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }} />
              </div>
            </div>

            {/* API Key */}
            <div className="mb-6">
              <label className="block text-[10px] font-medium text-white/30 mb-1 uppercase tracking-wider">Anthropic API Key (optional)</label>
              <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                placeholder="sk-ant-..."
                className="w-full px-3 py-2 rounded-lg text-sm text-white/90 placeholder-white/20 focus:outline-none focus:ring-2"
                style={{
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(255,255,255,0.08)',
                }} />
            </div>

            {error && (
              <div className="text-sm mb-4 p-3 rounded-lg"
                style={{ background: 'rgba(255,45,149,0.15)', color: '#ff6fb5', border: '1px solid rgba(255,45,149,0.3)' }}>
                {error}
              </div>
            )}

            {/* Submit button */}
            <button type="submit" disabled={loading || !oldFile || !newFile}
              className="w-full py-3.5 font-bold text-white rounded-xl transition-all disabled:opacity-30 disabled:cursor-not-allowed text-sm uppercase tracking-widest"
              style={{
                background: (loading || !oldFile || !newFile)
                  ? 'rgba(255,255,255,0.1)'
                  : 'linear-gradient(135deg, #ff2d95 0%, #d926ff 50%, #00e5ff 100%)',
                boxShadow: (loading || !oldFile || !newFile) ? 'none' : '0 0 30px rgba(255,45,149,0.4), 0 0 60px rgba(0,229,255,0.2)',
              }}>
              {loading ? 'Firing up the engine...' : 'Analyze Changes'}
            </button>
          </form>

          <div className="mt-6 text-center text-[10px] text-white/20 tracking-wider uppercase">
            Powered by Claude AI &middot; Drop any PDF pair up to 50 pages
          </div>
        </div>
      </div>
    </div>
  );
}
