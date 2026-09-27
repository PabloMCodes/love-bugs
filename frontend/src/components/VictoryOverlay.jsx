import { useState } from 'react';

const confetti = Array.from({ length: 18 }, (_, index) => index);

export default function VictoryOverlay({ backendAvailable, game, onReset, robots }) {
    const [resetting, setResetting] = useState(false);
    const [error, setError] = useState(null);

    if (game.status !== 'COMPLETED') {
        return null;
    }

    async function reset() {
        setResetting(true);
        setError(null);
        try {
            await onReset();
        } catch (failure) {
            setError(failure?.message || 'Unable to reset the game.');
            setResetting(false);
        }
    }

    return (
        <section
            aria-labelledby="victory-heading"
            aria-modal="true"
            className="victory-backdrop fixed inset-0 z-[70] flex items-center justify-center p-6"
            role="dialog"
        >
            <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
                {confetti.map((piece) => (
                    <span
                        className="victory-confetti absolute"
                        key={piece}
                        style={{
                            '--confetti-delay': `${(piece % 6) * 90}ms`,
                            '--confetti-left': `${4 + ((piece * 29) % 92)}%`,
                        }}
                    />
                ))}
            </div>

            <div className="victory-card market-parchment-card relative w-full max-w-xl p-8 text-center text-[#422313]">
                <p className="text-xs font-black uppercase tracking-[0.3em] text-[#805431]">
                    Stage {game.stage} complete
                </p>
                <h2 id="victory-heading" className="mt-3 text-4xl font-black sm:text-5xl">
                    Repair Fund Complete!
                </h2>
                <p className="mx-auto mt-3 max-w-md text-sm font-semibold text-[#63391f]">
                    {robots.map((robot) => robot.name).join(' and ')} worked together to raise{' '}
                    {game.goal.current} gold and save their home.
                </p>

                <div className="mt-6 grid grid-cols-2 gap-3">
                    {robots.map((robot) => (
                        <div className="border-2 border-[#805431] bg-[#efcc86]/70 px-3 py-3" key={robot.id}>
                            <p className="font-black">{robot.name}</p>
                            <p className="mt-1 text-xs font-semibold text-[#805431]">
                                {robot.game.money} gold saved
                            </p>
                        </div>
                    ))}
                </div>

                <p className="mt-5 text-xs font-bold uppercase tracking-wide text-[#805431]">
                    Goal: {game.goal.current} / {game.goal.target} gold
                </p>

                <button
                    className="market-action-button mt-5 px-6 py-3 text-sm font-black disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={!backendAvailable || resetting}
                    onClick={reset}
                    type="button"
                >
                    {resetting ? 'Preparing a new round…' : 'Play again'}
                </button>
                {!backendAvailable && (
                    <p className="mt-2 text-xs font-semibold text-amber-900">
                        Reconnect to the backend to reset this round.
                    </p>
                )}
                {error && (
                    <p className="mt-2 text-xs font-semibold text-red-900" role="alert">
                        {error}
                    </p>
                )}
            </div>
        </section>
    );
}
