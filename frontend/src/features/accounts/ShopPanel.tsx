/**
 * The shop's business and tax details.
 *
 * These are not filed away: the GSTIN is what lets a scan tell which party on
 * an invoice is us, and its first two digits decide whether a purchase is
 * CGST+SGST or IGST. The form says so, because a field whose purpose is
 * invisible gets filled in carelessly.
 */

import React, { useEffect, useState } from 'react';
import { Check, Loader2, Store } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface Shop { [key: string]: string | boolean | null | undefined }

const FIELDS: { key: string; label: string; hint?: string; required?: boolean }[] = [
  { key: 'legal_name', label: 'Registered business name', required: true },
  { key: 'trade_name', label: 'Shop name', hint: 'If different from the registered name.' },
  { key: 'gstin', label: 'GSTIN', required: true,
    hint: 'Checked including its check digit. PAN and state are read from it.' },
  { key: 'drug_licence_number', label: 'Drug licence number', hint: '20B / 21B.' },
  { key: 'fssai_number', label: 'FSSAI number', hint: 'Only if you stock nutraceuticals.' },
  { key: 'address_line1', label: 'Address', required: true },
  { key: 'address_line2', label: 'Address line 2' },
  { key: 'city', label: 'City', required: true },
  { key: 'pincode', label: 'PIN code', required: true },
  { key: 'phone', label: 'Phone' },
  { key: 'contact_email', label: 'Contact email' }
];

export const ShopPanel: React.FC = () => {
  const { isSuperAdmin } = useAuth();
  const [shop, setShop] = useState<Shop>({});
  const [missing, setMissing] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = async () => {
    try {
      const r = await fetch('/auth/shop');
      if (!r.ok) throw new Error('Could not load the shop profile.');
      const d = await r.json();
      setShop(d.shop || {});
      setMissing(d.missing || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the shop profile.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true); setError(null); setSaved(false);
    try {
      const body: Record<string, string> = {};
      FIELDS.forEach(({ key }) => {
        const v = shop[key];
        if (typeof v === 'string' && v.trim()) body[key] = v.trim();
      });
      const r = await fetch('/auth/shop', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'Could not save.');
      setShop(d.shop || {});
      setMissing(d.missing || []);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-2xl border border-[#e2e8f0] p-8 shadow-sm flex items-center justify-center text-xs text-gray-400">
        <Loader2 size={14} className="animate-spin mr-2" /> Loading shop profile...
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-4">
      <div className="border-b border-gray-100 pb-3">
        <h3 className="text-sm font-bold text-[#0f172a] flex items-center space-x-2">
          <Store size={15} className="text-[#1b5dfc]" />
          <span>Shop details</span>
        </h3>
        <p className="text-gray-500 text-[11px] mt-0.5">
          Your GSTIN is how a scanned invoice tells your side from the supplier's, and its
          state code is what decides CGST+SGST against IGST.
        </p>
      </div>

      {missing.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-3.5 py-2.5 text-[11px]">
          Still needed before scanning: {missing.join(', ').replace(/_/g, ' ')}
        </div>
      )}
      {shop.state && (
        <div className="bg-blue-50 border border-blue-200 text-blue-800 rounded-xl px-3.5 py-2.5 text-[11px]">
          Read from your GSTIN — PAN <strong>{String(shop.pan)}</strong>, state{' '}
          <strong>{String(shop.state)}</strong>.
        </div>
      )}
      {error && (
        <div role="alert" className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3.5 py-2.5 text-[11px] font-medium">
          {error}
        </div>
      )}
      {saved && !error && (
        <div className="bg-green-50 border border-green-200 text-green-800 rounded-xl px-3.5 py-2.5 text-[11px]">
          Saved.
        </div>
      )}

      <form onSubmit={save} className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {FIELDS.map(({ key, label, hint, required }) => (
            <div key={key} className="space-y-1">
              <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                {label}{required && <span className="text-red-500"> *</span>}
              </label>
              <input
                type="text"
                disabled={!isSuperAdmin}
                value={(shop[key] as string) || ''}
                onChange={(e) => setShop({ ...shop, [key]: e.target.value })}
                className={`w-full border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-blue-500 ${
                  key === 'gstin' ? 'font-mono uppercase' : ''
                } ${isSuperAdmin ? 'bg-white' : 'bg-slate-50 text-gray-500 cursor-not-allowed'}`}
              />
              {hint && <p className="text-[9px] text-gray-400">{hint}</p>}
            </div>
          ))}
        </div>

        {isSuperAdmin ? (
          <button
            type="submit"
            disabled={saving}
            className="bg-[#1b5dfc] hover:bg-blue-700 disabled:opacity-60 text-white font-semibold rounded-lg px-4 py-2 text-[11px] flex items-center space-x-1.5"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            <span>{saving ? 'Saving...' : 'Save shop details'}</span>
          </button>
        ) : (
          <p className="text-[10px] text-gray-400">
            Only a Super Admin can change these.
          </p>
        )}
      </form>
    </div>
  );
};

export default ShopPanel;
