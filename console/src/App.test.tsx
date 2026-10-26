import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { App } from './App';
import { AuthContext } from './auth/AuthContext';
import type { Role } from './auth/roles';

function renderApp(path: string, roles: Role[]) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthContext.Provider
        value={{
          status: 'signedIn',
          user: { email: 'j@demo.it', roles },
          signIn: async () => ({ newPasswordRequired: false }),
          confirmNewPassword: async () => {},
          signOut: async () => {},
        }}
      >
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

describe('App routes', () => {
  it('shows a not-found page with a way back for unknown paths', () => {
    renderApp('/nope', ['judge']);
    expect(screen.getByText(/page not found/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to orders/i })).toHaveAttribute('href', '/');
  });

  it('offers the demo page to the judge, in the navigation and at /demo', () => {
    renderApp('/demo', ['judge']);
    expect(screen.getByRole('heading', { name: /try suppliagent/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /try the demo/i })).toHaveAttribute('href', '/demo');
  });
});
