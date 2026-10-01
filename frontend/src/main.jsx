import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  Link,
  Navigate,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
} from "@tanstack/react-query";
import { MotionConfig, motion, useReducedMotion } from "motion/react";
import {
  LayoutDashboard,
  Database,
  ChartNoAxesCombined,
  Users as UsersIcon,
  Plus,
} from "lucide-react";
import { api } from "./api";
import { Heading, Field, Form, ErrorBox, Loading } from "./ui";
import { Dashboard, NewRequest, RequestDetail } from "./requests";
const Episodes = React.lazy(() =>
  import("./staff").then((m) => ({ default: m.Episodes })),
);
const Analytics = React.lazy(() =>
  import("./staff").then((m) => ({ default: m.Analytics })),
);
const Users = React.lazy(() =>
  import("./staff").then((m) => ({ default: m.Users })),
);
import "./styles.css";
import { SessionContext } from "./session";
import { NotificationBell, Notifications } from "./notifications";

const client = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15000, retry: false, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
});
class Boundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <main className="container">
        <h1>We couldn’t display this page</h1>
        <p>Your saved data is safe.</p>
        <button onClick={() => window.location.reload()}>Reload page</button>
      </main>
    ) : (
      this.props.children
    );
  }
}
function Login({ refresh }) {
  return (
    <div className="login-grid">
      <section className="login-story">
        <p className="eyebrow">FROM REQUEST TO READY</p>
        <h1>
          Better data.
          <br />
          Smoother collaboration.
        </h1>
        <p>One workspace to request, prepare and review robotics datasets.</p>
        <ol className="steps">
          <li>Describe the dataset you need</li>
          <li>Track progress with your operations team</li>
          <li>Review and accept your delivery</li>
        </ol>
      </section>
      <section>
        <Heading title="Welcome back">Sign in to your workspace.</Heading>
        <Form
          label="Sign in"
          submit={async (values) => {
            await api("login/", { method: "POST", body: values });
            client.clear();
            await refresh();
          }}
        >
          {(errors) => (
            <>
              <Field
                label="Email"
                name="email"
                type="email"
                required
                maxLength={150}
                autoComplete="username"
                error={errors.email}
              />
              <Password label="Password" autoComplete="current-password" />
            </>
          )}
        </Form>
      </section>
    </div>
  );
}
export function Password({ autoComplete = "new-password", ...props }) {
  const [show, setShow] = useState(false);
  return (
    <>
      <Field
        name="password"
        type={show ? "text" : "password"}
        required
        maxLength={128}
        autoComplete={autoComplete}
        {...props}
      />
      <button
        type="button"
        className="secondary password-toggle"
        aria-pressed={show}
        onClick={() => setShow(!show)}
      >
        {show ? "Hide" : "Show"} password
      </button>
    </>
  );
}
function Guard({ user, roles, children }) {
  return roles.includes(user.role) ? (
    children
  ) : (
    <>
      <Heading title="This page is unavailable">
        Your role does not have access to this workspace.
      </Heading>
      <Link to="/">Back to dashboard</Link>
    </>
  );
}
function App() {
  const identity = useRef(null);
  const [session, setSession] = useState(null),
    [error, setError] = useState(null);
  const navigate = useNavigate(),
    location = useLocation(),
    reduce = useReducedMotion();
  const refresh = async () => {
    const data = await api("session/");
    const nextIdentity = `${data.user?.id}:${data.user?.role}`;
    if (identity.current !== null && identity.current !== nextIdentity)
      client.clear();
    identity.current = nextIdentity;
    setSession(data);
    return data;
  };
  useEffect(() => {
    refresh().catch(setError);
    const expired = () => {
      client.clear();
      setSession((s) => ({ ...s, user: null }));
    };
    window.addEventListener("session-expired", expired);
    const resume = () => {
      if (!document.hidden) refresh().catch(() => {});
    };
    document.addEventListener("visibilitychange", resume);
    return () => {
      window.removeEventListener("session-expired", expired);
      document.removeEventListener("visibilitychange", resume);
    };
  }, []);
  useEffect(() => {
    const page = location.pathname.includes("/notifications")
      ? "Notifications"
      : location.pathname.includes("/requests/new")
        ? "New request"
        : location.pathname.includes("/requests/")
          ? "Request details"
          : location.pathname.includes("/episodes")
            ? "Episodes"
            : location.pathname.includes("/analytics")
              ? "Analytics"
              : location.pathname.includes("/users")
                ? "People & access"
                : location.pathname.includes("/login")
                  ? "Sign in"
                  : "Dashboard";
    document.title = `${page} · Dataset Request Desk`;
    document.getElementById("content")?.focus();
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [location.pathname]);
  const logout = useMutation({
    mutationFn: () => api("logout/", { method: "POST" }),
    onSuccess: async () => {
      client.clear();
      await refresh();
      navigate("/login/", { replace: true });
    },
  });
  if (error)
    return <ErrorBox error={error} retry={() => window.location.reload()} />;
  if (!session) return <Loading />;
  const user = session.user;
  return (
    <SessionContext.Provider value={{ ...session, refresh }}>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="brand" to="/">
            <span className="mark" aria-hidden="true">
              D<span />
            </span>
            <span>
              Dataset Request Desk<small>ROBOTICS DATA OPERATIONS</small>
            </span>
          </Link>
          {user ? (
            <div className="account">
              <span className="avatar">{user.name.slice(0, 1)}</span>
              <span>
                {user.name}
                <small>{user.role} workspace</small>
              </span>
              <button
                className="signout"
                disabled={logout.isPending}
                onClick={() => logout.mutate()}
              >
                {logout.isPending ? "Signing out…" : "Sign out"}
              </button>
            </div>
          ) : (
            <span className="header-note">From request to ready.</span>
          )}
        </div>
        {user && (
          <nav className="main-nav" aria-label="Main navigation">
            <NavLink to="/" end>
              <LayoutDashboard size={17} />
              Dashboard
            </NavLink>
            {user.role === "client" ? (
              <NavLink to="/requests/new/">
                <Plus size={17} />
                New request
              </NavLink>
            ) : (
              <>
                <NavLink to="/episodes/">
                  <Database size={17} />
                  Episodes
                </NavLink>
                <NavLink to="/analytics/">
                  <ChartNoAxesCombined size={17} />
                  Analytics
                </NavLink>
              </>
            )}
            {user.role === "admin" && (
              <NavLink to="/users/">
                <UsersIcon size={17} />
                Users
              </NavLink>
            )}
            <NotificationBell />
            <span className="nav-caption">Your {user.role} workspace</span>
          </nav>
        )}
      </header>
      <main id="content" tabIndex={-1} className="container">
        <ErrorBox error={logout.error} />
        <motion.div
          key={location.pathname}
          initial={reduce ? false : { opacity: 0, y: 7 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18 }}
        >
          {!user ? (
            <Login refresh={refresh} />
          ) : (
            <React.Suspense fallback={<Loading />}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/notifications/" element={<Notifications />} />
                <Route path="/login/" element={<Navigate to="/" replace />} />
                <Route
                  path="/requests/new/"
                  element={
                    <Guard user={user} roles={["client"]}>
                      <NewRequest />
                    </Guard>
                  }
                />
                <Route path="/requests/:id/" element={<RequestDetail />} />
                <Route
                  path="/episodes/"
                  element={
                    <Guard user={user} roles={["operator", "admin"]}>
                      <Episodes />
                    </Guard>
                  }
                />
                <Route
                  path="/analytics/"
                  element={
                    <Guard user={user} roles={["operator", "admin"]}>
                      <Analytics />
                    </Guard>
                  }
                />
                <Route
                  path="/users/"
                  element={
                    <Guard user={user} roles={["admin"]}>
                      <Users />
                    </Guard>
                  }
                />
                <Route
                  path="*"
                  element={
                    <>
                      <Heading title="Page not found" />
                      <Link to="/">Back to dashboard</Link>
                    </>
                  }
                />
              </Routes>
            </React.Suspense>
          )}
        </motion.div>
      </main>
      <footer>
        <span>Dataset Request Desk</span>
        <span>Recording metadata · Kigali time (UTC+2)</span>
      </footer>
    </SessionContext.Provider>
  );
}
createRoot(document.getElementById("react-root")).render(
  <React.StrictMode>
    <Boundary>
      <QueryClientProvider client={client}>
        <MotionConfig reducedMotion="user">
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </MotionConfig>
      </QueryClientProvider>
    </Boundary>
  </React.StrictMode>,
);
