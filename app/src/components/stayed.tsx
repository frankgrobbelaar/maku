import type { TidyResult } from "@/lib/engine";

/** The files a tidy-up or an undo couldn't move, each with why. */
export function Stayed({ problems }: { problems: TidyResult["problems"] }) {
  return (
    <section
      role="alert"
      className="flex flex-col gap-1.5 rounded-20 border border-broken/40 bg-broken/8 px-5 py-4 text-13"
    >
      <span className="font-extrabold">Some files stayed where they were</span>
      {problems.map((problem) => (
        <span key={problem.source} className="text-broken-fg">
          {problem.label}: {problem.problem}
        </span>
      ))}
    </section>
  );
}
