import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { makeApi, renderOrders } from './testUtils';
import type { OrderSummary } from './types';

const summary = (over: Partial<OrderSummary>): OrderSummary => ({
  orderId: 'ord_1',
  customerId: 'cus_1',
  customerName: 'Pub Demo',
  status: 'NEEDS_CLARIFICATION',
  createdAt: '2026-10-20T07:41:00Z',
  updatedAt: '2026-10-20T07:42:00Z',
  uncertainLines: 3,
  ...over,
});

const api = () =>
  makeApi({
    listOrders: vi.fn(async () => [
      summary({ orderId: 'ord_1' }),
      summary({
        orderId: 'ord_2',
        customerName: 'Bar Demo',
        status: 'CONFIRMED',
        uncertainLines: 0,
      }),
      summary({ orderId: 'ord_3', customerName: 'Trattoria Demo', status: 'DELIVERY_ISSUE' }),
    ]),
  });

describe('InboxPage (FN-28)', () => {
  it('lists orders newest-updated first with a link to the detail', async () => {
    renderOrders(
      makeApi({
        listOrders: vi.fn(async () => [
          summary({ orderId: 'ord_old', updatedAt: '2026-10-19T10:00:00Z' }),
          summary({ orderId: 'ord_new', updatedAt: '2026-10-21T10:00:00Z' }),
        ]),
      }),
      ['backoffice'],
      '/',
    );
    const links = await screen.findAllByRole('link', { name: /ord_/ });
    expect(links.map((l) => l.textContent)).toEqual(['ord_new', 'ord_old']);
    expect(links[0]).toHaveAttribute('href', '/orders/ord_new');
  });

  it('filters by status', async () => {
    renderOrders(api(), ['backoffice'], '/');
    await screen.findByText('Bar Demo');
    await userEvent.selectOptions(screen.getByLabelText(/status/i), 'CONFIRMED');
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText('Bar Demo')).toBeInTheDocument();
  });

  it('filters orders with uncertain lines and with delivery issues', async () => {
    renderOrders(api(), ['backoffice'], '/');
    await screen.findByText('Bar Demo');
    await userEvent.click(screen.getByLabelText(/uncertain lines/i));
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(2); // ord_1 and ord_3 (3 uncertain)
    await userEvent.click(screen.getByLabelText(/delivery issues/i));
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText('Trattoria Demo')).toBeInTheDocument();
  });

  it('says so when no order matches', async () => {
    renderOrders(api(), ['backoffice'], '/');
    await screen.findByText('Bar Demo');
    await userEvent.click(screen.getByLabelText(/handed off/i));
    expect(screen.getByText(/no orders match/i)).toBeInTheDocument();
  });

  it('tells the user when the data is mocked', async () => {
    renderOrders(api(), ['judge'], '/');
    expect(await screen.findByText(/mock data/i)).toBeInTheDocument();
  });

  it('shows an error when the list cannot be loaded', async () => {
    renderOrders(
      makeApi({
        listOrders: vi.fn(async () => {
          throw new Error('boom');
        }),
      }),
      ['backoffice'],
      '/',
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i);
  });
});
