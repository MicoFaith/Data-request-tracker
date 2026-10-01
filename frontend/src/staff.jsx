import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { AnalyticsDashboard } from "./analytics";
import { UserProfile } from "./user-profile";
import { useSession } from "./session";
import {
  Heading,
  Filters,
  QueryState,
  Pager,
  Empty,
  Form,
  Field,
  roleOptions,
} from "./ui";
import { EpisodeTable } from "./requests";

function Overview({ kind }) {
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => api("dashboard/", { signal }),
  });
  return (
    <QueryState query={query}>
      {(data) => {
        const values =
          kind === "inventory"
            ? [
                ["Total recordings", data.inventory.total],
                ["Ready to assign", data.inventory.eligible],
                ["Assigned", data.inventory.assigned],
              ]
            : [
                ["People", data.people.total],
                ["Active accounts", data.people.active],
                ["Inactive accounts", data.people.total - data.people.active],
              ];
        return (
          <div className="stats-grid">
            {values.map(([label, value]) => (
              <article className="card" key={label}>
                <p className="muted">{label}</p>
                <h2>{value}</h2>
              </article>
            ))}
          </div>
        );
      }}
    </QueryState>
  );
}

export function Episodes() {
  const [params, setParams] = useSearchParams(),
    [report, setReport] = useState(null),
    cache = useQueryClient();
  const query = useQuery({
    queryKey: ["episodes", params.toString()],
    queryFn: ({ signal }) => api(`episodes/?${params}`, { signal }),
  });
  return (
    <>
      <Heading eyebrow="RECORDING LIBRARY" title="Episodes">
        Find recordings, check quality, and bring new metadata into the
        workspace.
      </Heading>
      <Overview kind="inventory" />
      <details className="card import-panel">
        <summary>
          Import episode metadata{" "}
          <span className="muted">CSV · up to 10 MiB</span>
        </summary>
        <p>
          Existing episode IDs are skipped safely. You’ll receive a summary of
          imported and skipped rows.
        </p>
        <Form
          label="Import CSV"
          className="import-form"
          submit={async (values, form) => {
            const file = values.file;
            if (!file?.size) throw new Error("Choose a non-empty CSV file.");
            if (file.size > 10 * 1024 * 1024)
              throw new Error("Choose a CSV file no larger than 10 MiB.");
            setReport(null);
            setReport(
              await api("episodes/import/", {
                method: "POST",
                body: new FormData(form),
              }),
            );
            await cache.invalidateQueries();
          }}
        >
          <Field
            label="CSV file"
            name="file"
            type="file"
            accept=".csv,text/csv"
            required
          />
        </Form>
        {report && (
          <div className="import-summary" role="status">
            <h3>Import complete</h3>
            <p>
              {report.imported} imported · {report.skipped} skipped ·{" "}
              {report.total_rows} rows processed
            </p>
            {Object.keys(report.reasons).length > 0 && (
              <details>
                <summary>Why rows were skipped</summary>
                <ul>
                  {Object.entries(report.reasons).map(([reason, count]) => (
                    <li key={reason}>
                      {reason.replaceAll("_", " ")}: {count}
                    </li>
                  ))}
                </ul>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>CSV line</th>
                        <th>Episode</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.rows.map((row, i) => (
                        <tr key={i}>
                          <td>{row.line}</td>
                          <td>{row.episode_id || "—"}</td>
                          <td>{row.reason.replaceAll("_", " ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {report.unlisted_skips > 0 && (
                  <p>
                    {report.unlisted_skips} additional skipped rows are included
                    in the totals above.
                  </p>
                )}
              </details>
            )}
          </div>
        )}
      </details>
      <Filters
        fields={[
          {
            name: "task_name",
            label: "Task name",
            placeholder: "Exact task name",
          },
          {
            name: "quality",
            label: "Quality",
            options: [
              ["", "All quality"],
              ["good", "Good"],
              ["usable", "Usable"],
              ["bad", "Bad"],
            ],
          },
          {
            name: "available",
            label: "Availability",
            options: [
              ["", "All recordings"],
              ["true", "Unassigned"],
              ["false", "Assigned"],
            ],
          },
        ]}
      />
      <QueryState query={query}>
        {(data) => (
          <>
            {data.episodes.length ? (
              <EpisodeTable episodes={data.episodes} />
            ) : (
              <Empty />
            )}
            <Pager data={data} params={params} setParams={setParams} />
          </>
        )}
      </QueryState>
    </>
  );
}
export function Analytics() {
  const { today } = useSession(),
    [params, setParams] = useSearchParams();
  const start = params.get("start") || `${today.slice(0, 7)}-01`,
    end = params.get("end") || today;
  const valid = start <= end && start >= "0002-01-01" && end < "9999-01-01";
  const query = useQuery({
    queryKey: ["analytics", start, end],
    queryFn: ({ signal }) =>
      api(`analytics/?${new URLSearchParams({ start, end })}`, { signal }),
    enabled: valid,
  });
  return (
    <>
      <Heading eyebrow="OPERATIONS INSIGHTS" title="Analytics">
        Understand recording activity and delivery performance. Dates use Kigali
        time.
      </Heading>
      <nav className="date-shortcuts" aria-label="Date range shortcuts">
        <span>Quick view</span>
        {[7, 30, 90].map((days) => {
          const from = new Date(
            new Date(`${today}T00:00:00Z`).getTime() - (days - 1) * 86400000,
          )
            .toISOString()
            .slice(0, 10);
          return (
            <button
              key={days}
              type="button"
              className="secondary"
              aria-pressed={start === from && end === today}
              onClick={() => setParams({ start: from, end: today })}
            >
              Last {days} days
            </button>
          );
        })}
        <button
          type="button"
          className="secondary"
          aria-pressed={start === `${today.slice(0, 7)}-01` && end === today}
          onClick={() =>
            setParams({ start: `${today.slice(0, 7)}-01`, end: today })
          }
        >
          This month
        </button>
      </nav>
      <Filters
        fields={[
          {
            name: "start",
            label: "Start date",
            type: "date",
            defaultValue: start,
          },
          { name: "end", label: "End date", type: "date", defaultValue: end },
        ]}
      />
      {!valid ? (
        <p className="notice error" role="alert">
          Choose an end date on or after the start date, with years from 0002 to
          9998.
        </p>
      ) : (
        <QueryState query={query}>
          {(data) => <AnalyticsDashboard data={data} />}
        </QueryState>
      )}
    </>
  );
}
export function Users() {
  const { user, refresh } = useSession(),
    [params, setParams] = useSearchParams(),
    cache = useQueryClient();
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["users", params.toString()],
    queryFn: ({ signal }) => api(`users/?${params}`, { signal }),
  });
  const invalidate = () => cache.invalidateQueries();
  return (
    <>
      <Heading eyebrow="ADMINISTRATION" title="People & access">
        Give each person the right workspace and keep account access up to date.
      </Heading>
      <Overview kind="people" />
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
      <div className="user-layout">
        <section>
          <Filters
            fields={[
              {
                name: "q",
                label: "Search people",
                placeholder: "Name or email",
              },
              { name: "role", label: "Role", options: roleOptions },
              {
                name: "active",
                label: "Account",
                options: [
                  ["", "All accounts"],
                  ["true", "Active"],
                  ["false", "Inactive"],
                ],
              },
            ]}
          />
          <QueryState query={query}>
            {(data) => (
              <>
                {data.users.length ? (
                  data.users.map((person) => (
                    <article
                      key={`${person.id}-${person.role}-${person.is_active}-${person.name}-${person.email}-${person.organisation}`}
                      className="card user-record"
                    >
                      <div className="user-identity">
                        <span className="avatar">
                          {person.name.slice(0, 1)}
                        </span>
                        <div>
                          <h3>
                            {person.name}{" "}
                            {person.id === user.id && <small>(you)</small>}
                          </h3>
                          <p>{person.email}</p>
                          <small>
                            {person.organisation || "No organisation"}
                          </small>
                        </div>
                        <span
                          className={`status ${person.is_active ? "accepted" : "rejected"}`}
                        >
                          {person.is_active ? "Active" : "Inactive"}
                        </span>
                      </div>
                      {person.id === user.id && (
                        <p className="helptext">
                          Your own admin access is protected.
                        </p>
                      )}
                      <UserProfile
                        person={person}
                        isSelf={person.id === user.id}
                        onChange={async (message) => {
                          setNotice(message);
                          await invalidate();
                          if (person.id === user.id) await refresh?.();
                        }}
                      />
                    </article>
                  ))
                ) : (
                  <Empty />
                )}
                <Pager data={data} params={params} setParams={setParams} />
              </>
            )}
          </QueryState>
        </section>
        <aside>
          <h2>Add a person</h2>
          <p className="muted">
            Create an account and share their credentials securely.
          </p>
          <Form
            reset
            label="Create account"
            submit={async (data) => {
              await api("users/", { method: "POST", body: data });
              await invalidate();
            }}
          >
            {(errors) => (
              <>
                <Field
                  label="Full name"
                  name="name"
                  required
                  maxLength={120}
                  error={errors.name}
                />
                <Field
                  label="Email"
                  name="email"
                  type="email"
                  required
                  maxLength={150}
                  autoComplete="off"
                  error={errors.email}
                />
                <Field
                  label="Organisation (optional)"
                  name="organisation"
                  maxLength={120}
                  error={errors.organisation}
                />
                <Field label="Role" name="role" error={errors.role}>
                  <select defaultValue="client">
                    {roleOptions.slice(1).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Temporary password"
                  name="password"
                  type="password"
                  minLength={12}
                  maxLength={128}
                  required
                  autoComplete="new-password"
                  help="12–128 characters; cannot be only spaces."
                  error={errors.password}
                />
              </>
            )}
          </Form>
        </aside>
      </div>
    </>
  );
}
