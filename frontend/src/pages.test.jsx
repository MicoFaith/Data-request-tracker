import React from "react";
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionContext } from "./session";
import { Dashboard, NewRequest, RequestDetail } from "./requests";
import { Users, Analytics } from "./staff";

afterEach(() => vi.restoreAllMocks());
function renderPage(page, role = "client", path = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider
        value={{
          user: { id: 1, name: "Aline", role },
          today: "2026-10-01",
          tomorrow: "2026-10-02",
        }}
      >
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/requests/:id/" element={page} />
            <Route path="*" element={page} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}
const request = {
  id: 10,
  client_name: "Aline",
  task_name: "pick cup",
  deadline: "2026-10-10",
  status: "delivered",
  assigned_count: 2,
  episodes_requested: 2,
};
it("shows client review priorities and request navigation", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => ({
    ok: true,
    json: async () =>
      url.includes("dashboard")
        ? { counts: { total: 1, delivered: 1, in_progress: 0, accepted: 0 } }
        : { requests: [request], page: 1, page_size: 50, total: 1 },
  }));
  renderPage(<Dashboard />);
  expect(
    await screen.findByRole("link", { name: "Review delivery →" }),
  ).toHaveAttribute("href", "/requests/10/");
  expect(
    screen.getByRole("link", { name: /Ready for review 1/ }),
  ).toHaveAttribute("href", "/?status=delivered");
});
it("enforces future date and integer bounds before submitting a request", async () => {
  renderPage(<NewRequest />);
  const deadline = screen.getByLabelText("Delivery deadline"),
    count = screen.getByLabelText("Number of episodes");
  expect(deadline).toHaveAttribute("min", "2026-10-02");
  await userEvent.type(deadline, "2026-10-01");
  expect(deadline).toBeInvalid();
  await userEvent.type(count, "1.5");
  expect(count).toBeInvalid();
});
it("lets a client accept a delivered request and shows the updated state", async () => {
  let status = "delivered";
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url, options) => {
      if (options.method === "POST") {
        status = JSON.parse(options.body).status;
        return {
          ok: true,
          json: async () => ({ request: { ...request, status } }),
        };
      }
      return {
        ok: true,
        json: async () => ({
          request: { ...request, status },
          episodes: [],
          history: [],
        }),
      };
    });
  renderPage(<RequestDetail />, "client", "/requests/10/");
  await userEvent.click(
    await screen.findByRole("button", { name: "Accept delivery" }),
  );
  expect(
    await screen.findByRole("heading", { name: "Delivery accepted" }),
  ).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    "/api/requests/10/status/",
    expect.objectContaining({ method: "POST", body: '{"status":"accepted"}' }),
  );
  expect(
    screen.queryByRole("button", { name: "Accept delivery" }),
  ).not.toBeInTheDocument();
});
it("prevents staff delivery before enough episodes are assigned", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => ({
    ok: true,
    json: async () =>
      url.includes("/episodes/")
        ? { episodes: [], page: 1, page_size: 50, total: 0 }
        : {
            request: { ...request, status: "in_progress", assigned_count: 0 },
            episodes: [],
            history: [],
          },
  }));
  renderPage(<RequestDetail />, "operator", "/requests/10/");
  expect(
    await screen.findByRole("button", { name: "Deliver dataset" }),
  ).toBeDisabled();
  expect(
    screen.getByText("Assign 2 more episodes to deliver."),
  ).toBeInTheDocument();
});
it("protects the current admin account and offers account creation", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => ({
      people: { total: 1, active: 1 },
      users: [
        {
          id: 1,
          name: "Aline",
          email: "a@example.com",
          role: "admin",
          is_active: true,
        },
      ],
      page: 1,
      page_size: 50,
      total: 1,
    }),
  });
  renderPage(<Users />, "admin");
  expect(
    await screen.findByText("Your own admin access is protected."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Create account" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Update access" }),
  ).not.toBeInTheDocument();
});
it("keeps an invalid analytics range editable without sending a request", async () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  renderPage(
    <Analytics />,
    "operator",
    "/analytics/?start=2026-10-10&end=2026-10-01",
  );
  expect(screen.getByRole("alert")).toHaveTextContent("end date on or after");
  expect(screen.getByLabelText("Start date")).toHaveValue("2026-10-10");
  expect(fetch).not.toHaveBeenCalled();
});
