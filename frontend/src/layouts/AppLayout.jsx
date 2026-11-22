/**
 * Application shell: header, content area and footer.
 *
 * @param {{children: React.ReactNode}} props
 */
export default function AppLayout({ children }) {
  return (
    <div className="app-layout">
      <header className="app-layout__header">
        <span className="app-layout__brand">X FACTOR</span>
        <span className="app-layout__tagline">
          Agentic Supply Chain Resilience Platform
        </span>
      </header>

      <main className="app-layout__main">{children}</main>

      <footer className="app-layout__footer">
        SAP Resilient Supply Chains Hackathon
      </footer>
    </div>
  )
}
