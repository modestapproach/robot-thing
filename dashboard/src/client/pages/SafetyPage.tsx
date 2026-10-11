/**
 * Safety / Control (PRD §11.2, §6.6). The envelope shown here is read-only and mirrors
 * autolab/robot_gateway/safety.py; it is enforced in the local gateway, never from this page
 * or any database document. The physical e-stop is independent of all software.
 */
import { useMutation } from '@tanstack/react-query';
import { modelenceMutation, useSession } from 'modelence/client';
import toast from 'react-hot-toast';
import Page from '@/client/components/Page';
import { Panel, Stat } from '@/client/components/lab/Panel';
import { MonoId, StatusBadge } from '@/client/components/lab/Badges';
import { useCampaigns, useRobot, useStatus, when, type Envelope } from '@/client/lib/autolab';

function envelopeRows(e?: Envelope): [string, string][] {
  const fixed: [string, string][] = [
    ['reachability', 'IK pre-check: unreachable targets rejected before motion'],
    ['in-flight motions', 'at most 1'],
    ['duplicate commands', 'rejected by idempotency key before motion'],
    ['physical enable', 'ROBOT_PHYSICAL_ENABLE hard switch, default off'],
  ];
  if (!e) return [['envelope', 'not reported yet'], ...fixed];
  return [
    ['reachable box (F_base)', `x ${e.x_min}…${e.x_max} mm, y ${e.y_min}…${e.y_max} mm`],
    ['tool height', `${e.min_height_mm}…${e.max_height_mm} mm (safe working height 40 mm)`],
    ['max speed', `${Math.round(e.max_speed_fraction * 100)}% of manufacturer max (AI may only lower)`],
    ['command timeout', `${e.command_timeout_s} s`],
    ['single-move travel', `≤ ${e.max_step_mm} mm`],
    ...fixed,
  ];
}

export default function SafetyPage() {
  const { data: s } = useStatus();
  const { data: camps } = useCampaigns();
  const { data: robot } = useRobot();
  const { user } = useSession();
  const pause = useMutation({ ...modelenceMutation('autolab.pauseCampaign'), onSuccess: () => toast.success('Pause requested') });
  const resume = useMutation({ ...modelenceMutation('autolab.resumeCampaign'), onSuccess: () => toast.success('Resume requested') });
  return (
    <Page seo={{ title: 'Safety' }}>
      <div className="grid lg:grid-cols-3 gap-4 items-start">
        <Panel title="Robot status">
          <div className="grid grid-cols-2 gap-4">
            <Stat label="e-stop" value={s?.robot.estop == null ? 'unknown' : s.robot.estop ? 'ENGAGED' : 'released'} tone={s?.robot.estop ? 'fail' : s?.robot.estop === false ? 'ok' : 'warn'} />
            <Stat label="motion enable" value={s?.robot.physicalEnabled == null ? 'unknown' : s.robot.physicalEnabled ? 'enabled' : 'disabled'} tone={s?.robot.physicalEnabled ? 'warn' : undefined} />
            <Stat label="last command" value={s?.lastCommand ? <StatusBadge status={s.lastCommand.status} /> : '—'} sub={s?.lastCommand ? when(s.lastCommand.issuedAt) : undefined} />
            <Stat label="rejected commands" value={s?.counts.rejectedCommands ?? 0} />
          </div>
          {s?.lastCommand?.reason && <div className="mt-3 text-[12px] text-warn">{s.lastCommand.reason}</div>}
          <p className="mt-4 text-[12px] text-lab-faint">The hardware emergency stop is independent of this dashboard, Atlas, and the agents.</p>
        </Panel>
        <Panel title="Fixed safety envelope" tag={<span className="font-mono text-[10px] text-lab-faint">{robot?.model ?? 'robot'} · read-only mirror · enforced in the local gateway</span>} className="lg:col-span-2">
          <table className="w-full text-[13px]">
            <tbody>
              {envelopeRows(robot?.safety_envelope).map(([k, v]) => (
                <tr key={k} className="border-b border-lab-line/60 last:border-0">
                  <td className="py-1.5 text-lab-dim">{k}</td><td className="py-1.5 font-mono text-[12px] text-right">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[12px] text-lab-faint">Harness mutations can tighten operations but cannot reach these limits; loosening requires an operator-controlled procedure outside AutoLab.</p>
        </Panel>
      </div>
      <Panel title="Campaign control" tag={!user && <span className="text-[11px] text-lab-faint">sign in to pause or resume</span>} bodyClassName="p-0">
        <table className="w-full text-[12px]">
          <tbody>
            {(camps ?? []).map((c) => (
              <tr key={c._id} className="border-b border-lab-line/60 last:border-0">
                <td className="px-4 py-2"><MonoId id={c._id} /></td>
                <td><StatusBadge status={c.status} /></td>
                <td className="text-lab-dim">{c.checkpoint?.completed?.length ?? 0} stages done{c.pause_requested ? ' · pause requested' : ''}</td>
                <td className="text-right px-4 space-x-2">
                  <button disabled={!user || pause.isPending} onClick={() => pause.mutate({ id: c._id })} className="px-2.5 py-1 rounded border border-warn/40 text-warn disabled:opacity-40">Pause</button>
                  <button disabled={!user || resume.isPending} onClick={() => resume.mutate({ id: c._id })} className="px-2.5 py-1 rounded border border-measured/40 text-measured disabled:opacity-40">Resume</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </Page>
  );
}
