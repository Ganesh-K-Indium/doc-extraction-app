interface Props {
    position: number;            // 1-based place in the queue, or 0 when nothing is selected
    total: number;
    canConfirm: boolean;
    onStep: (dir: 1 | -1) => void;
    onConfirm: () => void;
}

/** The reviewer's controls, pinned to the bottom of the panel while anything is left to check. */
export function StepBar({ position, total, canConfirm, onStep, onConfirm }: Props) {
    return (
        <div className="rv-step" role="toolbar" aria-label="Values to check">
            <button className="btn btn--tiny" onClick={() => onStep(-1)} aria-label="Previous value to check">‹</button>
            <span className="rv-step__pos" role="status">{position > 0 ? `${position} of ${total}` : `${total}`} to check</span>
            <button className="btn btn--tiny" onClick={() => onStep(1)} aria-label="Next value to check">›</button>
            <span className="rv-step__keys muted"><kbd>j</kbd> <kbd>k</kbd> move</span>
            <button className="btn btn--tiny btn--primary rv-step__go" disabled={!canConfirm} onClick={onConfirm}>Confirm value <kbd>↵</kbd></button>
        </div>
    );
}
