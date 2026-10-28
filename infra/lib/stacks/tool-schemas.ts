import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';

const { ARRAY, BOOLEAN, NUMBER, OBJECT, STRING } = agentcore.SchemaDefinitionType;

/**
 * Declared so the Gateway forwards it to the Lambda; the agent removes it from the schema the model
 * sees and always overwrites it (INFRASTRUCTURE_DESIGN §5.3.2).
 */
const CALLER: agentcore.SchemaDefinition = {
  type: OBJECT,
  description: 'Set by the system on every call. Never set it.',
  properties: {
    role: { type: STRING },
    contactId: { type: STRING },
    channelAddress: { type: STRING },
    conversationId: { type: STRING },
  },
  required: ['role', 'channelAddress'],
};

/** Mirrors the pydantic inputs in services/tools/customers (T-42). */
export const CUSTOMERS_TOOLS: agentcore.ToolDefinition[] = [
  {
    name: 'identify_contact',
    description:
      'Returns who the caller is and their venues. For an unregistered caller, pass the venue name and the customer code (or VAT number) they gave you; never guess them. Status: KNOWN, MATCHED, NOT_FOUND or IDENTIFICATION_FAILED. For a customer contact, `privacy` says whether the privacy notice was sent and the answer on proactive messages (null = never asked).',
    inputSchema: {
      type: OBJECT,
      properties: {
        customerCode: {
          type: STRING,
          description: 'Customer code from invoices or delivery notes.',
        },
        vatNumber: { type: STRING, description: 'VAT number, if no customer code.' },
        venueName: { type: STRING, description: 'Venue name as given by the user.' },
        language: { type: STRING, description: 'Language of the conversation: it or en.' },
        privacyNoticeSent: {
          type: BOOLEAN,
          description:
            'True if you already sent the privacy notice to this unregistered caller in this conversation.',
        },
        caller: CALLER,
      },
      required: ['caller'],
    },
  },
  {
    name: 'get_customer_profile',
    description:
      "Returns a venue's profile: delivery days, last orders and, for sales reps, insights. Only for the caller's own venues (or portfolio).",
    inputSchema: {
      type: OBJECT,
      properties: {
        customerId: { type: STRING, description: 'customerId of one of the caller venues.' },
        caller: CALLER,
      },
      required: ['customerId', 'caller'],
    },
  },
  {
    name: 'update_privacy',
    description:
      "Records, for the caller's own contact, that the privacy notice was sent (noticeSent) and/or their answer on reminders and suggestions (proactiveConsent: true or false; false also revokes). Customer contacts only. Returns status UPDATED and the privacy state.",
    inputSchema: {
      type: OBJECT,
      properties: {
        noticeSent: {
          type: BOOLEAN,
          description: 'True once you have sent the privacy notice in your reply.',
        },
        proactiveConsent: {
          type: BOOLEAN,
          description:
            "The user's clear answer: true to receive reminders and suggestions, false not to.",
        },
        caller: CALLER,
      },
      required: ['caller'],
    },
  },
  {
    name: 'set_order_email',
    description:
      'Saves the email address the caller gave you for their order confirmation emails (with the PDF); it replaces the previous one. Customer contacts only, their own contact. Returns status UPDATED and the saved orderEmail, or INVALID_INPUT if it is not a valid address.',
    inputSchema: {
      type: OBJECT,
      properties: {
        email: { type: STRING, description: 'The email address exactly as the user wrote it.' },
        caller: CALLER,
      },
      required: ['email', 'caller'],
    },
  },
];

/** Mirrors the pydantic input in services/tools/order_intake (T-43). */
export const ORDER_INTAKE_TOOLS: agentcore.ToolDefinition[] = [
  {
    name: 'extract_order_lines',
    description:
      'Reads an order and returns its raw lines (text as written, quantity, unit, how sure the reading is). Pass the s3Uri of a photo or voice message of the conversation, or the text of the order. Statuses: OK, NOT_AN_ORDER, UNREADABLE_MEDIA (ask for a new photo, or for the order in writing). Does not match products.',
    inputSchema: {
      type: OBJECT,
      properties: {
        s3Uri: {
          type: STRING,
          description: 'Exactly as given for the attachment (photo or voice message).',
        },
        text: {
          type: STRING,
          description: 'Order written in the chat or email, if no attachment.',
        },
        caller: CALLER,
      },
      required: ['caller'],
    },
  },
];

