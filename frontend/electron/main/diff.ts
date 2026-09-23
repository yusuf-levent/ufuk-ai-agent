/**
 * Small LCS-based line diff (unified-diff style hunks) for the diff viewer.
 * Pure function, main process only; contents are UNTRUSTED file data and
 * are only ever rendered as text by the renderer.
 */

export interface DiffLine {
  kind: "add" | "del" | "ctx";
  text: string;
  /** 1-based line number in the respective side (null on the other side). */
  oldLine: number | null;
  newLine: number | null;
}

export interface DiffHunk {
  oldStart: number;
  newStart: number;
  lines: DiffLine[];
}

export interface DiffResult {
  /** true when old and new content are identical */
  identical: boolean;
  hunks: DiffHunk[];
  oldLines: number;
  newLines: number;
}

const CONTEXT = 3;

/** Classic dynamic-programming LCS on lines (files are capped by callers). */
function lcsTable(a: string[], b: string[]): Uint32Array[] {
  const table: Uint32Array[] = Array.from(
    { length: a.length + 1 },
    () => new Uint32Array(b.length + 1),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i]![j] =
        a[i] === b[j]
          ? table[i + 1]![j + 1]! + 1
          : Math.max(table[i + 1]![j]!, table[i]![j + 1]!);
    }
  }
  return table;
}

export function diffLines(oldText: string, newText: string): DiffResult {
  const a = oldText.length === 0 ? [] : oldText.split("\n");
  const b = newText.length === 0 ? [] : newText.split("\n");
  // cap: very large inputs get a single "full replace" hunk
  if (a.length * b.length > 4_000_000) {
    return {
      identical: oldText === newText,
      oldLines: a.length,
      newLines: b.length,
      hunks: [
        {
          oldStart: 1,
          newStart: 1,
          lines: [
            ...a.map((text, i) => ({
              kind: "del" as const,
              text,
              oldLine: i + 1,
              newLine: null,
            })),
            ...b.map((text, i) => ({
              kind: "add" as const,
              text,
              oldLine: null,
              newLine: i + 1,
            })),
          ],
        },
      ],
    };
  }

  const table = lcsTable(a, b);
  // walk the diff
  const raw: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    const left = a[i]!;
    const right = b[j]!;
    if (left === right) {
      raw.push({ kind: "ctx", text: left, oldLine: i + 1, newLine: j + 1 });
      i++;
      j++;
    } else if (table[i + 1]![j]! >= table[i]![j + 1]!) {
      raw.push({ kind: "del", text: left, oldLine: i + 1, newLine: null });
      i++;
    } else {
      raw.push({ kind: "add", text: right, oldLine: null, newLine: j + 1 });
      j++;
    }
  }
  while (i < a.length) {
    raw.push({ kind: "del", text: a[i]!, oldLine: i + 1, newLine: null });
    i++;
  }
  while (j < b.length) {
    raw.push({ kind: "add", text: b[j]!, oldLine: null, newLine: j + 1 });
    j++;
  }

  // group into hunks with context
  const hunks: DiffHunk[] = [];
  let idx = 0;
  while (idx < raw.length) {
    if (raw[idx]!.kind === "ctx") {
      idx++;
      continue;
    }
    // found a change: expand context window
    const start = Math.max(0, idx - CONTEXT);
    let end = idx;
    let k = idx;
    while (k < raw.length) {
      if (raw[k]!.kind !== "ctx") {
        end = k + CONTEXT + 1;
        k++;
      } else {
        // stop after a long run of context
        let ctxRun = 0;
        while (k < raw.length && raw[k]!.kind === "ctx") {
          ctxRun++;
          k++;
        }
        if (ctxRun > CONTEXT * 2) break;
        end = k + CONTEXT + 1;
      }
    }
    end = Math.min(end, raw.length);
    const lines = raw.slice(start, end);
    const firstOld = lines.find((l) => l.oldLine !== null)?.oldLine ?? 1;
    const firstNew = lines.find((l) => l.newLine !== null)?.newLine ?? 1;
    hunks.push({
      oldStart: Math.max(1, firstOld),
      newStart: Math.max(1, firstNew),
      lines,
    });
    idx = end;
  }

  return {
    identical: hunks.length === 0,
    hunks,
    oldLines: a.length,
    newLines: b.length,
  };
}
