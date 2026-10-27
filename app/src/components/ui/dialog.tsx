import { Eye, EyeOff, X } from "lucide-react";
import { Dialog as Primitive } from "radix-ui";
import {
  type ComponentProps,
  type ReactNode,
  type RefObject,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

// Adapted from shadcn/ui's dialog (MIT, see LICENSE-shadcn.txt), restyled to Cinema: a card over
// the page it tells more of, below the title bar, the page (the small player too) dimming behind
// it. It can carry a picture across its top (DialogPicture), its cross on the picture; without one
// it has a header (DialogHeader). Escape, the cross or a click beside it closes it; so does the
// title bar, which keeps working (it lets the pointer through: TitleBar).

export const Dialog = Primitive.Root;

export function DialogContent({
  className,
  children,
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: ComponentProps<typeof Primitive.Content>) {
  const content = useRef<HTMLDivElement>(null);
  // Where the focus goes back to as it closes: what had it outside the card last. Opened from a
  // row's menu, that's the menu's button, which the menu gives the focus back to as it closes. A
  // menu's own items don't count, the card's or a row's: they're gone once it closes.
  const back = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const outside = (target: unknown): target is HTMLElement =>
      target instanceof HTMLElement &&
      target !== document.body &&
      !content.current?.contains(target) &&
      !target.closest("[data-radix-popper-content-wrapper]");
    if (outside(document.activeElement)) back.current = document.activeElement;
    const note = (event: FocusEvent) => {
      if (outside(event.target)) back.current = event.target;
    };
    document.addEventListener("focusin", note);
    return () => document.removeEventListener("focusin", note);
  }, []);
  return (
    <Primitive.Portal>
      <Primitive.Overlay className="fixed inset-x-0 top-13 bottom-0 z-55 animate-fade-in bg-window/70" />
      <Primitive.Content
        {...props}
        ref={content}
        data-slot="dialog"
        className={cn(
          "fixed inset-x-0 top-[calc(3.25rem+6vh)] z-55 mx-auto flex max-h-[calc(100vh-3.25rem-6vh-2rem)] w-[min(40rem,calc(100vw-2rem))] animate-card-in flex-col overflow-hidden rounded-28 border border-edge bg-dialog shadow-dialog outline-none",
          className,
        )}
        // The card itself takes the focus as it opens, not its first button: the keyboard goes on
        // from there, and nothing in it looks picked before anything is.
        onOpenAutoFocus={(event) => {
          onOpenAutoFocus?.(event);
          if (event.defaultPrevented) return;
          event.preventDefault();
          content.current?.focus({ preventScroll: true });
        }}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event);
          if (event.defaultPrevented) return;
          event.preventDefault();
          if (back.current?.isConnected) back.current.focus();
        }}
      >
        {children}
      </Primitive.Content>
    </Primitive.Portal>
  );
}

/** A card's heading: what it's about, which names it for screen readers too. */
export function DialogTitle({ className, ...props }: ComponentProps<typeof Primitive.Title>) {
  return <Primitive.Title className={cn("font-extrabold leading-tight", className)} {...props} />;
}

/** The line under a card's heading ("TV series · 2019"). Every card has one. */
export function DialogDescription({
  className,
  ...props
}: ComponentProps<typeof Primitive.Description>) {
  return <Primitive.Description className={cn("text-13 text-fg-muted", className)} {...props} />;
}

