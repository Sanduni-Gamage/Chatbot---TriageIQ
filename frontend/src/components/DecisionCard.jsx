// Renders a TriageDecision: routing badge, key facts, the cited policy clause,
// fraud signals, rationale, and run metadata (tool calls / latency / cost).

const QUEUE_LABEL = {
  FAST_TRACK: "Fast track",
  STANDARD: "Standard",
  INVESTIGATE: "Investigate",
  SIU: "SIU — fraud",
};

export default function DecisionCard({ decision }) {
  const cov = decision.coverage || {};
  const signals = decision.fraud_signals || [];
  const triggered = signals.filter((s) => s.triggered);

  return (
    <>
      <h4>Triage decision</h4>

      <span className={`qbadge q-${decision.recommended_queue}`}>
        {QUEUE_LABEL[decision.recommended_queue] || decision.recommended_queue}
      </span>

      <div className="facts">
        <div className="fact">
          <div className="k">Severity</div>
          <div className="v">{decision.severity}</div>
        </div>
        <div className="fact">
          <div className="k">Coverage</div>
          <div className={`v ${cov.covered ? "yes" : "no"}`}>
            {cov.covered ? "Covered" : "Not confirmed"}
          </div>
        </div>
        <div className="fact">
          <div className="k">Fraud risk</div>
          <div className={`v risk-${decision.fraud_risk}`}>{decision.fraud_risk}</div>
        </div>
      </div>

      {cov.clause_id ? (
        <>
          <div className="block-label">Policy clause relied on</div>
          <div className="clause">
            <b>{cov.clause_id}</b> — {cov.clause_text}
          </div>
        </>
      ) : cov.reason ? (
        <>
          <div className="block-label">Coverage finding</div>
          <div className="clause">{cov.reason}</div>
        </>
      ) : null}

      {signals.length > 0 && (
        <>
          <div className="block-label">
            Fraud signals · {triggered.length} of {signals.length} triggered
          </div>
          <ul className="signals">
            {signals.map((s) => (
              <li key={s.name} className={s.triggered ? "on" : "off"}>
                <span className="mark">{s.triggered ? "⚠" : "○"}</span>
                <span>
                  {s.name.replace(/_/g, " ")}
                  {s.detail ? ` — ${s.detail}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {decision.rationale && (
        <>
          <div className="block-label">Rationale</div>
          <div className="rationale">{decision.rationale}</div>
        </>
      )}

      <div className="meta">
        <span>{decision.tool_calls ?? 0} tool calls</span>
        <span>{decision.latency_ms ?? 0} ms</span>
        {decision.cost_usd != null && <span>est. ${decision.cost_usd}</span>}
        {decision.model && <span className="meta-model">{decision.model}</span>}
      </div>
    </>
  );
}
