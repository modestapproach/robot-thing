import React from 'react';
import { cn } from '@/client/lib/utils';

export function Panel({ title, tag, action, children, className, bodyClassName }: {
  title: string; tag?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string; bodyClassName?: string;
}) {
  return (
    <section className={cn('flex flex-col min-w-0 rounded-[var(--radius-panel)] border border-lab-line bg-lab-panel', className)}>
      <header className="flex items-center gap-2 px-4 h-10 border-b border-lab-line">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-lab-dim">{title}</h2>
        {tag}
        <div className="ml-auto flex items-center gap-2">{action}</div>
      </header>
      <div className={cn('p-4 min-w-0', bodyClassName)}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: 'ok' | 'warn' | 'fail' }) {
  const color = tone === 'ok' ? 'text-ok' : tone === 'warn' ? 'text-warn' : tone === 'fail' ? 'text-fail' : 'text-lab-text';
  return (
    <div className="min-w-0">
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-lab-faint">{label}</div>
      <div className={cn('font-display text-xl font-semibold leading-tight tabular truncate', color)}>{value}</div>
      {sub && <div className="text-xs text-lab-dim truncate">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-sm text-lab-faint py-6 text-center">{children}</div>;
}

export function LiveDot({ on = true }: { on?: boolean }) {
  return <span className={cn('inline-block size-1.5 rounded-full', on ? 'bg-ok animate-pulse-dot' : 'bg-lab-faint')} />;
}
