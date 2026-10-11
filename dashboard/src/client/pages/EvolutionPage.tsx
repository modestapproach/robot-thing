/** Harness Evolution (PRD §11.2): lineage, diffs, proposal reasoning, evaluation evidence, rollbacks. */
import { useState } from 'react';
import Page from '@/client/components/Page';
import { Empty, Panel } from '@/client/components/lab/Panel';
import { MonoId, StatusBadge } from '@/client/components/lab/Badges';
import { HarnessDiff } from '@/client/components/lab/HarnessDiff';
import { MetricsCompare } from '@/client/components/lab/MetricsCompare';
import { cn } from '@/client/lib/utils';
import { useEvaluations, useHarnessVersions, useMutations, when } from '@/client/lib/autolab';

export default function EvolutionPage() {
  const { data: versions, isLoading } = useHarnessVersions();
  const { data: evals } = useEvaluations();
  const { data: muts } = useMutations();
  const [selId, setSel] = useState<string | null>(null);
  const list = [...(versions ?? [])].sort((a, b) => b.version - a.version || String(b.created_at).localeCompare(String(a.created_at)));
  const sel = list.find((v) => v._id === selId) ?? list.find((v) => v.status === 'ACTIVE') ?? list[0];
  const parent = sel ? (versions ?? []).find((v) => v._id === sel.parent_version_id) : undefined;
  const evaluation = sel ? (evals ?? []).find((e) => e.candidate_version_id === sel._id) : undefined;
  const proposal = sel ? (muts ?? []).find((m) => m.candidate_harness_version === sel._id) : undefined;
  const invalid = (muts ?? []).filter((m) => m.candidate_harness_version === '(invalid)');

  return (
    <Page seo={{ title: 'Harness Evolution' }} isLoading={isLoading}>
      <div className="grid lg:grid-cols-[320px_minmax(0,1fr)] gap-4 items-start">
        <Panel title="Lineage" bodyClassName="p-2">
          {list.length === 0 ? <Empty>No harness versions.</Empty> : (
            <ul className="grid gap-1 stagger">
              {list.map((v, i) => (
                <li key={v._id} style={{ ['--i' as any]: i }}>
                  <button onClick={() => setSel(v._id)} className={cn('w-full text-left rounded-md px-3 py-2 transition-colors', sel?._id === v._id ? 'bg-lab-raised' : 'hover:bg-lab-raised/60')}>
                    <div className="flex items-center gap-2">
                      <span className="font-display font-semibold">v{v.version}</span>
                      <StatusBadge status={v.status} />
                      <span className="ml-auto font-mono text-[10px] text-lab-faint">{when(v.created_at)}</span>
                    </div>
                    <div className="mt-0.5 text-[12px] text-lab-dim line-clamp-2">{v.proposal_reason || '—'}</div>
                    <div className="mt-0.5 flex gap-2 text-[10px]"><MonoId id={v._id} /><span className="text-lab-faint">by {v.created_by}</span></div>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {invalid.length > 0 && (
            <div className="mt-2 border-t border-lab-line pt-2 px-2">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint mb-1">refused before versioning</div>
              {invalid.map((m) => <div key={m._id} className="text-[11px] text-fail/90">{m.mutation_type}: {m.decision_reason}</div>)}
            </div>
          )}
        </Panel>

        {sel && (
          <div className="grid gap-4 min-w-0">
            <Panel title={`Version ${sel.version}`} tag={<StatusBadge status={sel.status} />} action={<MonoId id={sel._id} />}>
              <div className="grid xl:grid-cols-2 gap-5">
                <div className="grid gap-3 content-start">
                  {proposal && (
                    <div className="rounded-md border border-lab-line p-3 grid gap-2 text-[13px]">
                      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint">
                        proposal · {proposal.mutation_type} · risk {proposal.risk_classification}
                      </div>
                      <div><span className="text-lab-faint">hypothesis </span>{proposal.hypothesis}</div>
                      <div><span className="text-lab-faint">expected </span>{proposal.expected_improvement}</div>
                    </div>
                  )}
                  <HarnessDiff base={parent} cand={sel} />
                </div>
                <div className="min-w-0">
                  {evaluation ? <MetricsCompare evaluation={evaluation} /> : <Empty>{sel.parent_version_id ? 'Not evaluated yet.' : 'Baseline version: no evaluation needed.'}</Empty>}
                </div>
              </div>
            </Panel>
          </div>
        )}
      </div>
    </Page>
  );
}
