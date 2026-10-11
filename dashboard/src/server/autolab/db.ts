/**
 * Stores over the collections the Python services write (one canonical DB, PRD §5.4).
 *
 * Python owns the schema (autolab/shared/schemas.py) and uses string `_id`s, so the
 * Modelence schemas here are deliberately minimal and reads go through
 * `rawCollection()`. The dashboard never writes experiment evidence; the only write
 * is a campaign pause/resume *request* flag.
 */
import { Store, schema } from 'modelence/server';

const loose = { schema_version: schema.number().optional() };

export const dbExperiments = new Store('experiments', { schema: loose, indexes: [] });
export const dbHarnessVersions = new Store('harness_versions', { schema: loose, indexes: [] });
export const dbMutationProposals = new Store('mutation_proposals', { schema: loose, indexes: [] });
export const dbEvaluationResults = new Store('evaluation_results', { schema: loose, indexes: [] });
export const dbTwinVersions = new Store('twin_versions', { schema: loose, indexes: [] });
export const dbCampaigns = new Store('experiment_campaigns', { schema: loose, indexes: [] });
export const dbHardwareCommands = new Store('hardware_commands', { schema: loose, indexes: [] });
export const dbAgentTraces = new Store('agent_traces', { schema: loose, indexes: [] });
export const dbAuditLog = new Store('audit_log', { schema: loose, indexes: [] });
export const dbSimTrajectories = new Store('sim_trajectories', { schema: loose, indexes: [] });
export const dbRobots = new Store('robots', { schema: loose, indexes: [] });

export const allStores = [
  dbExperiments, dbHarnessVersions, dbMutationProposals, dbEvaluationResults, dbTwinVersions,
  dbCampaigns, dbHardwareCommands, dbAgentTraces, dbAuditLog, dbSimTrajectories, dbRobots,
];
