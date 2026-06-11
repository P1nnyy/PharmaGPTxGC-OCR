import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { RunProvider } from './context/RunContext';
import { Layout } from './components/Layout';
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
import { ErrorBoundary } from './components/ErrorBoundary';
import './App.css';

export const App: React.FC = () => {
  return (
    <Router>
      <RunProvider>
        <Layout>
          <ErrorBoundary>
            <Routes>
              <Route path="/runs" element={<RunsPage />} />
              <Route path="/debugger/:runId" element={<DebuggerPage />} />
              <Route path="/candidate-tables/:runId" element={<CandidateTablesPage />} />
              <Route path="/ocr-tokens/:runId" element={<OcrTokensPage />} />
              <Route path="/selected-table/:runId" element={<SelectedTablePage />} />
              <Route path="/semantic-mapping/:runId" element={<SemanticMappingPage />} />
              <Route path="/row-math/:runId" element={<RowMathPage />} />
              <Route path="/quality-gate/:runId" element={<QualityGatePage />} />
              <Route path="/artifacts/:runId" element={<ArtifactsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              
              {/* Catch-all redirects to runs */}
              <Route path="*" element={<Navigate to="/runs" replace />} />
            </Routes>
          </ErrorBoundary>
        </Layout>
      </RunProvider>
    </Router>
  );
};

export default App;
