/**
 * AutoLab module: live queries for the lab dashboard and the REST contract from
 * PRD §11.5. Reads are public (judges can open the dashboard); campaign control
 * requires a signed-in user (queries/mutations) or the AUTOLAB_API_KEY header (REST).
 */
import z from 'zod';
import { AuthError } from 'modelence';
import { LiveData, Module, UserInfo } from 'modelence/server';
import type { RouteParams } from 'modelence/server';
import { allStores, dbAgentTraces, dbCampaigns, dbEvaluationResults, dbExperiments, dbHardwareCommands, dbHarnessVersions, dbMutationProposals, dbRobots, dbSimTrajectories, dbTwinVersions } from './db';
import * as data from './data';

type AnyStore = { watch(pipeline?: any[]): { on(ev: string, cb: () => void): void; close(): Promise<void> | void } };

/** Live data that re-publishes (debounced) when any of the given collections change. */
function live<T>(fetch: () => Promise<T>, stores: AnyStore[]) {
  return new LiveData({
    fetch,
    watch: ({ publish }) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const bump = () => {
        if (timer) return;
        timer = setTimeout(() => { timer = null; publish(); }, 400); // aggregate bursts; never per physics step
      };
      const streams = stores.map((s) => {
        const cs = s.watch();
        cs.on('change', bump);
        cs.on('error', () => {}); // change streams need a replica set (Atlas); degrade to static data otherwise
        return cs;
      });
      return () => { streams.forEach((cs) => cs.close()); if (timer) clearTimeout(timer); };
    },
  });
}

function requireUser(user: UserInfo | null) {
  if (!user) throw new AuthError('Sign in to control campaigns');
}

function requireKey(headers: Record<string, string>) {
  const key = process.env.AUTOLAB_API_KEY;
  return !!key && headers['x-autolab-key'] === key;
}

const json = (d: unknown, status = 200) => ({ status, data: d });

export default new Module('autolab', {
  stores: allStores,

  queries: {
    status: async () => live(data.status, [dbHarnessVersions, dbTwinVersions, dbCampaigns, dbHardwareCommands, dbExperiments, dbMutationProposals]),
    experiments: async (args: unknown) => {
      const { limit } = z.object({ limit: z.number().int().min(1).max(500).optional() }).parse(args ?? {});
      return live(() => data.experiments(limit ?? 200), [dbExperiments]);
    },
    experiment: async (args: unknown) => {
      const { id } = z.object({ id: z.string() }).parse(args);
      return data.experiment(id);
    },
    harnessVersions: async () => live(data.harnessVersions, [dbHarnessVersions]),
    mutations: async () => live(data.mutations, [dbMutationProposals, dbEvaluationResults]),
    evaluations: async () => live(data.evaluations, [dbEvaluationResults]),
    twins: async () => live(data.twins, [dbTwinVersions]),
    campaigns: async () => live(data.campaigns, [dbCampaigns]),
    traces: async () => live(() => data.traces(150), [dbAgentTraces]),
    latestTrajectory: async () => live(data.latestTrajectory, [dbSimTrajectories]),
    trajectory: async (args: unknown) => {
      const { id } = z.object({ id: z.string() }).parse(args);
      return data.trajectory(id);
    },
    robot: async () => live(data.robot, [dbRobots]),
  },

  mutations: {
    pauseCampaign: async (args: unknown, { user }: { user: UserInfo | null }) => {
      requireUser(user);
      const { id } = z.object({ id: z.string() }).parse(args);
      return data.setCampaignFlag(id, 'pause');
    },
    resumeCampaign: async (args: unknown, { user }: { user: UserInfo | null }) => {
      requireUser(user);
      const { id } = z.object({ id: z.string() }).parse(args);
      return data.setCampaignFlag(id, 'resume');
    },
  },

  routes: [
    { path: '/api/autolab/status', handlers: { get: async () => json(await data.status()) } },
    { path: '/api/autolab/experiments', handlers: { get: async ({ query }: RouteParams) => json(await data.experiments(Math.min(500, Number(query.limit) || 200))) } },
    {
      path: '/api/autolab/experiments/:id',
      handlers: { get: async ({ params }: RouteParams) => { const e = await data.experiment(params.id); return e ? json(e) : json({ error: 'not found' }, 404); } },
    },
    {
      path: '/api/autolab/harness/active',
      handlers: { get: async () => { const h = await data.activeHarness(); return h ? json(h) : json({ error: 'no active harness' }, 404); } },
    },
    { path: '/api/autolab/harness/versions', handlers: { get: async () => json(await data.harnessVersions()) } },
    {
      path: '/api/autolab/mutations/:id',
      handlers: { get: async ({ params }: RouteParams) => { const m = await data.mutation(params.id); return m ? json(m) : json({ error: 'not found' }, 404); } },
    },
    {
      path: '/api/autolab/campaigns',
      handlers: {
        post: async ({ body, headers }: RouteParams) => {
          if (!requireKey(headers)) return json({ error: 'unauthorized' }, 401);
          const { objective } = z.object({ objective: z.string().max(500).optional() }).parse(body ?? {});
          const id = await data.requestCampaign(objective ?? 'Dashboard-requested campaign');
          return json({ id, status: 'requested', note: 'picked up by `python scripts/run_campaign.py --worker`' }, 202);
        },
      },
    },
    {
      path: '/api/autolab/campaigns/:id/pause',
      handlers: {
        post: async ({ params, headers }: RouteParams) => {
          if (!requireKey(headers)) return json({ error: 'unauthorized' }, 401);
          return (await data.setCampaignFlag(params.id, 'pause')) ? json({ id: params.id, pause_requested: true }) : json({ error: 'not found' }, 404);
        },
      },
    },
    {
      path: '/api/autolab/campaigns/:id/resume',
      handlers: {
        post: async ({ params, headers }: RouteParams) => {
          if (!requireKey(headers)) return json({ error: 'unauthorized' }, 401);
          return (await data.setCampaignFlag(params.id, 'resume')) ? json({ id: params.id, resume_requested: true }) : json({ error: 'not found' }, 404);
        },
      },
    },
  ],
});
