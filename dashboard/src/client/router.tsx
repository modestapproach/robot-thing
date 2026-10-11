import { lazy } from 'react';
import { createBrowserRouter, Navigate, Outlet, RouteObject, useLocation, useSearchParams } from 'react-router';
import { useSession } from 'modelence/client';
import { useEmailVerificationStatus } from './lib/verificationStatus';

// Handles the email verification ?status= param on whatever route it lands on.
function RootLayout() {
  useEmailVerificationStatus();
  return <Outlet />;
}

// For guest-only routes (login, signup) - redirects to home if already logged in
function GuestRoute() {
  const { user } = useSession();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const encodedRedirect = searchParams.get('_redirect');
  const redirect = encodedRedirect ? decodeURIComponent(encodedRedirect) : '/';

  if (user) {
    return <Navigate to={redirect} state={{ from: location }} replace />;
  }

  return <Outlet />;
}

// For protected routes - redirects to login if not authenticated
function PrivateRoute() {
  const { user } = useSession();
  const location = useLocation();

  if (!user) {
    const fullPath = location.pathname + location.search;
    return (
      <Navigate
        to={`/login?_redirect=${encodeURIComponent(fullPath)}`}
        state={{ from: location }}
        replace
      />
    );
  }

  return <Outlet />;
}

// Public routes (no auth required)
const publicRoutes: RouteObject[] = [
  {
    path: '/',
    Component: lazy(() => import('./pages/HomePage'))
  },
  { path: '/evolution', Component: lazy(() => import('./pages/EvolutionPage')) },
  { path: '/experiments', Component: lazy(() => import('./pages/ExperimentsPage')) },
  { path: '/twin', Component: lazy(() => import('./pages/TwinPage')) },
  { path: '/traces', Component: lazy(() => import('./pages/TracesPage')) },
  { path: '/safety', Component: lazy(() => import('./pages/SafetyPage')) },
  {
    path: '/terms',
    Component: lazy(() => import('./pages/TermsPage'))
  },
  {
    path: '/logout',
    Component: lazy(() => import('./pages/LogoutPage'))
  },
  // Public, not guest-only: a reset link may open with a stale session active,
  // which GuestRoute would redirect away.
  {
    path: '/forgot-password',
    Component: lazy(() => import('./pages/ForgotPasswordPage'))
  },
  {
    path: '/reset-password',
    Component: lazy(() => import('./pages/ResetPasswordPage'))
  },
  {
    path: '*',
    Component: lazy(() => import('./pages/NotFoundPage'))
  }
];

// Guest routes (redirect to home if already logged in)
const guestRoutes: RouteObject[] = [
  {
    path: '/login',
    Component: lazy(() => import('./pages/LoginPage'))
  },
  {
    path: '/signup',
    Component: lazy(() => import('./pages/SignupPage'))
  }
];

// Private routes (redirect to login if not authenticated)
const privateRoutes: RouteObject[] = [];

export const router = createBrowserRouter([
  {
    Component: RootLayout,
    children: [
      ...publicRoutes,
      {
        Component: GuestRoute,
        children: guestRoutes
      },
      {
        Component: PrivateRoute,
        children: privateRoutes
      }
    ]
  }
]);
