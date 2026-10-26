import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthContext, type AuthState } from './AuthContext';
import { RequireRole } from './RequireRole';
import type { Role } from './roles';

const noop = async () => {};

function renderGuard(state: AuthState, roles?: Role[]) {
  return render(
    <AuthContext.Provider value={{ ...state, signIn: noop, signOut: noop }}>
      <MemoryRouter initialEntries={['/secret']}>
        <Routes>
          <Route path="/login" element={<p>login page</p>} />
          <Route
            path="/secret"
            element={
              <RequireRole roles={roles}>
                <p>secret content</p>
              </RequireRole>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

const user = (roles: Role[]): AuthState => ({
  status: 'signedIn',
  user: { email: 'a@b.it', roles },
});

describe('RequireRole', () => {
  it('shows a placeholder while the session is loading', () => {
    renderGuard({ status: 'loading' });
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('redirects signed-out users to /login', () => {
    renderGuard({ status: 'signedOut' });
    expect(screen.getByText('login page')).toBeInTheDocument();
  });

  it('renders children for any signed-in console user when no role is required', () => {
    renderGuard(user(['judge']));
    expect(screen.getByText('secret content')).toBeInTheDocument();
  });

  it('denies a signed-in user without the required role', () => {
    renderGuard(user(['judge']), ['backoffice']);
    expect(screen.queryByText('secret content')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/not allowed/i);
  });

  it('denies a signed-in user that belongs to no console group', () => {
    renderGuard(user([]));
    expect(screen.queryByText('secret content')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('allows a user holding one of the required roles', () => {
    renderGuard(user(['sales_rep']), ['backoffice', 'sales_rep']);
    expect(screen.getByText('secret content')).toBeInTheDocument();
  });
});
