import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bot, Eye, Hand, Headset, Paperclip, Send, User } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { isReadOnly } from '../auth/roles';
import { useConversationsApi } from './ConversationsApiContext';
import { REFRESH_MS } from './ConversationsPage';
import { formatDate, handoffReasonLabel } from './format';
import type { ConversationMessage } from './types';
import { PageHeader } from '@/components/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

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

  if (error)
    return (
      <Alert variant="destructive" role="alert">
        <AlertDescription>Could not load the conversation.</AlertDescription>
      </Alert>
    );
  if (!data) return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
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

  const actions = readOnly ? null : human ? (
    <Button
      type="button"
      variant="outline"
      onClick={() => release.mutate()}
      disabled={release.isPending}
    >
      <Bot aria-hidden="true" />
      Release to the agent
    </Button>
  ) : (
    <Button type="button" onClick={() => takeOver.mutate()} disabled={takeOver.isPending}>
      <Hand aria-hidden="true" />
      Take over
    </Button>
  );

  return (
    <div className="max-w-3xl">
      <PageHeader
        title={
          <>
            {conversation.contactName ?? conversation.contactId ?? conversation.conversationId}
            {human ? (
              <Badge variant="default">
                <Headset aria-hidden="true" />
                Handoff
              </Badge>
            ) : (
              <Badge variant="muted">
                <Bot aria-hidden="true" />
                Agent
              </Badge>
            )}
          </>
        }
        description={
          <>
            {conversation.customerName ? `${conversation.customerName} · ` : ''}
            {conversation.role ?? ''}
            {conversation.channel ? ` · ${conversation.channel}` : ''}
          </>
        }
        actions={actions}
      >
        <Link
          to="/conversations"
          className="flex w-fit items-center gap-1 text-sm font-semibold text-primary hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          Conversations
        </Link>
      </PageHeader>

      <div className="grid gap-4">
        {conversation.handoff && (
          <Alert variant="warning" role="note">
            <Headset aria-hidden="true" />
            <AlertTitle>{handoffReasonLabel(conversation.handoff.reason)}</AlertTitle>
            <AlertDescription className="text-foreground">
              {conversation.handoff.summary}
            </AlertDescription>
          </Alert>
        )}
        {readOnly && (
          <Alert variant="info" role="note">
            <Eye aria-hidden="true" />
            <AlertDescription>
              Read-only access: you can follow the conversation, but not take over or reply.
            </AlertDescription>
          </Alert>
        )}
        {(takeOver.isError || release.isError) && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>The action failed. Reload and try again.</AlertDescription>
          </Alert>
        )}

        <Card className="py-4">
          <CardContent className="px-4">
            <ol className="grid gap-3" aria-label="Messages">
              {messages.map((m) => (
                <MessageBubble key={m.messageId} message={m} />
              ))}
            </ol>
          </CardContent>
        </Card>

        {!readOnly && human && (
          <form onSubmit={send} className="grid gap-2">
            <Label htmlFor="reply">Reply</Label>
            <Textarea
              id="reply"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={1000}
              rows={3}
            />
            {reply.isError && (
              <Alert variant="destructive" role="alert">
                <AlertDescription>{REPLY_ERROR}</AlertDescription>
              </Alert>
            )}
            <div className="flex justify-end">
              <Button type="submit" disabled={!text.trim() || reply.isPending}>
                <Send aria-hidden="true" />
                Send
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function MessageBubble({ message: m }: { message: ConversationMessage }) {
  const inbound = m.direction === 'INBOUND';
  const operator = m.sentBy === 'OPERATOR';
  const Icon = inbound ? User : operator ? Headset : Bot;
  return (
    <li className={cn('flex', inbound ? 'justify-start' : 'justify-end')}>
      <div
        className={cn(
          'grid max-w-[85%] gap-1 rounded-xl px-3.5 py-2.5 text-sm',
          inbound && 'rounded-bl-sm border bg-card',
          !inbound && !operator && 'rounded-br-sm bg-accent text-accent-foreground',
          operator && 'rounded-br-sm bg-primary text-primary-foreground',
        )}
      >
        <div
          className={cn(
            'flex flex-wrap items-center gap-1.5 text-xs',
            operator ? 'text-primary-foreground/80' : 'text-muted-foreground',
          )}
        >
          <Icon className="size-3.5" aria-hidden="true" />
          <span className="font-semibold">
            {inbound ? 'Contact' : operator ? 'Operator' : 'Agent'}
          </span>
          <span>
            {m.channel ?? '–'}
            {m.at && <> · {formatDate(m.at)}</>}
            {m.status === 'SANDBOX' && ' · sandbox (not delivered)'}
          </span>
        </div>
        {m.text && <p className="whitespace-pre-wrap">{m.text}</p>}
        {m.interactiveReply && (
          <p>
            <span className="opacity-70">Tapped:</span> {m.interactiveReply}
          </p>
        )}
        {m.attachments.length > 0 && (
          <p className="flex items-center gap-1 text-xs opacity-80">
            <Paperclip className="size-3.5" aria-hidden="true" />
            <span>[{m.attachments.join(', ')}]</span>
          </p>
        )}
      </div>
    </li>
  );
}
