export type Role = "owner" | "admin" | "member" | "viewer";
export type AssignableRole = Exclude<Role, "owner">;
export interface User {
  id: string;
  username: string;
}
export interface Workspace {
  id: string;
  name: string;
  slug: string;
  role: Role;
  owner_user_id: string;
  created_at: string;
}
export interface Member extends User {
  role: Role;
}
export interface Invitation {
  id: string;
  workspace_id: string;
  workspace_name: string;
  username: string;
  role: AssignableRole;
  status: string;
  expires_at: string;
}
export interface AuditEvent {
  id: string;
  action: string;
  created_at: string;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
    signal: init.signal ?? AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    let message = "The request could not be completed.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (response.status === 422)
        message = "Check the form values and try again.";
    } catch {
      /* Keep the generic error for non-JSON responses. */
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const json = (method: string, body?: object): RequestInit => ({
  method,
  ...(body ? { body: JSON.stringify(body) } : {}),
});
export const pagePath = (path: string, cursor: string | null) =>
  `${path}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`;
export const messageFor = (error: unknown) =>
  error instanceof ApiError
    ? error.message
    : "Unable to connect. Please try again.";
