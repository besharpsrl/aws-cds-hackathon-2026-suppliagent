import type { OrdersApi } from './api';
import { fixtureDetails } from './fixtures';
import { UNCERTAIN_LINE_STATUSES, type Order, type OrderSummary } from './types';

const summarize = (o: Order): OrderSummary => ({
  orderId: o.orderId,
  customerId: o.customerId,
  customerName: o.customerName,
  repId: o.repId,
  status: o.status,
  createdAt: o.createdAt,
  updatedAt: o.updatedAt,
  handoff: o.handoff,
  uncertainLines: o.lines.filter((l) => UNCERTAIN_LINE_STATUSES.includes(l.status)).length,
});

// In-memory state: corrections survive navigation but not a page reload.
const details = new Map(fixtureDetails.map((d) => [d.order.orderId, structuredClone(d)]));

export const mockOrdersApi: OrdersApi = {
  source: 'mock',
  async listOrders() {
    return [...details.values()].map((d) => summarize(d.order));
  },
  async getOrder(orderId) {
    const detail = details.get(orderId);
    if (!detail) throw new Error(`Order ${orderId} not found`);
    return structuredClone(detail);
  },
  async correctLine(orderId, lineId, sku) {
    const order = details.get(orderId)?.order;
    const line = order?.lines.find((l) => l.lineId === lineId);
    const candidate = line?.candidates.find((c) => c.sku === sku);
    if (!order || !line || !candidate) throw new Error('Unknown order, line or candidate');
    Object.assign(line, {
      status: 'MATCHED',
      sku: candidate.sku,
      name: candidate.name,
      confidence: 1,
      correctedBy: 'backoffice',
      quantity: line.quantity ?? (Number(line.rawQuantity) || 1),
    });
    order.updatedAt = new Date().toISOString();
  },
};
