import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown as a reader sees it, the way an editor's preview shows it: headings, emphasis, lists
 * and tables, in Maku's type. For Maku's own reports. It sits under a panel's heading, so its
 * headings start a level or two below. Raw HTML in it shows as text, and links don't open from
 * inside Maku.
 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-3 text-13 text-fg-soft leading-[1.6]">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={PARTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

const PARTS: Components = {
  h1: ({ children }) => (
    <h3 className="border-edge border-b pb-2 font-extrabold text-20 text-fg tracking-[-0.01em]">
      {children}
    </h3>
  ),
  h2: ({ children }) => (
    <h4 className="mt-2 border-edge border-b pb-1.5 font-extrabold text-16 text-fg">{children}</h4>
  ),
  h3: ({ children }) => <h5 className="mt-1 font-extrabold text-14 text-fg">{children}</h5>,
  p: ({ children }) => <p>{children}</p>,
  em: ({ children }) => <em className="text-fg-muted">{children}</em>,
  strong: ({ children }) => <strong className="font-extrabold text-fg">{children}</strong>,
  ul: ({ children }) => (
    <ul className="flex list-disc flex-col gap-1 pl-5 marker:text-fg-faint">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="flex list-decimal flex-col gap-1 pl-5 marker:text-fg-faint">{children}</ol>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-12">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-edge bg-glass px-2.5 py-1.5 text-left font-bold text-fg">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="border border-edge px-2.5 py-1.5 font-mono">{children}</td>,
  code: ({ children }) => (
    <code className="rounded-4 bg-tint/6 px-1 py-0.5 font-mono text-12">{children}</code>
  ),
  a: ({ children }) => <span className="text-accent-fg">{children}</span>,
  hr: () => <hr className="border-edge" />,
};
