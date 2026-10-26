import { signIn as amplifySignIn, signOut as amplifySignOut } from 'aws-amplify/auth';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { loadUser, type AuthUser } from './session';

export type AuthState =
  { status: 'loading' } | { status: 'signedOut' } | { status: 'signedIn'; user: AuthUser };

export type AuthValue = AuthState & {
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

export const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' });

  const refresh = useCallback(async () => {
    const user = await loadUser().catch(() => null);
    setState(user ? { status: 'signedIn', user } : { status: 'signedOut' });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<AuthValue>(
    () => ({
      ...state,
      async signIn(email, password) {
        const { nextStep } = await amplifySignIn({ username: email, password });
        // ponytail: users get a permanent password from the admin; no new-password challenge UI.
        if (nextStep.signInStep !== 'DONE') {
          throw new Error('This account needs a password reset: ask the administrator.');
        }
        await refresh();
      },
      async signOut() {
        await amplifySignOut();
        setState({ status: 'signedOut' });
      },
    }),
    [state, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
