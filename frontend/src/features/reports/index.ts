// Public surface of the reports feature.
//
// Everything outside this folder imports from here, so the internal layout
// (api / components / hooks) can move without touching callers. This is the
// pattern the other pages should migrate to as they are worked on.

export { ReportsPage } from './ReportsPage';
export { reportsApi } from './api';
export type { PeriodQuery, Period, Summary, SpendTrend, ExpiryExposure } from './types';
