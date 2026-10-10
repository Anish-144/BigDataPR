import { lazy, Suspense, type ReactNode } from "react";
import { Link, Route, Routes, Navigate } from "react-router-dom";
import { Layout } from "./components/layout/Layout";
import { LoadingBlock, EmptyState } from "./components/ui/states";
import Landing from "./pages/Landing";

const Overview = lazy(() => import("./pages/Overview"));
const TestingLab = lazy(() => import("./pages/TestingLab"));
const RunExplorer = lazy(() => import("./pages/RunExplorer"));
const TraceView = lazy(() => import("./pages/TraceView"));
const Performance = lazy(() => import("./pages/Performance"));
const Quality = lazy(() => import("./pages/Quality"));
const Anomalies = lazy(() => import("./pages/Anomalies"));
const Security = lazy(() => import("./pages/Security"));
const SqlAnalytics = lazy(() => import("./pages/SqlAnalytics"));
const Comparison = lazy(() => import("./pages/Comparison"));
const Assistant = lazy(() => import("./pages/Assistant"));
const PipelineHealth = lazy(() => import("./pages/PipelineHealth"));
const Reports = lazy(() => import("./pages/Reports"));

const page = (el: ReactNode) => <Suspense fallback={<LoadingBlock height={240} />}>{el}</Suspense>;

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/app" element={<Layout />}>
        <Route index element={page(<Overview />)} />
        <Route path="testing" element={page(<TestingLab />)} />
        <Route path="runs" element={page(<RunExplorer />)} />
        <Route path="runs/:traceId" element={page(<TraceView />)} />
        <Route path="performance" element={page(<Performance />)} />
        <Route path="quality" element={page(<Quality />)} />
        <Route path="anomalies" element={page(<Anomalies />)} />
        <Route path="security" element={page(<Security />)} />
        <Route path="sql" element={page(<SqlAnalytics />)} />
        <Route path="compare" element={page(<Comparison />)} />
        <Route path="assistant" element={page(<Assistant />)} />
        <Route path="pipeline" element={page(<PipelineHealth />)} />
        <Route path="reports" element={page(<Reports />)} />
        <Route
          path="*"
          element={
            <EmptyState title="Page not found">
              <Link className="link" to="/app">
                Back to overview
              </Link>
            </EmptyState>
          }
        />
      </Route>
      {/* Catch-all redirect to landing */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
