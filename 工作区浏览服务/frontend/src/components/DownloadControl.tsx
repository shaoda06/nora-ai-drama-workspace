import { PointerTooltip } from './PointerTooltip';
import './DownloadControl.css';

type Props = { label: string; title?: string } & (
  | { href: string; onClick?: never; disabled?: never; busy?: never }
  | { href?: never; onClick?: () => void; disabled?: boolean; busy?: boolean }
);

/** Shared appearance; callers retain native-link or prepared-file download behavior. */
export function DownloadControl({ label, title, href, onClick, disabled, busy }: Props) {
  const content = <>
    {busy ? <span className="download-control-spinner" aria-hidden="true" /> :
      <svg className="download-control-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
      </svg>}
    <span className="download-control-label">{label}</span>
  </>;
  return <PointerTooltip text={title}>{href !== undefined
    ? <a className="download-control" href={href} download>{content}</a>
    : <button className="download-control" type="button" disabled={disabled || busy} aria-busy={!!busy} onClick={onClick}>{content}</button>}
  </PointerTooltip>;
}
