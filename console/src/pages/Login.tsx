import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import logo from '../../../assets/brand/suppliagent_logo_light.svg';
import { useAuth } from '../auth/AuthContext';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

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

  const errorAlert = error && (
    <Alert variant="destructive" role="alert">
      <AlertDescription>{error}</AlertDescription>
    </Alert>
  );

  return (
    <main className="grid min-h-dvh lg:grid-cols-2">
      <section className="hidden flex-col justify-between bg-sidebar p-12 text-sidebar-foreground lg:flex">
        <p className="text-xs font-semibold uppercase tracking-widest text-sidebar-muted">
          beSharp · we make IT run
        </p>
        <div className="grid gap-4">
          <h2 className="font-display text-5xl leading-none font-black uppercase tracking-tight text-white">
            Orders in chat.
            <br />
            <span className="text-sidebar-primary">Under control.</span>
          </h2>
          <p className="max-w-md text-sidebar-muted">
            Supervise the orders the agent reads from WhatsApp and email, fix uncertain lines and
            take over conversations when a person is needed.
          </p>
        </div>
        <p className="text-xs text-sidebar-muted">SuppliAgent back-office console</p>
      </section>
      <section className="flex items-center justify-center p-6">
        <Card className="w-full max-w-sm">
          <CardHeader className="justify-items-center gap-3">
            <img src={logo} alt="SuppliAgent" className="h-14" />
            <CardDescription>
              {needsNewPassword
                ? 'First access: choose a new password (at least 12 characters).'
                : 'Sign in to the console.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {needsNewPassword ? (
              <form onSubmit={onNewPassword} className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="new-password">New password</Label>
                  <Input
                    id="new-password"
                    type="password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                  />
                </div>
                {errorAlert}
                <Button type="submit" disabled={busy} className="w-full">
                  Set password
                </Button>
              </form>
            ) : (
              <form onSubmit={onSignIn} className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
                {errorAlert}
                <Button type="submit" disabled={busy} className="w-full">
                  Sign in
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </section>
    </main>
  );
}
