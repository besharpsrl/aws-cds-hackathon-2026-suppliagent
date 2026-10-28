import { apiFetch } from '../api/client';
import { mockConversationsApi } from './mockApi';
import type { ConversationDetail, ConversationSummary } from './types';

export interface ConversationsApi {
  /** `mock` is local development only; the published console uses `api`. */
  readonly source: 'mock' | 'api';
  listConversations(): Promise<ConversationSummary[]>;
  getConversation(conversationId: string): Promise<ConversationDetail>;
  /** *Take over*: the agent stops answering this conversation. */
  takeOver(conversationId: string): Promise<void>;
  /** The operator's text, sent on the contact's channel. The same `idempotencyKey` never sends twice. */
  reply(conversationId: string, text: string, idempotencyKey: string): Promise<void>;
  /** *Release*: the agent answers again. */
  release(conversationId: string): Promise<void>;
}

const path = (conversationId: string, action: string) =>
  `/conversations/${encodeURIComponent(conversationId)}/${action}`;

const post = (url: string, body?: unknown) =>
  apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

/** console_api: the API checks role (only `backoffice` writes) and the conversation mode. */
export const httpConversationsApi: ConversationsApi = {
  source: 'api',
  async listConversations() {
    return (await apiFetch<{ conversations: ConversationSummary[] }>('/conversations'))
      .conversations;
  },
  getConversation: (id) => apiFetch<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`),
  async takeOver(id) {
    await post(path(id, 'takeover'));
  },
  async reply(id, text, idempotencyKey) {
    await post(path(id, 'reply'), { text, idempotencyKey });
  },
  async release(id) {
    await post(path(id, 'release'));
  },
};

export const defaultConversationsApi: ConversationsApi =
  import.meta.env.VITE_ORDERS_SOURCE === 'api' ? httpConversationsApi : mockConversationsApi;
