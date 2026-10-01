import React from "react";
import { NavLink, Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { api } from "./api";
import { Heading, QueryState, ErrorBox, Empty, Pager, Form, Field } from "./ui";

function useInbox(params = "") {
  return useQuery({
    queryKey: ["notifications", params],
    queryFn: () => api(`notifications/?${params}`),
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  });
}

export function NotificationBell() {
  const query = useInbox();
  const count = query.data?.unread_count;
  return (
    <NavLink
      to="/notifications/"
      aria-label={`Notifications${count ? `, ${count} unread` : ""}${query.isError ? ", updates unavailable" : ""}`}
    >
      <Bell size={17} aria-hidden="true" /> Notifications
      {count > 0 && (
        <span className="notification-badge" aria-hidden="true">
          {count > 99 ? "99+" : count}
        </span>
      )}
      {query.isError && (
        <span title="Open notifications to retry" aria-hidden="true">
          !
        </span>
      )}
    </NavLink>
  );
}

export function Notifications() {
  const [params, setParams] = useSearchParams();
  const query = useInbox(params.toString());
  const client = useQueryClient();
  const preferences = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => api("notifications/preferences/"),
  });
  const read = useMutation({
    mutationFn: (body) => api("notifications/", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });
  return (
    <>
      <Heading eyebrow="STAY IN THE LOOP" title="Notifications">
        Activity relevant to your role, refreshed every 30 seconds while you’re
        here.
      </Heading>
      <section
        className="surface notification-settings"
        aria-label="Email preferences"
      >
        <h2>Email updates</h2>
        <QueryState query={preferences}>
          {(data) => (
            <>
              <p>
                In-app updates are always on. Email alerts link you back to this
                inbox to view activity securely.
              </p>
              {!data.email_available && (
                <p className="notice" role="status">
                  Email delivery is not available for this account yet. Contact
                  the administrator to configure delivery or approve your demo
                  email address. Your in-app notifications still work.
                </p>
              )}
              <Form
                label="Save email preference"
                className="notification-preference-form"
                submit={async (values) => {
                  await api("notifications/preferences/", {
                    method: "PATCH",
                    body: {
                      email_notifications: values.email_notifications === "on",
                    },
                  });
                  await client.invalidateQueries({
                    queryKey: ["notification-preferences"],
                  });
                }}
              >
                <Field
                  key={`${data.email}:${data.email_notifications}`}
                  label={`Send activity alerts to ${data.email}`}
                  name="email_notifications"
                  type="checkbox"
                  defaultChecked={data.email_notifications}
                  disabled={!data.email_available && !data.email_notifications}
                  help="Applies to new activity after you save. You can turn this off at any time. Changing your account email turns this off until you opt in again."
                />
              </Form>
            </>
          )}
        </QueryState>
      </section>
      <section aria-label="Activity inbox">
        <div className="notification-toolbar">
          <h2>Activity inbox</h2>
          <label>
            <input
              type="checkbox"
              checked={params.get("unread") === "true"}
              onChange={(e) =>
                setParams(e.target.checked ? { unread: "true" } : {})
              }
            />{" "}
            Unread only
          </label>
          <button
            className="secondary"
            disabled={query.isFetching}
            onClick={() => query.refetch()}
          >
            Refresh
          </button>
          <button
            disabled={read.isPending || !query.data?.unread_count}
            onClick={() => read.mutate({ all: true })}
          >
            Mark all as read
          </button>
        </div>
        <ErrorBox error={read.error} />
        {read.isSuccess && (
          <p className="notice success" role="status">
            Notifications marked as read.
          </p>
        )}
        <QueryState query={query}>
          {(data) => (
            <>
              <p className="muted">{data.unread_count} unread updates</p>
              {data.notifications.length ? (
                <ul className="notification-list">
                  {data.notifications.map((item) => (
                    <li
                      key={item.id}
                      className={`surface notification-item ${item.read ? "" : "is-unread"}`}
                    >
                      <div>
                        <span className="eyebrow">
                          {item.read ? "READ" : "NEW"}
                        </span>
                        <h3>
                          <Link to={item.href}>{item.title}</Link>
                        </h3>
                        <p>{item.message}</p>
                        <time dateTime={item.created_at}>
                          {new Date(item.created_at).toLocaleString("en-GB", {
                            timeZone: "Africa/Kigali",
                          })}{" "}
                          · Kigali
                        </time>
                        {item.email_state === "failed" && (
                          <p className="field-error">
                            Email could not be sent. This update is available
                            here.
                          </p>
                        )}
                      </div>
                      {!item.read && (
                        <button
                          className="secondary"
                          aria-label={`Mark ${item.title} as read`}
                          disabled={read.isPending}
                          onClick={() => read.mutate({ id: item.id })}
                        >
                          Mark as read
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>
                  {params.get("unread") === "true"
                    ? "You’re all caught up. Turn off Unread only to see earlier activity."
                    : "Request progress and account activity will appear here as your team works."}
                </Empty>
              )}
              <Pager data={data} params={params} setParams={setParams} />
            </>
          )}
        </QueryState>
      </section>
    </>
  );
}
