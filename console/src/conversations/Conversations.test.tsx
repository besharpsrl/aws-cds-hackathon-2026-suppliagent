import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthContext } from '../auth/AuthContext';
import type { Role } from '../auth/roles';
import { httpConversationsApi, type ConversationsApi } from './api';
import { ConversationDetailPage } from './ConversationDetailPage';
import { ConversationsApiContext } from './ConversationsApiContext';
import { ConversationsPage } from './ConversationsPage';
import type { ConversationDetail, ConversationSummary } from './types';

vi.mock('../auth/session', () => ({ getIdToken: async () => 'id-token-123' }));
vi.stubEnv('VITE_API_URL', 'https://api.example.com/v1');
afterEach(() => vi.unstubAllGlobals());

const summary = (over: Partial<ConversationSummary> = {}): ConversationSummary => ({
  conversationId: 'conv_1',
  contactName: 'Anna',
  customerName: 'Pub Demo',
  mode: 'AGENT',
  channel: 'WHATSAPP',
  lastMessageAt: '2026-10-28T08:00:00Z',
  ...over,
});

const detail = (over: Partial<ConversationSummary> = {}): ConversationDetail => ({
  conversation: summary(over),
  messages: [
    {
      messageId: 'm1',
      direction: 'INBOUND',
      channel: 'WHATSAPP',
      at: '2026-10-28T07:59:00Z',
      text: 'Ciao, vorrei parlare con qualcuno',
      attachments: ['image'],
    },
    {
      messageId: 'm2',
      direction: 'OUTBOUND',
      channel: 'WHATSAPP',
      at: '2026-10-28T08:00:00Z',
      text: 'Buongiorno',
      attachments: [],
      status: 'SENT',
    },
  ],
});

const human = () =>
  detail({
    mode: 'HUMAN',
    handoff: {
      reason: 'OUT_OF_SCOPE',
      summary: 'Wants a discount',
      by: 'AGENT',
      at: '2026-10-28T07:00:00Z',
    },
  });

const makeApi = (over: Partial<ConversationsApi> = {}): ConversationsApi => ({
  source: 'api',
  listConversations: vi.fn(async () => [summary()]),
  getConversation: vi.fn(async () => detail()),
  takeOver: vi.fn(async () => {}),
  reply: vi.fn(async () => {}),
  release: vi.fn(async () => {}),
  ...over,
});

