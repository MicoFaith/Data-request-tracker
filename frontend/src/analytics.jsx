import React, { useId, useMemo, useState } from "react";
import { Database, ClipboardList, CheckCircle2, Clock3 } from "lucide-react";
import { labels, formatDate } from "./api";
import { Empty } from "./ui";

const palette = [
  "var(--accent)",
  "#b5ead3",
  "var(--ink)",
  "var(--muted)",
  "var(--border)",
];
const dayMs = 86400000;
const timestamp = (day) => new Date(`${day}T00:00:00Z`).getTime();

// At most 40 buckets, including quiet days; long date ranges stay inexpensive.
export function recordingBuckets(rows, start, end) {
  const first = timestamp(start),
    days = Math.round((timestamp(end) - first) / dayMs) + 1;
  const size = Math.max(1, Math.ceil(days / 40));
  const buckets = Array.from({ length: Math.ceil(days / size) }, (_, index) => {
    const from = new Date(first + index * size * dayMs)
      .toISOString()
      .slice(0, 10);
    const to = new Date(
      first + Math.min(days - 1, (index + 1) * size - 1) * dayMs,
    )
      .toISOString()
      .slice(0, 10);
    return { from, to, count: 0 };
  });
  rows.forEach((row) => {
    const index = Math.floor((timestamp(row.day) - first) / dayMs / size);
    if (index >= 0 && index < buckets.length) buckets[index].count += row.count;
  });
  return buckets;
}

function VolumeChart({ rows, start, end }) {
  const buckets = useMemo(
    () => recordingBuckets(rows, start, end),
    [rows, start, end],
  );
  const [active, setActive] = useState(null);
  const peak = Math.max(1, ...buckets.map((b) => b.count));
  const top = Math.max(4, Math.ceil(peak / 4) * 4),
    width = 680 / buckets.length;
  const selected = buckets[active] || null;
  const description = (b) =>
    `${formatDate(b.from)}${b.to !== b.from ? ` – ${formatDate(b.to)}` : ""}: ${b.count.toLocaleString()} episodes`;
  return (
    <>
      <div className="chart-readout" aria-live="polite">
        {selected
          ? description(selected)
          : "Select a bar to inspect recording volume."}
      </div>
      <svg
        className="volume-chart"
        viewBox="0 0 760 270"
        role="group"
        aria-label="Recording volume over the selected date range"
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line
              x1="55"
              x2="735"
              y1={225 - i * 48}
              y2={225 - i * 48}
              className="chart-gridline"
            />
            <text
              x="44"
              y={230 - i * 48}
              textAnchor="end"
              className="chart-axis"
            >
              {Math.round((top * i) / 4).toLocaleString()}
            </text>
          </g>
        ))}
        {buckets.map((b, i) => {
          const h = (b.count / top) * 192;
          return (
            <rect
              key={b.from}
              x={55 + i * width + width * 0.12}
              y={225 - Math.max(h, 2)}
              width={width * 0.76}
              height={Math.max(h, 2)}
              rx={Math.min(4, width * 0.15)}
              className={`chart-column ${active === i ? "selected" : ""}`}
              opacity={b.count ? 1 : 0.25}
              tabIndex={0}
              role="button"
              aria-label={description(b)}
              aria-pressed={active === i}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onClick={() => setActive(i)}
              onKeyDown={(e) => {
                if (["Enter", " "].includes(e.key)) {
                  e.preventDefault();
                  setActive(i);
                }
              }}
            >
              <title>{description(b)}</title>
            </rect>
          );
        })}
        <text x="55" y="258" className="chart-axis">
          {formatDate(start)}
        </text>
        <text x="735" y="258" textAnchor="end" className="chart-axis">
          {formatDate(end)}
        </text>
      </svg>
      <p className="chart-note">
        {buckets[0]?.from === buckets[0]?.to
          ? "Daily totals, including days without recordings."
          : "Totals grouped into equal date intervals to keep the chart readable."}{" "}
        Counts include all quality levels.
      </p>
    </>
  );
}

