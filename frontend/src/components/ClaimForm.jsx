// Sidebar claim entry: sample-claim chips (loaded from the real evaluation dataset)
// plus the editable fields that make up a First Notice of Loss.

export default function ClaimForm({ meta, claim, onChange, onSubmit, busy }) {
  const set = (field) => (e) => onChange({ ...claim, [field]: e.target.value });

  const applySample = (sample, i) =>
    onChange({
      ...claim,
      claim_id: `WEB-${String(i + 1).padStart(4, "0")}`,
      policy_id: sample.policy_id,
      loss_type: sample.loss_type,
      estimated_amount: sample.estimated_amount,
      incident_date: sample.incident_date,
      reported_date: sample.reported_date,
      description: sample.description,
    });

  return (
    <aside className="sidebar">
      <div className="sidebar-scroll">
        <p className="section-title">Sample claims</p>
        <div className="samples">
          {(meta.samples || []).map((s, i) => (
            <button key={i} className="chip" type="button" onClick={() => applySample(s, i)}>
              {s.loss_type.replace(/_/g, " ")} · ${Number(s.estimated_amount).toLocaleString()}
            </button>
          ))}
        </div>

        <p className="section-title">Claim details</p>

        <div className="field">
          <label htmlFor="policy">Policy</label>
          <select id="policy" value={claim.policy_id} onChange={set("policy_id")}>
            {(meta.policies || []).map((p) => (
              <option key={p.policy_id} value={p.policy_id}>
                {p.policy_id} — {p.product}
                {p.status !== "active" ? ` (${p.status})` : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="loss">Loss type</label>
          <select id="loss" value={claim.loss_type} onChange={set("loss_type")}>
            {(meta.loss_types || []).map((l) => (
              <option key={l} value={l}>{l.replace(/_/g, " ")}</option>
            ))}
          </select>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="amount">Estimated amount ($)</label>
            <input id="amount" type="number" min="0"
                   value={claim.estimated_amount} onChange={set("estimated_amount")} />
          </div>
          <div className="field">
            <label htmlFor="claimid">Claim ID</label>
            <input id="claimid" value={claim.claim_id} onChange={set("claim_id")} />
          </div>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="incident">Incident date</label>
            <input id="incident" type="date"
                   value={claim.incident_date} onChange={set("incident_date")} />
          </div>
          <div className="field">
            <label htmlFor="reported">Reported date</label>
            <input id="reported" type="date"
                   value={claim.reported_date} onChange={set("reported_date")} />
          </div>
        </div>

        <div className="field">
          <label htmlFor="desc">Description</label>
          <textarea id="desc" value={claim.description} onChange={set("description")} />
        </div>
      </div>

      <div className="sidebar-foot">
        <button className="send" type="button" onClick={onSubmit} disabled={busy}>
          {busy ? "Assessing…" : "Triage claim"}
        </button>
      </div>
    </aside>
  );
}