/** Mirrors the pydantic inputs in services/tools/catalog (T-44). */
export const CATALOG_TOOLS: agentcore.ToolDefinition[] = [
  {
    name: 'match_products',
    description:
      "Matches one raw order line to catalog products, using the customer's order history. Returns status MATCHED (order it), AMBIGUOUS (ask the customer, at most the 3 candidates given, the first is the one they buy most) or UNMATCHED (ask for a better description or a photo), with the candidates and their confidence. A discontinued candidate carries its official substitutes. Call once per line.",
    inputSchema: {
      type: OBJECT,
      properties: {
        rawText: {
          type: STRING,
          description:
            'The line as written ("il solito mozzarella" is understood). The catalog is in Italian: a line in another language goes in with the product words translated to Italian ("still water" -> "acqua naturale"), brands, sizes and quantities unchanged.',
        },
        customerId: { type: STRING, description: 'customerId of the venue the order is for.' },
        rawUnit: { type: STRING, description: 'The unit as written (cs, ct, kg, pz, lt), if any.' },
        caller: CALLER,
      },
      required: ['rawText', 'customerId', 'caller'],
    },
  },
  {
    name: 'search_catalog',
    description:
      'Searches the catalog by description (not by order line). Returns up to 5 active products with sku, name, brand, category, format and unit. Use it to answer "do you have X" and to suggest alternatives.',
    inputSchema: {
      type: OBJECT,
      properties: {
        query: { type: STRING, description: 'What the user is looking for.' },
        category: { type: STRING, description: 'Optional product category to restrict to.' },
        caller: CALLER,
      },
      required: ['query', 'caller'],
    },
  },
  {
    name: 'ask_product_sheets',
    description:
      'Searches the technical sheets of the products (allergens, ingredients, storage, shelf life, nutrition, use). Returns FOUND with passages, each with the sku and the sheet name to cite, or NOT_FOUND when the sheets do not say it. Never answer such questions from memory.',
    inputSchema: {
      type: OBJECT,
      properties: {
        question: {
          type: STRING,
          description: "The full question, in the user's words (not just a keyword).",
        },
        sku: {
          type: STRING,
          description: 'SKU of the product, if known (from match_products or search_catalog).',
        },
        caller: CALLER,
      },
      required: ['question', 'caller'],
    },
  },
];

/** Mirrors the pydantic inputs in services/tools/inventory_pricing (T-45). */
export const INVENTORY_PRICING_TOOLS: agentcore.ToolDefinition[] = [
  {
    name: 'check_availability',
    description:
      'Checks stock for order lines on a delivery date. Per line: status AVAILABLE, PARTIAL (availableQuantity), OUT_OF_STOCK (nextArrival), DISCONTINUED or UNKNOWN_SKU; roundedQuantity when the quantity is not a multiple of the pack (offer it, never apply it silently); substitutes that are available. Never states exact stock to customers.',
    inputSchema: {
      type: OBJECT,
      properties: {
        lines: {
          type: ARRAY,
          description: 'Lines to check.',
          items: {
            type: OBJECT,
            properties: {
              sku: { type: STRING, description: 'SKU from match_products or search_catalog.' },
              quantity: { type: NUMBER, description: 'Quantity in the product unit.' },
            },
            required: ['sku', 'quantity'],
          },
        },
        deliveryDate: { type: STRING, description: 'Delivery date, YYYY-MM-DD.' },
        caller: CALLER,
      },
      required: ['lines', 'deliveryDate', 'caller'],
    },
  },
  {
    name: 'get_prices',
    description:
      "Prices of products for a venue, from the venue's price list, with the promotion valid today if any. Per SKU: unitPrice, promo, finalPrice (EUR, VAT excluded) or status NO_PRICE. Never quote a price that does not come from here.",
    inputSchema: {
      type: OBJECT,
      properties: {
        customerId: { type: STRING, description: 'customerId of the venue.' },
        skus: { type: ARRAY, description: 'SKUs to price.', items: { type: STRING } },
        caller: CALLER,
      },
      required: ['customerId', 'skus', 'caller'],
    },
  },
  {
    name: 'get_delivery_options',
    description:
      'Delivery dates for a venue: nextDeliveryDate and the next options (served days, closures), the cut-off, whether it is already past (afterCutoff, with the missedDeliveryDate the customer would have had) and the minimum order value. With requestedDate, requestedDateServed says if that day works.',
    inputSchema: {
      type: OBJECT,
      properties: {
        customerId: { type: STRING, description: 'customerId of the venue.' },
        requestedDate: {
          type: STRING,
          description: 'Delivery date the customer asked for, YYYY-MM-DD.',
        },
        caller: CALLER,
      },
      required: ['customerId', 'caller'],
    },
  },
];

