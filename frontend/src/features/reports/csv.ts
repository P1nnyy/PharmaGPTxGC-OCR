// CSV export.
//
// The GST register is the reason this exists: it is pulled monthly and handed
// to an accountant or fed into GSTR-2B reconciliation, so the export needs to
// be a real file with a stable column order, not a screenshot of a table.

type Cell = string | number | boolean | null | undefined;

/**
 * Escapes one cell for CSV.
 *
 * Values are always quoted rather than only when they contain a comma: invoice
 * numbers routinely carry leading zeros and slashes, and an unquoted `007/26`
 * is reformatted by spreadsheet software on open.
 */
function escapeCell(value: Cell): string {
  if (value === null || value === undefined) return '""';
  return `"${String(value).replace(/"/g, '""')}"`;
}

export interface CsvColumn<T> {
  header: string;
  value: (row: T) => Cell;
}

export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const header = columns.map((column) => escapeCell(column.header)).join(',');
  const body = rows.map((row) => columns.map((column) => escapeCell(column.value(row))).join(','));
  return [header, ...body].join('\n');
}

/**
 * Triggers a download of `content` as `filename`.
 *
 * Uses a Blob rather than a `data:` URI: the register for a busy month exceeds
 * the URL length limit browsers enforce on data URIs, and the download fails
 * silently once it does.
 */
export function downloadCsv(filename: string, content: string): void {
  // The BOM makes Excel read the file as UTF-8; without it the rupee sign and
  // any non-ASCII supplier name arrive mangled.
  const blob = new Blob([`﻿${content}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** `PharmaGPT_GST_Register_FY-2026-27.csv` — period in the name, so a folder
 * of exports stays sortable and self-describing. */
export function reportFilename(report: string, periodLabel: string): string {
  const slug = periodLabel.replace(/[^\w-]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
  return `PharmaGPT_${report}_${slug}.csv`;
}
