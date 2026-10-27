import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface State {
  error: Error | null;
}

/**
 * Catches a screen that fails to draw, so the window says what happened and offers a way on
 * instead of going blank. A drawing error never touches the library.
 */
export class ScreenError extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <section
        role="alert"
        className="flex animate-fade-up flex-col gap-3 rounded-18 border border-broken/26 bg-broken/7 px-4.5 py-4"
      >
        <p>
          <strong>This screen couldn't be shown.</strong> Nothing in your folders was touched.
        </p>
        <pre className="max-h-40 overflow-auto rounded-12 bg-inset px-3 py-2.5 font-mono text-11 text-fg-muted leading-[1.7]">
          {error.message}
        </pre>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" size="sm" onClick={() => window.location.reload()}>
            Reload Maku
          </Button>
          <Button size="sm" onClick={() => this.setState({ error: null })}>
            Try again
          </Button>
        </div>
      </section>
    );
  }
}
