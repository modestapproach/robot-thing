/** Baseline vs candidate on the protected suite, with provenance on each block. */
import { cn } from '@/client/lib/utils';
import { fmt, pct, type EvaluationResult } from '@/client/lib/autolab';
import { EnvBadge, StatusBadge } from './Badges';

const ROWS: [string, string, (v: number) => string, 'lower' | 'higher'][] = [
  ['success_rate', 'success', pct, 'higher'],
  ['rmse_mm', 'RMSE mm', (v) => fmt(v), 'lower'],
  ['p90_error_mm', 'p90 mm', (v) => fmt(v), 'lower'],
  ['observations_per_task', 'obs / task', (v) => fmt(v, 1), 'lower'],
  ['movements_per_task', 'moves / task', (v) => fmt(v, 1), 'lower'],
];

function Block({ title, env, m }: { title: string; env: string; m: any }) {
  if (!m?.baseline) return null;
  if (m.kind === 'experiment_selection_study') {
    return (
      <div className="rounded-md border border-lab-line p-3">
        <div className="flex items-center gap-2 mb-2"><span className="font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint">{title}</span><EnvBadge env={env} /></div>
        <div className="grid grid-cols-3 gap-2 font-mono text-[12px] tabular">
          <span className="text-lab-faint">obs to {m.threshold_mm} mm</span><span className="text-right">{fmt(m.baseline.mean_observations)}</span><span className="text-right text-ok">{fmt(m.candidate.mean_observations)}</span>
          <span className="text-lab-faint">reached</span><span className="text-right">{pct(m.baseline.reached_fraction)}</span><span className="text-right">{pct(m.candidate.reached_fraction)}</span>
        </div>
        <div className="mt-1.5 text-[11px] text-lab-faint">{m.n_problems} identical randomized calibration problems · {m.baseline.policy} → {m.candidate.policy}</div>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-lab-line p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint">{title}</span>
        <EnvBadge env={env} />
        <span className="ml-auto font-mono text-[10px] text-lab-faint">n={m.n_targets} held-out</span>
      </div>
      <table className="w-full font-mono text-[12px] tabular">
        <thead><tr className="text-lab-faint text-[10px] uppercase"><th className="text-left font-normal">metric</th><th className="text-right font-normal">base</th><th className="text-right font-normal">cand</th></tr></thead>
        <tbody>
          {ROWS.map(([k, label, f, better]) => {
            const b = m.baseline[k], c = m.candidate[k];
            const good = better === 'lower' ? c < b : c > b;
            const same = Math.abs(c - b) < 1e-9;
            return (
              <tr key={k}>
                <td className="text-lab-dim py-0.5">{label}</td>
                <td className="text-right">{f(b)}</td>
                <td className={cn('text-right', same ? 'text-lab-dim' : good ? 'text-ok' : 'text-fail')}>{f(c)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function MetricsCompare({ evaluation }: { evaluation: EvaluationResult }) {
  const phys = evaluation.physical_metrics;
  return (
    <div className="@container grid gap-2.5 min-w-0">
      <div className="flex items-center gap-2">
        <StatusBadge status={evaluation.decision} />
        <span className="font-mono text-[10px] text-lab-faint">{evaluation.protected_test_set_version}</span>
      </div>
      <div className="grid @xl:grid-cols-2 gap-2.5">
        <Block title="simulation gate" env="simulation" m={evaluation.simulation_metrics} />
        {phys?.baseline && <Block title="physical stage" env={phys.environment ?? 'real_hardware'} m={phys} />}
      </div>
      <ul className="text-[12px] text-lab-dim space-y-1">
        {evaluation.reasons.map((r, i) => <li key={i} className="flex gap-2"><span className="text-lab-faint">›</span><span>{r}</span></li>)}
      </ul>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries({ ...evaluation.protected_tests, ...evaluation.safety_invariants }).map(([k, v]) => (
          <span key={k} className={cn('font-mono text-[10px] px-1.5 py-0.5 rounded border', v ? 'text-ok/90 border-ok/25' : 'text-fail border-fail/40')}>{v ? '✓' : '✗'} {k}</span>
        ))}
      </div>
    </div>
  );
}
