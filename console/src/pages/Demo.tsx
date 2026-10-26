import { Link } from 'react-router-dom';
import sampleTicket from '../../../agent/evals/data/bigliettini/ordine_ristorante.jpeg';

// Channels of the demo environment (FN-31), set in console/.env.local when known.
const channel = (value: unknown) => String(value ?? '') || 'to be announced';

export function Demo() {
  return (
    <>
      <h1>Try SuppliAgent in 5 minutes</h1>
      <p>
        SuppliAgent reads handwritten orders sent on WhatsApp or by email, asks only what it is
        unsure about, and confirms with the customer before anything reaches the ERP.
      </p>
      <ol className="steps">
        <li>
          <a href={sampleTicket} download="sample-order.jpeg">
            Download the sample ticket
          </a>{' '}
          (a handwritten order from a restaurant), or write your own.
        </li>
        <li>
          Send the photo on WhatsApp to{' '}
          <strong>{channel(import.meta.env.VITE_DEMO_WHATSAPP)}</strong> or by email to{' '}
          <strong>{channel(import.meta.env.VITE_DEMO_ORDER_EMAIL)}</strong>.
        </li>
        <li>Answer the agent&apos;s questions with the buttons, then confirm the summary.</li>
        <li>
          Open <Link to="/">Orders</Link> here: the order appears with your ticket beside the lines
          the agent read, and the corrections it needed.
        </li>
      </ol>
    </>
  );
}
