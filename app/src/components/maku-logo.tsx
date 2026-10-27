/** Maku's mark: a stage curtain drawn back (幕, maku, is a curtain). */
export function MakuLogo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="1" y="1" width="22" height="22" rx="7" className="fill-accent" />
      <rect x="5.8" y="5.4" width="12.4" height="2.2" rx="1.1" className="fill-on-accent" />
      <path
        d="M5.8 7.2H11.8C10.2 7.6 8.6 9.6 8 12.6C8 14.8 8.4 16.8 9 18.6H6.8A1 1 0 0 1 5.8 17.6Z"
        className="fill-on-accent"
      />
      <path
        d="M18.2 7.2H12.2C13.8 7.6 15.4 9.6 16 12.6C16 14.8 15.6 16.8 15 18.6H17.2A1 1 0 0 0 18.2 17.6Z"
        className="fill-on-accent"
      />
    </svg>
  );
}
