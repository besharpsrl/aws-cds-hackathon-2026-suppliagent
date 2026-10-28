import { afterEach, describe, expect, it, vi } from 'vitest';
import { httpOrdersApi } from './api';

vi.mock('../auth/session', () => ({ getIdToken: async () => 'id-token-123' }));
vi.stubEnv('VITE_API_URL', 'https://api.example.com/v1');

afterEach(() => vi.unstubAllGlobals());

describe('httpOrdersApi.correctLine', () => {
  it('PATCHes the chosen SKU on the line, with the ID token', async () => {
    const fetchMock = vi.fn(async () => new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    await httpOrdersApi.correctLine('ord_1', 'l 3', 'PAN-0100');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.example.com/v1/orders/ord_1/lines/l%203');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(String(init.body))).toEqual({ sku: 'PAN-0100' });
    expect(new Headers(init.headers).get('Authorization')).toBe('id-token-123');
  });

  it('fails when the API refuses the correction', async () => {
    vi.stubGlobal('fetch', async () => new Response('{"error":"not_editable"}', { status: 409 }));
    await expect(httpOrdersApi.correctLine('ord_1', 'l1', 'X')).rejects.toMatchObject({
      status: 409,
    });
  });
});
