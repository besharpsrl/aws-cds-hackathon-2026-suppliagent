import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthContext } from '../auth/AuthContext';
import type { Role } from '../auth/roles';
import { OrdersApiContext } from './OrdersApiContext';
import { OrderDetailPage } from './OrderDetailPage';
import { InboxPage } from './InboxPage';
import type { OrdersApi } from './api';
import type { Order, OrderLine } from './types';

export const line = (over: Partial<OrderLine>): OrderLine => ({
  lineId: 'l1',
  rawText: '10 wurstel',
  rawQuantity: '10',
  rawUnit: null,
  sourceMessageId: 'm1',
  imageRegion: { x: 0.2, y: 0.2, w: 0.3, h: 0.03 },
  candidates: [],
  status: 'MATCHED',
  sku: 'SAL-0001',
  name: 'Wurstel 500 g',
  quantity: 10,
  unit: 'pz',
  confidence: 0.95,
  correctedBy: null,
  ...over,
});

export const makeOrder = (over: Partial<Order> = {}): Order => ({
  orderId: 'ord_1',
  customerId: 'cus_1',
  customerName: 'Pub Demo',
  status: 'NEEDS_CLARIFICATION',
  source: 'photo',
  createdAt: '2026-10-20T07:41:00Z',
  updatedAt: '2026-10-20T07:42:00Z',
  lines: [
    line({ lineId: 'l1' }),
    line({
      lineId: 'l3',
      rawText: '20 hamburger (PANE)',
      imageRegion: { x: 0.2, y: 0.3, w: 0.3, h: 0.04 },
      status: 'AMBIGUOUS',
      sku: null,
      name: null,
      quantity: null,
      confidence: 0.62,
      candidates: [
        { sku: 'PAN-0100', name: 'Pane per hamburger 6 pz', confidence: 0.78, boughtBefore: true },
        { sku: 'PAN-0101', name: 'Pane per hamburger XL', confidence: 0.64, boughtBefore: false },
      ],
    }),
    line({
      lineId: 'l5',
      rawText: 'caffè 4 scatole',
      imageRegion: { x: 0.2, y: 0.5, w: 0.3, h: 0.04 },
      sku: 'CAF-0010',
      name: 'Caffè 1 kg',
      correctedBy: 'backoffice',
    }),
  ],
  ...over,
});

export function makeApi(over: Partial<OrdersApi> = {}): OrdersApi {
  return {
    source: 'mock',
    listOrders: vi.fn(async () => []),
    getOrder: vi.fn(async () => ({ order: makeOrder(), imageUrl: 'https://img.test/ticket.jpg' })),
    correctLine: vi.fn(async () => {}),
    ...over,
  };
}

/** Renders the inbox at `/` and the detail page at `/orders/:orderId`. */
export function renderOrders(api: OrdersApi, roles: Role[], path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={{
          status: 'signedIn',
          user: { email: 'u@demo.it', roles },
          signIn: async () => {},
          signOut: async () => {},
        }}
      >
        <OrdersApiContext.Provider value={api}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/" element={<InboxPage />} />
              <Route path="/orders/:orderId" element={<OrderDetailPage />} />
            </Routes>
          </MemoryRouter>
        </OrdersApiContext.Provider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}
