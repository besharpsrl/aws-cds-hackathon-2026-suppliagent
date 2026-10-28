export const formatDate = (iso: string) =>
  new Date(iso).toLocaleString('it-IT', {
    timeZone: 'Europe/Rome',
    dateStyle: 'short',
    timeStyle: 'short',
  });

const REASONS: Record<string, string> = {
  CUSTOMER_REQUEST: 'Customer asked for a person',
  IDENTIFICATION_FAILED: 'Could not identify the contact',
  NEW_CUSTOMER: 'New customer',
  UNRESOLVED_LINES: 'Unresolved order lines',
  ORDER_LOCKED: 'Change after the cut-off',
  DELIVERY_ISSUE: 'Delivery issue',
  NEGATIVE_SENTIMENT: 'Unhappy customer',
  LOW_CONFIDENCE: 'Agent not confident',
  OUT_OF_SCOPE: 'Out of scope',
  OPERATOR_TAKEOVER: 'Operator took over',
};

export const handoffReasonLabel = (reason: string): string => REASONS[reason] ?? reason;
