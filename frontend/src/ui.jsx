import React, { useEffect, useId, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { LoaderCircle, ArrowRight, Search, AlertCircle } from "lucide-react";
import { labels } from "./api";

export function Heading({ eyebrow, title, children, action }) {
  return (
    <div className="heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {children && <p className="muted">{children}</p>}
      </div>
      {action}
    </div>
  );
}
export function Status({ value }) {
  return <span className={`status ${value}`}>{labels[value] || value}</span>;
}
export function Loading() {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" /> Loading your workspace…
      <div className="skeleton" />
      <div className="skeleton" />
    </div>
  );
}
export function ErrorBox({ error, retry }) {
  return error ? (
    <div className="notice error" role="alert">
      <AlertCircle size={18} />
      <span>{error.message || String(error)}</span>
      {retry && (
        <button className="secondary" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  ) : null;
}
export function QueryState({ query, children }) {
  return query.isPending ? (
    <Loading />
  ) : query.isError ? (
    <ErrorBox error={query.error} retry={() => query.refetch()} />
  ) : (
    <>
      {query.isFetching && (
        <div role="status" className="refreshing">
          Refreshing…
        </div>
      )}
      {children(query.data)}
    </>
  );
}
export function Empty({ children = "No results match these filters." }) {
  return (
    <div className="empty">
      <Search />
      <h3>Nothing here yet</h3>
      <p>{children}</p>
    </div>
  );
}
export function Cards({ items }) {
  return (
    <div className="dashboard-stats">
      {items.map(([label, value, href]) => (
        <Link className="metric-card" to={href || "#"} key={label}>
          <span className="metric-label">{label}</span>
          <strong>{value ?? "—"}</strong>
          <span className="muted">
            View details <ArrowRight size={14} />
          </span>
        </Link>
      ))}
    </div>
  );
}
export function Pager({ data, params, setParams }) {
  const p = Number(data.page);
  const change = (page) => {
    const next = new URLSearchParams(params);
    next.set("page", page);
    setParams(next);
  };
  return (
    <nav className="pagination" aria-label="Pagination">
      <span>
        {data.total} results · Page {p} of{" "}
        {Math.max(1, Math.ceil(data.total / data.page_size))}
      </span>
      <button
        className="secondary"
        disabled={p <= 1}
        onClick={() => change(p - 1)}
      >
        Previous
      </button>
      <button
        className="secondary"
        disabled={!data.has_next}
        onClick={() => change(p + 1)}
      >
        Next
      </button>
    </nav>
  );
}
export function Filters({ fields }) {
  const [params, setParams] = useSearchParams();
  return (
    <form
      key={params.toString()}
      className="filters surface"
      onSubmit={(e) => {
        e.preventDefault();
        const next = new URLSearchParams();
        for (const [k, v] of new FormData(e.currentTarget))
          if (v) next.set(k, v);
        setParams(next);
      }}
    >
      {fields.map((f) => (
        <label key={f.name}>
          {f.label}
          {f.options ? (
            <select
              name={f.name}
              defaultValue={params.get(f.name) || f.defaultValue || ""}
            >
              {f.options.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          ) : (
            <input
              type={f.type || "search"}
              name={f.name}
              maxLength={160}
              defaultValue={params.get(f.name) || f.defaultValue || ""}
              placeholder={f.placeholder}
            />
          )}
        </label>
      ))}
      <button>Apply filters</button>
      <button type="button" className="secondary" onClick={() => setParams({})}>
        Reset
      </button>
    </form>
  );
}
export function Field({ label, name, error, help, children, ...props }) {
  const unique = useId();
  const id = `field-${name}-${unique}`;
  return (
    <div className={`form-field ${error ? "has-error" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children ? (
        React.cloneElement(children, {
          id,
          name,
          "aria-invalid": !!error,
          "aria-describedby": `${id}-help${error ? ` ${id}-error` : ""}`,
        })
      ) : (
        <input
          id={id}
          name={name}
          aria-invalid={!!error}
          aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`}
          {...props}
        />
      )}
      <small id={`${id}-help`} className="helptext">
        {help}
      </small>
      {error && (
        <p id={`${id}-error`} className="field-error">
          {[].concat(error).join(" ")}
        </p>
      )}
    </div>
  );
}
export function Form({
  submit,
  children,
  label = "Save changes",
  className = "card",
  reset = false,
}) {
  const [pending, setPending] = useState(false),
    [error, setError] = useState(null),
    [success, setSuccess] = useState(false);
  const busy = useRef(false),
    summary = useRef(null);
  useEffect(() => {
    if (error) summary.current?.focus();
  }, [error]);
  return (
    <form
      className={className}
      aria-busy={pending}
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy.current) return;
        const form = e.currentTarget;
        busy.current = true;
        setPending(true);
        setError(null);
        setSuccess(false);
        try {
          await submit(Object.fromEntries(new FormData(form)), form);
          setSuccess(true);
          if (reset) form.reset();
        } catch (err) {
          setError(err);
        } finally {
          busy.current = false;
          setPending(false);
        }
      }}
    >
      {error && (
        <div tabIndex={-1} ref={summary} className="notice error" role="alert">
          <p>{error.message}</p>
          {Object.entries(error.fields || {}).map(([field, messages]) => (
            <button
              type="button"
              className="error-link"
              key={field}
              onClick={(e) =>
                e.currentTarget.form.elements.namedItem(field)?.focus()
              }
            >
              {field.replaceAll("_", " ")}: {[].concat(messages).join(" ")}
            </button>
          ))}
        </div>
      )}
      {success && (
        <p className="notice success" role="status">
          Saved successfully.
        </p>
      )}
      <fieldset disabled={pending}>
        {typeof children === "function"
          ? children(error?.fields || {})
          : children}
        <div className="form-actions">
          <button type="submit" disabled={pending}>
            {pending ? (
              <>
                <LoaderCircle className="spin" size={16} /> Working…
              </>
            ) : (
              label
            )}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
export const statusOptions = [["", "All statuses"], ...Object.entries(labels)];
export const roleOptions = [
  ["", "All roles"],
  ["client", "Client"],
  ["operator", "Operator"],
  ["admin", "Admin"],
];
