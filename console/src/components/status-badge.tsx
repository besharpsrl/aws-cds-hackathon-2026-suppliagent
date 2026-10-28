import {
  CircleCheck,
  CircleDashed,
  CircleQuestionMark,
  CircleX,
  Clock,
  TriangleAlert,
  Truck,
  type LucideIcon,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';

type Tone = 'success' | 'warning' | 'destructive' | 'secondary' | 'muted';

const TONES: Record<string, [Tone, LucideIcon]> = {
  DRAFT: ['muted', CircleDashed],
  NEEDS_CLARIFICATION: ['warning', CircleQuestionMark],
  PENDING_CONFIRMATION: ['secondary', Clock],
  CONFIRMED: ['success', CircleCheck],
  EXPIRED: ['muted', CircleX],
  SUBMITTED: ['success', CircleCheck],
  SCHEDULED: ['secondary', Clock],
  OUT_FOR_DELIVERY: ['secondary', Truck],
  DELIVERED: ['success', CircleCheck],
  DELIVERY_ISSUE: ['destructive', TriangleAlert],
  CANCELLED: ['muted', CircleX],
  MATCHED: ['success', CircleCheck],
  AMBIGUOUS: ['warning', CircleQuestionMark],
  UNMATCHED: ['warning', TriangleAlert],
  OUT_OF_STOCK: ['destructive', TriangleAlert],
  SUBSTITUTED: ['secondary', CircleCheck],
  ADJUSTED: ['secondary', CircleCheck],
  REMOVED: ['muted', CircleX],
};

export const statusLabel = (status: string): string => {
  const text = status.replaceAll('_', ' ').toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** Order or line status: colour plus icon and text, never colour alone. */
export function StatusBadge({ status }: { status: string }) {
  const [tone, Icon] = TONES[status] ?? ['muted', CircleDashed];
  return (
    <Badge variant={tone}>
      <Icon aria-hidden="true" />
      {statusLabel(status)}
    </Badge>
  );
}
