import { Check, KeyRound } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConnectTmdb, useForgetTmdb, useTmdb } from "@/lib/engine";
import { openTmdbApiPage } from "@/lib/links";

/**
 * The TMDB key: where to find it, pasting it in (Maku checks it with TMDB before keeping it), and
 * removing it. Without it Maku reads the videos but can't tell which series or film each is.
 */
export function TmdbKey() {
  const tmdb = useTmdb();
  const connect = useConnectTmdb();
  const forget = useForgetTmdb();
  const [key, setKey] = useState("");
  const field = useId();
  const connected = tmdb.data?.connected ?? false;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!key.trim()) return;
    connect.mutate({ path: "/tmdb", body: { key } }, { onSuccess: () => setKey("") });
  }

  return (
    <div className="flex flex-col gap-3 rounded-16 border border-edge bg-glass px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-0.5">
          <span className="font-extrabold text-15">TMDB</span>
          <span className="text-13 text-fg-muted">
            Maku finds your series and films on TMDB, with your own free key. Without one, it reads
            your videos but can't tell what they are.
          </span>
        </div>
        {connected && (
          <span className="inline-flex items-center gap-2 font-bold text-13 text-accent-fg">
            <Check size={16} strokeWidth={3} aria-hidden="true" />
            Connected
          </span>
        )}
      </div>
      {connected ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-11 text-fg-faint">
            Key ending {tmdb.data?.keyEnd} · kept on this PC only
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={forget.isPending}
            onClick={() => forget.mutate({ path: "/tmdb" })}
          >
            Remove the key
          </Button>
        </div>
      ) : (
        <>
          <form onSubmit={submit} className="flex flex-wrap items-center gap-2.5">
            <label htmlFor={field} className="sr-only">
              TMDB API Read Access Token
            </label>
            <Input
              id={field}
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="Paste your API Read Access Token"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              className="flex-[1_1_320px]"
            />
            <Button type="submit" disabled={!key.trim() || connect.isPending}>
              {connect.isPending ? "Checking…" : "Connect"}
            </Button>
          </form>
          <p className="text-12 text-fg-muted">
            A free TMDB account has one under{" "}
            <button
              type="button"
              className="cursor-pointer text-accent-fg underline-offset-3 hover:text-accent-fg-hover hover:underline"
              onClick={() => void openTmdbApiPage()}
            >
              Settings › API
            </button>
            . Maku checks it with TMDB, then keeps it on this PC only.
          </p>
        </>
      )}
      {(connect.isError || forget.isError) && (
        <p role="alert" className="text-13 text-broken-fg">
          {(connect.error ?? forget.error)?.message}
        </p>
      )}
    </div>
  );
}

/**
 * Without a TMDB key Maku reads the videos but finds no series or film: one line to say so, and
 * the way to the key in Settings › Titles and artwork. Nothing shows once there's a key, nor while
 * Maku is still asking whether there is one.
 */
export function NoTmdbKey() {
  const tmdb = useTmdb();
  const navigate = useNavigate();
  if (tmdb.data?.connected !== false) return null;
  return (
    <div
      role="status"
      className="flex animate-fade-up flex-wrap items-center gap-3 rounded-20 border border-edge bg-glass px-5 py-3.5 shadow-panel"
    >
      <span
        aria-hidden="true"
        className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-accent/14 text-accent-fg"
      >
        <KeyRound size={18} />
      </span>
      <span className="min-w-0 flex-[1_1_320px] text-14">
        <strong className="font-extrabold">
          Maku needs your TMDB key to find your series and films.
        </strong>{" "}
        Your videos are read, and wait for it.
      </span>
      <Button size="sm" onClick={() => void navigate("/settings/titles")}>
        Add your key
      </Button>
    </div>
  );
}
