import { apiFetch } from '../api/client';
import { mockOrdersApi } from './mockApi';
import type { OrderDetail, OrderSummary } from './types';

export interface OrdersApi {
  /** `mock` until the orders tool (T-46) writes real orders. */
  readonly source: 'mock' | 'api';
  listOrders(): Promise<OrderSummary[]>;
  getOrder(orderId: string): Promise<OrderDetail>;
  /** Back-office correction of a line: pick one of its candidates. */
  correctLine(orderId: string, lineId: string, sku: string): Promise<void>;
}

/** console_api (T-60): read-only for now; corrections arrive with T-46. */
export const httpOrdersApi: OrdersApi = {
  source: 'api',
  async listOrders() {
    return (await apiFetch<{ orders: OrderSummary[] }>('/orders')).orders;
  },
  getOrder: (orderId) => apiFetch<OrderDetail>(`/orders/${encodeURIComponent(orderId)}`),
  async correctLine() {
    throw new Error('Line corrections are not available yet (orders tool, T-46).');
  },
};

/** `VITE_ORDERS_SOURCE=api` switches to the real API; mock is the default until T-46 is on main. */
export const defaultOrdersApi: OrdersApi =
  import.meta.env.VITE_ORDERS_SOURCE === 'api' ? httpOrdersApi : mockOrdersApi;
