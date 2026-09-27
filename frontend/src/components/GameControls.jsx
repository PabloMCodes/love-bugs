// Present authoritative game progress and send session lifecycle commands.
import { useState } from 'react';

const statusDetails = {
    READY: {
        label: 'Ready',
        className: 'bg-sky-100 text-sky-900',
        summary: 'Start the game when the robots are ready.',
    },
    RUNNING: {
        label: 'Running',
        className: 'bg-emerald-200 text-emerald-900',
        summary: 'Wall-y and Eeva are working toward the repair fund.',
    },
    STOPPED: {
        label: 'Stopped',
        className: 'bg-amber-200 text-amber-950',
        summary: 'The game is paused. Start it to resume autonomous planning.',
    },
    COMPLETED: {
        label: 'Completed',
        className: 'bg-yellow-200 text-yellow-950',
        summary: 'Repair fund complete! The team reached its goal.',
    },
};

export default function GameControls({
    backendAvailable,
    game,
    onReset,
    onStart,
    onStop,
}) {
    const [pendingAction, setPendingAction] = useState(null);
    const [error, setError] = useState(null);
    const status = statusDetails[game.status] ?? {
        label: game.status,
        className: 'bg-stone-200 text-stone-900',
        summary: 'Waiting for an updated game status.',
    };
    const currentGold = game.goal.current;
    const targetGold = game.goal.target;
    const progress = targetGold > 0
        ? Math.min(100, Math.max(0, (currentGold / targetGold) * 100))
        : 0;
    const controlsDisabled = !backendAvailable || pendingAction !== null;

    async function runAction(name, action) {
        setPendingAction(name);
        setError(null);

        try {
            await action();
        } catch (failure) {
            setError(failure?.message || `Unable to ${name.toLowerCase()} the game.`);
        } finally {
            setPendingAction(null);
        }
    }

    function confirmReset() {
        if (window.confirm('Reset the game and clear all progress from this session?')) {
            runAction('Reset', onReset);
        }
    }

    return (
        <section
            className="game-status-panel w-full shrink-0 px-5 py-3 text-sky-950"
            aria-labelledby="farm-stage-heading"
        >
            <h2
                id="farm-stage-heading"
                className="text-center text-xl font-extrabold tracking-wide text-sky-950"
            >
                Farm Stage {game.stage ?? 1}
            </h2>

            <div className="mt-1 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold uppercase tracking-wide text-sky-800">
                        Repair Fund
                    </h3>
                    <span className={`rounded-full px-2 py-1 text-xs font-bold ${status.className}`}>
                        {status.label}
                    </span>
                </div>
                <p className="min-w-0 text-xs text-sky-800 sm:truncate sm:text-right" aria-live="polite">
                    {status.summary}
                </p>
            </div>

            <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-end">
                <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center justify-between gap-3 text-xs font-bold text-sky-900">
                        <span>Combined gold</span>
                        <span>{currentGold} / {targetGold}</span>
                    </div>
                    <div
                        className="game-status-progress h-3 overflow-hidden rounded-full"
                        role="progressbar"
                        aria-label="Repair fund progress"
                        aria-valuemin="0"
                        aria-valuemax={targetGold}
                        aria-valuenow={Math.min(targetGold, Math.max(0, currentGold))}
                    >
                        <div
                            className="h-full rounded-full bg-rose-400 transition-[width] duration-300"
                            style={{ width: `${progress}%` }}
                        />
                    </div>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                    <button
                        type="button"
                        className="market-action-button px-4 py-2 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={controlsDisabled || game.status === 'RUNNING' || game.status === 'COMPLETED'}
                        onClick={() => runAction('Start', onStart)}
                    >
                        {pendingAction === 'Start' ? 'Starting…' : 'Start'}
                    </button>
                    <button
                        type="button"
                        className="market-action-button px-4 py-2 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={controlsDisabled || game.status !== 'RUNNING'}
                        onClick={() => runAction('Stop', onStop)}
                    >
                        {pendingAction === 'Stop' ? 'Stopping…' : 'Stop'}
                    </button>
                    <button
                        type="button"
                        className="market-action-button px-4 py-2 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={controlsDisabled}
                        onClick={confirmReset}
                    >
                        {pendingAction === 'Reset' ? 'Resetting…' : 'Reset'}
                    </button>
                </div>
            </div>

            {!backendAvailable && (
                <p className="mt-2 text-xs font-semibold text-amber-800">
                    Connect to the backend to control the game session.
                </p>
            )}
            {error && (
                <p className="mt-2 text-xs font-semibold text-red-800" role="alert">
                    {error}
                </p>
            )}
        </section>
    );
}
