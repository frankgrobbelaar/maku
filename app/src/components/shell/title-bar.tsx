import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, X } from "lucide-react";
import type { ReactNode } from "react";
import { MakuLogo } from "@/components/maku-logo";
import { LibrarySearch } from "./library-search";

/**
 * Maku draws its own title bar (the window has no Windows frame). Drag it to
 * move the window; double-click it to maximise. In the middle, with `search`,
 * the library's search. It takes the pointer even while a card holds the
 * rest of the window, which a press here closes.
 */
export function TitleBar({ title = "Maku", search = false }: { title?: string; search?: boolean }) {
  return (
    <header
      data-tauri-drag-region
      className="pointer-events-auto flex min-h-13 shrink-0 items-center gap-3 pl-5 select-none"
    >
      <div data-tauri-drag-region className="flex min-w-0 flex-[1_1_160px] items-center gap-2.5">
        <span className="pointer-events-none flex items-center gap-2.5">
          <MakuLogo />
          <span className="font-extrabold text-14">{title}</span>
        </span>
      </div>
      {search && <LibrarySearch />}
      <div data-tauri-drag-region className="flex flex-[1_1_160px] justify-end">
        <WindowButton label="Minimize" onClick={() => getCurrentWindow().minimize()}>
          <Minus size={14} strokeWidth={1.6} />
        </WindowButton>
        <WindowButton label="Maximize" onClick={() => getCurrentWindow().toggleMaximize()}>
          <Square size={12} strokeWidth={1.6} />
        </WindowButton>
        <WindowButton label="Close" onClick={() => getCurrentWindow().close()}>
          <X size={14} strokeWidth={1.6} />
        </WindowButton>
      </div>
    </header>
  );
}

function WindowButton(props: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={props.label}
      onClick={props.onClick}
      className="inline-flex h-13 w-11.5 cursor-pointer items-center justify-center text-fg transition-colors duration-120 hover:bg-tint/8"
    >
      {props.children}
    </button>
  );
}
