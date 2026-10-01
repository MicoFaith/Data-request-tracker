import React from "react";
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NotificationBell, Notifications } from "./notifications";
import { api } from "./api";

vi.mock("./api", async (original) => ({ ...(await original()), api: vi.fn() }));
afterEach(() => vi.resetAllMocks());
const inbox = {
  notifications: [
    {
      id: 7,
      title: "Request #4: delivered",
      message: "Ready to review.",
      created_at: "2026-10-01T08:00:00Z",
      read: false,
      href: "/requests/4/",
      email_state: "off",
    },
  ],
  unread_count: 1,
  total: 1,
  page: 1,
  page_size: 50,
  has_next: false,
};
function setup(component = <Notifications />, available = false) {
  api.mockImplementation(async (path) =>
    path === "notifications/preferences/"
      ? {
          email: "person@example.com",
          email_notifications: false,
          email_available: available,
        }
      : inbox,
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{component}</MemoryRouter>
    </QueryClientProvider>,
  );
}
it("shows an accessible unread badge and inbox link", async () => {
  setup(<NotificationBell />);
  expect(
    await screen.findByRole("link", { name: "Notifications, 1 unread" }),
  ).toHaveAttribute("href", "/notifications/");
});
it("marks one notification as read without affecting navigation", async () => {
  setup();
  expect(
    await screen.findByRole("link", { name: "Request #4: delivered" }),
  ).toHaveAttribute("href", "/requests/4/");
  await userEvent.click(
    screen.getByRole("button", { name: "Mark Request #4: delivered as read" }),
  );
  expect(api).toHaveBeenCalledWith("notifications/", {
    method: "POST",
    body: { id: 7 },
  });
  expect(
    await screen.findByText("Notifications marked as read."),
  ).toBeInTheDocument();
});
it("marks all as read and filters unread updates", async () => {
  setup();
  await screen.findByText("1 unread updates");
  await userEvent.click(
    screen.getByRole("button", { name: "Mark all as read" }),
  );
  expect(api).toHaveBeenCalledWith("notifications/", {
    method: "POST",
    body: { all: true },
  });
  await userEvent.click(screen.getByLabelText("Unread only"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("notifications/?unread=true"),
  );
});
it("explains unavailable email and disables opt in", async () => {
  setup();
  expect(
    await screen.findByText(/Email delivery is not available/),
  ).toBeInTheDocument();
  expect(
    screen.getByLabelText("Send activity alerts to person@example.com"),
  ).toBeDisabled();
});
it("saves an explicit email opt in as a boolean", async () => {
  setup(<Notifications />, true);
  await userEvent.click(
    await screen.findByLabelText("Send activity alerts to person@example.com"),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Save email preference" }),
  );
  expect(api).toHaveBeenCalledWith("notifications/preferences/", {
    method: "PATCH",
    body: { email_notifications: true },
  });
});
it("keeps the inbox visible when marking as read fails", async () => {
  setup();
  await screen.findByText("1 unread updates");
  api.mockImplementation(async (path, options) => {
    if (options?.method === "POST") throw new Error("Connection interrupted");
    return inbox;
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Mark all as read" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Connection interrupted",
  );
  expect(
    screen.getByRole("link", { name: "Request #4: delivered" }),
  ).toBeInTheDocument();
});
