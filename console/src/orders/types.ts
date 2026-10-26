// Contracts: docs/02_TECHNICAL_FLOWS.md §2.3 (order status), §2.4 (line status) and §6.3 (order line).

export const ORDER_STATUSES = [
  'DRAFT',
  'NEEDS_CLARIFICATION',
  'PENDING_CONFIRMATION',
  'CONFIRMED',
  'EXPIRED',
  'SUBMITTED',
  'SCHEDULED',
  'OUT_FOR_DELIVERY',
  'DELIVERED',
  'DELIVERY_ISSUE',
  'CANCELLED',
] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

export type LineStatus =
  | 'MATCHED'
  | 'AMBIGUOUS'
  | 'UNMATCHED'
  | 'OUT_OF_STOCK'
  | 'SUBSTITUTED'
  | 'ADJUSTED'
  | 'REMOVED'
  | 'CONFIRMED';

/** Lines that still need a decision (candidates to choose from, or nothing found). */
export const UNCERTAIN_LINE_STATUSES: readonly LineStatus[] = ['AMBIGUOUS', 'UNMATCHED'];

/** Region of the ticket photo, normalized 0–1 relative to the image size. */
export interface ImageRegion {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Candidate {
  sku: string;
  name: string;
  confidence: number;
  boughtBefore: boolean;
}

export interface OrderLine {
  lineId: string;
  rawText: string;
  rawQuantity: string | null;
  rawUnit: string | null;
  sourceMessageId: string;
  imageRegion: ImageRegion | null;
  candidates: Candidate[];
  status: LineStatus;
  sku: string | null;
  /** ponytail: product name is not in the 02 §6.3 extract; assumed denormalized on the line (T-46). */
  name: string | null;
  quantity: number | null;
  unit: string | null;
  confidence: number;
  correctedBy: 'customer' | 'rep' | 'backoffice' | null;
}

/** What `GET /orders` returns per order (console_api `SUMMARY_FIELDS`). */
export interface OrderSummary {
  orderId: string;
  customerId: string;
  /** ponytail: not returned by console_api yet; filled by the mock, shown when present. */
  customerName?: string;
  repId?: string;
  status: OrderStatus;
  createdAt: string;
  updatedAt: string;
  /** Assumption until T-46: count of AMBIGUOUS/UNMATCHED lines, and conversation `mode = HUMAN`. */
  uncertainLines?: number;
  handoff?: boolean;
}

export interface Order extends OrderSummary {
  source: 'photo' | 'voice' | 'text' | 'email' | 'reorder' | 'rep';
  lines: OrderLine[];
}

/** `GET /orders/{orderId}`: the order plus a short-lived presigned URL of the ticket photo. */
export interface OrderDetail {
  order: Order;
  imageUrl: string | null;
}
