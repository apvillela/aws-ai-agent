import { APIGatewayProxyEvent, APIGatewayProxyResult } from 'aws-lambda';
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';
import { v4 as uuidv4 } from 'uuid';

const sqsClient = new SQSClient({});

const VALID_BUDGET_SIGNALS = ['high', 'medium', 'low', 'unknown'] as const;
type BudgetSignal = (typeof VALID_BUDGET_SIGNALS)[number];

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface LeadPayload {
  company_name: string;
  sector: string;
  company_size: number;
  budget_signal: BudgetSignal;
  contact_email: string;
}

interface ValidationResult {
  valid: boolean;
  errors: string[];
  data?: LeadPayload;
}

function validatePayload(body: unknown): ValidationResult {
  const errors: string[] = [];

  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return { valid: false, errors: ['Request body must be a JSON object'] };
  }

  const data = body as Record<string, unknown>;

  if (!data.company_name || typeof data.company_name !== 'string' || data.company_name.trim() === '') {
    errors.push('company_name is required and must be a non-empty string');
  }

  if (!data.sector || typeof data.sector !== 'string' || data.sector.trim() === '') {
    errors.push('sector is required and must be a non-empty string');
  }

  if (data.company_size === undefined || data.company_size === null) {
    errors.push('company_size is required');
  } else if (
    typeof data.company_size !== 'number' ||
    !Number.isInteger(data.company_size) ||
    data.company_size <= 0
  ) {
    errors.push('company_size must be a positive integer');
  }

  if (!data.budget_signal) {
    errors.push('budget_signal is required');
  } else if (!VALID_BUDGET_SIGNALS.includes(data.budget_signal as BudgetSignal)) {
    errors.push(`budget_signal must be one of: ${VALID_BUDGET_SIGNALS.join(', ')}`);
  }

  if (!data.contact_email || typeof data.contact_email !== 'string') {
    errors.push('contact_email is required');
  } else if (!EMAIL_REGEX.test(data.contact_email)) {
    errors.push('contact_email must be a valid email address');
  }

  if (errors.length > 0) {
    return { valid: false, errors };
  }

  return {
    valid: true,
    errors: [],
    data: {
      company_name: (data.company_name as string).trim(),
      sector: (data.sector as string).trim().toLowerCase(),
      company_size: data.company_size as number,
      budget_signal: data.budget_signal as BudgetSignal,
      contact_email: (data.contact_email as string).toLowerCase().trim(),
    },
  };
}

export const handler = async (event: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> => {
  const requestId = event.requestContext?.requestId ?? 'unknown';
  console.log(JSON.stringify({ requestId, path: event.path, method: event.httpMethod }));

  try {
    let body: unknown;
    try {
      body = JSON.parse(event.body ?? '{}');
    } catch {
      return {
        statusCode: 400,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ error: 'Invalid JSON in request body' }),
      };
    }

    const validation = validatePayload(body);
    if (!validation.valid) {
      return {
        statusCode: 400,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ errors: validation.errors }),
      };
    }

    const lead_id = uuidv4();
    const message = {
      lead_id,
      ...validation.data,
      received_at: new Date().toISOString(),
    };

    const queueUrl = process.env.SQS_QUEUE_URL;
    if (!queueUrl) {
      throw new Error('SQS_QUEUE_URL environment variable is not set');
    }

    await sqsClient.send(
      new SendMessageCommand({
        QueueUrl: queueUrl,
        MessageBody: JSON.stringify(message),
        MessageAttributes: {
          lead_id: {
            DataType: 'String',
            StringValue: lead_id,
          },
        },
      }),
    );

    console.log(JSON.stringify({ requestId, lead_id, action: 'queued' }));

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lead_id,
        message: 'Lead received and queued for enrichment',
      }),
    };
  } catch (error) {
    console.error(JSON.stringify({ requestId, error: String(error) }));
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'Internal server error' }),
    };
  }
};
