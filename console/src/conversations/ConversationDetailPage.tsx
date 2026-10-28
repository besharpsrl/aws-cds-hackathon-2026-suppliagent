import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { isReadOnly } from '../auth/roles';
import { useConversationsApi } from './ConversationsApiContext';
import { REFRESH_MS } from './ConversationsPage';
import { formatDate, handoffReasonLabel } from './format';

const REPLY_ERROR =
  'The reply was not sent. The conversation may have been released, or the channel cannot be used now (WhatsApp allows free text only within 24 h of the last message).';

export function ConversationDetailPage() {
  const { conversationId = '' } = useParams();
  const api = useConversationsApi();
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [text, setText] = useState('');
  // A retry of the same text reuses its key, so the contact never gets it twice; other text, new key.
  const pending = useRef<{ text: string; key: string } | null>(null);
  const readOnly = auth.status === 'signedIn' && isReadOnly(auth.user.roles);

  const { data, error } = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api.getConversation(conversationId),
    refetchInterval: REFRESH_MS,
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] }),
      queryClient.invalidateQueries({ queryKey: ['conversations'] }),
      queryClient.invalidateQueries({ queryKey: ['orders'] }), // the "Handoff" badge of the inbox
    ]);
  const takeOver = useMutation({
    mutationFn: () => api.takeOver(conversationId),
    onSuccess: refresh,
  });
  const release = useMutation({
    mutationFn: () => api.release(conversationId),
    onSuccess: refresh,
  });
  const reply = useMutation({
    mutationFn: (message: { text: string; key: string }) =>
      api.reply(conversationId, message.text, message.key),
    onSuccess: () => {
      pending.current = null;
      setText('');
      return refresh();
    },
  });

  if (error) return <p role="alert">Could not load the conversation.</p>;
  if (!data) return <p className="status">Loading…</p>;
  const { conversation, messages } = data;
  const human = conversation.mode === 'HUMAN';

  const send = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || reply.isPending) return;
    if (pending.current?.text !== trimmed) {
      pending.current = { text: trimmed, key: crypto.randomUUID() };
    }
    reply.mutate(pending.current);
  };

  return (
    <>
      <p>
        <Link to="/conversations">← Conversations</Link>
      </p>
      <h1>
        {conversation.contactName ?? conversation.contactId ?? conversation.conversationId}{' '}
        <span className={`status status-${human ? 'handoff' : 'agent'}`}>
          {human ? 'Handoff' : 'Agent'}
        </span>
      </h1>
      <p>
        {conversation.customerName ? `${conversation.customerName} · ` : ''}
        {conversation.role ?? ''}
        {conversation.channel ? ` · ${conversation.channel}` : ''}
      </p>
      {conversation.handoff && (
        <p role="note" className="notice">
          <strong>{handoffReasonLabel(conversation.handoff.reason)}</strong> —{' '}
          {conversation.handoff.summary}
        </p>
      )}
      {readOnly && (
        <p role="note" className="notice">
          Read-only access: you can follow the conversation, but not take over or reply.
        </p>
      )}
      {(takeOver.isError || release.isError) && (
        <p role="alert">The action failed. Reload and try again.</p>
      )}

      <ol className="thread" aria-label="Messages">
        {messages.map((m) => (
          <li key={m.messageId} className={`bubble bubble-${m.direction.toLowerCase()}`}>
            <div className="meta">
              <span className="channel">{m.channel ?? '–'}</span>
              {m.direction === 'OUTBOUND'
                ? m.sentBy === 'OPERATOR'
                  ? ' · Operator'
                  : ' · Agent'
                : ' · Contact'}
              {m.at && <> · {formatDate(m.at)}</>}
              {m.status === 'SANDBOX' && ' · sandbox (not delivered)'}
            </div>
            {m.text && <p>{m.text}</p>}
            {m.interactiveReply && <p>Tapped: {m.interactiveReply}</p>}
            {m.attachments.length > 0 && (
              <p className="attachments">[{m.attachments.join(', ')}]</p>
            )}
          </li>
        ))}
      </ol>

      {!readOnly && !human && (
        <button type="button" onClick={() => takeOver.mutate()} disabled={takeOver.isPending}>
          Take over
        </button>
      )}
      {!readOnly && human && (
        <>
          <form className="reply" onSubmit={send}>
            <label>
              Reply
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={1000}
                rows={3}
              />
            </label>
            <button type="submit" disabled={!text.trim() || reply.isPending}>
              Send
            </button>
          </form>
          {reply.isError && <p role="alert">{REPLY_ERROR}</p>}
          <button type="button" onClick={() => release.mutate()} disabled={release.isPending}>
            Release to the agent
          </button>
        </>
      )}
    </>
  );
}
