import { useMemo, type ReactNode } from "react";

type Op =
  | { type: "same"; token: string }
  | { type: "del"; token: string }
  | { type: "ins"; token: string };

const MAX_CELLS = 400_000;

function tokenize(value: string): string[] {
  return value.match(/\S+\s*/g) ?? [];
}

/**
 * Word-level diff producing an interleaved render (removed words struck
 * through, added words highlighted) so the suggested change reads inline.
 */
function diffOps(before: string[], after: string[]): Op[] {
  const n = before.length;
  const m = after.length;

  if (n * m > MAX_CELLS || n === 0 || m === 0) {
    const ops: Op[] = [];
    for (const token of before) ops.push({ type: "del", token });
    for (const token of after) ops.push({ type: "ins", token });
    return ops;
  }

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = before[i] === after[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (before[i] === after[j]) {
      ops.push({ type: "same", token: before[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: "del", token: before[i] });
      i++;
    } else {
      ops.push({ type: "ins", token: after[j] });
      j++;
    }
  }
  while (i < n) {
    ops.push({ type: "del", token: before[i] });
    i++;
  }
  while (j < m) {
    ops.push({ type: "ins", token: after[j] });
    j++;
  }
  return ops;
}

export default function DiffView({ before, after }: { before: string; after: string }) {
  const ops = useMemo(() => diffOps(tokenize(before), tokenize(after)), [before, after]);

  const nodes: ReactNode[] = ops.map((op, index) => {
    if (op.type === "same") return <span key={index}>{op.token}</span>;
    if (op.type === "del")
      return (
        <del key={index} className="diff-del">
          {op.token}
        </del>
      );
    return (
      <ins key={index} className="diff-ins">
        {op.token}
      </ins>
    );
  });

  return <span className="diff">{nodes}</span>;
}