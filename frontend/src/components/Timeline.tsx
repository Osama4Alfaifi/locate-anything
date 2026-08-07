import type { ClipMatch } from "../api/types";

interface Props {
  durationS: number;
  matches: ClipMatch[];
  selectedFrameId: string | null;
  onSelect: (match: ClipMatch) => void;
}

function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function Timeline({ durationS, matches, selectedFrameId, onSelect }: Props) {
  const durationMs = Math.max(durationS * 1000, 1);

  return (
    <div className="panel p-4">
      <div className="mb-2 flex items-center justify-between font-mono text-xs text-ash">
        <span>
          <span className="text-lime">{matches.length}</span> match{matches.length === 1 ? "" : "es"}
        </span>
        <span>{formatTime(durationMs)}</span>
      </div>

      {matches.length === 0 ? (
        <div className="flex h-10 items-center justify-center rounded-md border border-dashed border-edge font-mono text-[11px] uppercase tracking-wider text-ash/60">
          no matches yet
        </div>
      ) : (
        <div className="relative h-10 rounded-md border border-edge bg-ink/60">
          {matches.map((m) => {
            const pct = Math.min(100, Math.max(0, (m.timestamp_ms / durationMs) * 100));
            const selected = m.frame_id === selectedFrameId;
            return (
              <button
                key={m.frame_id}
                type="button"
                onClick={() => onSelect(m)}
                title={formatTime(m.timestamp_ms)}
                aria-label={`Jump to ${formatTime(m.timestamp_ms)}`}
                className={`absolute top-1/2 h-6 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-sm transition-colors ${
                  selected ? "bg-lime shadow-glow" : "bg-lime/40 hover:bg-lime/70"
                }`}
                style={{ left: `${pct}%` }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
