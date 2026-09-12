'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import { API_URL } from '@/lib/api';
import { SamidaMark } from '@/components/samida-mark';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const failure: unknown = await response.json().catch(() => null);
        const detail =
          typeof failure === 'object' && failure !== null && 'detail' in failure
            ? (failure as { detail: unknown }).detail
            : null;
        throw new Error(typeof detail === 'string' ? detail : 'Could not create the account.');
      }
      router.push('/');
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not create the account.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-card">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <SamidaMark />
          </div>
          <div><h1>SAMIDA</h1><p>Create account</p></div>
        </div>
        <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
          {error && <p className="auth-error">{error}</p>}
          <div className="auth-field">
            <Label htmlFor="email">Email</Label>
            <Input
              autoComplete="email"
              id="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </div>
          <div className="auth-field">
            <Label htmlFor="password">Password</Label>
            <Input
              autoComplete="new-password"
              id="password"
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </div>
          <Button className="auth-submit" disabled={submitting} type="submit">
            {submitting ? 'Creating account…' : 'Create account'}
          </Button>
        </form>
        <p className="auth-switch">
          Already have an account? <a href="/login">Log in</a>
        </p>
      </div>
    </main>
  );
}
