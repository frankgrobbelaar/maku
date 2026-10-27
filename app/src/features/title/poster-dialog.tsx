import { Check } from "lucide-react";
import { Skeleton } from "@/components/skeleton";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogHeader } from "@/components/ui/dialog";
import {
  type PosterOption,
  posterChanged,
  type TitleDetail,
  useChoosePoster,
  useCover,
  usePosterChoices,
} from "@/lib/engine";
import { languageName } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Choosing a title's poster, in a card over its page: TMDB's (in English, in its own language or
 * without words). Maku keeps the choice, and the poster next to the show follows it. */
export function PosterDialog(props: { title: TitleDetail; open: boolean; onClose: () => void }) {
  const { title, open } = props;
  const choices = usePosterChoices(title.id, open);
  const choose = useChoosePoster();
  const found = choices.data;
  const pick = (poster: string | null) =>
    choose.mutate(
      { path: `/titles/${title.id}/poster`, body: { poster } },
      {
        onSuccess: () => {
          posterChanged(title.id);
          props.onClose();
        },
      },
    );
  return (
    <Dialog open={open} onOpenChange={(now) => !now && props.onClose()}>
      {open && (
        <DialogContent>
          <DialogHeader
            title="Choose a poster"
            description={`${title.name} · from TMDB. The poster next to the show follows, when you have those.`}
          />
          <DialogBody>
            {!found ? (
              choices.isError ? (
                <p role="alert" className="text-13 text-broken-fg">
                  {choices.error.message}
                </p>
              ) : (
                <div className="grid grid-cols-4 gap-3" aria-hidden="true">
                  {[0, 1, 2, 3, 4, 5, 6, 7].map((each) => (
                    <Skeleton key={each} className="aspect-[2/3] rounded-12" />
                  ))}
                </div>
              )
            ) : (
              <>
                {found.problem && <p className="text-13 text-fg-muted">{found.problem}</p>}
                {found.options.length === 0 ? (
                  <p className="text-13 text-fg-muted">TMDB has no poster of it.</p>
                ) : (
                  <ul aria-label="Posters" className="grid grid-cols-4 gap-3">
                    {found.options.map((option, index) => (
                      <Choice
                        key={option.poster}
                        option={option}
                        inUse={index === 0}
                        busy={choose.isPending}
                        onPick={() => pick(option.poster)}
                      />
                    ))}
                  </ul>
                )}
                {found.chosen && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="-ml-3.5 self-start"
                    disabled={choose.isPending}
                    onClick={() => pick(null)}
                  >
                    Back to the one Maku found
                  </Button>
                )}
                {choose.isError && (
                  <p role="alert" className="text-13 text-broken-fg">
                    {choose.error.message}
                  </p>
                )}
              </>
            )}
          </DialogBody>
        </DialogContent>
      )}
    </Dialog>
  );
}

function Choice(props: {
  option: PosterOption;
  inUse: boolean;
  busy: boolean;
  onPick: () => void;
}) {
  const { option } = props;
  const picture = useCover(option.address);
  const words = wordsOf(option);
  return (
    <li>
      <button
        type="button"
        aria-label={`${props.inUse ? "In use: " : "Use "}${words}`}
        aria-pressed={props.inUse}
        disabled={props.busy}
        onClick={props.inUse ? undefined : props.onPick}
        className={cn(
          "press flex w-full cursor-pointer flex-col gap-1.5 text-left",
          props.inUse && "cursor-default",
        )}
      >
        <span
          className={cn(
            "relative aspect-[2/3] w-full overflow-hidden rounded-12 bg-surface",
            props.inUse && "ring-2 ring-accent ring-offset-2 ring-offset-dialog",
          )}
        >
          {picture && (
            <img src={picture} alt="" className="absolute inset-0 size-full object-cover" />
          )}
          {props.inUse && (
            <span className="absolute top-2 left-2 inline-flex h-6 items-center gap-1 rounded-full bg-accent px-2 font-extrabold text-11 text-on-accent">
              <Check size={11} strokeWidth={3.2} aria-hidden="true" />
              In use
            </span>
          )}
        </span>
        <span className="text-12 text-fg-muted">{words}</span>
      </button>
    </li>
  );
}

/** "TMDB · English", "TMDB · French", "TMDB · no words". */
function wordsOf(option: PosterOption): string {
  return `TMDB · ${option.language ? languageName(option.language) : "no words"}`;
}
