import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { RunProvider } from './context/RunContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { JoinPage } from './features/auth/JoinPage';
import { ErrorBoundary } from './components/ErrorBoundary';

// Layouts
import { Layout } from './components/Layout';
import { SaaSLayout } from './components/SaaSLayout';

// New User-Facing Pages
import { DashboardPage } from './pages/DashboardPage';
import { UploadInvoicePage } from './pages/UploadInvoicePage';
import { InvoiceReviewPage } from './pages/InvoiceReviewPage';
import { InvoiceHistoryPage } from './pages/InvoiceHistoryPage';
import { ProductsPage } from './pages/ProductsPage';
import { InventoryPage } from './pages/InventoryPage';
import { ReportsPage } from './features/reports';
import { Gstr1Page } from './features/gstr1';
import { StatutoryPage } from './features/statutory';
import { SaaSSettingsPage } from './pages/SaaSSettingsPage';

// Old Developer Pages (under debug route)
import { RunsPage } from './pages/RunsPage';
import { DebuggerPage } from './pages/DebuggerPage';
import { CandidateTablesPage } from './pages/CandidateTablesPage';
import { OcrTokensPage } from './pages/OcrTokensPage';
import { SelectedTablePage } from './pages/SelectedTablePage';
import { SemanticMappingPage } from './pages/SemanticMappingPage';
import { RowMathPage } from './pages/RowMathPage';
import { QualityGatePage } from './pages/QualityGatePage';
import { ArtifactsPage } from './pages/ArtifactsPage';
import { SettingsPage } from './pages/SettingsPage';

import './App.css';


/**
 * Held blank only while the stored token is being checked.
 *
 * Signing in is no longer required to *look* at the application - the pages
 * render and can be browsed, and every data endpoint returns 401 until
 * someone signs in, so there is nothing behind the empty states to leak. The
 * sign-in dialog lives in the layout, over whatever page you were on.
 */
const AuthGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-[#f4f5fa] flex items-center justify-center">
        <div className="text-xs text-gray-400 font-medium">Loading...</div>
      </div>
    );
  }
  return <>{children}</>;
};

export const App: React.FC = () => {
  return (
    <Router>
      <AuthProvider>
        <ErrorBoundary>
          <AuthGate>
            {/* Mounted inside the gate, not outside it: RunProvider fetches
                the invoice list as soon as it mounts, and outside the gate
                that request goes out before anyone has signed in - returning
                401 and leaving the app showing zero invoices to a user who
                has plenty. */}
            <RunProvider>
          <Routes>
            {/* User-facing SaaS portal paths wrapped in SaaSLayout */}
            <Route
              path="/"
              element={
                <SaaSLayout>
                  <DashboardPage />
                </SaaSLayout>
              }
            />
            <Route
              path="/dashboard"
              element={
                <SaaSLayout>
                  <DashboardPage />
                </SaaSLayout>
              }
            />
            <Route
              path="/upload"
              element={
                <SaaSLayout>
                  <UploadInvoicePage />
                </SaaSLayout>
              }
            />
            <Route
              path="/review/:runId"
              element={
                <SaaSLayout>
                  <InvoiceReviewPage />
                </SaaSLayout>
              }
            />
            <Route
              path="/history"
              element={
                <SaaSLayout>
                  <InvoiceHistoryPage />
                </SaaSLayout>
              }
            />
            {/* Page route is /catalogue, not /products: the backend already
                owns /products, and both the dev proxy and the production
                server would resolve a shared path to the API and hand the
                browser raw JSON instead of the page. Page routes and API
                paths are kept distinct throughout (/history vs /invoices). */}
            <Route
              path="/catalogue"
              element={
                <SaaSLayout>
                  <ProductsPage />
                </SaaSLayout>
              }
            />
            <Route
              path="/inventory"
              element={
                <SaaSLayout>
                  <InventoryPage />
                </SaaSLayout>
              }
            />
            <Route
              path="/reports"
              element={
                <SaaSLayout>
                  <ReportsPage />
                </SaaSLayout>
              }
            />
            <Route
              path="/gst-returns"
              element={
                <SaaSLayout>
                  <Gstr1Page />
                </SaaSLayout>
              }
            />
            <Route
              path="/statutory-reports"
              element={
                <SaaSLayout>
                  <StatutoryPage />
                </SaaSLayout>
              }
            />
            <Route
              path="/settings"
              element={
                <SaaSLayout>
                  <SaaSSettingsPage />
                </SaaSLayout>
              }
            />

            {/* Old visual developer debug tools path wrapped in Layout */}
            <Route
              path="/debug/runs"
              element={
                <Layout>
                  <RunsPage />
                </Layout>
              }
            />
            <Route
              path="/debug/debugger/:runId"
              element={
                <Layout>
                  <DebuggerPage />
                </Layout>
              }
            />
            <Route
              path="/debug/candidate-tables/:runId"
              element={
                <Layout>
                  <CandidateTablesPage />
                </Layout>
              }
            />
            <Route
              path="/debug/ocr-tokens/:runId"
              element={
                <Layout>
                  <OcrTokensPage />
                </Layout>
              }
            />
            <Route
              path="/debug/selected-table/:runId"
              element={
                <Layout>
                  <SelectedTablePage />
                </Layout>
              }
            />
            <Route
              path="/debug/semantic-mapping/:runId"
              element={
                <Layout>
                  <SemanticMappingPage />
                </Layout>
              }
            />
            <Route
              path="/debug/row-math/:runId"
              element={
                <Layout>
                  <RowMathPage />
                </Layout>
              }
            />
            <Route
              path="/debug/quality-gate/:runId"
              element={
                <Layout>
                  <QualityGatePage />
                </Layout>
              }
            />
            <Route
              path="/debug/artifacts/:runId"
              element={
                <Layout>
                  <ArtifactsPage />
                </Layout>
              }
            />
            <Route
              path="/debug/settings"
              element={
                <Layout>
                  <SettingsPage />
                </Layout>
              }
            />

            {/* Retro-compatibility redirects for old routing */}
            <Route path="/runs" element={<Navigate to="/debug/runs" replace />} />
            <Route path="/debugger/:runId" element={<Navigate to="/debug/debugger/:runId" replace />} />
            <Route path="/candidate-tables/:runId" element={<Navigate to="/debug/candidate-tables/:runId" replace />} />
            <Route path="/ocr-tokens/:runId" element={<Navigate to="/debug/ocr-tokens/:runId" replace />} />
            <Route path="/selected-table/:runId" element={<Navigate to="/debug/selected-table/:runId" replace />} />
            <Route path="/semantic-mapping/:runId" element={<Navigate to="/debug/semantic-mapping/:runId" replace />} />
            <Route path="/row-math/:runId" element={<Navigate to="/debug/row-math/:runId" replace />} />
            <Route path="/quality-gate/:runId" element={<Navigate to="/debug/quality-gate/:runId" replace />} />
            <Route path="/artifacts/:runId" element={<Navigate to="/debug/artifacts/:runId" replace />} />

            {/* Invitation acceptance. Deliberately outside SaaSLayout: the
                visitor is not a member yet, so the workspace's navigation
                would be showing them something they cannot open. */}
            <Route path="/join/:token" element={<JoinPage />} />

            {/* Catch-all redirect to user dashboard */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
            </RunProvider>
          </AuthGate>
        </ErrorBoundary>
      </AuthProvider>
    </Router>
  );
};

export default App;

