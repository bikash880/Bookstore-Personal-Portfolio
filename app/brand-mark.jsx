// The site's emblem: an open book with a golden pen, on forest green inside a turning gold ring.
export default function BrandMark({ size = 44, className = "", title }) {
  return <svg className={`brand-mark ${className}`} width={size} height={size} viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" role={title ? "img" : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
    {title && <title>{title}</title>}
    <circle cx="24" cy="24" r="22.6" fill="#13281e" stroke="#d4ac6a" strokeWidth="1.1"/>
    <circle className="brand-mark-orbit" cx="24" cy="24" r="19.6" stroke="#d4ac6a" strokeWidth=".75" strokeDasharray="1.4 2.6" strokeLinecap="round" opacity=".7"/>
    <path d="M24 33.6c-3.3-2.2-7.2-2.9-11.3-2.5V19.6c4.1-.4 8 .3 11.3 2.5z" fill="#f6eedb" stroke="#d4ac6a" strokeWidth=".9" strokeLinejoin="round"/>
    <path d="M24 33.6c3.3-2.2 7.2-2.9 11.3-2.5V19.6c-4.1-.4-8 .3-11.3 2.5z" fill="#efe3c8" stroke="#d4ac6a" strokeWidth=".9" strokeLinejoin="round"/>
    <path d="M24 22.1v11.5" stroke="#b8894a" strokeWidth="1" strokeLinecap="round"/>
    <path d="M15 23.4c2.4-.2 4.6.2 6.6 1.2M15 26.4c2.4-.2 4.6.2 6.6 1.2M15 29.4c2.4-.2 4.6.2 6.6 1.2" stroke="#6f8f7e" strokeWidth=".7" strokeLinecap="round" opacity=".75"/>
    <g className="brand-mark-pen">
      <path d="M35.6 10.6l2.3 2.3-8.6 12.6-2.2-.3-.3-2.2z" fill="#d4ac6a" stroke="#8a6431" strokeWidth=".5" strokeLinejoin="round"/>
      <path d="M26.8 23l2.5 2.5-3.1 1.3z" fill="#2a1e10"/>
      <path d="M36.1 11.1l1.4 1.4" stroke="#fff3d6" strokeWidth=".6" strokeLinecap="round"/>
    </g>
    <circle cx="13.6" cy="13.4" r=".85" fill="#f0cf94"/>
  </svg>;
}
