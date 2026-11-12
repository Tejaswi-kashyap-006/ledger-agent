import { vi } from "vitest";
import { ApiError, api, setToken } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(body === undefined ? null : JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("sends the bearer token when one is stored", async () => {
    setToken("s3cret");
    const fetch = mockFetch(200, { status: "ok", llm: false });
    await api.health();
    const init = fetch.mock.calls[0]![1]!;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer s3cret");
  });

  it("omits Authorization when no token is set", async () => {
    const fetch = mockFetch(200, []);
    await api.months();
    expect(fetch.mock.calls[0]![1]!.headers).not.toHaveProperty("Authorization");
  });

  it("surfaces the server's detail message as an ApiError", async () => {
    mockFetch(422, { detail: "unknown category 'Crypto'" });
    await expect(api.setCategory(1, "Crypto")).rejects.toMatchObject({ status: 422, message: "unknown category 'Crypto'" });
  });

  it("handles 204 No Content", async () => {
    mockFetch(204, undefined);
    await expect(api.deleteRule(3)).resolves.toBeUndefined();
  });

  it("explains a network failure in plain words", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await api.stats().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toContain("ledger serve");
  });

  it("encodes query parameters and skips empty ones", async () => {
    const fetch = mockFetch(200, { total: 0, items: [] });
    await api.transactions({ q: "swiggy & co", month: "", limit: 40, offset: 0 });
    expect(fetch.mock.calls[0]![0]).toBe("/v1/transactions?q=swiggy+%26+co&limit=40&offset=0");
  });

  it("posts imports as multipart form data", async () => {
    const fetch = mockFetch(200, { rows_new: 1 });
    await api.importFile("HDFC Savings", new File(["a,b"], "june.csv"));
    const body = fetch.mock.calls[0]![1]!.body as FormData;
    expect(body.get("account")).toBe("HDFC Savings");
    expect((body.get("file") as File).name).toBe("june.csv");
  });
});
