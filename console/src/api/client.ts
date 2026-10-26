import { getIdToken } from '../auth/session';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** JSON call to the console REST API (`VITE_API_URL`) with the Cognito ID token. */
export async function apiFetch<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const base = String(import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');
  const headers = new Headers(init.headers);
  headers.set('Authorization', await getIdToken());
  const res = await fetch(`${base}${path}`, { ...init, headers });
  if (!res.ok) throw new ApiError(res.status, `API ${res.status} on ${path}`);
  return (await res.json()) as T;
}
