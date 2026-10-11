/**
 * Calibration board in F_board millimetres (200 x 150). Targets are rings, observed
 * end-effector positions are dots colored by provenance, error vectors connect them.
 * Error vectors can be exaggerated (scale) so millimetre misses are visible; the
 * scale is always printed on the plot.
 */
import type { Experiment } from '@/client/lib/autolab';

const W = 200, H = 150, PAD = 12;
const envColor = (e: string) => (e === 'real_hardware' ? 'var(--color-measured)' : e === 'replay' ? 'var(--color-replay)' : 'var(--color-simulated)');

export function BoardPlot({ experiments, exaggerate = 4, selectedId, onSelect, tolerance = 2 }: {
  experiments: Experiment[]; exaggerate?: number; selectedId?: string | null; onSelect?: (id: string) => void; tolerance?: number;
}) {
  const y = (v: number) => H - v; // board y-up -> svg y-down
  return (
    <svg viewBox={`${-PAD} ${-PAD} ${W + 2 * PAD} ${H + 2 * PAD}`} className="w-full h-auto max-h-[300px] block" role="img" aria-label="Calibration board with targets and observed positions">
      <rect x={0} y={0} width={W} height={H} rx={2} fill="var(--color-lab-bg)" stroke="var(--color-lab-line)" strokeWidth={0.6} />
      {Array.from({ length: 7 }, (_, i) => (i + 1) * 25).map((x) => <line key={`vx${x}`} x1={x} y1={0} x2={x} y2={H} stroke="var(--color-lab-grid)" strokeWidth={0.4} />)}
      {Array.from({ length: 5 }, (_, i) => (i + 1) * 25).map((v) => <line key={`hy${v}`} x1={0} y1={y(v)} x2={W} y2={y(v)} stroke="var(--color-lab-grid)" strokeWidth={0.4} />)}
      <text x={0} y={H + 8} fontSize={5} fill="var(--color-lab-faint)" fontFamily="var(--font-mono)">0</text>
      <text x={W - 14} y={H + 8} fontSize={5} fill="var(--color-lab-faint)" fontFamily="var(--font-mono)">200 mm</text>
      <text x={-PAD + 1} y={6} fontSize={5} fill="var(--color-lab-faint)" fontFamily="var(--font-mono)">150</text>
      <text x={W - 64} y={-4} fontSize={4.6} fill="var(--color-lab-faint)" fontFamily="var(--font-mono)">error vectors ×{exaggerate} · tol {tolerance} mm</text>
      {experiments.map((e) => {
        const t = e.target_position_mm;
        const o = e.observed_position_mm;
        const sel = e._id === selectedId;
        const ok = (e.position_error_mm ?? Infinity) <= tolerance;
        const ox = o ? t.x + (o.x - t.x) * exaggerate : null;
        const oy = o ? t.y + (o.y - t.y) * exaggerate : null;
        const c = envColor(e.execution_environment);
        return (
          <g key={e._id} onClick={() => onSelect?.(e._id)} style={{ cursor: onSelect ? 'pointer' : undefined }} opacity={selectedId && !sel ? 0.45 : 1}>
            <circle cx={t.x} cy={y(t.y)} r={tolerance * exaggerate} fill="none" stroke="var(--color-target)" strokeOpacity={0.18} strokeDasharray="1 1.4" strokeWidth={0.4} />
            <circle cx={t.x} cy={y(t.y)} r={2.2} fill="none" stroke="var(--color-target)" strokeWidth={sel ? 0.9 : 0.6} />
            {ox !== null && oy !== null && (
              <>
                <line x1={t.x} y1={y(t.y)} x2={ox} y2={y(oy)} stroke={ok ? 'var(--color-ok)' : 'var(--color-fail)'} strokeWidth={0.6} strokeOpacity={0.8} />
                <circle cx={ox} cy={y(oy)} r={sel ? 2 : 1.5} fill={c} />
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function BoardLegend() {
  const item = (c: string, l: string, ring = false) => (
    <span className="inline-flex items-center gap-1.5">
      <svg width="10" height="10">{ring ? <circle cx="5" cy="5" r="3.5" fill="none" stroke={c} /> : <circle cx="5" cy="5" r="3" fill={c} />}</svg>{l}
    </span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-lab-dim">
      {item('var(--color-target)', 'target', true)}
      {item('var(--color-measured)', 'measured')}
      {item('var(--color-simulated)', 'simulated')}
      <span className="inline-flex items-center gap-1.5"><span className="w-3 h-px bg-ok" />within tol</span>
      <span className="inline-flex items-center gap-1.5"><span className="w-3 h-px bg-fail" />miss</span>
    </div>
  );
}
