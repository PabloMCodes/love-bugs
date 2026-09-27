// Present authoritative game progress and send session lifecycle commands.
import { useState } from 'react';
import { hardwareInputReadiness } from '../utils/robotReadiness.js';
import EconomyStatus from './EconomyStatus.jsx';

export default function GameControls({
    backendAvailable,
    backendConnected,
    world,
    onReset,
    onStart,
    onStop,
}) {
    const { economy, game, mode, robots } = world;
    const [pendingAction, setPendingAction] = useState(null);
    const [error, setError] = useState(null);
    const currentGold = game.goal.current;
    const targetGold = game.goal.target;
    const progress = targetGold > 0
        ? Math.min(100, Math.max(0, (currentGold / targetGold) * 100))
        : 0;
    const controlsDisabled = (
        !backendAvailable || !backendConnected || pendingAction !== null
    );
    const inputReadiness = hardwareInputReadiness(world);
    const inputReady = backendConnected && inputReadiness.ready;
    const startRequiresInput = mode === 'hardware' && !inputReady;

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
            className="w-full shrink-0 text-sky-950"
            aria-labelledby="farm-stage-heading"
        >
            <h2
                id="farm-stage-heading"
                className="section-title mb-2 text-center text-xl font-extrabold tracking-wide"
            >
                Farm Stage {game.stage ?? 1}
            </h2>

            <div className="game-status-panel relative px-7 py-3">
                <img
                    className="game-status-cloud-art pointer-events-none absolute inset-0 h-full w-full"
                    src="/assets/ui/game-controls-cloud.svg"
                    alt=""
                    aria-hidden="true"
                />

                <div className="relative z-10 flex flex-col gap-3 md:flex-row md:items-end">
                    <div className="min-w-0 flex-1">
                        <div className="mb-1 flex items-center justify-between gap-3 text-xs font-bold text-sky-900">
                            <span>{game.status} · Combined gold</span>
                            <span>{currentGold} / {targetGold}</span>
                        </div>
                        <div
                            className="game-status-progress h-3 overflow-hidden rounded-full"
                            role="progressbar"
                            aria-label="Farm stage progress"
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
                            disabled={controlsDisabled || startRequiresInput || game.status === 'RUNNING' || game.status === 'COMPLETED'}
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

                <div className={`relative z-10 mt-2 text-[11px] font-bold ${
                    inputReady ? 'text-emerald-800' : 'text-amber-900'
                }`}>
                    {mode === 'simulation'
                        ? backendConnected
                            ? 'Movement source: deterministic simulation'
                            : 'Waiting for the backend event stream'
                        : !backendConnected
                            ? 'Waiting for the backend event stream'
                            : inputReadiness.ready
                            ? `Hardware input ready · ${inputReadiness.readyCount}/${inputReadiness.totalCount} robots online and tracked`
                            : `Waiting for hardware input · ${inputReadiness.robots
                                .filter((robot) => robot.issues.length > 0)
                                .map((robot) => `${robot.name}: ${robot.issues.join(', ')}`)
                                .join(' · ')}`
                    }
                </div>

                <div className="relative z-10">
                    <EconomyStatus economy={economy} robots={robots} />
                </div>

                {!backendAvailable && (
                    <p className="relative z-10 mt-2 text-xs font-semibold text-amber-800">
                        Connect to the backend to control the game session.
                    </p>
                )}
                {error && (
                    <p className="relative z-10 mt-2 text-xs font-semibold text-red-800" role="alert">
                        {error}
                    </p>
                )}
            </div>
        </section>
    );
}
