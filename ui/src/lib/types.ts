// Response shapes of the Ledger Agent HTTP API (src/ledger_agent/api.py). Amounts named *_minor are paise;
// month facts are whole rupees (as the report module produces them).

export type TxnStatus = "pending" | "categorized" | "needs_review";
export type CategorySource = "rule" | "llm" | "user" | null;

export interface Health { status: string; llm: boolean }

export interface Stats {
  transactions: number;
  by_status: Partial<Record<TxnStatus, number>>;
  categorized_by: Partial<Record<"rule" | "llm" | "user", number>>;
  automation_rate: number;
  review_backlog: number;
  rules: { user: number; compiled: number };
  verified_labels: number;
  llm: { purpose: string; calls: number; i: number | null; o: number | null; cost: number | null; hits: number | null;
         errors: number | null; ms: number | null }[];
  recent_runs: { id: string; status: string; stats_json: string; started_at: string; finished_at: string | null }[];
}

export interface MonthFacts {
  month: string;
  income: number;
  expenses: number;
  net_savings: number;
  savings_rate_pct: number | null;
  top_categories: { category: string; amount: number; share_pct: number }[];
  top_merchants: { merchant: string; amount: number; count: number }[];
  big_changes_vs_last_month: { category: string; this_month: number; last_month: number; change_pct: number }[];
  subscriptions: { merchant: string; cadence: string; amount: number; price_change_pct: number }[];
  unreviewed_transactions: number;
}

export interface TrendPoint { month: string; money_in: number; money_out: number; unreviewed: number }

export interface Account { id: number; name: string; currency: string; transactions: number }

export interface ReviewItem {
  id: number;
  date: string;
  amount_minor: number;
  merchant: string;
  description: string;
  suggestion: string | null;
  confidence: number | null;
  review_reason: string | null;
  llm_reason: string | null;
  merchant_rows?: number;
}

export interface CorrectionResult {
  transaction_id: number;
  category: string;
  rule_created: number | null;
  rules_invalidated: number;
  propagated: number;
  siblings_flagged: number;
}

export interface ImportResult {
  import_id: number;
  account: string;
  profile_name: string;
  rows_total: number;
  rows_new: number;
  rows_duplicate: number;
  rows_rejected: number;
  balance_check: "ok" | "mismatch" | "no_balance_column";
  balance_mismatches: number;
  rejects: [number, string][];
}

export interface RunStats {
  processed: number; by_rule: number; by_llm: number; to_review: number; suspicious: number;
  llm_errors: number; direction_flags: number; batches: number;
}
export interface ProcessResult { run_id: string; status: string; tokens: number; stats: RunStats }

export interface Txn {
  id: number;
  date: string;
  amount_minor: number;
  merchant: string;
  description: string;
  category: string | null;
  category_source: CategorySource;
  confidence: number | null;
  status: TxnStatus;
  review_reason: string | null;
  account: string;
}
export interface TxnPage { total: number; items: Txn[] }
export interface TxnQuery { q?: string; category?: string; status?: string; month?: string; limit?: number; offset?: number }

export interface ToolCallLog { name: string; args: Record<string, unknown>; error: boolean }
export interface ChatAnswer {
  answer: string; conversation_id: string; stop: string; turns: number; tool_calls: ToolCallLog[]; tokens: number;
}
export interface Turn { question: string; answer: string; created_at: string }

export interface Narrative { headline: string; highlights: string[]; watch_outs: string[]; suggestions: string[] }
export interface Report {
  month: string; facts: MonthFacts; narrative: Narrative | null; attempts: number; removed_sentences: string[];
  markdown: string;
}

export interface Recurring {
  merchant: string; category: string; cadence: string; occurrences: number; typical_amount_minor: number;
  last_amount_minor: number; last_date: string; next_expected: string; monthly_cost_minor: number;
  price_change_pct: number;
}

export interface Rule {
  id: number; pattern_type: "merchant" | "contains" | "regex"; pattern: string; direction: "debit" | "credit" | null;
  category: string; source: "user" | "compiled"; priority: number; hits: number; active: number; created_at: string;
}
export interface NewRule { pattern_type: Rule["pattern_type"]; pattern: string; category: string; direction: Rule["direction"] }

export interface MemoryBlock { label: string; description: string; value: string; char_limit: number }
export interface MemoryFact { id: number; text: string; importance: number; created_at: string; last_accessed: string }
