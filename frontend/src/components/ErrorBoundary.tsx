import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  /** Optional label shown in the error card to help identify which section crashed */
  label?: string;
}

interface State {
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * ErrorBoundary catches unhandled React render errors and shows a recovery
 * card instead of crashing the entire application.
 *
 * Usage:
 *   <ErrorBoundary label="Chat">
 *     <ChatBox />
 *   </ErrorBoundary>
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo });
    console.error("[ErrorBoundary] Caught error:", error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ error: null, errorInfo: null });
  };

  render() {
    if (this.state.error) {
      const { label = "This section" } = this.props;
      return (
        <div className="flex flex-col items-center justify-center h-full min-h-[200px] p-6 text-center">
          <AlertTriangle className="w-10 h-10 text-red-400 mb-3" />
          <p className="text-red-300 font-semibold mb-1">
            {label} encountered an error
          </p>
          <p className="text-gray-400 text-sm mb-4 max-w-md">
            {this.state.error.message}
          </p>
          <button
            onClick={this.handleReset}
            className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm transition-colors"
            aria-label="Retry rendering this section"
          >
            <RefreshCw className="w-4 h-4" />
            Try again
          </button>
          {import.meta.env.DEV && this.state.errorInfo && (
            <details className="mt-4 text-left text-xs text-gray-500 max-w-xl">
              <summary className="cursor-pointer">Stack trace</summary>
              <pre className="mt-2 overflow-auto whitespace-pre-wrap">
                {this.state.errorInfo.componentStack}
              </pre>
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
