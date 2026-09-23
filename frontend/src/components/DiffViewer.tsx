/**
 * Diff viewer (inline / side-by-side) for file changes against the newest
 * checkpoint snapshot. All content renders as inert text.
 */
import { useState } from "react";
import type { DiffResponse } from "@shared/ipc";

function LineClasses(kind: "add" | "del" | "ctx"): string {
  if (kind === "add") return "bg-emerald-950/40 text-emerald-200";
  if (kind === "del") return "bg-red-950/40 text-red-200";
  return "text-neutral-400";
}

export function DiffViewer({
  diff,
  onClose,
}: {
  diff: DiffResponse;
  onClose: () => void;
}) {
  const [sideBySide, setSideBySide] = useState(false);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        role="dialog"
        aria-label="Diff viewer"
        className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-xl border border-neutral-800 bg-neutral-900 shadow-2xl"
      >
        <div className="flex items-center gap-3 border-b border-neutral-800 px-4 py-2.5">
          <span className="truncate font-mono text-xs text-neutral-300">
            {diff.path}
          </span>
          <span className="text-[10px] text-neutral-500">
            {diff.oldLines} → {diff.newLines} lines
          </span>
          {diff.snapshotMissing && (
            <span
              className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] text-amber-300"
              title="The pre-change snapshot was consumed by an undo/revert or pruned"
            >
              no snapshot — current content only
            </span>
          )}
          {diff.identical && (
            <span className="text-[10px] text-emerald-400">identical</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSideBySide(!sideBySide)}
              className="rounded border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-400 hover:bg-neutral-800"
            >
              {sideBySide ? "inline" : "side-by-side"}
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close diff"
              className="rounded border border-neutral-700 px-2 py-0.5 text-[11px] text-neutral-400 hover:bg-neutral-800"
            >
              ✕
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-3">
          {diff.hunks.length === 0 && (
            <p className="p-4 text-center text-xs text-neutral-600">
              No changes.
            </p>
          )}
          {diff.hunks.map((hunk, hi) => (
            <div key={hi} className="mb-4">
              <div className="mb-1 font-mono text-[10px] text-neutral-600">
                @@ -{hunk.oldStart} +{hunk.newStart} @@
              </div>
              {sideBySide ? (
                <table className="w-full border-collapse font-mono text-[11px]">
                  <tbody>
                    {hunk.lines.map((line, li) => (
                      <tr key={li}>
                        <td
                          className={
                            "w-1/2 whitespace-pre-wrap break-all px-1 align-top " +
                            (line.kind === "add"
                              ? "opacity-30"
                              : LineClasses(line.kind))
                          }
                        >
                          {line.kind === "add"
                            ? ""
                            : `${line.oldLine ?? ""} ${line.text}`}
                        </td>
                        <td
                          className={
                            "w-1/2 whitespace-pre-wrap break-all px-1 align-top " +
                            (line.kind === "del"
                              ? "opacity-30"
                              : LineClasses(line.kind))
                          }
                        >
                          {line.kind === "del"
                            ? ""
                            : `${line.newLine ?? ""} ${line.text}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="font-mono text-[11px]">
                  {hunk.lines.map((line, li) => (
                    <div
                      key={li}
                      className={
                        "flex whitespace-pre-wrap break-all " +
                        LineClasses(line.kind)
                      }
                    >
                      <span className="w-10 shrink-0 select-none pr-1 text-right text-neutral-600">
                        {line.kind === "add" ? "" : (line.oldLine ?? "")}
                      </span>
                      <span className="w-10 shrink-0 select-none pr-1 text-right text-neutral-600">
                        {line.kind === "del" ? "" : (line.newLine ?? "")}
                      </span>
                      <span className="w-6 shrink-0 select-none">
                        {line.kind === "add"
                          ? "+"
                          : line.kind === "del"
                            ? "−"
                            : " "}
                      </span>
                      <span className="min-w-0 flex-1">{line.text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
