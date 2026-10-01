import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { Form, Field, Filters, QueryState } from "./ui";
import { ApiError, api } from "./api";

describe("Accessible forms and feedback", () => {
  it("retains values, connects errors and focuses the summary after API validation", async () => {
    const user = userEvent.setup();
    render(
      <Form
        submit={async () => {
          throw new ApiError(422, { task_name: ["Enter a task name."] });
        }}
      >
        {(errors) => (
          <Field label="Task name" name="task_name" error={errors.task_name} />
        )}
      </Form>,
    );
    await user.type(screen.getByLabelText("Task name"), "  ");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveFocus();
    expect(screen.getByLabelText("Task name")).toHaveValue("  ");
    expect(screen.getByLabelText("Task name")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    await user.click(
      screen.getByRole("button", { name: "task name: Enter a task name." }),
    );
    expect(screen.getByLabelText("Task name")).toHaveFocus();
  });
  it("prevents duplicate submissions while an action is pending", async () => {
    let done;
    const submit = vi.fn(
      () =>
        new Promise((resolve) => {
          done = resolve;
        }),
    );
    const user = userEvent.setup();
    render(
      <Form submit={submit}>
        <Field name="name" label="Name" />
      </Form>,
    );
    await user.dblClick(screen.getByRole("button", { name: "Save changes" }));
    expect(submit).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Name")).toBeDisabled();
    done();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Saved successfully",
    );
  });
  it("keeps labels unique when several user access forms are shown", () => {
    render(
      <>
        <Field label="First role" name="role" />
        <Field label="Second role" name="role" />
      </>,
    );
    expect(screen.getByLabelText("First role").id).not.toBe(
      screen.getByLabelText("Second role").id,
    );
  });
  it("blocks an invalid email using native validation", async () => {
    const submit = vi.fn(),
      user = userEvent.setup();
    render(
      <Form submit={submit}>
        <Field label="Email" name="email" type="email" required />
      </Form>,
    );
    await user.type(screen.getByLabelText("Email"), "wrong");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Email")).toBeInvalid();
  });
  it("shows retry feedback when a query fails", async () => {
    const refetch = vi.fn();
    render(
      <QueryState
        query={{ isError: true, error: new Error("Offline"), refetch }}
      >
        {() => null}
      </QueryState>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Offline");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledOnce();
  });
  it("applies search to the URL and resets stale pagination", async () => {
    function View() {
      const [p] = useSearchParams();
      return (
        <>
          <Filters fields={[{ name: "q", label: "Search" }]} />
          <output data-testid="url">{p.toString()}</output>
        </>
      );
    }
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/?page=3"]}>
        <View />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText("Search"), "pick cup");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(screen.getByTestId("url")).toHaveTextContent("q=pick+cup");
    expect(screen.getByTestId("url")).not.toHaveTextContent("page");
  });
});
describe("API integration", () => {
  it("sends CSRF tokens and same-origin session credentials", async () => {
    document.cookie = "csrftoken=test-token";
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    await api("requests/", { method: "POST", body: { task_name: "pick cup" } });
    expect(fetch).toHaveBeenCalledWith(
      "/api/requests/",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ "X-CSRFToken": "test-token" }),
        body: '{"task_name":"pick cup"}',
      }),
    );
    fetch.mockRestore();
  });
  it("preserves server field errors", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        error: { deadline: ["Choose tomorrow or later."] },
      }),
    });
    await expect(
      api("requests/", { method: "POST", body: {} }),
    ).rejects.toMatchObject({
      status: 422,
      fields: { deadline: ["Choose tomorrow or later."] },
    });
    fetch.mockRestore();
  });
  it("does not automatically retry a failed mutation", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(
      api("requests/", { method: "POST", body: {} }),
    ).rejects.toThrow("Check the current record");
    expect(fetch).toHaveBeenCalledOnce();
    fetch.mockRestore();
  });
});