/** A card without a picture: its heading, the line under it, and its cross. */
export function DialogHeader({ title, description }: { title: ReactNode; description: ReactNode }) {
  return (
    <header className="flex shrink-0 items-start gap-3 border-rule border-b px-6 pt-5 pb-4">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <DialogTitle className="text-18">{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </div>
      <Primitive.Close
        aria-label="Close"
        className="press -mt-1 -mr-2 inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-fg-muted hover:bg-tint/8 hover:text-fg"
      >
        <X size={18} aria-hidden="true" />
      </Primitive.Close>
    </header>
  );
}

/**
 * A picture across a card's top, dark in light mode too, as a picture is: a still from the
 * episode, say, or a cover blurred into a backdrop. While it loads the band waits in the featured
 * blue; with none to show, the boards' stand-in, the blue with its orange orb. The cross sits on
 * it, a tag in its top corner, and on its lower edge what the card leads with (its heading, or
 * Play), with how far a video was watched along its foot. One that could give a story away stays
 * blurred till asked ("Show the picture").
 */
export function DialogPicture(props: {
  /** The picture's address, or null while there's none yet. */
  src: string | null;
  /** There's none to show: the stand-in takes its place. */
  none?: boolean;
  /** Blurred and dimmed into a backdrop, for a tall cover that can't fill the band. */
  blur?: boolean;
  /** From an episode not watched yet: blurred till asked. */
  spoiler?: boolean;
  /** A tag in its top corner: the episode's code, or what a title is. */
  tag?: ReactNode;
  /** How much of the video was watched, 0 to 1, or null for none. */
  progress?: number | null;
  children?: ReactNode;
}) {
  const { src, progress } = props;
  const [asked, setAsked] = useState(false);
  const hidden = props.spoiler === true && src !== null && !asked;
  // "Show the picture" turns into "Hide the picture" and back: the keyboard's focus goes with it.
  const turned = useRef(false);
  const turn = (button: HTMLButtonElement) => {
    turned.current = button === document.activeElement;
    setAsked(!asked);
  };
  const focusTurned = (button: HTMLButtonElement | null) => {
    if (!button || !turned.current) return;
    turned.current = false;
    button.focus();
  };
  return (
    <div className="scheme-dark relative h-[min(13rem,28vh)] shrink-0 overflow-hidden bg-featured text-fg">
      {src ? (
        <img
          key={src}
          src={src}
          alt=""
          className={cn(
            "absolute inset-0 size-full animate-fade-in object-cover transition-[filter,scale] duration-200 ease-cinema",
            // Grown a little, so the blur's soft rim falls outside the band.
            props.blur && "scale-125 opacity-60 blur-2xl",
            hidden && "scale-125 blur-2xl",
          )}
        />
      ) : (
        props.none && (
          <span
            aria-hidden="true"
            className="-top-[45%] absolute right-[12%] aspect-square w-[42%] rounded-full bg-featured-orb"
          />
        )
      )}
      <span
        aria-hidden="true"
        className="absolute inset-x-0 bottom-0 h-30 bg-linear-to-b from-transparent to-dialog/92"
      />
      {props.tag && (
        <span className="absolute top-4.5 left-5 inline-flex h-6.5 items-center rounded-full bg-tag px-2.5 font-bold text-12">
          {props.tag}
        </span>
      )}
      {props.spoiler &&
        src !== null &&
        (hidden ? (
          <button
            ref={focusTurned}
            type="button"
            onClick={(event) => turn(event.currentTarget)}
            className="press absolute top-3.5 left-1/2 inline-flex h-9 -translate-x-1/2 cursor-pointer items-center gap-1.5 rounded-full bg-tag px-3.5 font-extrabold text-12"
          >
            <Eye size={15} aria-hidden="true" />
            Show the picture
          </button>
        ) : (
          <button
            ref={focusTurned}
            type="button"
            aria-label="Hide the picture"
            title="Hide the picture"
            onClick={(event) => turn(event.currentTarget)}
            className="press absolute top-3.5 left-1/2 inline-flex size-9 -translate-x-1/2 cursor-pointer items-center justify-center rounded-full bg-tag"
          >
            <EyeOff size={15} aria-hidden="true" />
          </button>
        ))}
      <Primitive.Close
        aria-label="Close"
        className="press absolute top-3.5 right-4 inline-flex size-9 cursor-pointer items-center justify-center rounded-full bg-tag"
      >
        <X size={16} aria-hidden="true" />
      </Primitive.Close>
      {props.children && (
        <div className="absolute inset-x-6 bottom-5 flex items-end">{props.children}</div>
      )}
      {progress !== null && progress !== undefined && (
        <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-1 bg-black/40">
          <span className="block h-full bg-accent" style={{ width: `${progress * 100}%` }} />
        </span>
      )}
    </div>
  );
}

/** What a card says, under its picture or header: it scrolls in its place when it's long. */
export function DialogBody({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 pt-4.5 pb-5.5",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** A card's foot, which stays put while its body scrolls. */
export function DialogFooter({
  children,
  at,
}: {
  children: ReactNode;
  at?: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      ref={at}
      className="flex shrink-0 items-center justify-between gap-3 border-rule border-t px-4 py-2.5"
    >
      {children}
    </div>
  );
}
