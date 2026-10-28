import { useQuery } from '@tanstack/react-query';
import { Headset, Info } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { filterOrders, NO_FILTERS, type OrderFilters } from './filters';
import { useOrdersApi } from './OrdersApiContext';
import { ORDER_STATUSES } from './types';
import { PageHeader } from '@/components/page-header';
import { StatusBadge, statusLabel } from '@/components/status-badge';
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

/** FN-28: the inbox is refreshed within 2 s; polling until the WebSocket push (T-63). */
const REFRESH_MS = 2000;

const formatDate = (iso: string) =>
  new Date(iso).toLocaleString('it-IT', {
    timeZone: 'Europe/Rome',
    dateStyle: 'short',
    timeStyle: 'short',
  });

export function InboxPage() {
  const api = useOrdersApi();
  const [filters, setFilters] = useState<OrderFilters>(NO_FILTERS);
  const { data, error } = useQuery({
    queryKey: ['orders'],
    queryFn: () => api.listOrders(),
    refetchInterval: REFRESH_MS,
  });

  const orders = filterOrders(data ?? [], filters).sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );
  const toggle = (key: 'uncertain' | 'issues' | 'handoff', label: string) => (
    <label className="flex cursor-pointer items-center gap-2 rounded-md border border-input bg-card px-3 py-1.5 text-sm font-medium shadow-xs transition-colors has-checked:border-primary has-checked:bg-accent has-checked:text-accent-foreground">
      <input
        type="checkbox"
        className="size-4 accent-primary"
        checked={filters[key]}
        onChange={(e) => setFilters({ ...filters, [key]: e.target.checked })}
      />
      {label}
    </label>
  );

  return (
    <>
      <PageHeader
        title="Orders"
        description="Orders read by the agent from WhatsApp and email, newest first."
      />
      {api.source === 'mock' && (
        <Alert variant="info" className="mb-4">
          <Info aria-hidden="true" />
          <AlertDescription>
            Mock data: real orders appear once the orders tool (T-46) is live.
          </AlertDescription>
        </Alert>
      )}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm font-medium">
          Status
          <select
            className="h-9 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
            value={filters.status}
            onChange={(e) =>
              setFilters({ ...filters, status: e.target.value as OrderFilters['status'] })
            }
          >
            <option value="ALL">All</option>
            {ORDER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </label>
        {toggle('uncertain', 'Uncertain lines')}
        {toggle('issues', 'Delivery issues')}
        {toggle('handoff', 'Handed off')}
      </div>
      {error && (
        <Alert variant="destructive" role="alert" className="mb-4">
          <AlertDescription>Could not load orders.</AlertDescription>
        </Alert>
      )}
      <Card className="gap-0 overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Order</TableHead>
              <TableHead>Customer</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Uncertain lines</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {orders.map((o) => (
              <TableRow key={o.orderId}>
                <TableCell>
                  <Link
                    to={`/orders/${o.orderId}`}
                    className="font-mono text-xs font-semibold text-primary hover:underline"
                  >
                    {o.orderId}
                  </Link>
                </TableCell>
                <TableCell className="font-medium">{o.customerName ?? o.customerId}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={o.status} />
                    {o.handoff && (
                      <Badge variant="default">
                        <Headset aria-hidden="true" />
                        Handoff
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {o.uncertainLines ? (
                    <span className="font-semibold text-warning">{o.uncertainLines}</span>
                  ) : (
                    <span className="text-muted-foreground">{o.uncertainLines ?? '–'}</span>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground tabular-nums">
                  {formatDate(o.updatedAt)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {data && orders.length === 0 && (
          <p className="p-8 text-center text-sm text-muted-foreground">
            No orders match the filters.
          </p>
        )}
      </Card>
    </>
  );
}
