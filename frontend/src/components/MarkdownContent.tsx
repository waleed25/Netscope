import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
  h1: ({ children }) => (
    <h1 className="text-sm font-bold text-foreground mt-4 mb-2 first:mt-0 pb-1 border-b border-border">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-xs font-bold text-accent mt-3 mb-1.5 first:mt-0 uppercase tracking-wider">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-xs font-semibold text-foreground mt-2 mb-1 first:mt-0">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="text-xs text-foreground leading-relaxed mb-2 last:mb-0">
      {children}
    </p>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 space-y-0.5 pl-1">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 space-y-0.5 pl-4 list-decimal marker:text-muted">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="text-xs text-foreground leading-relaxed flex gap-1.5">
      <span className="text-accent shrink-0 mt-0.5">›</span>
      <span>{children}</span>
    </li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-muted not-italic">{children}</em>
  ),
  code: ({ children, className }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return (
        <pre className="my-2 p-2.5 bg-surface border border-border rounded text-[10px] font-mono text-foreground overflow-x-auto">
          <code>{children}</code>
        </pre>
      );
    }
    return (
      <code className="text-[10px] font-mono bg-surface border border-border rounded px-1 py-0.5 text-accent">
        {children}
      </code>
    );
  },
  pre: ({ children }) => <>{children}</>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 pl-3 border-l-2 border-accent/50 text-muted text-xs">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-3 border-border" />,
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead>{children}</thead>,
  th: ({ children }) => (
    <th className="text-left text-muted font-semibold py-1 pr-3 border-b border-border text-[10px] uppercase tracking-wide">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="py-1 pr-3 border-b border-border-subtle text-foreground font-mono text-[10px]">
      {children}
    </td>
  ),
};

interface Props {
  children: string;
}

export function MarkdownContent({ children }: Props) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </ReactMarkdown>
  );
}
