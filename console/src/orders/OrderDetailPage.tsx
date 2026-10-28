import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Eye, ImageOff } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { isReadOnly } from '../auth/roles';
import { useOrdersApi } from './OrdersApiContext';
import { TicketImage } from './TicketImage';
import { UNCERTAIN_LINE_STATUSES, type OrderLine } from './types';
import { PageHeader } from '@/components/page-header';
import { StatusBadge } from '@/components/status-badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';

export function OrderDetailPage() {
  const { orderId = '' } = useParams();
  const api = useOrdersApi();
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [activeLineId, setActiveLineId] = useState<string | null>(null);
  const readOnly = auth.status === 'signedIn' && isReadOnly(auth.user.roles);

  const { data, error } = useQuery({
    queryKey: ['order', orderId],
    queryFn: () => api.getOrder(orderId),
  });
  const correct = useMutation({
    mutationFn: (v: { lineId: string; sku: string }) => api.correctLine(orderId, v.lineId, v.sku),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['order', orderId] }),
        queryClient.invalidateQueries({ queryKey: ['orders'] }),
      ]),
  });

  if (error)
    return (
      <Alert variant="destructive" role="alert">
        <AlertDescription>Could not load the order.</AlertDescription>
      </Alert>
    );
  if (!data) return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
  const { order, imageUrl } = data;

  return (
    <>
      <PageHeader
        title={
          <>
            <span className="font-mono normal-case">{order.orderId}</span>
            <StatusBadge status={order.status} />
          </>
        }
        description={
          <>
            <span className="font-semibold text-foreground">
              {order.customerName ?? order.customerId}
            </span>{' '}
            · source: {order.source}
          </>
        }
      >
        <Link
          to="/"
          className="flex w-fit items-center gap-1 text-sm font-semibold text-primary hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          Orders
        </Link>
      </PageHeader>
      {readOnly && (
        <Alert variant="info" role="note" className="mb-4">
          <Eye aria-hidden="true" />
          <AlertDescription>
            Read-only access: you can browse the order and its ticket, but not correct lines.
          </AlertDescription>
        </Alert>
      )}
      {correct.isError && (
        <Alert variant="destructive" role="alert" className="mb-4">
          <AlertDescription>{correctionError(correct.error)}</AlertDescription>
        </Alert>
      )}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(280px,2fr)_3fr]">
        <Card className="lg:sticky lg:top-8">
          <CardHeader>
            <CardTitle>Ticket</CardTitle>
          </CardHeader>
          <CardContent>
            {imageUrl ? (
              <TicketImage
                src={imageUrl}
                lines={order.lines}
                activeLineId={activeLineId}
                onSelect={setActiveLineId}
              />
            ) : (
              <div className="flex flex-col items-center gap-2 rounded-md border border-dashed p-8 text-sm text-muted-foreground">
                <ImageOff className="size-6" aria-hidden="true" />
                No ticket image for this order.
              </div>
            )}
          </CardContent>
        </Card>
        <Card className="gap-0 overflow-hidden py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Written</TableHead>
                <TableHead>Matched product</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead className="text-right">Conf.</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {order.lines.map((line) => (
                <LineRow
                  key={line.lineId}
                  line={line}
                  active={line.lineId === activeLineId}
                  readOnly={readOnly}
                  onSelect={() => setActiveLineId(line.lineId)}
                  onPick={(sku) => correct.mutate({ lineId: line.lineId, sku })}
                />
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>
    </>
  );
}

function correctionError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return 'The order changed in the meantime or is no longer editable: reload it.';
  }
  if (error instanceof ApiError && error.status === 400) {
    return 'This line cannot be matched: its quantity is missing or the product is not available.';
  }
  return 'Could not apply the correction.';
}

interface RowProps {
  line: OrderLine;
  active: boolean;
  readOnly: boolean;
  onSelect: () => void;
  onPick: (sku: string) => void;
}

function LineRow({ line, active, readOnly, onSelect, onPick }: RowProps) {
  const needsDecision = UNCERTAIN_LINE_STATUSES.includes(line.status) && line.candidates.length > 0;
  return (
    <TableRow
      aria-selected={active}
      data-corrected={line.correctedBy !== null}
      tabIndex={0}
      onClick={onSelect}
      onFocus={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
      className={cn(
        'cursor-pointer outline-none focus-visible:bg-accent/60',
        line.correctedBy !== null && 'shadow-[inset_4px_0_0_var(--success)]',
      )}
    >
      <TableCell className="font-medium">{line.rawText}</TableCell>
      <TableCell>
        <div className="grid gap-1">
          <span>
            {line.name ?? <em className="text-muted-foreground">not matched</em>}
            {line.sku && (
              <small className="ml-1.5 font-mono text-xs text-muted-foreground">{line.sku}</small>
            )}
          </span>
          {line.correctedBy && <Badge variant="success">Corrected by {line.correctedBy}</Badge>}
          {needsDecision && (
            <ul className="mt-1 grid gap-1.5">
              {line.candidates.map((c) => (
                <li key={c.sku}>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-auto min-h-8 w-full justify-between gap-3 py-1.5 text-left whitespace-normal"
                    disabled={readOnly}
                    title={readOnly ? 'Read-only access' : undefined}
                    aria-label={`Use ${c.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onPick(c.sku);
                    }}
                  >
                    <span>Use {c.name}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {Math.round(c.confidence * 100)}%
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </TableCell>
      <TableCell className="whitespace-nowrap tabular-nums">
        {line.quantity !== null ? `${line.quantity} ${line.unit ?? ''}` : '–'}
      </TableCell>
      <TableCell className="text-right text-muted-foreground tabular-nums">
        {Math.round(line.confidence * 100)}%
      </TableCell>
      <TableCell>
        <StatusBadge status={line.status} />
      </TableCell>
    </TableRow>
  );
}
