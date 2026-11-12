// Categories people reach for most often, offered as 1-9 shortcuts on the review card after the
// model's own suggestion. The full, authoritative list always comes from GET /v1/categories.
export const COMMON_CATEGORIES = [
  "Food:Groceries",
  "Food:Delivery",
  "Food:Dining Out",
  "Transfers:To People",
  "Shopping:Online",
  "Transport:Cab & Auto",
  "Bills:Mobile & Internet",
  "Housing:Rent",
  "Health:Pharmacy",
  "Transfers:Self",
];

export function quickPicks(suggestion: string | null, max = 9): string[] {
  const out: string[] = [];
  for (const c of [suggestion, ...COMMON_CATEGORIES]) if (c && !out.includes(c)) out.push(c);
  return out.slice(0, max);
}
