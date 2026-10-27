import { useRef, useState } from "react";
import { sizeName } from "@/lib/convert";
import { type Convertible, useEnginePicture } from "@/lib/engine";
import { clockTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Step } from "./convert-tabs";

const POINTS = [0.15, 0.5, 0.8]; // as the engine takes stills: 15%, 50% and 80% of the way in

/**
 * See it first: one frame of a file as it is, and as converting makes it, one over the other
 * with a handle to drag between them: deinterlaced, brought down to the standard, or only made
 * HEVC 10-bit. The engine makes the frames on asking and keeps them.
 */
export function SeeItFirst(props: { n: number; file: Convertible | null }) {
  const { file } = props;
  const [point, setPoint] = useState(1);
  const [split, setSplit] = useState(50);
  const [zoom, setZoom] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const before = useEnginePicture(
    file ? `/convert/${file.fileId}/preview/before?point=${point}` : null,
  );
  const after = useEnginePicture(
    file ? `/convert/${file.fileId}/preview/after?point=${point}` : null,
  );

  function follow(clientX: number) {
    const area = box.current?.getBoundingClientRect();
    if (!area || area.width === 0) return;
    setSplit(Math.min(100, Math.max(0, ((clientX - area.left) / area.width) * 100)));
  }

  return (
    <Step
      n={props.n}
      id="preview-title"
      title="See it first"
      note={file ? undefined : "Choose a file to see"}
    >
      {file && (
        <div className="-mt-1 flex flex-wrap items-center gap-2.5">
          <span className="text-13 text-fg-muted">{file.label} · drag the handle</span>
          <div className="ml-auto flex flex-wrap gap-1.5">
            {POINTS.map((share, index) => (
              <button
                key={share}
                type="button"
                aria-pressed={point === index}
                onClick={() => setPoint(index)}
                className={cn(
                  "press min-h-8.5 cursor-pointer rounded-full px-3 font-mono text-12",
                  point === index
                    ? "bg-accent/20 font-medium text-accent-fg"
                    : "bg-tint/6 text-fg-soft",
                )}
              >
                {clockTime(file.seconds * share)}
              </button>
            ))}
          </div>
        </div>
      )}
      {file && (
        <>
          <div
            ref={box}
            role="presentation"
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              follow(event.clientX);
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) follow(event.clientX);
            }}
            className="relative aspect-video w-full cursor-ew-resize touch-none select-none overflow-hidden rounded-18 bg-black scheme-dark"
          >
            {after.address && (
              <img
                src={after.address}
                alt=""
                draggable={false}
                className={cn(
                  "absolute inset-0 size-full object-contain transition-transform duration-320 ease-cinema",
                  zoom && "scale-200",
                )}
              />
            )}
            {before.address && (
              <img
                src={before.address}
                alt=""
                draggable={false}
                style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
                className={cn(
                  "absolute inset-0 size-full object-contain transition-transform duration-320 ease-cinema",
                  zoom && "scale-200",
                )}
              />
            )}
            <span
              aria-hidden="true"
              style={{ left: `${split}%` }}
              className="-ml-[1.5px] absolute inset-y-0 w-[3px] bg-white"
            />
            <span className="absolute top-3.5 left-3.5 inline-flex h-7 items-center rounded-full bg-black/60 px-3 font-bold text-12 text-white">
              Before · original {sizeName(file.width, file.height)}
            </span>
            <span className="absolute top-3.5 right-3.5 inline-flex h-7 items-center rounded-full bg-accent/92 px-3 font-extrabold text-12 text-on-accent">
              After · {file.method === "remux" ? "as it is" : "HEVC 10-bit"}{" "}
              {sizeName(file.outputWidth, file.outputHeight)}
            </span>
            {!after.address && (
              <span
                className={cn(
                  "absolute inset-x-6 bottom-6 text-center text-13",
                  after.problem ? "text-broken-fg" : "animate-pulse text-fg-muted",
                )}
              >
                {after.problem ?? "Making the after picture…"}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <fieldset className="inline-flex gap-1 rounded-20 bg-well p-1">
              <legend className="sr-only">Zoom</legend>
              {[false, true].map((close) => (
                <button
                  key={String(close)}
                  type="button"
                  aria-pressed={zoom === close}
                  onClick={() => setZoom(close)}
                  className={cn(
                    "press min-h-8.5 cursor-pointer rounded-full px-3.5 text-13",
                    zoom === close
                      ? "bg-tint/12 font-extrabold text-tint"
                      : "font-bold text-fg-soft",
                  )}
                >
                  {close ? "Zoom 2×" : "Fit"}
                </button>
              ))}
            </fieldset>
            <label className="flex items-center gap-2.5 text-12 text-fg-muted">
              Where it splits
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(split)}
                onChange={(event) => setSplit(Number(event.target.value))}
                className="w-36 accent-accent"
              />
            </label>
          </div>
        </>
      )}
    </Step>
  );
}
