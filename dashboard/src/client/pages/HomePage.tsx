/** Lab: the four-region dashboard (PRD §11.3) — Reality, Simulation, Experiments, Evolution. */
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import Page from '@/client/components/Page';
import { Empty, LiveDot, Panel, Stat } from '@/client/components/lab/Panel';
import { BoardLegend, BoardPlot } from '@/client/components/lab/BoardPlot';
import { EnvBadge, MonoId, StatusBadge } from '@/client/components/lab/Badges';
import { HarnessDiff } from '@/client/components/lab/HarnessDiff';
import { So101Viewer } from '@/client/components/lab/So101Viewer';
import { MetricsCompare } from '@/client/components/lab/MetricsCompare';
import { cn } from '@/client/lib/utils';
import {
  CAMPAIGN_STAGES, fmt, useEvaluations, useExperiments, useHarnessVersions, useLatestTrajectory, useMutations, useRobot, useStatus, useTwins, when,
} from '@/client/lib/autolab';

function CampaignStrip() {
  const { data: s } = useStatus();
  const c = s?.campaign;
  const done = new Set(c?.completed ?? []);
  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-4 rounded-[var(--radius-panel)] border border-lab-line bg-lab-panel px-4 py-3">
      <Stat label="active harness" value={s?.activeHarness ? `v${s.activeHarness.version}` : '—'} sub={<MonoId id={s?.activeHarness?.id} />} />
      <Stat label="twin" value={s?.twin ? (s.twin.backend === 'mujoco' ? 'Level 1' : 'Level 0') : '—'} sub={<span>{s?.twin?.backend} · <MonoId id={s?.twin?.id} /></span>} />
      <Stat label="experiments" value={s?.counts.experiments ?? '—'} sub={`${s?.counts.acknowledgedMoves ?? 0} moves acked`} />
      <Stat label="mutations" value={s?.counts.mutations ?? '—'} sub={`${s?.counts.rejectedMutations ?? 0} rejected`} tone={s?.counts.rejectedMutations ? undefined : undefined} />
      <div className="col-span-2 min-w-0">
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint">
          campaign <LiveDot on={c?.status === 'running'} /> {c && <StatusBadge status={c.status} />}
          <span className="ml-auto normal-case tracking-normal"><MonoId id={c?.id} /></span>
        </div>
        <div className="mt-2 flex gap-1">
          {CAMPAIGN_STAGES.map((st) => (
            <div key={st} title={st} className={cn('h-1.5 flex-1 rounded-full', done.has(st) ? 'bg-measured' : 'bg-lab-raised')} />
          ))}
        </div>
        <div className="mt-1 text-[11px] text-lab-dim truncate">
          {c ? `${done.size}/${CAMPAIGN_STAGES.length} stages · last: ${c.completed.at(-1) ?? 'none'} · ${when(c.updatedAt)}` : 'no campaign yet — run scripts/run_campaign.py'}
        </div>
      </div>
    </div>
  );
}

function RealityPanel() {
  const { data: exps } = useExperiments(120);
  const [sel, setSel] = useState<string | null>(null);
  const recent = useMemo(() => {
    const seen = new Set<string>();
    return (exps ?? []).filter((e) => e.campaign_id !== 'eval' && e.observed_position_mm && !seen.has(e.scenario_id) && seen.add(e.scenario_id)).slice(0, 20);
  }, [exps]);
  const chosen = recent.find((e) => e._id === sel) ?? recent[0];
  const env = chosen?.execution_environment;
  return (
    <Panel title="Reality" tag={env && <EnvBadge env={env} />} action={<span className="text-[11px] text-lab-faint">latest trial per target</span>}>
      {recent.length === 0 ? <Empty>No observations yet.</Empty> : (
        <div className="grid gap-3">
          <BoardPlot experiments={recent} selectedId={chosen?._id} onSelect={setSel} />
          <BoardLegend />
          {chosen && (
            <div className="grid grid-cols-3 gap-3 font-mono text-[12px] tabular rounded-md bg-lab-raised px-3 py-2">
              <div><div className="text-[10px] text-lab-faint">target</div>{fmt(chosen.target_position_mm.x, 1)}, {fmt(chosen.target_position_mm.y, 1)}</div>
              <div><div className="text-[10px] text-lab-faint">observed</div>{chosen.observed_position_mm ? `${fmt(chosen.observed_position_mm.x, 1)}, ${fmt(chosen.observed_position_mm.y, 1)}` : '—'}</div>
              <div><div className="text-[10px] text-lab-faint">error</div><span className={(chosen.position_error_mm ?? 99) <= 2 ? 'text-ok' : 'text-fail'}>{fmt(chosen.position_error_mm)} mm</span></div>
            </div>
          )}
          {env === 'simulation' && <p className="text-[11px] text-lab-faint">Simulated world (SO-101 MuJoCo physics or mock arm, with a simulated camera): not physical measurements.</p>}
        </div>
      )}
    </Panel>
  );
}

