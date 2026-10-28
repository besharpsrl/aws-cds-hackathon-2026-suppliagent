import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { makeApi, makeOrder, renderOrders } from './testUtils';

const open = async (roles: Parameters<typeof renderOrders>[1], api = makeApi()) => {
  renderOrders(api, roles, '/orders/ord_1');
  await screen.findByRole('img', { name: /ticket/i });
  return api;
};

describe('OrderDetailPage: bigliettino affiancato alle righe (FN-28)', () => {
  it('shows the ticket image next to one table row per line', async () => {
    await open(['backoffice']);
    expect(screen.getByRole('img', { name: /ticket/i })).toHaveAttribute(
      'src',
      'https://img.test/ticket.jpg',
    );
    expect(screen.getAllByRole('row')).toHaveLength(1 + 3); // header + lines
    expect(screen.getByTestId('region-l1')).toBeInTheDocument();
    expect(screen.getByTestId('region-l3')).toBeInTheDocument();
  });

  it('positions each region from imageRegion, in percent of the image', async () => {
    await open(['backoffice']);
    expect(screen.getByTestId('region-l3')).toHaveStyle({
      left: '20%',
      top: '30%',
      width: '30%',
      height: '4%',
    });
  });

  it('highlights the region of the selected row and vice versa', async () => {
    await open(['backoffice']);
    expect(screen.getByTestId('region-l3')).toHaveAttribute('data-active', 'false');
    await userEvent.click(screen.getByText('20 hamburger (PANE)'));
    expect(screen.getByTestId('region-l3')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('region-l1')).toHaveAttribute('data-active', 'false');
    await userEvent.click(screen.getByTestId('region-l1'));
    expect(screen.getByTestId('region-l1')).toHaveAttribute('data-active', 'true');
    expect(screen.getByRole('row', { selected: true })).toHaveTextContent('10 wurstel');
  });

  it('flags corrected lines and who corrected them', async () => {
    await open(['backoffice']);
    const row = screen.getByText('caffè 4 scatole').closest('tr') as HTMLElement;
    expect(row).toHaveAttribute('data-corrected', 'true');
    expect(within(row).getByText(/corrected by backoffice/i)).toBeInTheDocument();
  });

  it('degrades gracefully when the order has no ticket image', async () => {
    const api = makeApi({
      getOrder: vi.fn(async () => ({ order: makeOrder({ source: 'email' }), imageUrl: null })),
    });
    renderOrders(api, ['backoffice'], '/orders/ord_1');
    expect(await screen.findByText(/no ticket image/i)).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(4);
  });
});

describe('OrderDetailPage: correzione righe e ruolo judge (FN-28, FN-32)', () => {
  it('lets backoffice pick a candidate for an ambiguous line', async () => {
    const api = await open(['backoffice']);
    await userEvent.click(screen.getByRole('button', { name: /pane per hamburger 6 pz/i }));
    await waitFor(() => expect(api.correctLine).toHaveBeenCalledWith('ord_1', 'l3', 'PAN-0100'));
  });

  it('shows the candidate buttons only for lines that need a decision', async () => {
    await open(['backoffice']);
    expect(screen.getAllByRole('button', { name: /^use /i })).toHaveLength(2); // l3 candidates
  });

  it('disables corrections for the read-only judge role', async () => {
    const api = await open(['judge']);
    const button = screen.getByRole('button', { name: /pane per hamburger 6 pz/i });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(api.correctLine).not.toHaveBeenCalled();
  });

  it('explains a refused correction by its status', async () => {
    const api = makeApi({
      correctLine: vi.fn(async () => {
        throw new ApiError(409, 'API 409');
      }),
    });
    await open(['backoffice'], api);
    await userEvent.click(screen.getByRole('button', { name: /pane per hamburger 6 pz/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/reload it/i);
  });

  it('shows an error when the order cannot be loaded', async () => {
    const api = makeApi({
      getOrder: vi.fn(async () => {
        throw new Error('boom');
      }),
    });
    renderOrders(api, ['backoffice'], '/orders/ord_1');
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i);
  });
});
