export class ApiError extends Error {
  constructor(status, detail) {
    super(
      typeof detail === "string"
        ? detail
        : "Please correct the highlighted fields.",
    );
    this.status = status;
    this.fields = typeof detail === "object" ? detail : {};
  }
}
export async function api(path, options = {}) {
  const csrf = document.cookie
    .split("; ")
    .find((c) => c.startsWith("csrftoken="))
    ?.split("=")[1];
  const isForm = options.body instanceof FormData;
  let response;
  try {
    response = await fetch(`/api/${path}`, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body && !isForm
          ? { "Content-Type": "application/json" }
          : {}),
        ...(csrf ? { "X-CSRFToken": decodeURIComponent(csrf) } : {}),
        ...options.headers,
      },
      body:
        options.body && !isForm ? JSON.stringify(options.body) : options.body,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(
      0,
      options.method
        ? "Connection interrupted. Check the current record before repeating this action."
        : "Unable to connect. Check your connection and try again.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== "login/")
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(
      response.status,
      data.error ||
        (response.status === 403
          ? "Your session or permissions changed. Reload the page and sign in again."
          : "This action could not be completed. Please try again."),
    );
  }
  return data;
}
export const labels = {
  submitted: "Submitted",
  in_progress: "In progress",
  delivered: "Ready for review",
  accepted: "Accepted",
  rejected: "Needs rework",
};
export const formatDate = (value) =>
  new Date(
    value.length === 10 ? `${value}T12:00:00+02:00` : value,
  ).toLocaleString("en-GB", {
    timeZone: "Africa/Kigali",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
