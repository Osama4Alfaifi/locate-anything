import { useRef, useState } from "react";

interface Props {
  onFile: (file: File) => void;
  fileName?: string | null;
  /** `<input accept>` value, e.g. "video/*". Defaults to images. */
  accept?: string;
  /** Prefix used to validate dropped/picked files, e.g. "video/". Defaults to images. */
  mimePrefix?: string;
  /** Label shown in the dropzone, e.g. "drop video". Defaults to "drop image". */
  label?: string;
}

export default function UploadDropzone({
  onFile,
  fileName,
  accept = "image/*",
  mimePrefix = "image/",
  label = "drop image",
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const isImage = mimePrefix === "image/";

  function pick(files: FileList | null) {
    const f = files?.[0];
    if (f && f.type.startsWith(mimePrefix)) onFile(f);
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          pick(e.dataTransfer.files);
        }}
        className={`group flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-7 text-center transition-colors ${
          drag ? "border-lime bg-lime/10" : "border-edge hover:border-ash/60"
        }`}
      >
        <span className="font-mono text-2xl text-lime">[ + ]</span>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ash">
          {fileName ? (
            <span className="text-bone">{fileName}</span>
          ) : (
            <>
              {label} · <span className="text-bone underline-offset-2 group-hover:underline">browse</span>
            </>
          )}
        </span>
      </div>

      {isImage && (
        <button
          type="button"
          onClick={() => cameraRef.current?.click()}
          className="mt-2 w-full rounded-md border border-edge py-2 font-mono text-[11px] uppercase tracking-wider text-ash transition-colors hover:border-ash/60 hover:text-bone sm:hidden"
        >
          ⊙ use camera
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => pick(e.target.files)}
      />
      {isImage && (
        <input
          ref={cameraRef}
          type="file"
          accept={accept}
          capture="environment"
          className="hidden"
          onChange={(e) => pick(e.target.files)}
        />
      )}
    </div>
  );
}
