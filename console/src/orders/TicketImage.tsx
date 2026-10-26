import type { OrderLine } from './types';

interface Props {
  src: string;
  lines: OrderLine[];
  activeLineId: string | null;
  onSelect: (lineId: string) => void;
}

/** Ticket photo with one clickable box per line, drawn from the normalized `imageRegion`. */
export function TicketImage({ src, lines, activeLineId, onSelect }: Props) {
  return (
    <div className="ticket">
      <img src={src} alt="Ticket photo" />
      {lines.map(
        (line) =>
          line.imageRegion && (
            <button
              key={line.lineId}
              type="button"
              className="region"
              data-testid={`region-${line.lineId}`}
              data-active={line.lineId === activeLineId}
              data-corrected={line.correctedBy !== null}
              aria-label={`Line: ${line.rawText}`}
              onClick={() => onSelect(line.lineId)}
              style={{
                left: `${line.imageRegion.x * 100}%`,
                top: `${line.imageRegion.y * 100}%`,
                width: `${line.imageRegion.w * 100}%`,
                height: `${line.imageRegion.h * 100}%`,
              }}
            />
          ),
      )}
    </div>
  );
}
