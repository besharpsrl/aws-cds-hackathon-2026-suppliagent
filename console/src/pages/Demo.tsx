import { Download, MessageCircle, MousePointerClick, Inbox } from 'lucide-react';
import { Link } from 'react-router-dom';
import sampleTicket from '../../../agent/evals/data/bigliettini/ordine_ristorante.jpeg';
import { PageHeader } from '@/components/page-header';
import { Card, CardContent } from '@/components/ui/card';

// Channels of the demo environment (FN-31), set in console/.env.local when known.
const channel = (value: unknown) => String(value ?? '') || 'to be announced';

const linkClass = 'font-semibold text-primary underline-offset-4 hover:underline';

export function Demo() {
  const steps = [
    {
      Icon: Download,
      body: (
        <>
          <a href={sampleTicket} download="sample-order.jpeg" className={linkClass}>
            Download the sample ticket
          </a>{' '}
          (a handwritten order from a restaurant), or write your own.
        </>
      ),
    },
    {
      Icon: MessageCircle,
      body: (
        <>
          Send the photo on WhatsApp to{' '}
          <strong>{channel(import.meta.env.VITE_DEMO_WHATSAPP)}</strong> or by email to{' '}
          <strong>{channel(import.meta.env.VITE_DEMO_ORDER_EMAIL)}</strong>.
        </>
      ),
    },
    {
      Icon: MousePointerClick,
      body: <>Answer the agent&apos;s questions with the buttons, then confirm the summary.</>,
    },
    {
      Icon: Inbox,
      body: (
        <>
          Open{' '}
          <Link to="/" className={linkClass}>
            Orders
          </Link>{' '}
          here: the order appears with your ticket beside the lines the agent read, and the
          corrections it needed.
        </>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Try SuppliAgent in 5 minutes"
        description="SuppliAgent reads handwritten orders sent on WhatsApp or by email, asks only what it is unsure about, and confirms with the customer before anything reaches the ERP."
      />
      <ol className="grid gap-4 sm:grid-cols-2">
        {steps.map(({ Icon, body }, i) => (
          <li key={i}>
            <Card className="h-full">
              <CardContent className="flex gap-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <div className="grid gap-1">
                  <span className="font-display text-xs font-black uppercase tracking-widest text-primary">
                    Step {i + 1}
                  </span>
                  <p className="text-sm leading-relaxed">{body}</p>
                </div>
              </CardContent>
            </Card>
          </li>
        ))}
      </ol>
    </>
  );
}
