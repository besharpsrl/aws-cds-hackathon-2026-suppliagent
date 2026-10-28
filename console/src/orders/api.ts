import { apiFetch } from '../api/client';
import { mockOrdersApi } from './mockApi';
import type { OrderDetail, OrderSummary } from './types';

export interface OrdersApi {
  /** `mock` is local development only; the published console uses `api`. */
  readonly source: 'mock' | 'api';
  listOrders(): Promise<OrderSummary[]>;
  getOrder(orderId: string): Promise<OrderDetail>;
  /** Back-office correction of a line: pick one of its candidates. */
  correctLine(orderId: string, lineId: string, sku: string): Promise<void>;
}

/** console_api: list, detail and line correction (the API also checks role and portfolio). */
export const httpOrdersApi: OrdersApi = {
  source: 'api',
  async listOrders() {
    return (await apiFetch<{ orders: OrderSummary[] }>('/orders')).orders;
  },
  getOrder: (orderId) => apiFetch<OrderDetail>(`/orders/${encodeURIComponent(orderId)}`),
  async correctLine(orderId, lineId, sku) {
    await apiFetch(`/orders/${encodeURIComponent(orderId)}/lines/${encodeURIComponent(lineId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sku }),
    });
  },
};

/** `VITE_ORDERS_SOURCE=api` uses the real API (what `scripts/deploy-console.sh` builds); mock is the local default. */
export const defaultOrdersApi: OrdersApi =
  import.meta.env.VITE_ORDERS_SOURCE === 'api' ? httpOrdersApi : mockOrdersApi;
