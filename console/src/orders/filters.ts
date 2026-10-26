import type { OrderStatus, OrderSummary } from './types';

export interface OrderFilters {
  status: OrderStatus | 'ALL';
  uncertain: boolean;
  issues: boolean;
  handoff: boolean;
}

export const NO_FILTERS: OrderFilters = {
  status: 'ALL',
  uncertain: false,
  issues: false,
  handoff: false,
};

/** Inbox filters of FN-28; all active filters must match. */
export function filterOrders(orders: OrderSummary[], f: OrderFilters): OrderSummary[] {
  return orders.filter(
    (o) =>
      (f.status === 'ALL' || o.status === f.status) &&
      (!f.uncertain || (o.uncertainLines ?? 0) > 0) &&
      (!f.issues || o.status === 'DELIVERY_ISSUE') &&
      (!f.handoff || o.handoff === true),
  );
}
