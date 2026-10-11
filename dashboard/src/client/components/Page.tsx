/**
 * Page frame for every AutoLab page: lab header with section nav, live status dot,
 * and session controls. See DESIGN.md.
 */
import React from 'react';
import { Link, NavLink } from 'react-router';
import { useSession } from 'modelence/client';
import LoadingSpinner from '@/client/components/LoadingSpinner';
import { Seo, type SeoProps } from '@/client/components/Seo';
import { cn } from '@/client/lib/utils';

interface PageProps {
  children?: React.ReactNode;
  isLoading?: boolean;
  className?: string;
  seo?: SeoProps;
}

const NAV = [
  { to: '/', label: 'Lab' },
  { to: '/evolution', label: 'Harness Evolution' },
  { to: '/experiments', label: 'Experiments' },
  { to: '/twin', label: 'Digital Twin' },
  { to: '/traces', label: 'Agent Traces' },
  { to: '/safety', label: 'Safety' },
];

function Header() {
  const { user } = useSession();
  return (
    <header className="sticky top-0 z-20 border-b border-lab-line bg-lab-bg/90 backdrop-blur">
      <div className="flex items-center gap-6 px-4 md:px-6 h-14">
        <Link to="/" className="flex items-center gap-2.5 shrink-0">
          <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden>
            <rect x="1" y="1" width="20" height="20" rx="4" fill="none" stroke="var(--color-measured)" strokeWidth="1.5" />
            <circle cx="7" cy="15" r="2" fill="var(--color-target)" />
            <path d="M7 15 L11 7 L16 9" fill="none" stroke="var(--color-simulated)" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="16" cy="9" r="1.6" fill="var(--color-measured)" />
          </svg>
          <span className="font-display font-semibold tracking-tight text-[15px]">AutoLab</span>
        </Link>
        <nav className="hidden md:flex items-center gap-1 overflow-x-auto">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                cn(
                  'px-3 py-1.5 rounded-[var(--radius-chip)] text-[13px] transition-colors whitespace-nowrap',
                  isActive ? 'bg-lab-raised text-lab-text' : 'text-lab-dim hover:text-lab-text'
                )
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-[13px]">
          {user ? (
            <>
              <span className="hidden sm:inline font-mono text-lab-dim">{user.handle}</span>
              <Link to="/logout" className="text-lab-dim hover:text-lab-text">Sign out</Link>
            </>
          ) : (
            <Link to="/login" className="px-3 py-1.5 rounded-[var(--radius-chip)] border border-lab-line text-lab-dim hover:text-lab-text">
              Operator sign in
            </Link>
          )}
        </div>
      </div>
      <nav className="md:hidden flex gap-1 px-4 pb-2 overflow-x-auto">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => cn('px-2.5 py-1 rounded text-xs whitespace-nowrap', isActive ? 'bg-lab-raised text-lab-text' : 'text-lab-dim')}>
            {n.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}

export default function Page({ children, className, isLoading = false, seo }: PageProps) {
  return (
    <div className="flex flex-col min-h-screen max-w-full overflow-x-hidden">
      <Seo {...seo} />
      <Header />
      <main className={cn('flex flex-col flex-1 px-4 md:px-6 py-5 gap-4 overflow-x-hidden animate-fade-in', className)}>
        {isLoading ? (
          <div className="flex items-center justify-center w-full flex-1">
            <LoadingSpinner />
          </div>
        ) : (
          children
        )}
      </main>
    </div>
  );
}
