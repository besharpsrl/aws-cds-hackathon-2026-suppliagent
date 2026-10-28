import type { ConversationsApi } from './api';
import type { ConversationDetail } from './types';

const details = new Map<string, ConversationDetail>(
  [
    {
      conversation: {
        conversationId: 'conv_demo_1',
        contactName: 'Anna',
        customerName: 'Pub Demo',
        role: 'CUSTOMER_CONTACT',
        mode: 'HUMAN',
        channel: 'WHATSAPP',
        lastMessageAt: '2026-10-28T07:12:00Z',
        handoff: {
          reason: 'OUT_OF_SCOPE',
          summary: 'Asks for a discount on the weekly order: not in the price list.',
          by: 'AGENT',
          at: '2026-10-28T07:12:00Z',
        },
      },
      messages: [
        {
          messageId: 'm1',
          direction: 'INBOUND',
          channel: 'WHATSAPP',
          at: '2026-10-28T07:10:00Z',
          text: 'Buongiorno, posso avere uno sconto sull’ordine di questa settimana?',
          attachments: [],
        },
        {
          messageId: 'm2',
          direction: 'OUTBOUND',
          channel: 'WHATSAPP',
          at: '2026-10-28T07:12:00Z',
          text: 'Non posso concordare sconti: la passo a un collega del back office.',
          attachments: [],
          status: 'SENT',
        },
      ],
    },
    {
      conversation: {
        conversationId: 'conv_demo_2',
        contactName: 'Marco',
        customerName: 'Bar Demo',
        role: 'CUSTOMER_CONTACT',
        mode: 'AGENT',
        channel: 'EMAIL',
        lastMessageAt: '2026-10-28T06:50:00Z',
      },
      messages: [
        {
          messageId: 'm3',
          direction: 'INBOUND',
          channel: 'EMAIL',
          at: '2026-10-28T06:50:00Z',
          text: 'Ordine per domani: 10 kg di farina.',
          attachments: ['image'],
        },
      ],
    },
  ].map((d) => [d.conversation.conversationId, d as ConversationDetail]),
);

const find = (id: string) => {
  const detail = details.get(id);
  if (!detail) throw new Error(`Conversation ${id} not found`);
  return detail;
};

// In-memory state: it survives navigation but not a page reload.
export const mockConversationsApi: ConversationsApi = {
  source: 'mock',
  async listConversations() {
    return [...details.values()].map((d) => structuredClone(d.conversation));
  },
  async getConversation(id) {
    return structuredClone(find(id));
  },
  async takeOver(id) {
    const { conversation } = find(id);
    if (conversation.mode === 'HUMAN') return;
    conversation.mode = 'HUMAN';
    conversation.handoff = {
      reason: 'OPERATOR_TAKEOVER',
      summary: 'Back office took over from the console.',
      by: 'BACKOFFICE',
      at: new Date().toISOString(),
    };
  },
  async reply(id, text) {
    const detail = find(id);
    if (detail.conversation.mode !== 'HUMAN') throw new Error('Not in handoff');
    detail.messages.push({
      messageId: `m_${detail.messages.length + 1}`,
      direction: 'OUTBOUND',
      channel: detail.conversation.channel ?? undefined,
      at: new Date().toISOString(),
      text,
      attachments: [],
      status: 'SANDBOX',
      sentBy: 'OPERATOR',
    });
  },
  async release(id) {
    const { conversation } = find(id);
    conversation.mode = 'AGENT';
    delete conversation.handoff;
  },
};
