import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { isReadOnly } from '../auth/roles';
import { useOrdersApi } from './OrdersApiContext';
import { TicketImage } from './TicketImage';
import { UNCERTAIN_LINE_STATUSES, type OrderLine } from './types';

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

  if (error) return <p role="alert">Could not load the order.</p>;
  if (!data) return <p className="status">Loading…</p>;
  const { order, imageUrl } = data;

  return (
    <>
      <p>
        <Link to="/">← Orders</Link>
      </p>
      <h1>
        {order.orderId} <span className={`status status-${order.status}`}>{order.status}</span>
      </h1>
      <p>
        {order.customerName ?? order.customerId} · source: {order.source}
      </p>
      {readOnly && (
        <p role="note" className="notice">
          Read-only access: you can browse the order and its ticket, but not correct lines.
        </p>
      )}
      {correct.isError && <p role="alert">{correctionError(correct.error)}</p>}
      <div className="detail">
        {imageUrl ? (
          <TicketImage
            src={imageUrl}
            lines={order.lines}
            activeLineId={activeLineId}
            onSelect={setActiveLineId}
          />
        ) : (
          <p className="notice">No ticket image for this order.</p>
        )}
        <table className="lines">
          <thead>
            <tr>
              <th>Written</th>
              <th>Matched product</th>
              <th>Qty</th>
              <th>Conf.</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
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
          </tbody>
        </table>
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
    <tr
      aria-selected={active}
      data-corrected={line.correctedBy !== null}
      tabIndex={0}
      onClick={onSelect}
      onFocus={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
    >
      <td>{line.rawText}</td>
      <td>
        {line.name ?? <em>not matched</em>}
        {line.sku && <small> {line.sku}</small>}
        {line.correctedBy && <strong className="badge">Corrected by {line.correctedBy}</strong>}
        {needsDecision && (
          <ul className="candidates">
            {line.candidates.map((c) => (
              <li key={c.sku}>
                <button
                  type="button"
                  disabled={readOnly}
                  title={readOnly ? 'Read-only access' : undefined}
                  aria-label={`Use ${c.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onPick(c.sku);
                  }}
                >
                  Use {c.name} ({Math.round(c.confidence * 100)}%)
                </button>
              </li>
            ))}
          </ul>
        )}
      </td>
      <td>{line.quantity !== null ? `${line.quantity} ${line.unit ?? ''}` : '–'}</td>
      <td>{Math.round(line.confidence * 100)}%</td>
      <td>
        <span className={`status status-${line.status}`}>{line.status}</span>
      </td>
    </tr>
  );
}
