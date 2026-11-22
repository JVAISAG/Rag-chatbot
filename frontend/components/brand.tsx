export function Brand() {
  return (
    <div className="brand" aria-label="Research Workspace">
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 28 28" fill="none">
          <path d="M6 6.5h7.2c2.1 0 3.8 1.4 3.8 3.5v11H9.8C7.7 21 6 19.4 6 17.4V6.5Z" stroke="currentColor" strokeWidth="1.6" />
          <path d="M17 10c0-2.1 1.7-3.5 3.8-3.5H22v10.9c0 2-1.7 3.6-3.8 3.6H17V10Z" stroke="currentColor" strokeWidth="1.6" />
          <path d="M9 10h4.5M9 13h4.5M9 16h3.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </span>
      <span className="brand-name">Research<span>Workspace</span></span>
    </div>
  );
}