function renderAt(api: ConversationsApi, roles: Role[], path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={{
          status: 'signedIn',
          user: { email: 'u@demo.it', roles },
          signIn: async () => ({ newPasswordRequired: false }),
          confirmNewPassword: async () => {},
          signOut: async () => {},
        }}
      >
        <ConversationsApiContext.Provider value={api}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/conversations" element={<ConversationsPage />} />
              <Route path="/conversations/:conversationId" element={<ConversationDetailPage />} />
            </Routes>
          </MemoryRouter>
        </ConversationsApiContext.Provider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

describe('ConversationsPage (FN-28)', () => {
  it('lists conversations with contact, venue, channel and a handoff badge', async () => {
    renderAt(
      makeApi({
        listConversations: vi.fn(async () => [
          summary({ conversationId: 'conv_2', contactName: 'Marco', mode: 'AGENT' }),
          summary({
            mode: 'HUMAN',
            handoff: {
              reason: 'OUT_OF_SCOPE',
              summary: 's',
              by: 'AGENT',
              at: '2026-10-28T07:00:00Z',
            },
          }),
        ]),
      }),
      ['backoffice'],
      '/conversations',
    );
    const link = await screen.findByRole('link', { name: 'Anna' });
    expect(link).toHaveAttribute('href', '/conversations/conv_1');
    expect(screen.getByText(/Handoff · Out of scope/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Marco' })).toBeInTheDocument();
  });

  it('shows an error when the list cannot be loaded', async () => {
    renderAt(
      makeApi({ listConversations: vi.fn(async () => Promise.reject(new Error('boom'))) }),
      ['backoffice'],
      '/conversations',
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i);
  });
});

describe('ConversationDetailPage (FN-24)', () => {
  it('shows the history with who wrote what, and Take over while the agent answers', async () => {
    const api = makeApi();
    renderAt(api, ['backoffice'], '/conversations/conv_1');
    expect(await screen.findByText('Ciao, vorrei parlare con qualcuno')).toBeInTheDocument();
    expect(screen.getByText('[image]')).toBeInTheDocument();
    expect(screen.getByText(/Contact/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Take over' }));
    expect(api.takeOver).toHaveBeenCalledWith('conv_1');
  });

  it('shows the handoff reason and summary, the reply box and Release while HUMAN', async () => {
    const api = makeApi({ getConversation: vi.fn(async () => human()) });
    renderAt(api, ['backoffice'], '/conversations/conv_1');
    expect(await screen.findByText('Out of scope')).toBeInTheDocument();
    expect(screen.getByText(/Wants a discount/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Take over' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /release/i }));
    expect(api.release).toHaveBeenCalledWith('conv_1');
  });

  it('sends the trimmed reply with an idempotency key and clears the box', async () => {
    const api = makeApi({ getConversation: vi.fn(async () => human()) });
    renderAt(api, ['backoffice'], '/conversations/conv_1');
    const box = await screen.findByRole('textbox', { name: 'Reply' });
    await userEvent.type(box, '  Ci penso io  ');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(api.reply).toHaveBeenCalledTimes(1));
    const [id, text, key] = vi.mocked(api.reply).mock.calls[0];
    expect([id, text]).toEqual(['conv_1', 'Ci penso io']);
    expect(key.length).toBeGreaterThanOrEqual(8);
    await waitFor(() => expect(box).toHaveValue(''));
  });

  it('does not send an empty reply', async () => {
    renderAt(
      makeApi({ getConversation: vi.fn(async () => human()) }),
      ['backoffice'],
      '/conversations/conv_1',
    );
    await screen.findByRole('textbox', { name: 'Reply' });
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('retries the same text with the same key, and new text with a new key', async () => {
    const reply = vi
      .fn<ConversationsApi['reply']>()
      .mockRejectedValueOnce(new Error('API 502'))
      .mockResolvedValue(undefined);
    renderAt(
      makeApi({ getConversation: vi.fn(async () => human()), reply }),
      ['backoffice'],
      '/conversations/conv_1',
    );
    const box = await screen.findByRole('textbox', { name: 'Reply' });
    await userEvent.type(box, 'Ciao');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/not sent/i);
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(reply).toHaveBeenCalledTimes(2));
    expect(reply.mock.calls[1][2]).toBe(reply.mock.calls[0][2]);
    await userEvent.type(box, 'Altro');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(reply).toHaveBeenCalledTimes(3));
    expect(reply.mock.calls[2][2]).not.toBe(reply.mock.calls[0][2]);
  });

  it('is read-only for the judge: no Take over, reply or Release', async () => {
    renderAt(
      makeApi({ getConversation: vi.fn(async () => human()) }),
      ['judge'],
      '/conversations/conv_1',
    );
    await screen.findByText(/Wants a discount/);
    expect(screen.getByText(/read-only access/i)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /release|take over|send/i }),
    ).not.toBeInTheDocument();
  });
});

describe('httpConversationsApi', () => {
  const call = async (run: () => Promise<unknown>, body = '{}') => {
    const fetchMock = vi.fn(async () => new Response(body));
    vi.stubGlobal('fetch', fetchMock);
    await run();
    return fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  };

  it('lists and reads with the ID token', async () => {
    const [url, init] = await call(
      () => httpConversationsApi.getConversation('conv 1'),
      JSON.stringify(detail()),
    );
    expect(url).toBe('https://api.example.com/v1/conversations/conv%201');
    expect(new Headers(init.headers).get('Authorization')).toBe('id-token-123');
    const [listUrl] = await call(
      () => httpConversationsApi.listConversations(),
      '{"conversations":[]}',
    );
    expect(listUrl).toBe('https://api.example.com/v1/conversations');
  });

  it('POSTs take over and release without a body, and the reply with its key', async () => {
    const [takeUrl, take] = await call(() => httpConversationsApi.takeOver('conv_1'));
    expect([takeUrl, take.method, take.body]).toEqual([
      'https://api.example.com/v1/conversations/conv_1/takeover',
      'POST',
      undefined,
    ]);
    const [releaseUrl] = await call(() => httpConversationsApi.release('conv_1'));
    expect(releaseUrl).toBe('https://api.example.com/v1/conversations/conv_1/release');
    const [replyUrl, reply] = await call(() =>
      httpConversationsApi.reply('conv_1', 'Ciao', 'key-12345678'),
    );
    expect(replyUrl).toBe('https://api.example.com/v1/conversations/conv_1/reply');
    expect(JSON.parse(String(reply.body))).toEqual({
      text: 'Ciao',
      idempotencyKey: 'key-12345678',
    });
  });

  it('fails when the API refuses', async () => {
    vi.stubGlobal('fetch', async () => new Response('{"error":"not_in_handoff"}', { status: 409 }));
    await expect(httpConversationsApi.reply('c', 'x', 'key-12345678')).rejects.toMatchObject({
      status: 409,
    });
  });
});
