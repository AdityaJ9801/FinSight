import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./styles.css";
import "./features.css";
import "./polish.css";
import "./statements.css";
import { Shell } from "./components/Shell";
import { FeedbackProvider } from "./components/feedback";
import { NewAnalysisPage } from "./pages/NewAnalysis";
import { AnalysesPage } from "./pages/Analyses";
import { JobPage } from "./pages/Job";
import { SettingsPage } from "./pages/Settings";
import { ComparePage } from "./pages/Compare";
import { EmptyState } from "./components/ui";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <FeedbackProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<NewAnalysisPage />} />
              <Route path="analyses" element={<AnalysesPage />} />
              <Route path="analyses/:jobId" element={<JobPage />} />
              <Route path="compare" element={<ComparePage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<div className="page"><EmptyState title="Page not found">That address doesn't match anything in FinSight.</EmptyState></div>} />
            </Route>
          </Routes>
        </BrowserRouter>
      </FeedbackProvider>
    </QueryClientProvider>
  </StrictMode>,
);
