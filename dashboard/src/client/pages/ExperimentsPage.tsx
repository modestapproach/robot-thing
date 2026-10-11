/** Experiments (PRD §11.2): trial history with provenance, filters, and board view. */
import { useMemo, useState } from 'react';
import Page from '@/client/components/Page';
import { Empty, Panel } from '@/client/components/lab/Panel';
import { BoardLegend, BoardPlot } from '@/client/components/lab/BoardPlot';
import { EnvBadge, MonoId, StatusBadge } from '@/client/components/lab/Badges';
import { cn } from '@/client/lib/utils';
import { fmt, useExperiments, useHarnessVersions, useTrajectory, useTwins, when, type Experiment } from '@/client/lib/autolab';
import { So101Viewer } from '@/client/components/lab/So101Viewer';

function TrialReplay({ e }: { e: Experiment }) {
  const ref = [...((e as any).artifact_refs ?? [])].reverse().find((a: string) => a.startsWith('traj'));
  const { data: traj } = useTrajectory(ref);
  const { data: twins } = useTwins();
  const twin = (twins ?? []).find((t) => t._id === e.twin_version_id);
  if (!ref) return null;
  return (
    <Panel title="Replay" tag={traj && <EnvBadge env={traj.environment} />} action={<span className="font-mono text-[11px] text-lab-faint">final attempt · drag to orbit</span>}>
      {traj ? <So101Viewer traj={traj} board={twin?.calibration_parameters} height={280} /> : <Empty>Loading trajectory…</Empty>}
    </Panel>
  );
}

const SOURCES = [
  { id: 'campaign', label: 'campaign trials' },
  { id: 'eval', label: 'evaluator runs' },
  { id: 'all', label: 'all' },
];

export default function ExperimentsPage() {
  const { data: exps, isLoading } = useExperiments(500);
  const { data: versions } = useHarnessVersions();
  const [source, setSource] = useState('campaign');
  const [hv, setHv] = useState<string>('all');
  const [sel, setSel] = useState<string | null>(null);
  const ver = new Map((versions ?? []).map((v) => [v._id, v.version]));
  const rows = useMemo(() => (exps ?? []).filter((e) =>
    (source === 'all' || (source === 'eval' ? e.campaign_id === 'eval' : e.campaign_id !== 'eval')) && (hv === 'all' || e.harness_version_id === hv)), [exps, source, hv]);
  const chosen: Experiment | undefined = rows.find((e) => e._id === sel) ?? rows[0];

  return (
    <Page seo={{ title: 'Experiments' }} isLoading={isLoading}>
      <div className="flex flex-wrap items-center gap-2">
        {SOURCES.map((s) => (
          <button key={s.id} onClick={() => setSource(s.id)} className={cn('px-3 py-1 rounded-[var(--radius-chip)] text-[12px] border', source === s.id ? 'border-measured/50 text-lab-text bg-lab-raised' : 'border-lab-line text-lab-dim')}>{s.label}</button>
        ))}
        <select value={hv} onChange={(e) => setHv(e.target.value)} className="ml-2 bg-lab-panel border border-lab-line rounded-[var(--radius-chip)] px-2 py-1 text-[12px] font-mono">
          <option value="all">all harness versions</option>
          {(versions ?? []).map((v) => <option key={v._id} value={v._id}>v{v.version} · {v.status}</option>)}
        </select>
        <span className="ml-auto font-mono text-[11px] text-lab-faint">{rows.length} trials</span>
      </div>
      <div className="grid xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-4 items-start">
        <Panel title="Trials" bodyClassName="p-0">
          {rows.length === 0 ? <Empty>No trials match.</Empty> : (
            <div className="overflow-x-auto max-h-[70vh] overflow-y-auto">
              <table className="w-full text-[12px]">
                <thead className="sticky top-0 bg-lab-panel font-mono text-[10px] uppercase tracking-wider text-lab-faint">
                  <tr className="border-b border-lab-line">
                    <th className="text-left font-normal px-4 py-2">time</th><th className="text-left font-normal">scenario</th><th className="text-left font-normal">env</th>
                    <th className="text-left font-normal">harness</th><th className="text-left font-normal">status</th><th className="text-right font-normal">1st try</th><th className="text-right font-normal px-4">final mm</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e._id} onClick={() => setSel(e._id)} className={cn('border-b border-lab-line/60 cursor-pointer', chosen?._id === e._id ? 'bg-lab-raised' : 'hover:bg-lab-raised/60')}>
                      <td className="px-4 py-1.5 font-mono text-lab-faint">{when(e.started_at)}</td>
                      <td className="font-mono">{e.scenario_id}</td>
                      <td><EnvBadge env={e.execution_environment} /></td>
                      <td className="font-mono text-lab-dim">v{ver.get(e.harness_version_id) ?? '?'}</td>
                      <td><StatusBadge status={e.verification_status} /></td>
                      <td className="text-right font-mono text-lab-dim tabular">{fmt(e.first_attempt_error_mm)}</td>
                      <td className={cn('px-4 text-right font-mono tabular', e.position_error_mm == null ? 'text-warn' : e.position_error_mm <= 2 ? 'text-ok' : 'text-fail')}>{e.position_error_mm == null ? 'unknown' : fmt(e.position_error_mm)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <div className="grid gap-4">
          <Panel title="Board" tag={chosen && <EnvBadge env={chosen.execution_environment} />}>
            <BoardPlot experiments={rows.slice(0, 40)} selectedId={chosen?._id} onSelect={setSel} />
            <div className="mt-2"><BoardLegend /></div>
          </Panel>
          {chosen && <TrialReplay e={chosen} />}
          {chosen && (
            <Panel title="Trial" action={<MonoId id={chosen._id} />}>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-[12px]">
                {([
                  ['target', `${fmt(chosen.target_position_mm.x, 1)}, ${fmt(chosen.target_position_mm.y, 1)}`],
                  ['observed', chosen.observed_position_mm ? `${fmt(chosen.observed_position_mm.x, 1)}, ${fmt(chosen.observed_position_mm.y, 1)}` : 'unknown'],
                  ['error vector', chosen.error_xy_mm ? `${fmt(chosen.error_xy_mm.x)}, ${fmt(chosen.error_xy_mm.y)}` : '—'],
                  ['retries', String(chosen.retries ?? 0)],
                  ['observations', String(chosen.observations ?? 0)],
                  ['board moved', chosen.board_moved_detected ? 'detected' : 'no'],
                  ['twin', chosen.twin_version_id],
                  ['trace', chosen.trace_id ?? '—'],
                  ['rejection', (chosen as any).rejection_reason ?? '—'],
                ] as [string, string][]).map(([k, v]) => (
                  <div key={k} className="contents"><dt className="text-lab-faint">{k}</dt><dd className="truncate" title={v}>{v}</dd></div>
                ))}
              </dl>
            </Panel>
          )}
        </div>
      </div>
    </Page>
  );
}
