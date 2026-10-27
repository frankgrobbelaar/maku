import { type TitleSummary, usePoster } from "@/lib/engine";
import { cn } from "@/lib/utils";

/**
 * A title's poster, or in its place the boards' placeholder: the featured blue with its orange
 * orb, and the title's first letters.
 */
export function Poster(props: {
  title: Pick<TitleSummary, "id" | "name" | "hasPoster">;
  /** A thumbnail beside a line of text: its letters to fit ("small"), or none ("tiny"). */
  size?: "small" | "tiny";
  className?: string;
}) {
  const { title, className } = props;
  const address = usePoster(title.id, title.hasPoster);
  return (
    <div
      aria-hidden="true"
      className={cn("relative aspect-[2/3] overflow-hidden rounded-14 bg-featured", className)}
    >
      {address ? (
        <img src={address} alt="" className="absolute inset-0 size-full object-cover" />
      ) : (
        <>
          <span className="-right-[22%] -top-[12%] absolute aspect-square w-[76%] rounded-full bg-featured-orb" />
          <span
            className={cn(
              "absolute font-extrabold text-white leading-none tracking-[-0.03em]",
              props.size === "small"
                ? "right-1 bottom-1.5 left-1.5 text-15"
                : "right-2.5 bottom-3 left-3 text-36",
              props.size === "tiny" && "hidden",
            )}
          >
            {initials(title.name)}
          </span>
        </>
      )}
    </div>
  );
}

/** "The Harbour Line" is "THL"; one word gives its first four letters ("Starfall" is "Star"). */
function initials(name: string): string {
  const words = name.split(/[\s:·\-–]+/).filter(Boolean);
  if (words.length === 1) return (words[0] ?? "").slice(0, 4);
  return words
    .slice(0, 3)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}
