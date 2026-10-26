import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthState, type AuthValue } from '../auth/AuthContext';
import { Login } from './Login';

const done = { newPasswordRequired: false };

function renderLogin(state: AuthState, over: Partial<AuthValue> = {}) {
  const auth = {
    ...state,
    signIn: vi.fn(async () => done),
    confirmNewPassword: vi.fn(async () => {}),
    signOut: async () => {},
    ...over,
  } as AuthValue;
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<p>home</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
  return auth;
}

async function fillAndSubmit(email: string, password: string) {
  await userEvent.type(screen.getByLabelText(/email/i), email);
  await userEvent.type(screen.getByLabelText(/password/i), password);
  await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
}

describe('Login', () => {
  it('submits email and password', async () => {
    const auth = renderLogin({ status: 'signedOut' });
    await fillAndSubmit('rep@demo.it', 'S3cret!pass');
    expect(auth.signIn).toHaveBeenCalledWith('rep@demo.it', 'S3cret!pass');
  });

  it('shows the error when sign-in fails, without echoing the password', async () => {
    const signIn = vi.fn(async () => {
      throw new Error('Incorrect username or password.');
    });
    renderLogin({ status: 'signedOut' }, { signIn });
    await fillAndSubmit('rep@demo.it', 'wrong-pass');
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/incorrect/i));
    expect(screen.getByRole('alert')).not.toHaveTextContent('wrong-pass');
  });

  it('goes to the home page when already signed in', () => {
    renderLogin({ status: 'signedIn', user: { email: 'a@b.it', roles: ['backoffice'] } });
    expect(screen.getByText('home')).toBeInTheDocument();
  });
});

describe('Login: first access with a temporary password (user created from the Cognito console)', () => {
  const needsNewPassword = { signIn: vi.fn(async () => ({ newPasswordRequired: true })) };

  it('asks for a new password instead of failing', async () => {
    renderLogin({ status: 'signedOut' }, needsNewPassword);
    await fillAndSubmit('new@demo.it', 'Temp0rary!pass');
    expect(await screen.findByLabelText(/new password/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });

  it('sets the chosen password and finishes the sign-in', async () => {
    const auth = renderLogin({ status: 'signedOut' }, needsNewPassword);
    await fillAndSubmit('new@demo.it', 'Temp0rary!pass');
    await userEvent.type(await screen.findByLabelText(/new password/i), 'Br4nd-new-Passw0rd!');
    await userEvent.click(screen.getByRole('button', { name: /set password/i }));
    expect(auth.confirmNewPassword).toHaveBeenCalledWith('Br4nd-new-Passw0rd!');
  });

  it('shows the Cognito error (e.g. password policy) and keeps the form', async () => {
    const confirmNewPassword = vi.fn(async () => {
      throw new Error('Password does not conform to policy');
    });
    renderLogin({ status: 'signedOut' }, { ...needsNewPassword, confirmNewPassword });
    await fillAndSubmit('new@demo.it', 'Temp0rary!pass');
    await userEvent.type(await screen.findByLabelText(/new password/i), 'short');
    await userEvent.click(screen.getByRole('button', { name: /set password/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/policy/i));
    expect(screen.getByLabelText(/new password/i)).toBeInTheDocument();
  });
});
