import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { RunProvider } from './context/RunContext';
import { ErrorBoundary } from './components/ErrorBoundary';

// Layouts
import { Layout } from './components/Layout';
import { SaaSLayout } from './components/SaaSLayout';

// New User-Facing Pages
import { DashboardPage } from './pages/DashboardPage';
import { UploadInvoicePage } from './pages/UploadInvoicePage';
import { InvoiceReviewPage } from './pages/InvoiceReviewPage';
import { InvoiceHistoryPage } from './pages/InvoiceHistoryPage';
import { InventoryPage } from './pages/InventoryPage';
import { ReportsPage } from './pages/ReportsPage';
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

export const App: React.FC = () => {
  return (
    <Router>
      <RunProvider>
        <ErrorBoundary>
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

            {/* Catch-all redirect to user dashboard */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </ErrorBoundary>
      </RunProvider>
    </Router>
  );
};

export default App;

