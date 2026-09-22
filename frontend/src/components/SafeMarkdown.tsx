/**
 * SafeMarkdown — renders UNTRUSTED model output.
 *
 * - react-markdown: no raw HTML is rendered by default (markdown escapes it)
 * - rehype-sanitize: default schema strips scripts, event handlers, iframes,
 *   forms, style attributes and javascript: URLs even if raw HTML slipped in
 * - links never navigate the app: they open in the system browser after a
 *   confirmation dialog (handled in the main process via IPC)
 * - code blocks are inert text (no syntax-highlight scripts, no copy events)
 */
import { memo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { api } from "../ipc/client";

function SafeLink({
  href,
  children,
}: {
  href?: string;
  children: React.ReactNode;
}) {
  const open = (): void => {
    if (typeof href === "string" && href.length > 0) {
      void api.openExternal(href).catch(() => {
        /* user cancelled or invalid link */
      });
    }
  };
  return (
    <button
      type="button"
      onClick={open}
      className="text-sky-400 underline underline-offset-2 hover:text-sky-300"
      title={href}
    >
      {children}
    </button>
  );
}

export const SafeMarkdown = memo(function SafeMarkdown({
  text,
}: {
  text: string;
}) {
  return (
    <div className="prose-sm max-w-none break-words leading-relaxed [&_a]:break-all [&_code]:rounded [&_code]:bg-neutral-200/10 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.9em] [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-neutral-900 [&_pre]:p-3 [&_pre]:font-mono [&_pre]:text-xs dark:[&_code]:bg-neutral-800/60">
      <ReactMarkdown
        rehypePlugins={[rehypeSanitize]}
        components={{
          a: ({ href, children }) => (
            <SafeLink href={href}>{children}</SafeLink>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
