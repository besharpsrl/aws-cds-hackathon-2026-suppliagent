import { Inbox, LogOut, MessagesSquare, Sparkles, type LucideIcon } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import icon from '../../../assets/brand/suppliagent_icon.svg';
import { useAuth } from '../auth/AuthContext';
import { isReadOnly } from '../auth/roles';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const NAV: { to: string; label: string; Icon: LucideIcon; end?: boolean }[] = [
  { to: '/', label: 'Orders', Icon: Inbox, end: true },
  { to: '/conversations', label: 'Conversations', Icon: MessagesSquare },
  { to: '/demo', label: 'Try the demo', Icon: Sparkles },
];

export function Layout() {
  const auth = useAuth();
  if (auth.status !== 'signedIn') return null; // always rendered under <RequireRole>
  const { user } = auth;
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <aside className="flex flex-wrap items-center gap-3 bg-sidebar p-3 text-sidebar-foreground md:sticky md:top-0 md:h-dvh md:flex-col md:flex-nowrap md:items-stretch md:gap-6 md:p-4">
        <div className="flex items-center gap-3 px-2 pt-1">
          <img src={icon} alt="" className="size-9 rounded-lg" />
          <span className="font-display text-lg font-black uppercase tracking-tight text-white">
            Suppli<span className="text-sidebar-primary">Agent</span>
          </span>
        </div>
        <nav
          aria-label="Main"
          className="order-last flex w-full gap-1 overflow-x-auto md:order-none md:flex-col"
        >
          {NAV.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-semibold transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-primary',
                  isActive
                    ? 'bg-primary text-white'
                    : 'text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-foreground',
                )
              }
            >
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto md:mt-auto md:ml-0 md:grid md:gap-3 md:border-t md:border-sidebar-accent md:pt-4">
          <div className="hidden gap-1 px-2 text-xs md:grid">
            <span className="truncate font-semibold text-sidebar-foreground">{user.email}</span>
            <span className="flex flex-wrap items-center gap-1.5 text-sidebar-muted">
              {user.roles.join(', ')}
              {isReadOnly(user.roles) && (
                <Badge variant="secondary" className="text-[10px]">
                  Read-only
                </Badge>
              )}
            </span>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="justify-start text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-foreground"
            onClick={() => void auth.signOut()}
          >
            <LogOut aria-hidden="true" />
            Sign out
          </Button>
          <p className="hidden px-2 text-[10px] uppercase tracking-widest text-sidebar-muted md:block">
            by beSharp
          </p>
        </div>
      </aside>
      <main className="mx-auto w-full max-w-7xl p-4 md:p-8">
        <Outlet />
      </main>
    </div>
  );
}
