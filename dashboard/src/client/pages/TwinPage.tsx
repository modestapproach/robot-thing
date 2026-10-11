/** Digital Twin: version lineage with provenance and calibration parameters (PRD §7.6). */
import Page from '@/client/components/Page';
import { Empty, Panel, Stat } from '@/client/components/lab/Panel';
import { EnvBadge, MonoId } from '@/client/components/lab/Badges';
import { fmt, pct, useTwins, when } from '@/client/lib/autolab';

export default function TwinPage() {
  const { data: twins, isLoading } = useTwins();
  return (
    <Page seo={{ title: 'Digital Twin' }} isLoading={isLoading}>
      <p className="text-[13px] text-lab-dim max-w-3xl">
        Level-0 geometric twin: a versioned board→base similarity transform with an empirical error model. Each version records the
        experiments that informed it and the simulation batch that chose it. Versions are never mutated after use.
      </p>
      {(twins ?? []).length === 0 ? <Empty>No twin versions.</Empty> : (
        <div className="grid gap-4 stagger">
          {(twins ?? []).map((t, i) => {
            const vs = t.validation_summary ?? {};
            const cal = t.calibration_parameters;
            return (
              <Panel key={t._id} title={t._id} tag={<EnvBadge env="simulation" />} action={<span className="font-mono text-[11px] text-lab-faint">{when(t.created_at)}</span>} className="animate-slide-up">
                <div style={{ ['--i' as any]: i }} className="grid md:grid-cols-4 gap-4">
                  <Stat label="offset mm" value={`${fmt(cal.offset_mm.x)}, ${fmt(cal.offset_mm.y)}`} />
                  <Stat label="rotation" value={`${fmt(cal.rotation_deg, 3)}°`} />
                  <Stat label="scale" value={fmt(cal.scale, 4)} />
                  <Stat label="parent" value={<MonoId id={t.parent_version_id} className="text-base" />} sub={`${t.source_experiment_ids?.length ?? 0} source experiments`} />
                </div>
                {vs.prediction_rmse_mm_new !== undefined && (
                  <div className="mt-4 grid md:grid-cols-3 gap-4 border-t border-lab-line pt-3">
                    <Stat label="prediction rmse" value={`${fmt(vs.prediction_rmse_mm_parent)} → ${fmt(vs.prediction_rmse_mm_new)} mm`} sub={`${vs.candidates} candidates, ${vs.rejected_inadmissible} implausible`} />
                    {vs.heldout_physical && (
                      <>
                        <Stat label="held-out rmse" value={`${fmt(vs.heldout_physical.before.rmse_mm)} → ${fmt(vs.heldout_physical.after.rmse_mm)} mm`} tone="ok" />
                        <Stat label="held-out success" value={`${pct(vs.heldout_physical.before.success_rate)} → ${pct(vs.heldout_physical.after.success_rate)}`} sub={`n=${vs.heldout_physical.n_targets} protected targets`} />
                      </>
                    )}
                  </div>
                )}
                {vs.note && <div className="mt-2 text-[12px] text-lab-faint">{vs.note}</div>}
              </Panel>
            );
          })}
        </div>
      )}
    </Page>
  );
}