function StatusChart({ counts }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0),
    id = useId();
  let offset = 0;
  return (
    <section className="card chart-card">
      <div className="section-head">
        <div>
          <p className="eyebrow">REQUEST HEALTH</p>
          <h2>Where requests stand</h2>
        </div>
      </div>
      <p className="chart-note">
        Current status of requests submitted in this date range.
      </p>
      <div className="status-visual">
        <svg
          viewBox="0 0 220 220"
          className="status-donut"
          role="img"
          aria-labelledby={id}
        >
          <title id={id}>
            {total} requests;{" "}
            {Object.entries(counts)
              .map(([s, c]) => `${labels[s]}: ${c}`)
              .join(", ")}
          </title>
          <circle
            cx="110"
            cy="110"
            r="80"
            fill="none"
            stroke="var(--border)"
            strokeWidth="23"
          />
          {total > 0 &&
            Object.entries(counts).map(([s, c], i) => {
              const length = (c / total) * 100,
                start = offset;
              offset += length;
              return (
                <circle
                  key={s}
                  cx="110"
                  cy="110"
                  r="80"
                  fill="none"
                  stroke={palette[i]}
                  strokeWidth="23"
                  pathLength="100"
                  strokeDasharray={`${length} ${100 - length}`}
                  strokeDashoffset={-start}
                  transform="rotate(-90 110 110)"
                />
              );
            })}
          <text x="110" y="108" textAnchor="middle" className="donut-total">
            {total.toLocaleString()}
          </text>
          <text x="110" y="132" textAnchor="middle" className="chart-axis">
            requests
          </text>
        </svg>
        <ul className="chart-legend">
          {Object.entries(counts).map(([s, c], i) => (
            <li key={s}>
              <span className="legend-dot" style={{ background: palette[i] }} />
              <span>{labels[s]}</span>
              <strong>{c.toLocaleString()}</strong>
              <small>{total ? Math.round((c / total) * 100) : 0}%</small>
            </li>
          ))}
        </ul>
      </div>
      {!total && (
        <p className="chart-note">No requests were submitted in this range.</p>
      )}
    </section>
  );
}

export function AnalyticsDashboard({ data }) {
  const [robot, setRobot] = useState("");
  const rows = data.episodes_per_day_per_robot,
    counts = data.request_fulfilment.counts_by_status;
  const total = rows.reduce((a, r) => a + r.count, 0),
    requests = Object.values(counts).reduce((a, b) => a + b, 0);
  const median =
    data.request_fulfilment.median_seconds_submitted_to_first_delivered;
  const robots = [...new Set(rows.map((r) => r.robot_id))].sort();
  const selectedRobot = robots.includes(robot) ? robot : "";
  const filtered = rows.filter(
    (r) => !selectedRobot || r.robot_id === selectedRobot,
  );
  const metrics = [
    [
      "Recorded episodes",
      total.toLocaleString(),
      "Across all robots and quality levels",
      Database,
    ],
    [
      "Requests submitted",
      requests.toLocaleString(),
      "Created within the selected date range",
      ClipboardList,
    ],
    [
      "Accepted requests",
      requests
        ? `${Math.round(((counts.accepted || 0) / requests) * 100)}%`
        : "—",
      `${counts.accepted || 0} of ${requests} submitted requests accepted`,
      CheckCircle2,
    ],
    [
      "Median first delivery",
      median == null
        ? "—"
        : median < 3600
          ? `${Math.round(median / 60)} min`
          : `${(median / 3600).toFixed(1)} hrs`,
      median == null
        ? "No delivered requests in this cohort"
        : "For requests submitted in this date range",
      Clock3,
    ],
  ];
  return (
    <div className="analytics-dashboard">
      <div className="analytics-metrics">
        {metrics.map(([label, value, note, Icon]) => (
          <article className="card analytics-metric" key={label}>
            <div>
              <span>{label}</span>
              <Icon size={19} aria-hidden="true" />
            </div>
            <strong>{value}</strong>
            <p>{note}</p>
          </article>
        ))}
      </div>
      <section className="card chart-card">
        <div className="section-head">
          <div>
            <p className="eyebrow">COLLECTION ACTIVITY</p>
            <h2>Recording volume</h2>
          </div>
          <label className="chart-filter">
            Show robot
            <select
              value={selectedRobot}
              onChange={(e) => setRobot(e.target.value)}
            >
              <option value="">All robots</option>
              {robots.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
        </div>
        {rows.length ? (
          <VolumeChart
            key={`${data.start}:${data.end}:${selectedRobot}`}
            rows={filtered}
            start={data.start}
            end={data.end}
          />
        ) : (
          <Empty>No recordings in this date range. Try a wider range.</Empty>
        )}
        <details className="chart-data">
          <summary>
            View recording data{selectedRobot ? ` · ${selectedRobot}` : ""}
          </summary>
          <div className="table-wrap analytics-table">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Robot</th>
                  <th>Episodes</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={`${r.day}:${r.robot_id}`}>
                    <td>{r.day}</td>
                    <td>{r.robot_id}</td>
                    <td>{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>
      <div className="analytics-charts">
        <StatusChart counts={counts} />
        <section className="card chart-card">
          <p className="eyebrow">DATA QUALITY</p>
          <h2>Top tasks by good episodes</h2>
          <p className="chart-note">
            The five most recorded tasks with good-quality episodes.
          </p>
          {data.top_5_good_tasks.length ? (
            <ol className="task-ranking">
              {data.top_5_good_tasks.map((r, i) => (
                <li key={r.task_name}>
                  <span className="task-rank">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <div className="task-bar-label">
                      <strong>{r.task_name}</strong>
                      <span>{r.count.toLocaleString()}</span>
                    </div>
                    <progress
                      aria-label={`${r.task_name}: ${r.count} good episodes`}
                      value={r.count}
                      max={data.top_5_good_tasks[0].count}
                    />
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <Empty>No good episodes in this date range.</Empty>
          )}
        </section>
      </div>
    </div>
  );
}
