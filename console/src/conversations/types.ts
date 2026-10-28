// Contract of console_api `/conversations` (services/console_api/src/console_api/conversations.py).

export type ConversationMode = 'AGENT' | 'HUMAN';

export interface Handoff {
  /** Reason code of F-14, e.g. `OUT_OF_SCOPE`, `OPERATOR_TAKEOVER`. */
  reason: string;
  summary: string;
  /** `AGENT` or the operator that started it. */
  by: string;
  at: string;
}

export interface ConversationSummary {
  conversationId: string;
  contactId?: string;
  contactName?: string;
  customerName?: string;
  role?: string;
  mode: ConversationMode;
  channel?: string | null;
  lastMessageAt?: string;
  handoff?: Handoff;
}

export interface ConversationMessage {
  messageId: string;
  direction: 'INBOUND' | 'OUTBOUND';
  channel?: string;
  at?: string;
  text?: string | null;
  /** Attachment types only (`image`, `audio`…): the console never gets media URIs here. */
  attachments: string[];
  interactiveReply?: string;
  status?: string;
  /** `OPERATOR` for a back-office reply; absent for the agent's. */
  sentBy?: 'OPERATOR';
}

export interface ConversationDetail {
  conversation: ConversationSummary;
  messages: ConversationMessage[];
}
