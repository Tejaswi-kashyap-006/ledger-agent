// Typed client for the Ledger Agent API. Same origin in production (FastAPI serves the UI);
// proxied by Vite in development. The optional bearer token lives in localStorage (per browser).
import type {
  Account, Bill, BillRow, ChatAnswer, CorrectionResult, Health, ImportResult, MemoryBlock, MemoryFact, MonthFacts, NewRule,
  ProcessResult, Recurring, Report, ReviewItem, Rule, Stats, TrendPoint, Turn, TxnPage, TxnQuery,
} from "./types";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

const TOKEN_KEY = "ledger.apiToken";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): the token simply won't persist */
  }
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...authHeaders() };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "Can't reach the ledger server. Is `ledger serve` running?");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : null;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? "The request was not valid." : res.statusText;
    throw new ApiError(res.status, message || `Request failed (${res.status})`);
  }
  return data as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

/** A stored bill's photo or PDF, fetched with the bearer token (an <img src> can't send one). */
async function fetchFile(path: string): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch(path, { headers: authHeaders() });
  } catch {
    throw new ApiError(0, "Can't reach the ledger server. Is `ledger serve` running?");
  }
  if (!res.ok) throw new ApiError(res.status, res.statusText || `Request failed (${res.status})`);
  return res.blob();
}

export const api = {
  health: () => request<Health>("GET", "/healthz"),
  stats: () => request<Stats>("GET", "/v1/stats"),
  months: () => request<string[]>("GET", "/v1/months"),
  accounts: () => request<Account[]>("GET", "/v1/accounts"),
  categories: () => request<string[]>("GET", "/v1/categories"),
  trend: () => request<TrendPoint[]>("GET", "/v1/trend"),
  facts: (month: string) => request<MonthFacts>("GET", `/v1/facts/${encodeURIComponent(month)}`),

  review: (limit = 50) => request<ReviewItem[]>("GET", `/v1/review${qs({ limit })}`),
  audit: (n = 5) => request<ReviewItem[]>("GET", `/v1/audit${qs({ n })}`),
  setCategory: (id: number, category: string) =>
    request<CorrectionResult>("POST", `/v1/transactions/${id}/category`, { category }),
  accept: (id: number) => request<CorrectionResult>("POST", `/v1/transactions/${id}/accept`),

  transactions: (q: TxnQuery) => request<TxnPage>("GET", `/v1/transactions${qs({ ...q })}`),

  importFile: (account: string, file: File, password?: string) => {
    const form = new FormData();
    form.set("account", account);
    form.set("file", file, file.name);
    if (password) form.set("password", password);       // opens a locked PDF; the server never stores it
    return request<ImportResult>("POST", "/v1/imports", form);
  },
  process: () => request<ProcessResult>("POST", "/v1/process"),

  addBill: (file: File) => {
    const form = new FormData();
    form.set("file", file, file.name);
    return request<Bill>("POST", "/v1/receipts", form);
  },
  bills: () => request<BillRow[]>("GET", "/v1/receipts"),
  bill: (id: number) => request<Bill>("GET", `/v1/receipts/${id}`),
  billFile: (id: number) => fetchFile(`/v1/receipts/${id}/file`),
  pinBill: (id: number, transaction_id: number | null) =>
    request<Bill>("POST", `/v1/receipts/${id}/attach`, { transaction_id }),
  deleteBill: (id: number) => request<void>("DELETE", `/v1/receipts/${id}`),

  chat: (message: string, conversation_id?: string) =>
    request<ChatAnswer>("POST", "/v1/chat", { message, conversation_id }),
  conversation: (id: string) => request<Turn[]>("GET", `/v1/conversations/${encodeURIComponent(id)}`),

  report: (month: string) => request<Report>("GET", `/v1/reports/${encodeURIComponent(month)}`),
  subscriptions: () => request<Recurring[]>("GET", "/v1/subscriptions"),

  rules: () => request<Rule[]>("GET", "/v1/rules"),
  addRule: (rule: NewRule) => request<{ id: number }>("POST", "/v1/rules", rule),
  deleteRule: (id: number) => request<void>("DELETE", `/v1/rules/${id}`),

  memoryBlocks: () => request<MemoryBlock[]>("GET", "/v1/memory/blocks"),
  putMemoryBlock: (label: string, value: string) =>
    request<MemoryBlock>("PUT", `/v1/memory/blocks/${encodeURIComponent(label)}`, { value }),
  memoryFacts: () => request<MemoryFact[]>("GET", "/v1/memory/facts"),
  forgetFact: (id: number) => request<void>("DELETE", `/v1/memory/facts/${id}`),
};

export type Api = typeof api;
