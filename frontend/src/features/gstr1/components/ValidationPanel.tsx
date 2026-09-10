import React from 'react';
import { ExternalLink } from 'lucide-react';

import { AllClear, Card, SeverityChip, Td, Table, Th } from './Primitives';
import type { ValidationItem } from '../types';

// Where a validation item points. A message with no route back to the record
// is a message somebody has to go hunting behind, so every item that names a
// record gets a link - and the ones that name a whole period or the shop
// profile say so instead of rendering a dead link.
const linkFor = (item: ValidationItem): string | null => {
  if (!item.record_id) return null;
  switch (item.record_type) {
    case 'SALE':
    case 'SALE_LINE':
      return `/invoices/${item.record_id}`;
    case 'PHARMACY':
      return '/settings';
    default:
      return null;
  }
};

const RecordLink: React.FC<{ item: ValidationItem }> = ({ item }) => {
  const href = linkFor(item);
  if (!href) {
    return <span className="text-[11px] text-gray-400">{item.record_type.toLowerCase()}</span>;
  }
  return (
    <a
      href={href}
      className="inline-flex items-center gap-1 text-[11px] font-medium text-[#1b5dfc] hover:underline"
    >
      Open <ExternalLink size={11} aria-hidden />
    </a>
  );
};

export const ValidationPanel: React.FC<{
  blocking: ValidationItem[];
  warnings: ValidationItem[];
  acknowledged: Set<string>;
  onToggle: (id: string) => void;
  readOnly: boolean;
}> = ({ blocking, warnings, acknowledged, onToggle, readOnly }) => {
  const outstanding = blocking.filter((item) => !acknowledged.has(item.id));

  return (
    <Card
      title="Before this period can close"
      subtitle={
        blocking.length === 0 && warnings.length === 0
          ? 'Nothing outstanding.'
          : `${outstanding.length} of ${blocking.length} blocking ${
              blocking.length === 1 ? 'item' : 'items'
            } outstanding, ${warnings.length} ${warnings.length === 1 ? 'warning' : 'warnings'}.`
      }
    >
      {blocking.length === 0 && warnings.length === 0 ? (
        <AllClear>Every check passed. This period is ready to close.</AllClear>
      ) : (
        <div className="flex flex-col gap-6">
          {blocking.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-3">
                A GSTR-1 cannot be revised, so these would each go out wrong and need an
                amendment. Tick one only if you have checked it and it is correct as it
                stands — the acknowledgement is recorded against the period.
              </p>
              <Table
                head={
                  <>
                    <Th>{readOnly ? '' : 'Accept'}</Th>
                    <Th>Severity</Th>
                    <Th>What is wrong</Th>
                    <Th>Record</Th>
                  </>
                }
              >
                {blocking.map((item) => (
                  <tr key={item.id} className="align-top">
                    <Td>
                      {!readOnly && item.acknowledgeable && (
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={acknowledged.has(item.id)}
                          onChange={() => onToggle(item.id)}
                          aria-label={`Accept: ${item.message}`}
                        />
                      )}
                    </Td>
                    <Td>
                      <SeverityChip severity={item.severity} />
                    </Td>
                    <Td className="max-w-xl">
                      <span className="text-[#0f172a]">{item.message}</span>
                      <span className="block text-[10px] text-gray-400 mt-0.5 font-mono">
                        {item.code}
                      </span>
                    </Td>
                    <Td>
                      <RecordLink item={item} />
                    </Td>
                  </tr>
                ))}
              </Table>
            </div>
          )}

          {warnings.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-3">
                These do not stop the return. They are worth looking at because each one
                costs more to fix later than it does now.
              </p>
              <Table
                head={
                  <>
                    <Th>Severity</Th>
                    <Th>What to look at</Th>
                    <Th>Record</Th>
                  </>
                }
              >
                {warnings.map((item) => (
                  <tr key={item.id} className="align-top">
                    <Td>
                      <SeverityChip severity={item.severity} />
                    </Td>
                    <Td className="max-w-xl">
                      <span className="text-[#0f172a]">{item.message}</span>
                      <span className="block text-[10px] text-gray-400 mt-0.5 font-mono">
                        {item.code}
                      </span>
                    </Td>
                    <Td>
                      <RecordLink item={item} />
                    </Td>
                  </tr>
                ))}
              </Table>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};
