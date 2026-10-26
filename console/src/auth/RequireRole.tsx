import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import type { Role } from './roles';

/**
 * Route guard. UI only: the API enforces the same roles from the token claims (FN-32).
 * Without `roles`, any user that belongs to at least one console group gets in.
 */
export function RequireRole({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const auth = useAuth();
  if (auth.status === 'loading') return <p className="status">Loading…</p>;
  if (auth.status === 'signedOut') return <Navigate to="/login" replace />;
  const allowed = roles
    ? roles.some((role) => auth.user.roles.includes(role))
    : auth.user.roles.length > 0;
  if (!allowed) return <p role="alert">You are not allowed to see this page.</p>;
  return <>{children}</>;
}
