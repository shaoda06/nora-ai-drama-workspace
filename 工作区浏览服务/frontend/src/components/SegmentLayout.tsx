import type { ReactNode } from 'react';
import './SegmentWideLayout.css';

export function SegmentLayout({ wide, player, navigation, children }: {
  wide: boolean; player: ReactNode; navigation: ReactNode; children: ReactNode;
}) {
  return <div className={'segment-workspace' + (wide ? ' is-wide' : '')}>
    <div className="segment-playback-row">
      {player}
      {wide && <aside className="segment-side-navigation" aria-label="宽屏分段导航">{navigation}</aside>}
    </div>
    {children}
  </div>;
}
