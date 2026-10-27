import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';

const { OBJECT, STRING } = agentcore.SchemaDefinitionType;

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
      'Returns who the caller is and their venues. For an unregistered caller, pass the venue name and the customer code (or VAT number) they gave you; never guess them. Status: KNOWN, MATCHED, NOT_FOUND or IDENTIFICATION_FAILED.',
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
          description: 'The line as written ("il solito mozzarella" is understood).',
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
];
