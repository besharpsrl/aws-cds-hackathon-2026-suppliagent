import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthState } from '../auth/AuthContext';
import { Login } from './Login';

function renderLogin(state: AuthState, signIn = vi.fn(async () => {})) {
  render(
    <AuthContext.Provider value={{ ...state, signIn, signOut: async () => {} }}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<p>home</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
  return signIn;
}

describe('Login', () => {
  it('submits email and password', async () => {
    const signIn = renderLogin({ status: 'signedOut' });
    await userEvent.type(screen.getByLabelText(/email/i), 'rep@demo.it');
    await userEvent.type(screen.getByLabelText(/password/i), 'S3cret!pass');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(signIn).toHaveBeenCalledWith('rep@demo.it', 'S3cret!pass');
  });

  it('shows the error when sign-in fails, without echoing the password', async () => {
    const signIn = vi.fn(async () => {
      throw new Error('Incorrect username or password.');
    });
    renderLogin({ status: 'signedOut' }, signIn);
    await userEvent.type(screen.getByLabelText(/email/i), 'rep@demo.it');
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong-pass');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/incorrect/i));
    expect(screen.getByRole('alert')).not.toHaveTextContent('wrong-pass');
  });

  it('goes to the home page when already signed in', () => {
    renderLogin({ status: 'signedIn', user: { email: 'a@b.it', roles: ['backoffice'] } });
    expect(screen.getByText('home')).toBeInTheDocument();
  });
});
