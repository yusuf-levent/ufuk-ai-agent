// @vitest-environment node
/** LCS line diff for the diff viewer. */
import { describe, expect, it } from "vitest";
import { diffLines } from "../../electron/main/diff";

describe("diffLines", () => {
  it("reports identical content with no hunks", () => {
    const r = diffLines("a\nb\nc\n", "a\nb\nc\n");
    expect(r.identical).toBe(true);
    expect(r.hunks).toEqual([]);
    expect(r.oldLines).toBe(4);
    expect(r.newLines).toBe(4);
  });

  it("detects a single-line change with context", () => {
    const old = "line1\nline2\nline3\nline4\nline5\nline6\nline7\n";
    const now = "line1\nline2\nline3\nCHANGED\nline5\nline6\nline7\n";
    const r = diffLines(old, now);
    expect(r.identical).toBe(false);
    expect(r.hunks).toHaveLength(1);
    const hunk = r.hunks[0]!;
    const del = hunk.lines.find((l) => l.kind === "del");
    const add = hunk.lines.find((l) => l.kind === "add");
    expect(del?.text).toBe("line4");
    expect(del?.oldLine).toBe(4);
    expect(add?.text).toBe("CHANGED");
    expect(add?.newLine).toBe(4);
    // context around the change
    expect(hunk.lines[0]?.kind).toBe("ctx");
    expect(hunk.lines.at(-1)?.kind).toBe("ctx");
  });

  it("splits distant changes into separate hunks", () => {
    const old = Array.from({ length: 30 }, (_, i) => `l${i}`).join("\n");
    const now = old.replace("l2", "X").replace("l27", "Y");
    const r = diffLines(old, now);
    expect(r.hunks.length).toBe(2);
  });

  it("handles created content (everything added) and deleted files", () => {
    const created = diffLines("", "new file\ncontent\n");
    expect(created.hunks).toHaveLength(1);
    expect(created.hunks[0]!.lines.every((l) => l.kind === "add")).toBe(true);
    const deleted = diffLines("gone\n", "");
    expect(deleted.hunks[0]!.lines.every((l) => l.kind === "del")).toBe(true);
  });

  it("caps pathological inputs with a full-replace hunk", () => {
    const a = Array.from({ length: 3000 }, (_, i) => `a${i}`).join("\n");
    const b = Array.from({ length: 3000 }, (_, i) => `b${i}`).join("\n");
    const r = diffLines(a, b);
    expect(r.hunks).toHaveLength(1);
    expect(r.hunks[0]!.lines).toHaveLength(6000);
  });
});
