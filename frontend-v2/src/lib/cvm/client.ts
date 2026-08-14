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

/** Turns a failed Response into the ApiError the console renders. */
async function errorFrom(response: Response): Promise<ApiError> {
  const payload = await response.json().catch(() => null);
  const { message, code } = messageFrom(
    payload,
    `${response.status} ${response.statusText}`,
  );
  return new ApiError(message, response.status, code);
}

/** The ApiError for a request that never reached the server. */
function unreachable(): ApiError {
  return new ApiError(
    "Could not reach the CVM API. Is `caspar serve` running?",
    0,
    "unreachable",
  );
}

/**
 * A write action.
 *
 * Long-running work (builds, plugin installs) answers 202 with a `job_id`
 * rather than blocking, so this resolves as soon as the job is ACCEPTED — not
 * when it finishes. Callers poll `useJob`. A 202 is a success here for exactly
 * that reason: treating it as anything else would make every build look failed.
 */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw unreachable();
  }

  if (!response.ok) throw await errorFrom(response);
  // 204 carries no body; parsing it would throw on valid success.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * A multipart upload.
 *
 * `Content-Type` is deliberately NOT set: the browser has to append the
 * multipart boundary itself, and naming the type here would produce a header
 * without one, which the server cannot parse.
 */
export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
      body: form,
    });
  } catch {
    throw unreachable();
  }

  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

/**
 * A DELETE.
 *
 * Assessments accumulate — every scan is stored — so without this the database
 * grows without bound and the console offers no way to prune it.
 */
export async function apiDelete<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "DELETE",
      headers: {
        Accept: "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
    });
  } catch {
    throw unreachable();
  }

  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return undefined as T;
  return (await response.json().catch(() => undefined)) as T;
}

/**
 * A POST whose response is a file rather than JSON.
 *
 * Report generation streams bytes back, so it cannot go through `apiPost`.
 * It still belongs here: an unreachable server and a 500 must look the same
 * to the console whether the reply was going to be JSON or a PDF.
 */
export async function apiPostBlob(path: string, body?: unknown): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw unreachable();
  }

  if (!response.ok) throw await errorFrom(response);
  return await response.blob();
}

export type QueryParams = Record<
  string,
  string | number | boolean | null | undefined
>;

/** Shared by `apiGet` and `apiGetPaged` so the two build the same URL. */
function buildUrl(path: string, params?: QueryParams): URL {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    // null/undefined mean "filter not applied". Serialising them would send
    // the literal string "undefined" and get a 400 back.
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

async function getResponse(url: URL): Promise<Response> {
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
    throw unreachable();
  }

  if (!response.ok) throw await errorFrom(response);
  return response;
}

export async function apiGet<T>(path: string, params?: QueryParams): Promise<T> {
  const response = await getResponse(buildUrl(path, params));
  return (await response.json()) as T;
}

/** An array response plus how many rows exist beyond the requested window. */
export interface Paged<T> {
  items: T[];
  total: number;
}

/**
 * A GET over an endpoint that answers with a bare array and reports the full
 * count in `X-Total-Count`.
 *
 * A pager cannot work from the array alone: a page that comes back full is
 * indistinguishable from the last page, so "Next" would either stop one page
 * early or offer a page that turns out to be empty. The header carries the
 * total without changing the body shape that the v1 console and the
 * CLI-parity tests already consume.
 *
 * Readable without CORS configuration because the console is served from the
 * same origin as the API — see the note at the top of this file. When the
 * header is absent (an older server), the page length stands in for the total,
 * which degrades to "no pager" rather than to a broken one.
 */
export async function apiGetPaged<T>(
  path: string,
  params?: QueryParams,
): Promise<Paged<T>> {
  const response = await getResponse(buildUrl(path, params));
  const items = (await response.json()) as T[];
  const header = response.headers.get("X-Total-Count");
  const parsed = header === null ? Number.NaN : Number(header);
  return {
    items,
    total: Number.isFinite(parsed) ? parsed : items.length,
  };
}
