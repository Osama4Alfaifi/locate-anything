import { useMemo, useRef, useState } from "react";

import { resolveUrl } from "../api/client";
import {
  useCancelClipSearch,
  useClip,
  useClipSearch,
  useHealth,
  useStartClipSearch,
  useTasks,
  useUploadClip,
} from "../api/hooks";
import type { ClipMatch, GenerationMode, TaskInfo } from "../api/types";
import InfoTip from "../components/InfoTip";
import Scope from "../components/Scope";
import Timeline from "../components/Timeline";
import UploadDropzone from "../components/UploadDropzone";
import { formatTime } from "../lib/time";

const MODES: GenerationMode[] = ["fast", "hybrid", "slow"];
const DECODE_HELP =
  "Speed vs. quality of box decoding, applied per sampled frame. fast = predict all boxes in " +
  "parallel. hybrid (default) = parallel first, falls back to careful decoding when unsure. " +
  "slow = fully sequential, most accurate but slowest across many frames.";

export default function DashcamPage() {
  const { data: tasks } = useTasks();
  const { data: health } = useHealth();
  const uploadClip = useUploadClip();
  const startSearch = useStartClipSearch();
  const cancelSearch = useCancelClipSearch();

  const [clipId, setClipId] = useState<string | null>(null);
  const [videoFileName, setVideoFileName] = useState<string | null>(null);
  const [task, setTask] = useState("ground_multi");
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<GenerationMode>("hybrid");
  const [readPlates, setReadPlates] = useState(false);
  const [searchId, setSearchId] = useState<string | null>(null);
  const [selectedMatch, setSelectedMatch] = useState<ClipMatch | null>(null);

  const { data: clip } = useClip(clipId);
  const { data: search } = useClipSearch(clipId, searchId);

  const spec: TaskInfo | undefined = useMemo(
    () => tasks?.find((t) => t.name === task) ?? tasks?.[0],
    [tasks, task],
  );

  const videoRef = useRef<HTMLVideoElement>(null);

  function chooseFile(f: File) {
    setVideoFileName(f.name);
    setClipId(null);
    setSearchId(null);
    setSelectedMatch(null);
    const form = new FormData();
    form.append("video", f);
    uploadClip.mutate(form, { onSuccess: (c) => setClipId(c.id) });
  }

  function runSearch() {
    if (!clipId || !spec) return;
    const form = new FormData();
    form.append("task", task);
    form.append("prompt", prompt);
    form.append("generation_mode", mode);
    form.append("read_plates", String(readPlates));
    setSelectedMatch(null);
    startSearch.mutate({ clipId, form }, { onSuccess: (s) => setSearchId(s.id) });
  }

  function selectMatch(m: ClipMatch) {
    setSelectedMatch(m);
    if (videoRef.current) {
      videoRef.current.currentTime = m.timestamp_ms / 1000;
      videoRef.current.pause();
    }
  }

  const modelLoading = health?.status === "loading";
  const modelError = health?.status === "error";
  const promptRequired = spec ? spec.input_kind !== "none" : true;
  const clipReady = clip?.status === "ready";
  const searchRunning = search?.status === "queued" || search?.status === "running";
  const canSearch =
    clipReady &&
    (!promptRequired || prompt.trim().length > 0) &&
    !searchRunning &&
    !modelLoading &&
    !modelError;

  const scopeSrc = selectedMatch ? resolveUrl(selectedMatch.image_url) : null;
  const scopeBoxes = useMemo(() => {
    if (!selectedMatch) return [];
    const plateBoxes = selectedMatch.plate_reads.map((pr) => ({ ...pr.box, label: pr.text }));
    return [...selectedMatch.boxes, ...plateBoxes];
  }, [selectedMatch]);

  const bestPlateRead = useMemo(() => {
    const all = (search?.matches ?? []).flatMap((m) =>
      m.plate_reads.map((pr) => ({ ...pr, timestamp_ms: m.timestamp_ms })),
    );
    return all.length === 0 ? null : all.reduce((best, pr) => (pr.confidence > best.confidence ? pr : best));
  }, [search?.matches]);

  return (
    <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[360px_1fr]">
      {/* Console */}
      <section className="space-y-5">
        <div>
          <p className="label-kicker mb-2">dashcam clip</p>
          <UploadDropzone
            onFile={chooseFile}
            fileName={videoFileName}
            accept="video/*"
            mimePrefix="video/"
            label="drop video"
          />
          {uploadClip.isPending && <p className="mt-2 font-mono text-xs text-amber">Uploading…</p>}
          {uploadClip.isError && (
            <p className="mt-2 font-mono text-xs text-rose">{(uploadClip.error as Error).message}</p>
          )}
          {clip?.status === "extracting" && (
            <p className="mt-2 font-mono text-xs text-amber">Extracting frames…</p>
          )}
          {clip?.status === "error" && (
            <p className="mt-2 font-mono text-xs text-rose">{clip.error ?? "Extraction failed."}</p>
          )}
          {clip?.status === "ready" && (
            <p className="mt-2 font-mono text-xs text-ash">
              <span className="text-lime">{clip.frame_count}</span> frames sampled ·{" "}
              {clip.duration_s?.toFixed(0)}s clip
            </p>
          )}
        </div>

        <div>
          <p className="label-kicker mb-2">task</p>
          <div className="grid grid-cols-2 gap-2">
            {tasks?.map((t) => (
              <div key={t.name} className="relative flex">
                <button
                  onClick={() => setTask(t.name)}
                  className={`chip flex-1 pr-7 ${task === t.name ? "chip-on" : "chip-off"}`}
                >
                  {t.label}
                </button>
                <span className="absolute right-1.5 top-1/2 -translate-y-1/2">
                  <InfoTip text={t.description} align="right" label={`About ${t.label}`} />
                </span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <p className="label-kicker mb-2">{spec?.input_kind === "categories" ? "categories" : "prompt"}</p>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={!promptRequired}
            rows={2}
            placeholder={spec?.placeholder ?? ""}
            className="w-full resize-none rounded-md border border-edge bg-ink/60 px-3 py-2 font-mono text-sm text-bone placeholder:text-ash/50 focus:border-lime/60 focus:outline-none disabled:opacity-40"
          />
        </div>

        <div>
          <div className="mb-2 flex items-center gap-2">
            <p className="label-kicker">decode mode</p>
            <InfoTip text={DECODE_HELP} label="About decode modes" />
          </div>
          <div className="flex overflow-hidden rounded-md border border-edge">
            {MODES.map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 py-2 font-mono text-[11px] uppercase tracking-wider transition-colors ${
                  mode === m ? "bg-lime/15 text-lime" : "text-ash hover:text-bone"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center gap-2 font-mono text-xs text-ash">
          <input
            type="checkbox"
            checked={readPlates}
            onChange={(e) => setReadPlates(e.target.checked)}
            className="h-3.5 w-3.5 accent-lime"
          />
          also read license plates
        </label>

        <button
          onClick={runSearch}
          disabled={!canSearch}
          className="ticks w-full rounded-md bg-lime py-3 font-display text-sm font-bold uppercase tracking-widest text-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-25"
        >
          {searchRunning
            ? `scanning ${search?.frames_done ?? 0}/${search?.frames_total ?? 0}…`
            : modelLoading
              ? "loading model…"
              : "▸ search clip"}
        </button>

        {searchRunning && search && clipId && (
          <div className="space-y-2">
            <div className="h-1.5 overflow-hidden rounded-full bg-ink/60">
              <div
                className="h-full bg-lime transition-all"
                style={{
                  width: `${
                    search.frames_total ? (search.frames_done / search.frames_total) * 100 : 0
                  }%`,
                }}
              />
            </div>
            <button
              onClick={() => cancelSearch.mutate({ clipId, searchId: search.id })}
              className="w-full rounded-md border border-edge py-1.5 font-mono text-[11px] uppercase tracking-wider text-ash transition-colors hover:border-rose/60 hover:text-rose"
            >
              cancel
            </button>
          </div>
        )}

        {modelLoading && (
          <p className="font-mono text-xs text-amber">
            Model is loading — this can take a minute on first run.
          </p>
        )}
        {modelError && (
          <p className="font-mono text-xs text-rose">Model failed to load. Check the System page.</p>
        )}
        {startSearch.isError && (
          <p className="font-mono text-xs text-rose">{(startSearch.error as Error).message}</p>
        )}
        {search?.status === "error" && (
          <p className="font-mono text-xs text-rose">{search.error ?? "Search failed."}</p>
        )}
      </section>

      {/* Viewport */}
      <section className="space-y-4">
        {clip && (
          <video
            ref={videoRef}
            src={resolveUrl(clip.video_url)}
            controls
            className="w-full rounded-lg border border-edge bg-black"
          />
        )}

        <Scope src={scopeSrc} boxes={scopeBoxes} points={selectedMatch?.points ?? []} />

        {search?.read_plates && search.status === "done" && (
          <div className="panel p-3 font-mono text-xs">
            {bestPlateRead ? (
              <p>
                <span className="text-ash">best plate read </span>
                <span className="text-lime">{bestPlateRead.text}</span>
                <span className="text-ash">
                  {" "}
                  · {Math.round(bestPlateRead.confidence * 100)}% · at{" "}
                  {formatTime(bestPlateRead.timestamp_ms)}
                </span>
              </p>
            ) : (
              <p className="text-ash">plate reading was on — no plates read.</p>
            )}
          </div>
        )}

        {clip && (
          <Timeline
            durationS={clip.duration_s ?? 0}
            matches={search?.matches ?? []}
            selectedFrameId={selectedMatch?.frame_id ?? null}
            onSelect={selectMatch}
          />
        )}
      </section>
    </div>
  );
}
