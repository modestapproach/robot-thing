/** Side-by-side harness diff: workflow ops (LCS-aligned) plus changed policy fields. */
import { cn } from '@/client/lib/utils';
import type { HarnessVersion } from '@/client/lib/autolab';

type Row = { kind: 'same' | 'add' | 'del'; op: string };

function diffOps(a: string[], b: string[]): Row[] {
  const n = a.length, m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: Row[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ kind: 'same', op: a[i] }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ kind: 'del', op: a[i++] });
    else out.push({ kind: 'add', op: b[j++] });
  }
  while (i < n) out.push({ kind: 'del', op: a[i++] });
  while (j < m) out.push({ kind: 'add', op: b[j++] });
  return out;
}

function flatten(o: Record<string, unknown>, prefix = ''): Record<string, string> {
  const r: Record<string, string> = {};
  for (const [k, v] of Object.entries(o ?? {})) {
    if (v && typeof v === 'object' && !Array.isArray(v)) Object.assign(r, flatten(v as Record<string, unknown>, `${prefix}${k}.`));
    else r[`${prefix}${k}`] = JSON.stringify(v);
  }
  return r;
}

export function HarnessDiff({ base, cand, compact = false }: { base: HarnessVersion | null | undefined; cand: HarnessVersion; compact?: boolean }) {
  const rows = diffOps(base?.workflow_steps.map((s) => s.op) ?? [], cand.workflow_steps.map((s) => s.op));
  const fb = flatten({ retry_policy: base?.retry_policy ?? {}, memory_policy: base?.memory_policy ?? {}, experiment_policy: base?.experiment_policy ?? {} });
  const fc = flatten({ retry_policy: cand.retry_policy, memory_policy: cand.memory_policy, experiment_policy: cand.experiment_policy });
  const changed = Object.keys({ ...fb, ...fc }).filter((k) => fb[k] !== fc[k]);
  return (
    <div className="grid gap-3 font-mono text-[12px] min-w-0">
      <div>
        <div className="flex flex-wrap justify-between gap-x-3 text-[10px] uppercase tracking-[0.14em] text-lab-faint mb-1.5">
          <span>workflow {base ? `v${base.version} → v${cand.version}` : `v${cand.version}`}</span>
          <span>{rows.filter((r) => r.kind !== 'same').length} op changes</span>
        </div>
        <ol className="rounded-md border border-lab-line overflow-hidden">
          {rows.map((r, i) => (
            <li key={i} className={cn('flex items-center gap-2 px-2.5 min-w-0', compact ? 'py-0.5' : 'py-1',
              r.kind === 'add' && 'bg-ok/10 text-ok', r.kind === 'del' && 'bg-fail/10 text-fail line-through decoration-fail/50', r.kind === 'same' && 'text-lab-dim')}>
              <span className="w-3 shrink-0 text-center">{r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ''}</span>
              <span className="min-w-0 truncate" title={r.op}>{r.op}</span>
            </li>
          ))}
        </ol>
      </div>
      {changed.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-lab-faint mb-1.5">policy fields</div>
          <table className="w-full table-fixed rounded-md border border-lab-line">
            <tbody>
              {changed.map((k) => (
                <tr key={k} className="border-t border-lab-line first:border-t-0">
                  <td className="px-2.5 py-1 text-lab-dim truncate" title={k}>{k}</td>
                  <td className="w-16 px-1.5 py-1 text-fail/90 text-right truncate">{fb[k] ?? '—'}</td>
                  <td className="w-5 px-0.5 text-lab-faint text-center">→</td>
                  <td className="w-16 px-1.5 py-1 text-ok truncate">{fc[k] ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
