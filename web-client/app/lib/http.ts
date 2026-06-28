import type { HTTPValidationError } from "~/types/common";

type Query = Record<string, string | number | boolean | undefined>;

export class HttpError extends Error {
  constructor(
    public status: number,
    public detail: HTTPValidationError["detail"] | string,
  ) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.name = "HttpError";
  }
}

function url(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined) params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(
  method: string,
  path: string,
  opts: { query?: Query; body?: unknown } = {},
): Promise<T> {
  const res = await fetch(url(path, opts.query), {
    method,
    headers:
      opts.body !== undefined
        ? { "Content-Type": "application/json" }
        : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new HttpError(res.status, data?.detail ?? res.statusText);
  }
  // 204 / empty bodies: callers that expect data won't hit this.
  return res.status === 204 ? (undefined as T) : res.json();
}

export const http = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, { query }),
  post: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>("POST", path, { body, query }),
};
