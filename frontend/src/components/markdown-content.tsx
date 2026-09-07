import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "../lib/utils";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

const markdownComponents: Components = {
  h1: ({ className, ...props }) => (
    <h1 className={cn("mb-4 text-2xl font-bold text-white", className)} {...props} />
  ),
  h2: ({ className, ...props }) => (
    <h2 className={cn("mb-3 mt-7 text-xl font-semibold text-white first:mt-0", className)} {...props} />
  ),
  h3: ({ className, ...props }) => (
    <h3 className={cn("mb-2 mt-5 text-lg font-semibold text-slate-100", className)} {...props} />
  ),
  p: ({ className, ...props }) => (
    <p className={cn("mb-4 leading-7 text-slate-300 last:mb-0", className)} {...props} />
  ),
  ul: ({ className, ...props }) => (
    <ul className={cn("mb-4 list-disc space-y-2 pl-6 text-slate-300", className)} {...props} />
  ),
  ol: ({ className, ...props }) => (
    <ol className={cn("mb-4 list-decimal space-y-2 pl-6 text-slate-300", className)} {...props} />
  ),
  blockquote: ({ className, ...props }) => (
    <blockquote
      className={cn("mb-4 border-l-2 border-cyan-400/60 pl-4 italic text-slate-400", className)}
      {...props}
    />
  ),
  a: ({ className, ...props }) => (
    <a
      className={cn("text-cyan-300 underline decoration-cyan-400/40 underline-offset-4", className)}
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  code: ({ className, children, ...props }) => {
    const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
    const code = String(children).replace(/\n$/, "");

    if (!language) {
      return (
        <code className="rounded bg-slate-800 px-1.5 py-0.5 text-sm text-cyan-200" {...props}>
          {children}
        </code>
      );
    }

    return (
      <div className="mb-5 overflow-hidden rounded-xl border border-slate-700 bg-slate-950">
        <div className="border-b border-slate-800 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
          {language}
        </div>
        <pre className="overflow-x-auto p-4 text-sm leading-6 text-slate-200">
          <code className={className} {...props}>
            {code}
          </code>
        </pre>
      </div>
    );
  },
  pre: ({ children }) => <>{children}</>,
};

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div className={cn("markdown-content", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}