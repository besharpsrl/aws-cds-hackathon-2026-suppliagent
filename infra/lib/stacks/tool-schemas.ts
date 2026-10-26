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
