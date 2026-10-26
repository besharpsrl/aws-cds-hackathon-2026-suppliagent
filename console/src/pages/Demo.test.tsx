import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Demo } from './Demo';

const renderDemo = () =>
  render(
    <MemoryRouter>
      <Demo />
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllEnvs());

describe('Demo page for judges (FN-31)', () => {
  it('offers the sample handwritten order as a download', () => {
    renderDemo();
    const link = screen.getByRole('link', { name: /download the sample ticket/i });
    expect(link).toHaveAttribute('download');
    expect(link.getAttribute('href')).toMatch(/\.jpe?g$/);
  });

  it('shows the WhatsApp number and order email when configured', () => {
    vi.stubEnv('VITE_DEMO_WHATSAPP', '+39 000 000 0000');
    vi.stubEnv('VITE_DEMO_ORDER_EMAIL', 'ordini@demo.example');
    renderDemo();
    expect(screen.getByText('+39 000 000 0000')).toBeInTheDocument();
    expect(screen.getByText('ordini@demo.example')).toBeInTheDocument();
  });

  it('says the channels are not announced yet instead of showing empty values', () => {
    vi.stubEnv('VITE_DEMO_WHATSAPP', '');
    vi.stubEnv('VITE_DEMO_ORDER_EMAIL', '');
    renderDemo();
    expect(screen.getAllByText(/to be announced/i)).toHaveLength(2);
  });

  it('links back to the orders where the new order shows up', () => {
    renderDemo();
    expect(screen.getByRole('link', { name: /orders/i })).toHaveAttribute('href', '/');
  });
});
