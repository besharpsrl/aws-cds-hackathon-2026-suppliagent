import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useConversationsApi } from './ConversationsApiContext';
import { formatDate, handoffReasonLabel } from './format';

/** FN-28: live conversations, refreshed within 2 s by polling (a WebSocket push is not built yet). */
export const REFRESH_MS = 2000;

export function ConversationsPage() {
  const api = useConversationsApi();
  const { data, error } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api.listConversations(),
    refetchInterval: REFRESH_MS,
  });

  return (
    <>
      <h1>Conversations</h1>
      {api.source === 'mock' && (
        <p className="notice">Mock data: set VITE_ORDERS_SOURCE=api to use the real API.</p>
      )}
      {error && <p role="alert">Could not load conversations.</p>}
      <table className="orders">
        <thead>
          <tr>
            <th>Contact</th>
            <th>Channel</th>
            <th>Mode</th>
            <th>Last message</th>
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((c) => (
            <tr key={c.conversationId}>
              <td>
                <Link to={`/conversations/${c.conversationId}`}>
                  {c.contactName ?? c.contactId ?? c.conversationId}
                </Link>
                {c.customerName && <> · {c.customerName}</>}
              </td>
              <td>{c.channel ?? '–'}</td>
              <td>
                {c.mode === 'HUMAN' ? (
                  <strong className="badge">
                    Handoff{c.handoff ? ` · ${handoffReasonLabel(c.handoff.reason)}` : ''}
                  </strong>
                ) : (
                  'Agent'
                )}
              </td>
              <td>{c.lastMessageAt ? formatDate(c.lastMessageAt) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && data.length === 0 && <p>No conversations yet.</p>}
    </>
  );
}
