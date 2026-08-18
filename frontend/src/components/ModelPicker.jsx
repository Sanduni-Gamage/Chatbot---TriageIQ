// Header control for choosing which model runs the next triage.
//
// Free tiers meter quota per model, so being able to switch mid-demo is practical, not just a
// nicety — when one model is exhausted, another usually still has allowance.

export default function ModelPicker({ providers, selection, onChange, mock }) {
  if (mock) {
    return <span className="badge">MOCK · no API key</span>;
  }
  if (!providers.length) {
    return <span className="badge">…</span>;
  }

  const multiProvider = providers.length > 1;
  const current = providers.find((p) => p.provider === selection.provider) || providers[0];

  const pickProvider = (e) => {
    const provider = e.target.value;
    const next = providers.find((p) => p.provider === provider);
    onChange({ provider, model: next?.models?.[0] });
  };

  return (
    <div className="model-picker">
      <span className="badge live">LIVE</span>

      {multiProvider && (
        <select
          className="picker"
          value={selection.provider}
          onChange={pickProvider}
          title="Model provider"
        >
          {providers.map((p) => (
            <option key={p.provider} value={p.provider}>{p.provider}</option>
          ))}
        </select>
      )}

      <select
        className="picker wide"
        value={selection.model}
        onChange={(e) => onChange({ ...selection, model: e.target.value })}
        title="Model used for the next triage"
      >
        {(current.models || []).map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    </div>
  );
}
