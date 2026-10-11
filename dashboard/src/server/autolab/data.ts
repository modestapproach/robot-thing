/** Read models shared by live queries and REST routes. All reads are bounded. */
import {
  dbAgentTraces, dbAuditLog, dbCampaigns, dbEvaluationResults, dbExperiments, dbHardwareCommands,
  dbHarnessVersions, dbMutationProposals, dbRobots, dbSimTrajectories, dbTwinVersions,
} from './db';

type Doc = Record<string, any>;
const raw = (s: { rawCollection(): any }) => s.rawCollection();

export async function activeHarness(): Promise<Doc | null> {
  return raw(dbHarnessVersions).findOne({ status: 'ACTIVE' });
}

export async function harnessVersions(): Promise<Doc[]> {
  return raw(dbHarnessVersions).find({}).sort({ version: 1 }).limit(100).toArray();
}

export async function experiments(limit = 200, filter: Doc = {}): Promise<Doc[]> {
  return raw(dbExperiments).find(filter).sort({ started_at: -1 }).limit(limit).toArray();
}

export async function experiment(id: string): Promise<Doc | null> {
  return raw(dbExperiments).findOne({ _id: id });
}

export async function mutations(): Promise<Doc[]> {
  return raw(dbMutationProposals).find({}).sort({ created_at: -1 }).limit(100).toArray();
}

export async function mutation(id: string): Promise<Doc | null> {
  const m = await raw(dbMutationProposals).findOne({ _id: id });
  if (!m) return null;
  const evaluation = await raw(dbEvaluationResults).findOne({ candidate_version_id: m.candidate_harness_version });
  return { ...m, evaluation };
}

export async function evaluations(): Promise<Doc[]> {
  return raw(dbEvaluationResults).find({}).sort({ evaluated_at: -1 }).limit(100).toArray();
}

export async function twins(): Promise<Doc[]> {
  return raw(dbTwinVersions).find({}).sort({ created_at: -1 }).limit(50).toArray();
}

export async function campaigns(): Promise<Doc[]> {
  return raw(dbCampaigns).find({}).sort({ updated_at: -1 }).limit(20).toArray();
}

export async function traces(limit = 100): Promise<Doc[]> {
  return raw(dbAgentTraces).find({}).sort({ started: -1 }).limit(limit).toArray();
}

export async function status(): Promise<Doc> {
  const [active, twin, campaign, lastCommand, counts] = await Promise.all([
    activeHarness(),
    raw(dbTwinVersions).find({}).sort({ created_at: -1 }).limit(1).next(),
    raw(dbCampaigns).find({}).sort({ updated_at: -1 }).limit(1).next(),
    raw(dbHardwareCommands).find({}).sort({ issued_at: -1 }).limit(1).next(),
    Promise.all([
      raw(dbExperiments).countDocuments({}),
      raw(dbHardwareCommands).countDocuments({ status: 'acknowledged' }),
      raw(dbHardwareCommands).countDocuments({ status: 'rejected' }),
      raw(dbMutationProposals).countDocuments({}),
      raw(dbMutationProposals).countDocuments({ status: 'REJECTED' }),
      raw(dbHarnessVersions).countDocuments({}),
      raw(dbAuditLog).countDocuments({}),
    ]),
  ]);
  const [nExp, nAck, nRejCmd, nMut, nMutRej, nVersions, nAudit] = counts;
  return {
    activeHarness: active ? { id: active._id, version: active.version, reason: active.proposal_reason } : null,
    twin: twin ? { id: twin._id, backend: twin.backend, parent: twin.parent_version_id, calibration: twin.calibration_parameters } : null,
    campaign: campaign
      ? { id: campaign._id, status: campaign.status, completed: campaign.checkpoint?.completed ?? [], pauseRequested: !!campaign.pause_requested, updatedAt: campaign.updated_at }
      : null,
    lastCommand: lastCommand
      ? { id: lastCommand._id, status: lastCommand.status, issuedAt: lastCommand.issued_at, reason: lastCommand.rejection_reason ?? null }
      : null,
    robot: {
      driver: lastCommand?.controller_state_before ? 'reported' : 'unknown',
      estop: lastCommand?.controller_state_after?.estop_engaged ?? lastCommand?.controller_state_before?.estop_engaged ?? null,
      physicalEnabled: lastCommand?.controller_state_before?.physical_enabled ?? null,
    },
    counts: {
      experiments: nExp, acknowledgedMoves: nAck, rejectedCommands: nRejCmd,
      mutations: nMut, rejectedMutations: nMutRej, harnessVersions: nVersions, auditEvents: nAudit,
    },
  };
}

export async function setCampaignFlag(id: string, flag: 'pause' | 'resume'): Promise<boolean> {
  const update = flag === 'pause'
    ? { $set: { pause_requested: true, updated_at: new Date() } }
    : { $set: { pause_requested: false, resume_requested: true, updated_at: new Date() } };
  const r = await raw(dbCampaigns).updateOne({ _id: id }, update);
  await raw(dbAuditLog).insertOne({ _id: `aud_dash_${Date.now().toString(16)}`, event: `campaign_${flag}_requested`, campaign_id: id, at: new Date(), source: 'dashboard' });
  return r.matchedCount === 1;
}

export async function requestCampaign(objective: string): Promise<string> {
  const id = `camp_req_${Date.now().toString(16)}`;
  await raw(dbCampaigns).insertOne({
    _id: id, objective, status: 'requested', baseline_version_id: (await activeHarness())?._id ?? null,
    scenario_set_id: 'targets_v1', candidate_ids: [], completed_trial_ids: [], pending_trial_ids: [],
    budget: {}, checkpoint: { completed: [], outputs: {}, lab: { bumped: false } },
    created_at: new Date(), updated_at: new Date(), schema_version: 1, source: 'dashboard',
  });
  return id;
}

export async function latestTrajectory(): Promise<Doc | null> {
  return raw(dbSimTrajectories).find({}).sort({ created_at: -1 }).limit(1).next();
}

export async function trajectory(id: string): Promise<Doc | null> {
  return raw(dbSimTrajectories).findOne({ _id: id });
}

export async function robot(): Promise<Doc | null> {
  return raw(dbRobots).find({}).sort({ created_at: -1 }).limit(1).next();
}
