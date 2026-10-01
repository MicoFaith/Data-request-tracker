import React from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, labels, formatDate } from "./api";
import { useSession } from "./session";
import {
  Heading,
  Cards,
  Filters,
  QueryState,
  Pager,
  Empty,
  Status,
  Form,
  Field,
  ErrorBox,
  statusOptions,
} from "./ui";

export function Dashboard() {
  const { user } = useSession();
  const [params, setParams] = useSearchParams();
  const stats = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => api("dashboard/", { signal }),
  });
  const query = useQuery({
    queryKey: ["requests", params.toString()],
    queryFn: ({ signal }) => api(`requests/?${params}`, { signal }),
  });
  return (
    <>
      <Heading
        eyebrow={`${user.role} workspace`}
        title={`Welcome back, ${user.name.split(" ")[0]}`}
        action={
          user.role === "client" && (
            <Link className="button" to="/requests/new/">
              + New request
            </Link>
          )
        }
      >
        Your requests, priorities and next steps in one place.
      </Heading>
      <QueryState query={stats}>
        {({ counts: c }) => (
          <Cards
            items={
              user.role === "client"
                ? [
                    ["Your requests", c.total, "/"],
                    ["Ready for review", c.delivered, "/?status=delivered"],
                    ["In progress", c.in_progress, "/?status=in_progress"],
                    ["Accepted", c.accepted, "/?status=accepted"],
                  ]
                : [
                    ["New requests", c.submitted, "/?status=submitted"],
                    ["In progress", c.in_progress, "/?status=in_progress"],
                    ["Needs rework", c.rejected, "/?status=rejected"],
                    ["Overdue", c.overdue, "/?attention=overdue"],
                  ]
            }
          />
        )}
      </QueryState>
      <section id="requests" className="list-section">
        <div className="section-head">
          <h2>{user.role === "client" ? "Your requests" : "Request queue"}</h2>
          <span className="muted">Select a request to see its next step</span>
        </div>
        <Filters
          fields={[
            {
              name: "q",
              label: "Search requests",
              placeholder: "Task, request # or client",
            },
            { name: "status", label: "Status", options: statusOptions },
            {
              name: "attention",
              label: "Deadline",
              options: [
                ["", "All deadlines"],
                ["overdue", "Overdue"],
              ],
            },
            {
              name: "sort",
              label: "Order",
              options: [
                ["newest", "Newest first"],
                ["deadline", "Deadline first"],
              ],
            },
          ]}
        />
        <QueryState query={query}>
          {(data) => (
            <>
              {data.requests.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Request</th>
                        {user.role !== "client" && <th>Client</th>}
                        <th>Status</th>
                        <th>Progress</th>
                        <th>Deadline</th>
                        <th>Details</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.requests.map((r) => (
                        <tr key={r.id}>
                          <td>
                            <span className="row-kicker">REQUEST #{r.id}</span>
                            <Link className="strong" to={`/requests/${r.id}/`}>
                              {r.task_name}
                            </Link>
                          </td>
                          {user.role !== "client" && <td>{r.client_name}</td>}
                          <td>
                            <Status value={r.status} />
                          </td>
                          <td>
                            <Progress request={r} />
                          </td>
                          <td>{formatDate(r.deadline)}</td>
                          <td>
                            <Link to={`/requests/${r.id}/`}>
                              {r.status === "delivered" &&
                              user.role === "client"
                                ? "Review delivery"
                                : "Open request"}{" "}
                              →
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty />
              )}
              <Pager data={data} params={params} setParams={setParams} />
            </>
          )}
        </QueryState>
      </section>
    </>
  );
}
function Progress({ request: r }) {
  return (
    <div className="request-progress">
      <span>
        {r.assigned_count} / {r.episodes_requested} episodes
      </span>
      <progress
        aria-label="Assigned episodes"
        value={Math.min(r.assigned_count, r.episodes_requested)}
        max={r.episodes_requested}
      />
    </div>
  );
}
export function NewRequest() {
  const { tomorrow } = useSession(),
    navigate = useNavigate(),
    cache = useQueryClient();
  return (
    <>
      <Link to="/">← Dashboard</Link>
      <Heading eyebrow="NEW DATASET" title="What data do you need?">
        Tell us the task and size. We’ll handle the rest.
      </Heading>
      <div className="form-layout">
        <Form
          label="Submit request"
          submit={async (data) => {
            const result = await api("requests/", {
              method: "POST",
              body: {
                ...data,
                episodes_requested: Number(data.episodes_requested),
              },
            });
            await cache.invalidateQueries();
            navigate(`/requests/${result.request.id}/`);
          }}
        >
          {(errors) => (
            <>
              <Field
                name="task_name"
                label="Task name"
                required
                maxLength={160}
                placeholder="e.g. pick cup"
                error={errors.task_name}
                help="Use the task name agreed with your operations team."
              />
              <Field
                name="episodes_requested"
                label="Number of episodes"
                type="number"
                min={1}
                max={1000000}
                step={1}
                required
                error={errors.episodes_requested}
              />
              <Field
                name="deadline"
                label="Delivery deadline"
                type="date"
                min={tomorrow}
                max="9999-12-31"
                required
                error={errors.deadline}
                help="Choose tomorrow or later, in Kigali time."
              />
              <Field
                name="notes"
                label="Additional notes (optional)"
                error={errors.notes}
                help="Up to 4,000 characters."
              >
                <textarea maxLength={4000} rows={5} />
              </Field>
            </>
          )}
        </Form>
        <aside className="card guide-card">
          <h2>What happens next?</h2>
          <ol className="steps">
            <li>Operations reviews your request.</li>
            <li>Matching episodes are prepared.</li>
            <li>You review the delivery and accept it or request rework.</li>
          </ol>
          <p>You can follow each step from your dashboard.</p>
        </aside>
      </div>
    </>
  );
}
export function RequestDetail() {
  const { id } = useParams(),
    { user } = useSession(),
    cache = useQueryClient();
  const query = useQuery({
    queryKey: ["request", id],
    queryFn: ({ signal }) => api(`requests/${id}/`, { signal }),
  });
  const action = useMutation({
    mutationFn: ({ path, method = "POST", body }) =>
      api(`requests/${id}/${path}`, { method, body }),
    onSettled: () => cache.invalidateQueries(),
  });
  return (
    <>
      <Link to="/">← All requests</Link>
      <QueryState query={query}>
        {({ request: r, episodes, history }) => {
          const staff = user.role !== "client";
          return (
            <>
              <Heading
                eyebrow={`REQUEST #${r.id} · ${r.client_name}`}
                title={r.task_name}
                action={<Status value={r.status} />}
              >
                Due {formatDate(r.deadline)} · {r.episodes_requested} episodes
                requested
              </Heading>
              <ErrorBox error={action.error} />
              <div className="next-action">
                <div>
                  <h2>
                    {r.status === "submitted"
                      ? "Ready to get started"
                      : r.status === "in_progress"
                        ? "Dataset preparation is underway"
                        : r.status === "delivered"
                          ? "Your dataset is ready for review"
                          : r.status === "rejected"
                            ? "Rework requested"
                            : "Delivery accepted"}
                  </h2>
                  <p>
                    {staff
                      ? "Prepare matching good or usable episodes, then deliver for client review."
                      : "Track preparation below. When your dataset is delivered, review the episodes before accepting."}
                  </p>
                </div>
                <div className="actions">
                  {staff && ["submitted", "rejected"].includes(r.status) && (
                    <button
                      disabled={action.isPending}
                      onClick={() =>
                        action.mutate({
                          path: "status/",
                          body: { status: "in_progress" },
                        })
                      }
                    >
                      {r.status === "rejected"
                        ? "Start rework"
                        : "Start preparation"}
                    </button>
                  )}
                  {staff && r.status === "in_progress" && (
                    <>
                      <button
                        disabled={
                          action.isPending ||
                          r.assigned_count < r.episodes_requested
                        }
                        onClick={() =>
                          action.mutate({
                            path: "status/",
                            body: { status: "delivered" },
                          })
                        }
                      >
                        Deliver dataset
                      </button>
                      {r.assigned_count < r.episodes_requested && (
                        <small>
                          Assign {r.episodes_requested - r.assigned_count} more
                          episodes to deliver.
                        </small>
                      )}
                    </>
                  )}
                  {!staff && r.status === "delivered" && (
                    <>
                      <button
                        disabled={action.isPending}
                        onClick={() =>
                          action.mutate({
                            path: "status/",
                            body: { status: "accepted" },
                          })
                        }
                      >
                        Accept delivery
                      </button>
                      <button
                        className="secondary"
                        disabled={action.isPending}
                        onClick={() =>
                          action.mutate({
                            path: "status/",
                            body: { status: "rejected" },
                          })
                        }
                      >
                        Request rework
                      </button>
                    </>
                  )}
                  {action.isPending && <span role="status">Saving…</span>}
                </div>
              </div>
              <div className="detail-grid">
                <section className="card">
                  <h2>Dataset progress</h2>
                  <Progress request={r} />
                  {r.notes && (
                    <>
                      <h3>Your notes</h3>
                      <p className="preserve-lines">{r.notes}</p>
                    </>
                  )}
                  <h3>Assigned episodes</h3>
                  {episodes.length ? (
                    <EpisodeTable
                      episodes={episodes}
                      action={
                        staff && r.status === "in_progress"
                          ? (ep) => (
                              <button
                                className="secondary"
                                disabled={action.isPending}
                                onClick={() =>
                                  action.mutate({
                                    path: `assignments/${encodeURIComponent(ep.episode_id)}/`,
                                    method: "DELETE",
                                  })
                                }
                              >
                                Remove
                              </button>
                            )
                          : null
                      }
                    />
                  ) : (
                    <Empty>No episodes assigned yet.</Empty>
                  )}
                </section>
                <aside className="card">
                  <h2>Activity</h2>
                  <ol className="timeline">
                    {history.map((e, i) => (
                      <li key={i}>
                        <strong>{labels[e.to_status]}</strong>
                        <p>{e.actor_name}</p>
                        <small>
                          {formatDate(e.at)} ·{" "}
                          {new Date(e.at).toLocaleTimeString("en-GB", {
                            timeZone: "Africa/Kigali",
                          })}
                        </small>
                      </li>
                    ))}
                  </ol>
                </aside>
              </div>
              {staff && r.status === "in_progress" && (
                <Assignments request={r} action={action} />
              )}
            </>
          );
        }}
      </QueryState>
    </>
  );
}
export function EpisodeTable({ episodes, action }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Episode</th>
            <th>Task / robot</th>
            <th>Quality</th>
            <th>Duration</th>
            {action && <th>Action</th>}
          </tr>
        </thead>
        <tbody>
          {episodes.map((ep) => (
            <tr key={ep.episode_id}>
              <td>
                <strong>{ep.episode_id}</strong>
                <small className="row-kicker">
                  {formatDate(ep.recorded_at)}
                </small>
              </td>
              <td>
                {ep.task_name}
                <small className="row-kicker">{ep.robot_id}</small>
              </td>
              <td>
                <span className={`quality ${ep.quality}`}>{ep.quality}</span>
              </td>
              <td>{ep.duration_seconds}s</td>
              {action && <td>{action(ep)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Assignments({ request, action }) {
  const [params, setParams] = useSearchParams();
  const filter = new URLSearchParams({
    task_name: request.task_name,
    available: "true",
    page: params.get("page") || "1",
    quality: params.get("quality") || "",
  });
  const query = useQuery({
    queryKey: ["episodes", filter.toString()],
    queryFn: ({ signal }) => api(`episodes/?${filter}`, { signal }),
  });
  return (
    <section className="card" id="assignment-panel">
      <Heading title="Assign matching episodes">
        Available recordings for “{request.task_name}”. Bad-quality recordings
        cannot be assigned.
      </Heading>
      <label className="chart-filter">
        Quality
        <select
          value={params.get("quality") || ""}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            next.set("quality", e.target.value);
            next.delete("page");
            setParams(next);
          }}
        >
          <option value="">All quality</option>
          <option value="good">Good</option>
          <option value="usable">Usable</option>
          <option value="bad">Bad (cannot assign)</option>
        </select>
      </label>
      <QueryState query={query}>
        {(data) => (
          <>
            {data.episodes.length ? (
              <EpisodeTable
                episodes={data.episodes}
                action={(ep) => (
                  <button
                    disabled={action.isPending || ep.quality === "bad"}
                    onClick={() =>
                      action.mutate({
                        path: "assignments/",
                        body: { episode_id: ep.episode_id },
                      })
                    }
                  >
                    {ep.quality === "bad" ? "Ineligible" : "Assign"}
                  </button>
                )}
              />
            ) : (
              <Empty>
                No matching, unassigned episodes. Import more recordings from
                Episodes.
              </Empty>
            )}
            <Pager data={data} params={params} setParams={setParams} />
          </>
        )}
      </QueryState>
    </section>
  );
}
