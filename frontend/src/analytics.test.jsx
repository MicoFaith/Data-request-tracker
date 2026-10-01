import React from "react";
import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnalyticsDashboard, recordingBuckets } from "./analytics";

const data = {
  start: "2026-10-01",
  end: "2026-10-03",
  episodes_per_day_per_robot: [
    { day: "2026-10-01", robot_id: "arm-01", count: 4 },
    { day: "2026-10-01", robot_id: "arm-02", count: 2 },
    { day: "2026-10-03", robot_id: "arm-02", count: 3 },
  ],
  request_fulfilment: {
    counts_by_status: {
      submitted: 1,
      in_progress: 2,
      delivered: 0,
      accepted: 1,
      rejected: 0,
    },
    median_seconds_submitted_to_first_delivered: 7200,
  },
  top_5_good_tasks: [{ task_name: "pick cup", count: 5 }],
};
it("includes quiet dates and combines robot totals without inventing recordings", () => {
  expect(
    recordingBuckets(data.episodes_per_day_per_robot, data.start, data.end).map(
      (r) => r.count,
    ),
  ).toEqual([6, 0, 3]);
});
it("bounds large-range chart size while preserving the total", () => {
  const buckets = recordingBuckets(
    data.episodes_per_day_per_robot,
    "0002-01-01",
    "9998-12-31",
  );
  expect(buckets.length).toBeLessThanOrEqual(40);
  expect(buckets.reduce((a, b) => a + b.count, 0)).toBe(9);
});
it("filters chart and exact recording table by robot without changing cohort metrics", async () => {
  render(<AnalyticsDashboard data={data} />);
  await userEvent.selectOptions(screen.getByLabelText("Show robot"), "arm-01");
  expect(
    screen.getByRole("button", { name: "1 Oct 2026: 4 episodes" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText("25%")).toHaveLength(3);
  expect(
    screen.getByRole("button", { name: "3 Oct 2026: 0 episodes" }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByText("View recording data · arm-01"));
  expect(
    screen.queryByRole("cell", { name: "arm-02" }),
  ).not.toBeInTheDocument();
});
it("shows an accurate empty state without NaN or a misleading acceptance percentage", () => {
  render(
    <AnalyticsDashboard
      data={{
        ...data,
        episodes_per_day_per_robot: [],
        top_5_good_tasks: [],
        request_fulfilment: {
          counts_by_status: {
            submitted: 0,
            in_progress: 0,
            delivered: 0,
            accepted: 0,
            rejected: 0,
          },
          median_seconds_submitted_to_first_delivered: null,
        },
      }}
    />,
  );
  expect(
    screen.getByText(/No recordings in this date range/),
  ).toBeInTheDocument();
  expect(
    screen.getByText("No requests were submitted in this range."),
  ).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("NaN");
});
