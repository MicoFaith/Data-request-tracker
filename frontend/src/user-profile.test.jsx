import React from "react";
import { it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UserProfile } from "./user-profile";
const person = {
  id: 2,
  name: "Aline",
  email: "aline@example.com",
  organisation: "Acme",
  role: "client",
  is_active: true,
};
afterEach(() => vi.restoreAllMocks());
it("updates the full profile while protecting own admin access", async () => {
  const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ ok: true, json: async () => ({}) }),
    onChange = vi.fn();
  render(<UserProfile person={person} isSelf onChange={onChange} />);
  const input = screen.getByLabelText("Full name for aline@example.com");
  await userEvent.clear(input);
  await userEvent.type(input, "Aline Uwase");
  await userEvent.clear(screen.getByLabelText("Email for Aline"));
  await userEvent.type(
    screen.getByLabelText("Email for Aline"),
    "updated@example.com",
  );
  await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(fetch).toHaveBeenCalledWith(
    "/api/users/2/",
    expect.objectContaining({
      method: "PATCH",
      body: '{"name":"Aline Uwase","email":"updated@example.com","organisation":"Acme"}',
    }),
  );
  expect(onChange).toHaveBeenCalledWith("Profile updated.");
  expect(screen.queryByText("Delete account")).not.toBeInTheDocument();
});
it("keeps profile edits when the server rejects a duplicate email", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: false,
    status: 409,
    json: async () => ({
      error: { email: ["A user with this email already exists."] },
    }),
  });
  render(<UserProfile person={person} onChange={vi.fn()} />);
  await userEvent.clear(screen.getByLabelText("Email for Aline"));
  await userEvent.type(
    screen.getByLabelText("Email for Aline"),
    "taken@example.com",
  );
  await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  expect(screen.getByLabelText("Email for Aline")).toHaveValue(
    "taken@example.com",
  );
  expect(screen.getByLabelText("Email for Aline")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
});
it("asks for an email confirmation and sends a deliberate delete", async () => {
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue({ ok: true, json: async () => ({}) });
  render(<UserProfile person={person} onChange={vi.fn()} />);
  await userEvent.click(screen.getByText("Delete account"));
  await userEvent.click(
    screen.getByRole("button", { name: "Permanently delete account" }),
  );
  expect(fetch).not.toHaveBeenCalled();
  await userEvent.type(
    screen.getByLabelText("Type aline@example.com to confirm"),
    "aline@example.com",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Permanently delete account" }),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/users/2/",
    expect.objectContaining({
      method: "DELETE",
      body: '{"confirm_email":"aline@example.com"}',
    }),
  );
});
it("explains a protected account without pretending it was deleted", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: false,
    status: 409,
    json: async () => ({
      error: "This user has audit history. Deactivate the account instead.",
    }),
  });
  const onChange = vi.fn();
  render(<UserProfile person={person} onChange={onChange} />);
  await userEvent.click(screen.getByText("Delete account"));
  await userEvent.type(
    screen.getByLabelText("Type aline@example.com to confirm"),
    "aline@example.com",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Permanently delete account" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Deactivate");
  expect(onChange).not.toHaveBeenCalled();
});
