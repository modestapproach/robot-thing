/** Agent Traces (PRD §11.2, §12): every meaningful run with spans, signals, and Raindrop linkage. */
import { useState } from 'react';
import Page from '@/client/components/Page';
import { Empty, Panel } from '@/client/components/lab/Panel';
import { MonoId } from '@/client/components/lab/Badges';
import { cn } from '@/client/lib/utils';
import { useTraces, when } from '@/client/lib/autolab';

const NEG = new Set(['robot_target_missed', 'twin_prediction_mismatch', 'unnecessary_retry', 'candidate_rejected', 'harness_regression']);

export default function TracesPage() {
  const { data: traces, isLoading } = useTraces();
  const [agent, setAgent] = useState('all');
  const rows = (traces ?? []).filter((t) => agent === 'all' || t.agent === agent);
  return (
    <Page seo={{ title: 'Agent Traces' }} isLoading={isLoading}>
      <div className="flex items-center gap-2">
        {['all', 'autolab-operator', 'autolab-scientist'].map((a) => (
          <button key={a} onClick={() => setAgent(a)} className={cn('px-3 py-1 rounded-[var(--radius-chip)] text-[12px] border font-mono', agent === a ? 'border-measured/50 bg-lab-raised' : 'border-lab-line text-lab-dim')}>{a}</button>
        ))}
        <span className="ml-auto text-[11px] text-lab-faint">{rows.some((t) => t.raindrop) ? 'mirrored to Raindrop (event id = trace id)' : 'Raindrop not configured: local traces only'}</span>
      </div>
      {rows.length === 0 ? <Empty>No traces yet.</Empty> : (
        <div className="grid gap-2">
          {rows.map((t) => {
            const total = Math.max(1, t.spans.reduce((a, s) => a + s.ms, 0));
            return (
              <Panel key={t._id} title={`${t.agent} · ${t.event}`} action={<><MonoId id={t._id} /><span className="font-mono text-[11px] text-lab-faint">{when(t.started)}</span></>}>
                <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4 text-[12px]">
                  <div className="grid gap-1.5 min-w-0">
                    <div className="text-lab-dim"><span className="text-lab-faint">in </span>{t.input}</div>
                    <div className="text-lab-text break-words"><span className="text-lab-faint">out </span>{t.output}</div>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {t.properties.outcome && <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-lab-line">{String(t.properties.outcome)}</span>}
                      {t.properties.model && <span className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-lab-line text-lab-dim">{String(t.properties.model)}</span>}
                      {t.signals.map((s, i) => (
                        <span key={i} className={cn('font-mono text-[10px] px-1.5 py-0.5 rounded border', NEG.has(s.name) ? 'text-fail border-fail/40' : 'text-ok border-ok/40')}>⚑ {s.name}</span>
                      ))}
                    </div>
                  </div>
                  <div className="grid gap-1 content-start">
                    {t.spans.map((s, i) => (
                      <div key={i} className="flex items-center gap-2 font-mono text-[11px]">
                        <span className="w-36 truncate text-lab-dim">{s.name}</span>
                        <div className="flex-1 h-1.5 rounded-sm bg-lab-raised overflow-hidden"><div className="h-full bg-measured/70" style={{ width: `${Math.max(2, (s.ms / total) * 100)}%` }} /></div>
                        <span className="w-16 text-right text-lab-faint tabular">{s.ms.toFixed(1)} ms</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Panel>
            );
          })}
        </div>
      )}
    </Page>
  );
}
