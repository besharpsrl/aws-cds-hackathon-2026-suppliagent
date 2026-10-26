import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { makeApi, renderOrders } from './testUtils';

const open = async (roles: Parameters<typeof renderOrders>[1]) => {
  renderOrders(makeApi(), roles, '/orders/ord_1');
  await screen.findByRole('img', { name: /ticket/i });
};

describe('OrderDetailPage: avviso sola lettura per il judge (FN-28, FN-31)', () => {
  it('tells the judge why corrections are disabled', async () => {
    await open(['judge']);
    expect(screen.getByRole('note')).toHaveTextContent(/read-only access/i);
  });

  it('does not show the notice to roles that can correct', async () => {
    await open(['backoffice']);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('does not show it to a judge who is also backoffice (groups are additive)', async () => {
    await open(['judge', 'backoffice']);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});
