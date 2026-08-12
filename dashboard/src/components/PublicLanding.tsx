import Link from "next/link";

export const GATEWAY_PAYMENT_REFERENCE = "7def6214-d8d1-4562-9d0a-b50bcff80b72";
export const RECEIPT_REGISTRY = "0xa8dB3390bC66278788F723A05bEAfFd9A70e02c0";
export const RECEIPT_ANCHOR =
  "0xc29eecd907ee53038e1c35c8d974b735f8f996b259f1025bbd77d3cf691c01fd";
export const ARCSCAN_RECEIPT_URL = `https://testnet.arcscan.app/tx/${RECEIPT_ANCHOR}`;

export function PublicLanding({ openMandateHref }: { openMandateHref: string }) {
  return (
    <div className="landing">
      <header className="landing-nav shell">
        <Link href="/" className="landing-brand" aria-label="Mandate home">
          <span className="landing-mark" aria-hidden />
          Mandate
        </Link>
        <Link href={openMandateHref} className="btn btn-primary landing-action">
          Open Mandate
        </Link>
      </header>
      <section className="landing-hero shell">
        <p className="landing-kicker">Mandate</p>
        <h1>Financial fault tolerance for autonomous agents.</h1>
        <p className="landing-rule">One Intent. No blind retries.</p>
        <p className="landing-lede">
          When a payment result is unknown, Mandate blocks a second authorization for the same
          Intent.
        </p>
        <div className="landing-actions">
          <Link href={openMandateHref} className="btn btn-primary landing-action">
            Open Mandate
          </Link>
          <a href="#proof" className="btn btn-secondary landing-action">
            See the proof
          </a>
        </div>
      </section>

      <section id="failure" className="landing-section shell" aria-labelledby="failure-title">
        <p className="landing-kicker">The failure</p>
        <h2 id="failure-title">The result disappears. The payment might not.</h2>
        <ol className="landing-sequence">
          <li>
            <strong>01</strong>
            <span>An agent creates one Payment Authorization.</span>
          </li>
          <li>
            <strong>02</strong>
            <span>The application loses the payment result.</span>
          </li>
          <li>
            <strong>03</strong>
            <span>A blind retry can authorize the same economic action again.</span>
          </li>
        </ol>
        <p className="landing-answer">
          Mandate records the Intent first. If value may have moved, it freezes new authorization.
        </p>
      </section>

      <section id="rule" className="landing-section shell" aria-labelledby="rule-title">
        <p className="landing-kicker">Economic Safety State</p>
        <div className="landing-state" data-state="unknown">
          <div>
            <h2 id="rule-title">UNKNOWN</h2>
            <p>Value may have moved.</p>
          </div>
          <dl>
            <div>
              <dt>Permitted action</dt>
              <dd>WAIT or REQUEST_REVIEW.</dd>
            </div>
            <div>
              <dt>New Payment Authorization</dt>
              <dd>BLOCKED.</dd>
            </div>
          </dl>
          <p className="sr-only">Permitted action: WAIT or REQUEST_REVIEW.</p>
          <p className="sr-only">New Payment Authorization: BLOCKED.</p>
        </div>
      </section>

      <section
        id="proof"
        className="landing-section landing-proof shell"
        aria-labelledby="proof-title"
      >
        <div className="landing-section-head">
          <p className="landing-kicker">Golden proof</p>
          <h2 id="proof-title">One completed payment. One separate Arc record.</h2>
          <p>These are different values.</p>
        </div>
        <div className="landing-proof-grid">
          <article className="landing-proof-card" data-proof="gateway">
            <p className="landing-proof-source">Circle Gateway</p>
            <h3>$0.01 USDC</h3>
            <dl>
              <div>
                <dt>Network</dt>
                <dd>Arc testnet</dd>
              </div>
              <div>
                <dt>Gateway state</dt>
                <dd className="proof-success">completed</dd>
              </div>
              <div>
                <dt>Payment Reference</dt>
                <dd className="mono proof-value">{GATEWAY_PAYMENT_REFERENCE}</dd>
              </div>
            </dl>
          </article>
          <article className="landing-proof-card" data-proof="arc">
            <p className="landing-proof-source">Arc Receipt Registry</p>
            <h3>ReceiptRecorded</h3>
            <dl>
              <div>
                <dt>Registry</dt>
                <dd className="mono proof-value">{RECEIPT_REGISTRY}</dd>
              </div>
              <div>
                <dt>Receipt Anchor</dt>
                <dd className="mono proof-value">{RECEIPT_ANCHOR}</dd>
              </div>
            </dl>
            <a
              href={ARCSCAN_RECEIPT_URL}
              target="_blank"
              rel="noreferrer noopener"
              className="landing-proof-link"
              aria-label="Inspect the Arc Receipt Anchor"
            >
              Inspect on Arcscan ↗
            </a>
          </article>
        </div>
      </section>

      <section id="mechanism" className="landing-section shell" aria-labelledby="mechanism-title">
        <p className="landing-kicker">How it works</p>
        <h2 id="mechanism-title">Authority first. Authorization second.</h2>
        <ol className="landing-mechanism">
          <li>
            <strong>1</strong>
            <span>A User creates bounded authority.</span>
          </li>
          <li>
            <strong>2</strong>
            <span>Mandate records one economic Intent.</span>
          </li>
          <li>
            <strong>3</strong>
            <span>Mandate reserves the amount before authorization.</span>
          </li>
          <li>
            <strong>4</strong>
            <span>Mandate returns the exact Economic Safety Action.</span>
          </li>
        </ol>
        <div className="landing-envelope" aria-label="Authority envelope">
          <span>Total amount</span>
          <span>Per-call cap</span>
          <span>Allowed services</span>
          <span>Expiry</span>
        </div>
      </section>

      <section id="access" className="landing-section shell" aria-labelledby="access-title">
        <p className="landing-kicker">Agent access</p>
        <h2 id="access-title">Use the interface that fits the agent.</h2>
        <div className="landing-access-grid">
          <article>
            <h3>REST</h3>
            <p>Stable interface</p>
            <code>POST /spend · GET /status</code>
          </article>
          <article>
            <p className="landing-access-label">MCP</p>
            <h3>Connect with MCP</h3>
            <p>Tested adapter</p>
            <code>mandate.spend · mandate.status</code>
          </article>
        </div>
        <a
          href="https://github.com/degencodebeast/mandate#architecture"
          target="_blank"
          rel="noreferrer noopener"
          className="landing-text-link"
        >
          Read the technical guide ↗
        </a>
      </section>

      <section className="landing-close shell" aria-labelledby="landing-close-title">
        <h2 id="landing-close-title">One Intent. No blind retries.</h2>
        <Link href={openMandateHref} className="btn btn-primary landing-action">
          Open Mandate
        </Link>
        <nav aria-label="Evidence links" className="landing-evidence-links">
          <a
            href="https://github.com/degencodebeast/mandate"
            target="_blank"
            rel="noreferrer noopener"
          >
            GitHub ↗
          </a>
          <a href={ARCSCAN_RECEIPT_URL} target="_blank" rel="noreferrer noopener">
            Arc proof ↗
          </a>
          <a
            href="https://github.com/degencodebeast/mandate/blob/main/evidence/ticket-11-real-gateway-payment.md"
            target="_blank"
            rel="noreferrer noopener"
          >
            Gateway evidence ↗
          </a>
        </nav>
      </section>
    </div>
  );
}