const LINE_FIELDS: Record<string, agentcore.SchemaDefinition> = {
  rawText: { type: STRING, description: 'The line as the customer wrote it.' },
  rawUnit: { type: STRING, description: 'The unit as written, if any.' },
  sku: { type: STRING, description: 'SKU chosen with match_products. Never invent one.' },
  quantity: { type: NUMBER, description: 'Quantity in the unit of the product.' },
  status: {
    type: STRING,
    description:
      'Only to say AMBIGUOUS, UNMATCHED or OUT_OF_STOCK (still to resolve), SUBSTITUTED (the customer accepted a substitute) or ADJUSTED (accepted the rounding to the pack). Default: MATCHED with sku and quantity.',
  },
  candidates: {
    type: ARRAY,
    description: 'For an AMBIGUOUS line: up to 3 SKUs offered to the customer.',
    items: { type: STRING },
  },
  note: { type: STRING, description: 'A note on the line, if the customer gave one.' },
};

/** Mirrors the pydantic inputs in services/tools/orders (T-46). */
export const ORDERS_TOOLS: agentcore.ToolDefinition[] = [
  {
    name: 'create_order_draft',
    description:
      'Creates the draft order of the conversation for a venue, with the lines read and matched so far (also the ones still to clarify). Names, prices and the total are computed by the system. If the conversation already has an open draft it is returned unchanged (existing: true): change it with update_order_draft. Status DRAFT, or NEEDS_CLARIFICATION while some line is unresolved.',
    inputSchema: {
      type: OBJECT,
      properties: {
        customerId: { type: STRING, description: 'customerId of the venue the order is for.' },
        lines: {
          type: ARRAY,
          description: 'Order lines.',
          items: { type: OBJECT, properties: LINE_FIELDS },
        },
        source: {
          type: STRING,
          description: 'How the order arrived: photo, voice, text or email.',
        },
        deliveryDate: { type: STRING, description: 'Agreed delivery date, YYYY-MM-DD.' },
        deliveryNotes: { type: STRING, description: 'Delivery notes from the customer.' },
        caller: CALLER,
      },
      required: ['customerId', 'lines', 'caller'],
    },
  },
  {
    name: 'update_order_draft',
    description:
      'Changes an order: ops add, update or remove lines (update changes only the fields given; set status SUBSTITUTED or ADJUSTED when the customer accepted a substitute or a rounding) and sets the delivery date and notes. Editing a summary waiting for confirmation puts it back to draft. A confirmed order can still be changed until the cut-off (status UPDATED); after it you get ORDER_LOCKED: hand over to the back office. NEEDS_FIXES lists what is wrong and saves nothing.',
    inputSchema: {
      type: OBJECT,
      properties: {
        orderId: { type: STRING, description: 'orderId of the order.' },
        ops: {
          type: ARRAY,
          description: 'Line changes.',
          items: {
            type: OBJECT,
            properties: {
              op: { type: STRING, description: 'add, update or remove.' },
              lineId: { type: STRING, description: 'Line to update or remove (l1, l2...).' },
              ...LINE_FIELDS,
            },
            required: ['op'],
          },
        },
        deliveryDate: { type: STRING, description: 'New delivery date, YYYY-MM-DD.' },
        deliveryNotes: { type: STRING, description: 'Delivery notes.' },
        caller: CALLER,
      },
      required: ['orderId', 'caller'],
    },
  },
  {
    name: 'request_order_confirmation',
    description:
      'Call when the order is complete, before asking the customer to confirm. Checks it (unresolved lines, packs, delivery date and cut-off, minimum) and returns either NEEDS_FIXES with the issues, or status PENDING_CONFIRMATION with the summary to show: lines, prices, total, delivery date, notes, and orderEmail: where the confirmation email will go (null = no address on record). Without this call the order cannot be confirmed. Not needed after changing a confirmed order: it answers NOT_CONFIRMABLE with reason ALREADY_CONFIRMED (the change is already saved).',
    inputSchema: {
      type: OBJECT,
      properties: {
        orderId: { type: STRING, description: 'orderId of the order.' },
        caller: CALLER,
      },
      required: ['orderId', 'caller'],
    },
  },
  {
    name: 'confirm_order',
    description:
      'Confirms the order ONLY after the customer explicitly said so (tap on Confirm or an unambiguous yes) in answer to the summary. Idempotent: a repeat answers ALREADY_CONFIRMED. NOT_CONFIRMABLE means no summary was shown yet (draft) or the order expired or was cancelled. Returns the confirmed order.',
    inputSchema: {
      type: OBJECT,
      properties: {
        orderId: { type: STRING, description: 'orderId of the order.' },
        interactiveReply: {
          type: OBJECT,
          description: 'Only when the answer is a button tap: the contextId of the message.',
          properties: { contextId: { type: STRING } },
          required: ['contextId'],
        },
        caller: CALLER,
      },
      required: ['orderId', 'caller'],
    },
  },
  {
    name: 'cancel_order',
    description:
      'Cancels an order at the customer request: freely until confirmation, until the cut-off after it; later ORDER_LOCKED (hand over to the back office).',
    inputSchema: {
      type: OBJECT,
      properties: {
        orderId: { type: STRING, description: 'orderId of the order.' },
        caller: CALLER,
      },
      required: ['orderId', 'caller'],
    },
  },
  {
    name: 'get_order_status',
    description:
      'Status, delivery date and window of orders. Pass the customerId for the latest orders of a venue (newest first), or the orderId for one order, never both.',
    inputSchema: {
      type: OBJECT,
      properties: {
        customerId: { type: STRING, description: 'customerId of the venue.' },
        orderId: { type: STRING, description: 'orderId of one order.' },
        caller: CALLER,
      },
      required: ['caller'],
    },
  },
  {
    name: 'report_delivery_issue',
    description:
      'Records a delivery problem for an order that is out for delivery or delivered, with the lines involved and photos (s3Uri exactly as given). Type: MISSING, DAMAGED, WRONG or EXPIRED.',
    inputSchema: {
      type: OBJECT,
      properties: {
        orderId: { type: STRING, description: 'orderId of the order.' },
        type: { type: STRING, description: 'MISSING, DAMAGED, WRONG or EXPIRED.' },
        lineIds: {
          type: ARRAY,
          description: 'Lines involved (l1, l2...).',
          items: { type: STRING },
        },
        note: { type: STRING, description: 'What the customer said.' },
        s3Uris: { type: ARRAY, description: 'Photos of the problem.', items: { type: STRING } },
        caller: CALLER,
      },
      required: ['orderId', 'type', 'caller'],
    },
  },
  {
    name: 'handoff_to_human',
    description:
      'Hands this conversation to a person of the distributor: you stop answering until they give it back. Returns HANDED_OFF or ALREADY_HANDED_OFF.',
    inputSchema: {
      type: OBJECT,
      properties: {
        reason: {
          type: STRING,
          description:
            'CUSTOMER_REQUEST, IDENTIFICATION_FAILED, NEW_CUSTOMER, UNRESOLVED_LINES, ORDER_LOCKED, DELIVERY_ISSUE, NEGATIVE_SENTIMENT, LOW_CONFIDENCE or OUT_OF_SCOPE.',
        },
        summary: {
          type: STRING,
          description: 'For the operator: what the user wants, what was done, what is open.',
        },
        caller: CALLER,
      },
      required: ['reason', 'summary', 'caller'],
    },
  },
];

