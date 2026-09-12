export const API_URL =
  process.env.NEXT_PUBLIC_SAMIDA_API_URL ?? 'http://127.0.0.1:8000';

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
  });
  if (!response.ok) {
    const failure: unknown = await response.json().catch(() => null);
    const detail =
      typeof failure === 'object' && failure !== null && 'detail' in failure
        ? (failure as { detail: unknown }).detail
        : null;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : 'SAMIDA could not complete the action.',
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type CurrentUser = {
  id: string;
  email: string;
  tier: string;
  is_owner: boolean;
};

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const response = await fetch(`${API_URL}/api/auth/me`, { credentials: 'include' });
  if (!response.ok) return null;
  return response.json() as Promise<CurrentUser>;
}

export async function logout(): Promise<void> {
  await fetch(`${API_URL}/api/auth/logout`, { method: 'POST', credentials: 'include' });
}
