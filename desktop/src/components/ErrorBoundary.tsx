import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** A short label for what crashed, shown to the user (e.g. "Workspace"). */
  boundaryName: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Stage 4 "FRONTEND CRASH BOUNDARY": a rendering error in one page (a bad
 * API response shape, a null a component didn't expect, ...) must not take
 * down the entire renderer -- the sidebar, connection status, and the
 * ability to switch to a different page should all keep working. Wrapping
 * each top-level page individually (see `App.tsx`) means a crash is scoped
 * to "this page is broken", not "the app is broken".
 *
 * The error itself is never sent anywhere automatically (see the Stage 4
 * privacy/local-first principle) -- it is only shown locally and logged to
 * the browser console for local debugging.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Local-only diagnostic (browser devtools), never transmitted anywhere.
    console.error(`[ErrorBoundary:${this.props.boundaryName}]`, error, info.componentStack);
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center" data-testid="error-boundary">
          <AlertTriangle className="size-8 text-destructive" />
          <div>
            <p className="text-sm font-medium">
              A tela "{this.props.boundaryName}" encontrou um erro inesperado.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              O restante do aplicativo continua funcionando. Você pode tentar novamente ou trocar de
              tela pela barra lateral.
            </p>
          </div>
          <Button size="sm" onClick={this.reset}>
            Tentar novamente
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