/** Mirrors the pydantic inputs in services/tools/reco (T-50). */
export const RECO_TOOLS: agentcore.ToolDefinition[] = [
  {
    name: 'recommend_products',
    description:
      'Motivated product suggestions from the data. With orderId (only after request_order_confirmation returned PENDING_CONFIRMATION): at most one suggestion per order, only with the customer consent; a second call returns ALREADY_SUGGESTED. With customerId (sales reps only, briefing): up to 3. Each suggestion has sku, name, format, price and reason: REORDER_DUE (everyDays, lastOrderedAt, lastQuantity), DROPPED, SIMILAR_VENUES (note) or PROMOTION (promo). Status OK, or NONE with reason NO_CONSENT, ALREADY_SUGGESTED, SUMMARY_FIRST, ORDER_CLOSED, ORDER_REQUIRED or NOTHING_RELEVANT.',
    inputSchema: {
      type: OBJECT,
      properties: {
        orderId: { type: STRING, description: 'orderId of the open order, exactly as given.' },
        customerId: {
          type: STRING,
          description: 'customerId of the venue, for a sales rep briefing (no order).',
        },
        caller: CALLER,
      },
      required: ['caller'],
    },
  },
  {
    name: 'record_suggestion_outcome',
    description:
      "Records the customer's answer to the suggestion made on an order: accepted true after the product was added with update_order_draft, false if they declined or confirmed without it. A declined product is not proposed again. Status RECORDED, ALREADY_RECORDED or NO_SUGGESTION.",
    inputSchema: {
      type: OBJECT,
      properties: {
        orderId: { type: STRING, description: 'orderId of the order, exactly as given.' },
        accepted: { type: BOOLEAN, description: 'True if the customer took the suggestion.' },
        caller: CALLER,
      },
      required: ['orderId', 'accepted', 'caller'],
    },
  },
];
