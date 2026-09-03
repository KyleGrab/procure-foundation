/**
 * Thin fetch wrapper. Access token lives in memory (React state / context), never localStorage -
 * a stolen XSS payload reading localStorage is a bigger blast radius than one reading in-memory
 * state, and refresh tokens are httpOnly cookies set by the backend, not touched by JS at all.
 */
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export interface ApiError {
  error: { code: string; message: string; details: unknown[]; request_id: string };
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { accessToken?: string } = {}
): Promise<T> {
  const { accessToken, ...rest } = options;
  const res = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...rest.headers,
    },
  });

  if (!res.ok) {
    const body = (await res.json()) as ApiError;
    throw new Error(body.error?.message ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}
