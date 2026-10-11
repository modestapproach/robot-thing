import { cn } from '@/client/lib/utils';
import type { Env } from '@/client/lib/autolab';

const chip = 'inline-flex items-center gap-1 rounded-[var(--radius-chip)] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider border whitespace-nowrap';

/** Provenance is mandatory on every result (PRD §22 scientific integrity). */
export function EnvBadge({ env }: { env: Env | string }) {
  const map: Record<string, [string, string]> = {
    real_hardware: ['measured', 'text-measured border-measured/40 bg-measured/10'],
    simulation: ['simulated', 'text-simulated border-simulated/40 bg-simulated/10'],
    replay: ['replay', 'text-replay border-replay/40 bg-replay/10'],
  };
  const [label, cls] = map[env] ?? [String(env), 'text-lab-dim border-lab-line'];
  return <span className={cn(chip, cls)} title={env === 'simulation' ? 'Simulation or mock arm — not a physical measurement' : undefined}>{label}</span>;
}

const STATUS_TONE: Record<string, string> = {
  ACTIVE: 'text-ok border-ok/40 bg-ok/10',
  APPROVED: 'text-ok border-ok/30',
  approve: 'text-ok border-ok/40 bg-ok/10',
  verified: 'text-ok border-ok/30',
  completed: 'text-ok border-ok/30',
  acknowledged: 'text-ok border-ok/30',
  REJECTED: 'text-fail border-fail/40 bg-fail/10',
  reject: 'text-fail border-fail/40 bg-fail/10',
  failed: 'text-fail border-fail/30',
  rejected: 'text-fail border-fail/30',
  ROLLED_BACK: 'text-warn border-warn/40',
  NEEDS_REVIEW: 'text-warn border-warn/40',
  needs_review: 'text-warn border-warn/40',
  paused: 'text-warn border-warn/40',
  unknown: 'text-warn border-warn/40',
  running: 'text-measured border-measured/40',
  SUPERSEDED: 'text-lab-dim border-lab-line',
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={cn(chip, STATUS_TONE[status] ?? 'text-lab-dim border-lab-line')}>{status.replace(/_/g, ' ')}</span>;
}

export function MonoId({ id, className }: { id?: string | null; className?: string }) {
  return <span className={cn('font-mono text-[11px] text-lab-dim', className)} title={id ?? undefined}>{id ? id.replace(/^(\w+?)_[0-9a-f]{8,}_/, '$1_') : '—'}</span>;
}
