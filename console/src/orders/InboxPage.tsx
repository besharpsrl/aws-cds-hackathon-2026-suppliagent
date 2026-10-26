import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { filterOrders, NO_FILTERS, type OrderFilters } from './filters';
import { useOrdersApi } from './OrdersApiContext';
import { ORDER_STATUSES } from './types';

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
  const toggle = (key: 'uncertain' | 'issues' | 'handoff') => (
    <input
      type="checkbox"
      checked={filters[key]}
      onChange={(e) => setFilters({ ...filters, [key]: e.target.checked })}
    />
  );

  return (
    <>
      <h1>Orders</h1>
      {api.source === 'mock' && (
        <p className="notice">Mock data: real orders appear once the orders tool (T-46) is live.</p>
      )}
      <div className="filters">
        <label>
          Status
          <select
            value={filters.status}
            onChange={(e) =>
              setFilters({ ...filters, status: e.target.value as OrderFilters['status'] })
            }
          >
            <option value="ALL">All</option>
            {ORDER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>{toggle('uncertain')} Uncertain lines</label>
        <label>{toggle('issues')} Delivery issues</label>
        <label>{toggle('handoff')} Handed off</label>
      </div>
      {error && <p role="alert">Could not load orders.</p>}
      <table className="orders">
        <thead>
          <tr>
            <th>Order</th>
            <th>Customer</th>
            <th>Status</th>
            <th>Uncertain lines</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.orderId}>
              <td>
                <Link to={`/orders/${o.orderId}`}>{o.orderId}</Link>
              </td>
              <td>{o.customerName ?? o.customerId}</td>
              <td>
                <span className={`status status-${o.status}`}>{o.status}</span>
                {o.handoff && <strong className="badge">Handoff</strong>}
              </td>
              <td>{o.uncertainLines ?? '–'}</td>
              <td>{formatDate(o.updatedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && orders.length === 0 && <p>No orders match the filters.</p>}
    </>
  );
}
