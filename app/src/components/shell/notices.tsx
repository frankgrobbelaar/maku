import { listen } from "@tauri-apps/api/event";
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { useEngineChanged } from "@/lib/engine";

/** A note from the engine. Mirrors `Notice` in app/src-tauri/src/tray.rs. */
interface Notice {
  title: string;
  body: string;
  /** Where in Maku it leads: "/titles/12". */
  link: string | null;
}

const SHOWN_FOR = 12_000; // milliseconds a note stays

/**
 * What the engine tells while the window is open (a batch done, the queue paused), one note at a
 * time at the foot of the window, for a few seconds: longer while it's pointed at or focused, and
 * till it's dismissed. Away from the window, Windows shows them. What the engine changed by itself
 * is asked again, so the screen behind shows it too.
 */
export function Notices() {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [held, setHeld] = useState(false); // pointed at or focused: it stays to be read
  const navigate = useNavigate();
  const engineChanged = useEngineChanged();
  const changed = useRef(engineChanged); // the listener, set up once, calls the latest
  changed.current = engineChanged;

  useEffect(() => {
    const stopListening = listen<Notice>("notice", (event) => {
      setNotice(event.payload);
      setHeld(false);
      changed.current();
    });
    return () => {
      stopListening.then((unlisten) => unlisten());
    };
  }, []);

  useEffect(() => {
    if (!notice || held) return;
    const timer = setTimeout(() => setNotice(null), SHOWN_FOR);
    return () => clearTimeout(timer);
  }, [notice, held]);

  if (!notice) return null;
  const { link } = notice;
  // The note is the featured panel, dark on a light page too (its accent and focus ring with
  // it); the shadow under it is the page's own, soft on a light page.
  return (
    <div
      role="status"
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      className="animate-pop rounded-18 shadow-toast"
    >
      <div className="flex items-center gap-3.5 rounded-18 bg-featured px-4 py-3.5 text-white scheme-dark">
        <span
          aria-hidden="true"
          className="relative size-11 shrink-0 overflow-hidden rounded-12 bg-white/12"
        >
          <span className="absolute -top-2.5 -right-2.5 size-8 rounded-full bg-featured-orb" />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-extrabold">{notice.title}</span>
          <span className="text-12 text-white/80">{notice.body}</span>
        </span>
        {link && (
          <Button
            size="sm"
            variant="primary"
            onClick={() => {
              setNotice(null);
              setHeld(false);
              void navigate(link);
            }}
          >
            View
          </Button>
        )}
        <button
          type="button"
          aria-label="Dismiss"
          onClick={() => {
            setNotice(null);
            setHeld(false);
          }}
          className="press inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full text-white/70 hover:text-white"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
