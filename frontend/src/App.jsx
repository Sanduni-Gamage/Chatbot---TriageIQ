import { useEffect, useRef, useState } from "react";
import { getHealth, getMeta, getModels, triageClaim } from "./api";
import ClaimForm from "./components/ClaimForm.jsx";
import DecisionCard from "./components/DecisionCard.jsx";
import ModelPicker from "./components/ModelPicker.jsx";

const INITIAL_CLAIM = {
  claim_id: "WEB-0001",
  policy_id: "HOM-205678",
  loss_type: "home_burglary",
  description: "Contents stolen overnight. No forced entry found, no witnesses.",
  estimated_amount: 12000,
  incident_date: "2026-06-01",
  reported_date: "2026-07-20",
  claimant_statement: "",
};

const GREETING = {
  id: 0,
  role: "bot",
  kind: "text",
  text: "Pick a sample claim or fill in the details, then hit Triage claim. I'll check coverage " +
        "against the policy wording, score severity, look for fraud signals, and route it — " +
        "showing the clause I relied on.",
};

const nextClaimId = (id) => {
  const m = String(id).match(/^(.*?)(\d+)$/);
  return m ? m[1] + String(+m[2] + 1).padStart(m[2].length, "0") : id;
};

export default function App() {
  const [health, setHealth] = useState(null);
  const [meta, setMeta] = useState({ policies: [], loss_types: [], samples: [] });
  const [providers, setProviders] = useState([]);
  const [isMock, setIsMock] = useState(true);
  const [selection, setSelection] = useState({ provider: "", model: "" });
  const [claim, setClaim] = useState(INITIAL_CLAIM);
  const [messages, setMessages] = useState([GREETING]);
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ mode: "unknown", model: "—" }));
    getMeta().then(setMeta).catch(() => {});
    getModels()
      .then((data) => {
        setProviders(data.providers || []);
        setIsMock(Boolean(data.mock));
        if (data.current) {
          setSelection({ provider: data.current.provider, model: data.current.model });
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function handleSubmit() {
    const submitted = { ...claim, estimated_amount: parseFloat(claim.estimated_amount) || 0 };
    const base = Date.now();
    setMessages((m) => [...m, { id: base, role: "user", kind: "claim", claim: submitted }]);
    setBusy(true);

    try {
      const decision = await triageClaim(submitted, selection);
      setMessages((m) => [...m, { id: base + 1, role: "bot", kind: "decision", decision }]);
    } catch (err) {
      setMessages((m) => [...m, { id: base + 1, role: "bot", kind: "error", text: err.message }]);
    } finally {
      setBusy(false);
      setClaim((c) => ({ ...c, claim_id: nextClaimId(c.claim_id) }));
    }
  }

  return (
    <div className="app">
      <header>
        <span className="logo">TriageIQ</span>
        <span className="tag">Claims triage assistant</span>
        <ModelPicker
          providers={providers}
          selection={selection}
          onChange={setSelection}
          mock={isMock}
        />
      </header>

      <div className="body">
        <ClaimForm
          meta={meta}
          claim={claim}
          onChange={setClaim}
          onSubmit={handleSubmit}
          busy={busy}
        />

        <section className="chat">
          <div className="chat-inner">
            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.role}`}>
                <div className="bubble">
                  {m.kind === "claim" && (
                    <>
                      <b>{m.claim.claim_id}</b> · {m.claim.loss_type.replace(/_/g, " ")} · $
                      {Number(m.claim.estimated_amount).toLocaleString()}
                      <div className="claim-line">{m.claim.description}</div>
                    </>
                  )}
                  {m.kind === "decision" && <DecisionCard decision={m.decision} />}
                  {m.kind === "text" && m.text}
                  {m.kind === "error" && (
                    <>
                      <h4>Error</h4>
                      {m.text}
                    </>
                  )}
                </div>
              </div>
            ))}

            {busy && (
              <div className="msg bot">
                <div className="bubble"><em>Assessing…</em></div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </section>
      </div>
    </div>
  );
}
