import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiFetch } from './client';

vi.mock('../auth/session', () => ({ getIdToken: async () => 'id-token-123' }));
vi.stubEnv('VITE_API_URL', 'https://api.example.com/v1/');

afterEach(() => vi.unstubAllGlobals());

describe('apiFetch', () => {
  it('calls the API with the Cognito ID token and parses JSON', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ orders: [] })));
    vi.stubGlobal('fetch', fetchMock);
    await expect(apiFetch('/orders')).resolves.toEqual({ orders: [] });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.example.com/v1/orders');
    expect(new Headers(init.headers).get('Authorization')).toBe('id-token-123');
  });

  it('throws an ApiError carrying the status on non-2xx', async () => {
    vi.stubGlobal('fetch', async () => new Response('{"error":"forbidden"}', { status: 403 }));
    await expect(apiFetch('/orders')).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
    });
    await expect(apiFetch('/orders')).rejects.toBeInstanceOf(ApiError);
  });
});
