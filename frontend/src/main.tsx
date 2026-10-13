import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type Connection = 'checking' | 'connected' | 'unavailable';

function App() {
  const [connection, setConnection] = useState<Connection>('checking');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    let active = true;
    setConnection('checking');
    async function checkHealth() {
      try {
        const response = await fetch('/api/health', { signal: controller.signal });
        if (!response.ok) throw new Error('Health request failed');
        const body: unknown = await response.json();
        if (
          typeof body !== 'object' || body === null ||
          !('status' in body) || body.status !== 'ok' ||
          !('service' in body) || body.service !== 'webhook-relay'
        ) throw new Error('Unexpected health response');
        if (active) setConnection('connected');
      } catch {
        if (active) setConnection('unavailable');
      } finally {
        window.clearTimeout(timeout);
      }
    }
    void checkHealth();
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  const status = { checking: 'Checking API…', connected: 'API connected', unavailable: 'API unavailable' }[connection];
  return (
    <div className="layout">
      <aside className="sidebar" aria-label="Project information">
        <a className="brand" href="/" aria-label="Webhook Relay home"><span className="brand-icon" aria-hidden="true">↗</span> relay</a>
        <div className="workspace"><span className="avatar">WR</span><div>Webhook Relay<small>Local development</small></div></div>
        <div className="section-label">WORKSPACE</div>
        <div className="current-page">Overview <span>01</span></div>
        <p className="sidebar-note">Built one reviewed increment at a time.</p>
        <div className="baseline-badge">Baseline · v0.1.0</div>
      </aside>
      <main>
        <header className="topbar"><span>Workspace <span className="slash">/</span> Overview</span><span className="tag">LOCAL</span></header>
        <div className="content">
          <div className="eyebrow">DELIVERY INFRASTRUCTURE</div>
          <div className="title-row"><div><h1>Webhook Relay</h1><p className="subtitle">A clear view of every event, from intake to delivery.</p></div><span className={`connection ${connection}`} role="status">{status}</span></div>
          <section className="hero" aria-labelledby="foundation-title">
            <div><span className="pill">FOUNDATION</span><h2 id="foundation-title">Your relay starts here.</h2><p>The dashboard and API are ready for their first review. Workspaces, subscriptions, and event delivery will arrive in the next increments.</p></div>
            <div className="flow" aria-label="Planned event flow"><span>Event</span><i aria-hidden="true">→</i><span className="flow-relay">Relay</span><i aria-hidden="true">→</i><span>Endpoint</span></div>
          </section>
          <section className="panels" aria-label="Project status">
            <article className="panel"><div className="panel-heading"><h2>Service status</h2><span className="tag">LIVE CHECK</span></div><div className="service-row"><div><strong>Relay API</strong><small>Liveness · /api/health</small></div><span className={`status-dot ${connection}`} aria-hidden="true" /></div><p className="status-description">{connection === 'connected' ? 'The API responded successfully. Database readiness will be added with persistence.' : connection === 'checking' ? 'Waiting for a response from the API.' : 'The API could not be reached or returned an unexpected response. Start the backend and try again.'}</p><button type="button" disabled={connection === 'checking'} onClick={() => setAttempt(value => value + 1)}>Check connection <span aria-hidden="true">↻</span></button></article>
            <article className="panel"><div className="panel-heading"><h2>Next increment</h2><span className="tag">PLANNED</span></div><h3>Database foundation</h3><p>PostgreSQL, migrations, and the first workspace table. Each schema change gets its own review.</p><div className="review-note">Review → fix findings → merge → next PR</div></article>
          </section>
          <section className="empty-state" aria-labelledby="events-title"><div className="empty-icon" aria-hidden="true">⇄</div><h2 id="events-title">Event history is planned</h2><p>Event ingestion and delivery are not implemented in this baseline.</p></section>
          <footer>Webhook Relay <span>Small changes. Reviewed together.</span></footer>
        </div>
      </main>
    </div>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Root element missing');
createRoot(root).render(<StrictMode><App /></StrictMode>);
