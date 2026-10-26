import { describe, expect, it } from 'vitest';
import { filterOrders, NO_FILTERS } from './filters';
import type { OrderSummary } from './types';

const order = (over: Partial<OrderSummary>): OrderSummary => ({
  orderId: 'ord_x',
  customerId: 'cus_1',
  status: 'DRAFT',
  createdAt: '2026-10-20T07:41:00Z',
  updatedAt: '2026-10-20T07:42:00Z',
  ...over,
});

const orders = [
  order({ orderId: 'a', status: 'NEEDS_CLARIFICATION', uncertainLines: 3 }),
  order({ orderId: 'b', status: 'CONFIRMED', uncertainLines: 0 }),
  order({ orderId: 'c', status: 'DELIVERY_ISSUE' }),
  order({ orderId: 'd', status: 'DRAFT', handoff: true }),
];
const ids = (list: OrderSummary[]) => list.map((o) => o.orderId);

describe('filterOrders (FN-28: stato, righe incerte, problemi, handoff)', () => {
  it('returns everything without filters', () => {
    expect(ids(filterOrders(orders, NO_FILTERS))).toEqual(['a', 'b', 'c', 'd']);
  });

  it('filters by status', () => {
    expect(ids(filterOrders(orders, { ...NO_FILTERS, status: 'CONFIRMED' }))).toEqual(['b']);
  });

  it('keeps only orders with uncertain lines', () => {
    expect(ids(filterOrders(orders, { ...NO_FILTERS, uncertain: true }))).toEqual(['a']);
  });

  it('keeps only orders with delivery issues', () => {
    expect(ids(filterOrders(orders, { ...NO_FILTERS, issues: true }))).toEqual(['c']);
  });

  it('keeps only orders handed off to a human', () => {
    expect(ids(filterOrders(orders, { ...NO_FILTERS, handoff: true }))).toEqual(['d']);
  });

  it('combines filters with AND', () => {
    const filters = { ...NO_FILTERS, status: 'NEEDS_CLARIFICATION' as const, uncertain: true };
    expect(ids(filterOrders(orders, filters))).toEqual(['a']);
    expect(ids(filterOrders(orders, { ...filters, handoff: true }))).toEqual([]);
  });
});
