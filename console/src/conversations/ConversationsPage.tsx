import { useQuery } from '@tanstack/react-query';
import { Bot, Headset, Info } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useConversationsApi } from './ConversationsApiContext';
import { formatDate, handoffReasonLabel } from './format';
import { PageHeader } from '@/components/page-header';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

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
      <PageHeader
        title="Conversations"
        description="Live chats with customers and sales reps. Take over when a person is needed."
      />
      {api.source === 'mock' && (
        <Alert variant="info" className="mb-4">
          <Info aria-hidden="true" />
          <AlertDescription>
            Mock data: set VITE_ORDERS_SOURCE=api to use the real API.
          </AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive" role="alert" className="mb-4">
          <AlertDescription>Could not load conversations.</AlertDescription>
        </Alert>
      )}
      <Card className="gap-0 overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Contact</TableHead>
              <TableHead>Channel</TableHead>
              <TableHead>Mode</TableHead>
              <TableHead>Last message</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).map((c) => (
              <TableRow key={c.conversationId}>
                <TableCell>
                  <Link
                    to={`/conversations/${c.conversationId}`}
                    className="font-semibold text-primary hover:underline"
                  >
                    {c.contactName ?? c.contactId ?? c.conversationId}
                  </Link>
                  {c.customerName && (
                    <span className="text-muted-foreground"> · {c.customerName}</span>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{c.channel ?? '–'}</TableCell>
                <TableCell>
                  {c.mode === 'HUMAN' ? (
                    <Badge variant="default">
                      <Headset aria-hidden="true" />
                      Handoff{c.handoff ? ` · ${handoffReasonLabel(c.handoff.reason)}` : ''}
                    </Badge>
                  ) : (
                    <Badge variant="muted">
                      <Bot aria-hidden="true" />
                      Agent
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground tabular-nums">
                  {c.lastMessageAt ? formatDate(c.lastMessageAt) : '–'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {data && data.length === 0 && (
          <p className="p-8 text-center text-sm text-muted-foreground">No conversations yet.</p>
        )}
      </Card>
    </>
  );
}
