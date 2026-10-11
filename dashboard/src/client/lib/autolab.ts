/** Typed live-query hooks for the AutoLab module. Shapes mirror autolab/shared/schemas.py. */
import { useQuery } from '@tanstack/react-query';
import { modelenceLiveQuery, modelenceQuery } from 'modelence/client';

export type XY = { x: number; y: number };
export type Env = 'simulation' | 'real_hardware' | 'replay';

export interface Experiment {
  _id: string;
  campaign_id?: string | null;
  scenario_id: string;
  harness_version_id: string;
  twin_version_id: string;
  target_position_mm: XY;
  predicted_position_mm?: XY | null;
  observed_position_mm?: XY | null;
  position_error_mm?: number | null;
  error_xy_mm?: XY | null;
  execution_environment: Env;
  verification_status: 'pending' | 'verified' | 'failed' | 'unknown';
  started_at: string | Date;
  completed_at?: string | Date | null;
  trace_id?: string | null;
  retries?: number;
  observations?: number;
  movements?: number;
  board_moved_detected?: boolean;
  first_attempt_error_mm?: number | null;
}

export interface WorkflowStep { op: string; params?: Record<string, unknown> }
export interface HarnessVersion {
  _id: string;
  version: number;
  parent_version_id: string | null;
  status: string;
  workflow_steps: WorkflowStep[];
  memory_policy: Record<string, unknown>;
  retry_policy: Record<string, unknown>;
  experiment_policy: Record<string, unknown>;
  created_by: string;
  proposal_reason: string;
  created_at: string | Date;
}

export interface MutationProposal {
  _id: string;
  base_harness_version: string;
  candidate_harness_version: string;
  mutation_type: string;
  patch: Record<string, unknown>;
  hypothesis: string;
  expected_improvement: string;
  risk_classification: string;
  status: string;
  decision_reason?: string | null;
  created_at: string | Date;
}

export interface Metrics {
  n: number; success_rate: number; mean_error_mm: number; median_error_mm: number; rmse_mm: number; p90_error_mm: number;
  unknown_rate: number; observations_per_task: number; movements_per_task: number; retries_per_task: number;
}
export interface EvaluationResult {
  _id: string;
  candidate_version_id: string;
  baseline_version_id: string;
  protected_test_set_version: string;
  simulation_metrics: Record<string, any>;
  physical_metrics: Record<string, any>;
  safety_invariants: Record<string, boolean>;
  protected_tests: Record<string, boolean>;
  decision: 'approve' | 'reject' | 'needs_review';
  reasons: string[];
  evaluated_at: string | Date;
}

export interface TwinVersion {
  _id: string;
  parent_version_id: string | null;
  backend: string;
  calibration_parameters: { offset_mm: XY; rotation_deg: number; scale: number; calibration_version: string };
  uncertainty_parameters: { actuation_sigma_mm: number; observation_sigma_mm: number };
  source_experiment_ids: string[];
  validation_summary: Record<string, any>;
  created_at: string | Date;
}

export interface Trace {
  _id: string; agent: string; event: string; input: string; output: string;
  properties: Record<string, any>; spans: { name: string; ms: number; [k: string]: unknown }[];
  signals: { name: string }[]; started: number; raindrop?: boolean;
}

export interface Campaign {
  _id: string; objective: string; status: string; checkpoint: { completed: string[]; outputs: Record<string, any>; lab?: { bumped?: boolean } };
  pause_requested?: boolean; updated_at: string | Date;
}

export interface Status {
  activeHarness: { id: string; version: number; reason: string } | null;
  twin: { id: string; backend: string; parent: string | null; calibration: TwinVersion['calibration_parameters'] } | null;
  campaign: { id: string; status: string; completed: string[]; pauseRequested: boolean; updatedAt: string } | null;
  lastCommand: { id: string; status: string; issuedAt: string; reason: string | null } | null;
  robot: { driver: string; estop: boolean | null; physicalEnabled: boolean | null };
  counts: Record<string, number>;
}

const live = <T,>(name: string, args: Record<string, unknown> = {}) => useQuery(modelenceLiveQuery<T>(`autolab.${name}`, args));

export const useStatus = () => live<Status>('status');
export const useExperiments = (limit = 200) => live<Experiment[]>('experiments', { limit });
export const useHarnessVersions = () => live<HarnessVersion[]>('harnessVersions');
export const useMutations = () => live<MutationProposal[]>('mutations');
export const useEvaluations = () => live<EvaluationResult[]>('evaluations');
export const useTwins = () => live<TwinVersion[]>('twins');
export const useCampaigns = () => live<Campaign[]>('campaigns');
export const useTraces = () => live<Trace[]>('traces');

export const CAMPAIGN_STAGES = ['setup', 'baseline', 'recalibrate', 'verify_calibration', 'disturbance', 'investigate', 'recovered', 'meta_improvement', 'report'];

export const fmt = (n: number | null | undefined, d = 2) => (n === null || n === undefined || Number.isNaN(n) ? '—' : n.toFixed(d));
export const pct = (n: number | null | undefined) => (n === null || n === undefined || Number.isNaN(n) ? '—' : `${Math.round(n * 100)}%`);
export const shortId = (id?: string | null) => (id ? id.replace(/^(\w+?)_[0-9a-f]+_/, '$1_') : '—');
export const when = (d: string | Date | number | undefined | null) => {
  if (!d) return '—';
  const t = typeof d === 'number' ? new Date(d * 1000) : new Date(d);
  return t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export interface Trajectory {
  _id: string; command_id: string; harness_version_id: string; driver: string; environment: Env;
  target_base_mm: XY; height_mm: number; t: number[]; bodies: string[]; pos_mm: number[][][]; q_rad: number[][]; created_at: string | Date;
}
export interface Envelope { x_min: number; x_max: number; y_min: number; y_max: number; min_height_mm: number; max_height_mm: number; max_speed_fraction: number; command_timeout_s: number; max_step_mm: number }
export interface Robot { _id: string; name: string; manufacturer: string; model: string; control_interface: string; joint_count: number; safety_envelope?: Envelope; driver?: string; is_physical?: boolean }

export const useLatestTrajectory = () => live<Trajectory | null>('latestTrajectory');
export const useRobot = () => live<Robot | null>('robot');
export const useTrajectory = (id?: string | null) =>
  useQuery({ ...modelenceQuery<Trajectory | null>('autolab.trajectory', { id: id ?? '' }), enabled: !!id });
