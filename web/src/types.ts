// Shapes returned by accounts-api, payments-api and insights-api. Money is always a fixed-point string.

export interface Me {
  id: number;
  username: string;
  display_name: string;
  title: string;
  role: 'initiator' | 'approver' | string;
  email: string;
  company: { id: number; name: string };
}

export interface Account {
  id: number;
  name: string;
  kind: string;
  iban: string;
  currency: string;
  balance: string;
  updated_at: string;
}

export interface Transaction {
  id: number;
  booked_at: string;
  value_date: string;
  amount: string;
  balance_after: string;
  category: string;
  counterparty: string | null;
  description: string | null;
  payment_id: number | null;
}

export interface Anomaly {
  id: number;
  payment_id: number | null;
  occurred_at: string;
  counterparty: string;
  amount: string;
  score: string;
  reason: string;
}

export interface Dashboard {
  company: { id: number; name: string };
  currency: string;
  as_of: string | null;
  total_cash: string | null;
  available: string | null;
  scheduled_out_7d: string | null;
  forecast_low: string | null;
  payroll_due: { date: string; amount: string } | null;
  refreshed_at: string | null;
  /** non_reserve: every account except Reserve, the basis the forecast projects. */
  trend: { date: string; total_cash: string; available: string; non_reserve: string }[];
  anomalies: Anomaly[];
  operational: { total_cash: string; available: string; accounts: Account[] };
}

/** insights-api GET /forecast: the latest batch scoring of the registered cash_forecast model. */
export interface Forecast {
  company: { id: number; name: string };
  currency: string;
  model: { name: string; version: string } | null;
  generated_at: string | null;
  points: { date: string; predicted: string; lower: string; upper: string }[];
}

export type PaymentStatus = 'AWAITING_APPROVAL' | 'EXECUTED' | 'REJECTED';

export interface Payment {
  id: number;
  status: PaymentStatus;
  amount: string;
  currency: string;
  value_date: string | null;
  reference: string | null;
  from_account: { id: number; name: string };
  to_account: { id: number; name: string } | null;
  beneficiary: { id: number; name: string } | null;
  created_by: { id: number; name: string };
  created_at: string | null;
  decided_by: { id: number; name: string } | null;
  decided_at: string | null;
  executed_at: string | null;
  awaiting_approval_from: string[];
  anomaly: { score: string; reason: string } | null;
}

export interface Beneficiary {
  id: number;
  name: string;
  iban: string;
  category: string;
}

export type PipelineStage = 'ledger' | 'event_hubs' | 'bronze' | 'silver' | 'gold' | 'serving';

/** accounts-api GET /pipeline/trace/{payment_id}: the stages reached, in order. */
export interface PipelineTrace {
  payment_id: number;
  status: PaymentStatus;
  stages: { stage: PipelineStage; at: string }[];
  last_batch_at: string | null;
  next_batch_at: string | null;
}
