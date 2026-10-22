import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Changing this value (e.g. the route) clears a previous error. */
  resetKey?: string;
  /** Route shown in the message; defaults to the current location. */
  route?: string;
}

interface State {
  error: Error | null;
  stack: string;
}

/** Keeps a render error in one view from unmounting the whole app (black screen). */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, stack: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("View crashed:", error, info.componentStack);
    this.setState({ stack: (info.componentStack ?? "").split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 6).join("\n") });
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null, stack: "" });
  }

  render(): ReactNode {
    const { error, stack } = this.state;
    if (!error) return this.props.children;
    const route = this.props.route ?? (typeof window === "undefined" ? "" : window.location.pathname + window.location.search);
    return (
      <section className="panel error-boundary" role="alert" aria-labelledby="eb-h">
        <h2 id="eb-h">Something went wrong showing this view</h2>
        <p>
          The data was received but this view could not be drawn. Nothing was changed. You can go back or reload; if it keeps happening, report the message below.
        </p>
        <pre className="error-detail">{`${error.message}\nRoute: ${route}${stack ? `\nComponents:\n${stack}` : ""}`}</pre>
        <p>
          <button type="button" className="btn" onClick={() => window.history.back()}>
            Back
          </button>{" "}
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
            Reload
          </button>
        </p>
      </section>
    );
  }
}
