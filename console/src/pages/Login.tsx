import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import logo from '../../../assets/brand/suppliagent_logo_light.svg';
import { useAuth } from '../auth/AuthContext';

export function Login() {
  const auth = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [needsNewPassword, setNeedsNewPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (auth.status === 'signedIn') return <Navigate to="/" replace />;

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  const onSignIn = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const result = await auth.signIn(email, password);
      if (result.newPasswordRequired) setNeedsNewPassword(true);
    }, 'Sign-in failed');
  };

  const onNewPassword = (event: FormEvent) => {
    event.preventDefault();
    void run(() => auth.confirmNewPassword(newPassword), 'Could not set the password');
  };

  return (
    <main className="login">
      <img src={logo} alt="SuppliAgent" className="logo" />
      {needsNewPassword ? (
        <form onSubmit={onNewPassword}>
          <p>First access: choose a new password (at least 12 characters).</p>
          <label>
            New password
            <input
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <button type="submit" disabled={busy}>
            Set password
          </button>
        </form>
      ) : (
        <form onSubmit={onSignIn}>
          <label>
            Email
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <button type="submit" disabled={busy}>
            Sign in
          </button>
        </form>
      )}
    </main>
  );
}