function SimulationPanel() {
  const { data: twins } = useTwins();
  const { data: traj } = useLatestTrajectory();
  const { data: robot } = useRobot();
  const latest = twins?.[0];
  const vs = latest?.validation_summary ?? {};
  const ranking: { index: number; rmse: number }[] = vs.ranking ?? [];
  const max = Math.max(...ranking.map((r) => r.rmse), 0.001);
  const held = vs.heldout_physical;
  return (
    <Panel title="Simulation" tag={<EnvBadge env="simulation" />} action={<Link to="/twin" className="text-[11px] text-lab-dim hover:text-lab-text">twin lineage →</Link>}>
      {!latest ? <Empty>No twin versions.</Empty> : (
        <div className="grid grid-cols-1 gap-3 min-w-0">
          {traj && (
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint">
                <span>{robot?.model ?? 'arm'} · official URDF · last move, joint angles from MuJoCo</span>
                <span className="ml-auto normal-case tracking-normal">drag to orbit</span>
              </div>
              <So101Viewer traj={traj} board={latest.calibration_parameters} height={260} />
            </div>
          )}
          <div className="flex items-baseline gap-2 text-sm">
            <MonoId id={latest.parent_version_id} /><span className="text-lab-faint">→</span><MonoId id={latest._id} className="text-lab-text" />
            <span className="ml-auto font-mono text-[11px] text-lab-faint">{latest.backend} twin{(latest as any).robot_model && (latest as any).robot_model !== 'generic' ? ` · ${(latest as any).robot_model}` : ''}</span>
          </div>
          {vs.prediction_rmse_mm_new !== undefined && (
            <div className="grid grid-cols-2 gap-3">
              <Stat label="twin prediction rmse" value={<>{fmt(vs.prediction_rmse_mm_parent)} <span className="text-lab-faint">→</span> <span className="text-ok">{fmt(vs.prediction_rmse_mm_new)}</span></>} sub="mm, vs. observed landings" />
              {held && <Stat label="held-out task rmse" value={<>{fmt(held.before.rmse_mm)} <span className="text-lab-faint">→</span> <span className="text-ok">{fmt(held.after.rmse_mm)}</span></>} sub={`mm, n=${held.n_targets}, success ${Math.round(held.before.success_rate * 100)}% → ${Math.round(held.after.success_rate * 100)}%`} />}
            </div>
          )}
          {ranking.length > 0 && (
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint mb-1.5">candidate calibrations · batch <MonoId id={vs.batch_id} /></div>
              <div className="grid gap-1">
                {ranking.map((r, i) => (
                  <div key={r.index} className="flex items-center gap-2 font-mono text-[11px] tabular">
                    <span className="w-6 text-lab-faint">#{r.index}</span>
                    <div className="flex-1 h-2 rounded-sm bg-lab-raised overflow-hidden">
                      <div className={cn('h-full', i === 0 ? 'bg-simulated' : 'bg-simulated/40')} style={{ width: `${Math.max(3, (r.rmse / max) * 100)}%` }} />
                    </div>
                    <span className="w-12 text-right">{fmt(r.rmse)}</span>
                  </div>
                ))}
                {(vs.rejections ?? []).map((r: any) => (
                  <div key={`rej${r.index}`} className="flex items-center gap-2 font-mono text-[11px]"><span className="w-6 text-lab-faint">#{r.index}</span><span className="text-fail/90 truncate">rejected: {r.reason}</span></div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function ExperimentsPanel() {
  const { data: exps } = useExperiments(60);
  const { data: versions } = useHarnessVersions();
  const ver = new Map((versions ?? []).map((v) => [v._id, v.version]));
  const rows = (exps ?? []).filter((e) => e.campaign_id !== 'eval').slice(0, 14);
  return (
    <Panel title="Experiments" action={<Link to="/experiments" className="text-[11px] text-lab-dim hover:text-lab-text">all →</Link>} bodyClassName="p-0">
      {rows.length === 0 ? <Empty>No experiments recorded.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead className="font-mono text-[10px] uppercase tracking-wider text-lab-faint">
              <tr className="border-b border-lab-line"><th className="text-left font-normal px-4 py-2">time</th><th className="text-left font-normal">scenario</th><th className="text-left font-normal">env</th><th className="text-left font-normal">harness</th><th className="text-right font-normal">retries</th><th className="text-right font-normal px-4">error mm</th></tr>
            </thead>
            <tbody className="stagger">
              {rows.map((e, i) => (
                <tr key={e._id} style={{ ['--i' as any]: i }} className="border-b border-lab-line/60 last:border-0 hover:bg-lab-raised">
                  <td className="px-4 py-1.5 font-mono text-lab-faint">{when(e.started_at)}</td>
                  <td className="font-mono">{e.scenario_id}</td>
                  <td><EnvBadge env={e.execution_environment} /></td>
                  <td className="font-mono text-lab-dim">v{ver.get(e.harness_version_id) ?? '?'}</td>
                  <td className="text-right font-mono text-lab-dim">{e.retries ?? 0}</td>
                  <td className={cn('px-4 text-right font-mono tabular', e.position_error_mm === null || e.position_error_mm === undefined ? 'text-warn' : e.position_error_mm <= 2 ? 'text-ok' : 'text-fail')}>
                    {e.position_error_mm === null || e.position_error_mm === undefined ? 'unknown' : fmt(e.position_error_mm)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function EvolutionPanel() {
  const { data: versions } = useHarnessVersions();
  const { data: evals } = useEvaluations();
  const { data: muts } = useMutations();
  const byId = new Map((versions ?? []).map((v) => [v._id, v]));
  // Most recent harness-task evaluation (not the experiment-policy study) is the headline diff.
  const headline = (evals ?? []).find((e) => e.decision === 'approve' && !e.simulation_metrics?.kind) ?? (evals ?? [])[0];
  const cand = headline ? byId.get(headline.candidate_version_id) : undefined;
  const base = headline ? byId.get(headline.baseline_version_id) : undefined;
  return (
    <Panel title="Evolution" action={<Link to="/evolution" className="text-[11px] text-lab-dim hover:text-lab-text">lineage →</Link>}>
      {!headline || !cand ? <Empty>No mutations evaluated yet.</Empty> : (
        <div className="@container grid gap-4">
          <div className="grid @4xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-4">
            <HarnessDiff base={base} cand={cand} compact />
            <MetricsCompare evaluation={headline} />
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint mb-1.5">recent proposals</div>
            <ul className="grid gap-1.5">
              {(muts ?? []).slice(0, 4).map((m) => (
                <li key={m._id} className="flex items-start gap-2 text-[12px]">
                  <StatusBadge status={m.status} />
                  <span className="font-mono text-lab-dim shrink-0">{m.mutation_type}</span>
                  <span className="text-lab-dim line-clamp-1">{m.hypothesis}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Panel>
  );
}

export default function HomePage() {
  return (
    <Page seo={{ title: 'Lab' }}>
      <CampaignStrip />
      <div className="grid xl:grid-cols-[minmax(0,5fr)_minmax(0,4fr)] gap-4">
        <RealityPanel />
        <SimulationPanel />
      </div>
      <div className="grid xl:grid-cols-[minmax(0,4fr)_minmax(0,5fr)] gap-4">
        <ExperimentsPanel />
        <EvolutionPanel />
      </div>
    </Page>
  );
}
