/**
 * src/lib/cvm/client.ts
 * ---------------------
 * The single point where the console talks to the CVM API.
 *
 * Everything goes through `apiGet` so that error handling, the base path and
 * the API-key header have exactly one definition. A page that builds its own
 * `fetch` would eventually disagree with this one about what an error looks
 * like, and the disagreement would only show up in front of a user.
 *
 * SAME-ORIGIN BY DESIGN. The backend mounts no CORS middleware, deliberately.
 * In production the console is served by `caspar serve` from the same origin as
 * the API; in development Vite proxies /api to the API process (vite.config.ts),
 * which reproduces that arrangement rather than working around it.
 */

/** Set only when the server runs with CASPAR_API_KEY; see api/deps.py. */
const API_KEY: string | undefined = import.meta.env["VITE_CVM_API_KEY"];

export const API_BASE = "/api/v1";

/**
 * An API call that failed.
 *
 * Carries the status so the UI can distinguish "nothing here yet" from "the
 * server is broken" — those need different words in front of a user, and a
 * bare Error would flatten them into the same red box.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** No scan has run yet, as opposed to a genuine failure. */
  get isEmpty(): boolean {
    return this.status === 404;
  }
}

/**
 * The API reports errors as {"error": {code, message, detail}} (contract §9),
 * but FastAPI's own validation failures use a bare {"detail": ...}. Both reach
 * the console, so both are unwrapped here — otherwise a 422 surfaces as
 * "[object Object]".
 */
function messageFrom(payload: unknown, fallback: string): {
  message: string;
  code: string | null;
} {
  if (typeof payload !== "object" || payload === null) {
    return { message: fallback, code: null };
  }
  const body = payload as Record<string, unknown>;

  const detail = body["detail"];
  const wrapped =
    (body["error"] as Record<string, unknown> | undefined) ??
    (typeof detail === "object" && detail !== null
      ? ((detail as Record<string, unknown>)["error"] as
          | Record<string, unknown>
          | undefined)
      : undefined);

  if (wrapped && typeof wrapped["message"] === "string") {
    return {
      message: wrapped["message"],
      code: typeof wrapped["code"] === "string" ? wrapped["code"] : null,
    };
  }
  if (typeof detail === "string") return { message: detail, code: null };
  return { message: fallback, code: null };
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>,
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    // null/undefined mean "filter not applied". Serialising them would send
    // the literal string "undefined" and get a 400 back.
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        Accept: "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
    });
  } catch {
    // fetch only rejects when the request never completed — the server is
    // down, or the browser is offline. Saying so is more useful than the
    // generic "Failed to fetch".
    throw new ApiError(
      "Could not reach the CVM API. Is `caspar serve` running?",
      0,
      "unreachable",
    );
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const { message, code } = messageFrom(
      payload,
      `${response.status} ${response.statusText}`,
    );
    throw new ApiError(message, response.status, code);
  }

  return (await response.json()) as T;
}
