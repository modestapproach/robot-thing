import { startApp } from 'modelence/server';
import exampleModule from '@/server/example';
import autolabModule from '@/server/autolab';
import { createDemoUser } from '@/server/migrations/createDemoUser';

startApp({
  modules: [autolabModule, exampleModule],

  email: {
    // Without this the reset link redirects to the site root and dead-ends.
    passwordReset: {
      redirectUrl: '/reset-password',
    },
  },

  security: {
    frameAncestors: ['https://modelence.com', 'https://*.modelence.com', 'http://localhost:*', 'https://*.exp.direct'],
  },

  migrations: [{
    version: 1,
    description: 'Create demo user',
    handler: createDemoUser,
  }],
});
