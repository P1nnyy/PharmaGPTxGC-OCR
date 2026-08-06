import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, Trash2, Check, Lock, AlertTriangle, Package } from 'lucide-react';
import { apiClient } from '../api/client';
import type { ItemType, ItemTypesResponse } from '../api/types';

/**
 * The catalogue's vocabulary, made editable.
 *
 * An item type is what a product IS — tablet, cream, respule — and it carries
 * the units that product can be measured in. That list used to be hardcoded in
 * five places that had to be edited together, so a pharmacy stocking anything
 * the original list didn't anticipate had no way to say so.
 *
 * Two rules the UI has to make legible, because both protect existing data:
 * built-in types can be switched off but never deleted or renamed (products
 * name their type, so removing one would strand every product using it), and a
 * custom type still in use can't be deleted either. "Switch off" is what
 * "stop offering this" actually means here.
 */

const emptyDraft = {
  name: '',
  supported_units: [] as string[],
  base_unit: '',
  single_container: false,
};

export const ItemTypesPanel: React.FC = () => {
  const [data, setData] = useState<ItemTypesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ ...emptyDraft });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Inactive types are included: this is the screen where you switch one
      // back on, so hiding them here would make that impossible.
      setData(await apiClient.listItemTypes(true));
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Failed to load item types.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const units = data?.known_units ?? [];
  const countUnits = useMemo(() => new Set(data?.count_units ?? []), [data]);

  const flash = (message: string) => {
    setNotice(message);
    setTimeout(() => setNotice(null), 3000);
  };

  const startCreate = () => {
    setDraft({ ...emptyDraft });
    setCreating(true);
    setEditingId(null);
    setError(null);
  };

  const startEdit = (type: ItemType) => {
    setDraft({
      name: type.name,
      supported_units: [...type.supported_units],
      base_unit: type.base_unit,
      single_container: type.single_container,
    });
    setEditingId(type.id);
    setCreating(false);
    setError(null);
  };

  const cancel = () => { setCreating(false); setEditingId(null); setError(null); };

  const toggleUnit = (unit: string) => {
    setDraft((prev) => {
      const has = prev.supported_units.includes(unit);
      const next = has
        ? prev.supported_units.filter((u) => u !== unit)
        : [...prev.supported_units, unit];
      // The dispensing unit has to stay one of the supported ones, or the
      // product form would offer a default it then refuses to save.
      const base = next.includes(prev.base_unit) ? prev.base_unit : (next[0] ?? '');
      return { ...prev, supported_units: next, base_unit: base };
    });
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (creating) {
        await apiClient.createItemType(draft);
        flash(`"${draft.name}" added.`);
      } else if (editingId) {
        await apiClient.updateItemType(editingId, draft);
        flash(`"${draft.name}" saved.`);
      }
      cancel();
      await load();
    } catch (e: any) {
      setError(e.message || 'Save failed.');
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (type: ItemType) => {
    setBusy(true);
    try {
      await apiClient.updateItemType(type.id, { active: !type.active });
      flash(type.active
        ? `"${type.name}" switched off — it stays on existing products but is no longer offered.`
        : `"${type.name}" switched back on.`);
      await load();
    } catch (e: any) {
      setError(e.message || 'Failed to update.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (type: ItemType) => {
    if (!window.confirm(`Delete the item type "${type.name}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await apiClient.deleteItemType(type.id);
      flash(`"${type.name}" deleted.`);
      await load();
    } catch (e: any) {
      // The server says why — built-in, or N products still using it — and
      // that reason names the way out, so it is shown verbatim.
      setError(e.message || 'Failed to delete.');
    } finally {
      setBusy(false);
    }
  };

  const canSave = draft.name.trim().length > 0 && draft.supported_units.length > 0;

  const editor = (
    <div className="bg-[#f8fafc] border border-[#cbd5e1] rounded-xl p-4 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block">
            Item type name
          </label>
          <input
            autoFocus
            value={draft.name}
            disabled={!creating && data?.item_types.find((t) => t.id === editingId)?.builtin}
            onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g. Surgical Consumable"
            className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a] disabled:bg-slate-100 disabled:text-gray-400 disabled:cursor-not-allowed"
          />
          {!creating && data?.item_types.find((t) => t.id === editingId)?.builtin && (
            <p className="text-[10px] text-gray-400">
              Built-in types keep their name — products refer to it.
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block">
            Dispensing unit
          </label>
          <select
            value={draft.base_unit}
            onChange={(e) => setDraft((p) => ({ ...p, base_unit: e.target.value }))}
            className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-[#0f172a]"
          >
            {draft.supported_units.length === 0 && <option value="">Pick units below first</option>}
            {draft.supported_units.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
          <p className="text-[10px] text-gray-400">The one stock is counted in by default.</p>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block">
          Units this type can be measured in
        </label>
        <div className="flex flex-wrap gap-1.5">
          {units.map((unit) => {
            const on = draft.supported_units.includes(unit);
            return (
              <button
                key={unit}
                type="button"
                onClick={() => toggleUnit(unit)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition-colors cursor-pointer ${
                  on
                    ? 'bg-[#1b5dfc] text-white border-[#1b5dfc]'
                    : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
                }`}
                title={countUnits.has(unit) ? 'Counts dispensable items' : 'Measures container contents'}
              >
                {unit}
              </button>
            );
          })}
        </div>
        <p className="text-[10px] text-gray-400">
          Blue units are offered on products of this type. Most types need one; creams and
          ointments often need both GM and ML.
        </p>
      </div>

      <label className="flex items-start gap-2.5 cursor-pointer">
        <input
          type="checkbox"
          checked={draft.single_container}
          onChange={(e) => setDraft((p) => ({ ...p, single_container: e.target.checked }))}
          className="mt-0.5 accent-[#1b5dfc]"
        />
        <span className="text-[11px] text-gray-600 leading-relaxed">
          <span className="font-semibold text-[#0f172a]">Sold as a single container.</span>{' '}
          Tick this when the pack size is how much is inside one container, not how many
          items it holds — a 100 ML lotion is one bottle. Leave it off for tablets and
          capsules, where a strip really does hold a countable number.
        </span>
      </label>

      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          onClick={cancel}
          className="bg-white hover:bg-slate-50 text-gray-600 font-semibold px-4 py-2 rounded-lg text-xs border border-gray-200 cursor-pointer"
        >
          Cancel
        </button>
        <button
          onClick={save}
          disabled={!canSave || busy}
          className="bg-[#1b5dfc] hover:bg-[#154ecb] disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold px-4 py-2 rounded-lg text-xs flex items-center gap-1.5 cursor-pointer"
        >
          <Check size={13} />
          {creating ? 'Add item type' : 'Save changes'}
        </button>
      </div>
    </div>
  );

  return (
    <div className="bg-white rounded-2xl border border-[#e2e8f0] p-6 shadow-sm space-y-5">
      <div className="flex items-start justify-between border-b border-gray-100 pb-4">
        <div>
          <h3 className="text-sm font-bold text-[#0f172a] flex items-center gap-2">
            <Package size={15} className="text-[#1b5dfc]" />
            Item Types &amp; Units
          </h3>
          <p className="text-gray-500 text-[11px] mt-0.5 max-w-xl">
            What a product can be, and the units it is measured in. Products offer only the
            units their type supports, so a cream cannot be recorded in tablets.
          </p>
        </div>
        <button
          onClick={startCreate}
          disabled={creating}
          className="shrink-0 bg-[#1b5dfc] hover:bg-[#154ecb] disabled:opacity-40 text-white font-semibold px-3.5 py-2 rounded-lg text-xs flex items-center gap-1.5 cursor-pointer"
        >
          <Plus size={14} />
          New type
        </button>
      </div>

      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg px-3 py-2 text-[11px] font-medium flex items-center gap-2">
          <Check size={13} /> {notice}
        </div>
      )}
      {error && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2 text-[11px] font-medium flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {creating && editor}

      {loading ? (
        <p className="text-xs text-gray-400 py-8 text-center">Loading item types…</p>
      ) : (
        <div className="divide-y divide-gray-100 border border-gray-100 rounded-xl overflow-hidden">
          {(data?.item_types ?? []).map((type) =>
            editingId === type.id ? (
              <div key={type.id} className="p-3">{editor}</div>
            ) : (
              <div
                key={type.id}
                className={`flex items-center gap-3 px-4 py-3 hover:bg-slate-50/70 transition-colors ${
                  type.active ? '' : 'opacity-55'
                }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-[#0f172a]">{type.name}</span>
                    {type.builtin && (
                      <span
                        title="Built in — can be switched off, but not renamed or deleted"
                        className="inline-flex items-center gap-1 text-[9px] font-bold text-gray-400 uppercase tracking-wider"
                      >
                        <Lock size={9} /> built-in
                      </span>
                    )}
                    {!type.active && (
                      <span className="text-[9px] font-bold text-amber-600 uppercase tracking-wider">
                        switched off
                      </span>
                    )}
                    {type.single_container && (
                      <span
                        title="Pack size is the container's size, not a count"
                        className="text-[9px] font-bold text-sky-600 uppercase tracking-wider"
                      >
                        single container
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                    {type.supported_units.map((unit) => (
                      <span
                        key={unit}
                        className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                          unit === type.base_unit
                            ? 'bg-blue-50 text-[#1b5dfc] font-bold'
                            : 'bg-slate-100 text-gray-500'
                        }`}
                      >
                        {unit}
                      </span>
                    ))}
                    <span className="text-[10px] text-gray-300 ml-1">
                      {type.base_unit} is the default
                    </span>
                  </div>
                </div>

                <button
                  onClick={() => startEdit(type)}
                  className="text-[11px] font-semibold text-[#1b5dfc] hover:text-[#154ecb] px-2 cursor-pointer"
                >
                  Edit
                </button>
                <button
                  onClick={() => toggleActive(type)}
                  disabled={busy}
                  title={type.active ? 'Stop offering this type on products' : 'Offer this type again'}
                  className="text-[11px] font-semibold text-gray-500 hover:text-[#0f172a] px-2 cursor-pointer"
                >
                  {type.active ? 'Switch off' : 'Switch on'}
                </button>
                <button
                  onClick={() => remove(type)}
                  disabled={busy || type.builtin}
                  title={type.builtin ? 'Built-in types cannot be deleted — switch it off instead' : 'Delete'}
                  className="text-gray-300 hover:text-red-500 disabled:hover:text-gray-200 disabled:opacity-40 disabled:cursor-not-allowed px-1 cursor-pointer"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            )
          )}
          {(data?.item_types.length ?? 0) === 0 && (
            <p className="text-xs text-gray-400 py-8 text-center">
              No item types yet. Add the first one above.
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default ItemTypesPanel;
