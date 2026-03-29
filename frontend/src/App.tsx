import { useEffect, useState, useCallback } from "react";
import { Dashboard } from "./components/Dashboard";
import { UpdateFallback } from "./components/UpdateFallback";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useStore } from "./store/useStore";
import { useFeaturesStore } from "./store/featuresStore";
import { fetchInterfaces, fetchLLMStatus } from "./lib/api";

function App() {
  const { setInterfaces, setLLMStatus, llmBackend, theme } = useStore();
  const loadFeatures = useFeaturesStore((s) => s.loadFeatures);

  useEffect(() => { loadFeatures(); }, [loadFeatures]);

  // ---------------------------------------------------------------------------
  // Apply dark class to <html> so Tailwind + CSS variables react
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  // ---------------------------------------------------------------------------
  // Update-failure fallback state
  // ---------------------------------------------------------------------------
  const [updateFailed, setUpdateFailed]   = useState(false);
  const [failureReason, setFailureReason] = useState("");

  const handleUpdateFailed = useCallback((reason: string) => {
    setUpdateFailed(true);
    setFailureReason(reason);
  }, []);

  const handleRecovered = useCallback(() => {
    setUpdateFailed(false);
    setFailureReason("");
  }, []);

  // ---------------------------------------------------------------------------
  // Normal startup effects
  // ---------------------------------------------------------------------------
  useEffect(() => {
    fetchInterfaces()
      .then(setInterfaces)
      .catch(() => console.warn("Could not fetch interfaces — is the backend running?"));

    fetchLLMStatus()
      .then(setLLMStatus)
      .catch(() => console.warn("LLM backend not reachable"));

    const interval = setInterval(() => {
      fetchLLMStatus().then(setLLMStatus).catch(() => {});
    }, 15000);

    return () => clearInterval(interval);
  }, [llmBackend, setInterfaces, setLLMStatus]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (updateFailed) {
    return (
      <UpdateFallback
        reason={failureReason}
        onRecovered={handleRecovered}
        autoRetrySeconds={15}
      />
    );
  }

  return (
    <ErrorBoundary label="NetScope">
      <Dashboard onUpdateFailed={handleUpdateFailed} />
    </ErrorBoundary>
  );
}

export default App;
