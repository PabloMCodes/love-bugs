import { useEffect, useRef } from 'react';
import { useAgentChat } from '../hooks/useAgentChat.js';

export default function AgentChat({ world }) {
    const { feed, connected, enabled, setEnabled, provider, setProvider, error } = useAgentChat(world);
    const list = useRef(null);
    const follow = useRef(true);
    const messages = feed.session_id === world.session_id ? feed.messages : [];
    const lastMessage = messages.at(-1)?.id;

    useEffect(() => {
        if (follow.current && list.current) list.current.scrollTop = list.current.scrollHeight;
    }, [lastMessage]);

    return (
        <section className="flex h-80 min-h-0 flex-col rounded-2xl border border-stone-800 bg-stone-900 p-4 lg:h-full" aria-label="Agent chat">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-semibold">Robot conversation</h2>
                <span className={`text-xs ${connected ? 'text-emerald-300' : 'text-stone-400'}`}>
                    {connected ? 'Live feed connected' : 'Connecting to chat server…'}
                </span>
            </div>
            <p className="mt-1 text-xs text-stone-400">Planning together. Chat proposes moves; it does not execute them.</p>
            <div className="my-3 flex flex-wrap items-center gap-2">
                <label htmlFor="chat-provider" className="text-xs text-stone-400">Voices</label>
                <select id="chat-provider" value={provider} disabled={enabled || feed.running}
                    onChange={(event) => setProvider(event.target.value)}
                    className="rounded-md bg-stone-800 px-2 py-1 text-sm disabled:opacity-50">
                    <option value="mock">Mock demo</option>
                    <option value="gemini">Gemini agents</option>
                </select>
                <button type="button" onClick={() => setEnabled(!enabled)}
                    disabled={!enabled && (!connected || feed.running)}
                    className="rounded-md bg-rose-400 px-3 py-1 text-sm font-semibold text-stone-950 disabled:opacity-50">
                    {enabled ? 'Pause chat' : 'Start chat'}
                </button>
                <span className="text-xs text-stone-400">
                    {feed.running ? 'Robots are thinking…' : enabled ? 'Listening for the next round' : 'Paused'}
                </span>
            </div>
            {(error || feed.error) && <p role="alert" className="mb-2 text-xs text-red-300">{error || feed.error}</p>}
            <div ref={list} role="log" aria-live="polite" aria-relevant="additions"
                onScroll={() => {
                    const element = list.current;
                    follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48;
                }}
                className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                {messages.length === 0 && (
                    <p className="py-4 text-sm text-stone-500">
                        Start chat to hear the robots coordinate. Mock demo works without an API key.
                    </p>
                )}
                {messages.map((message) => (
                    <article key={message.id} className="rounded-xl border border-stone-700 bg-stone-800 p-3">
                        <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                            <span className="font-semibold text-rose-300">{message.name}</span>
                            <time dateTime={message.timestamp} className="text-stone-400">
                                {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </time>
                        </div>
                        <p className="break-words text-sm text-stone-100">{message.text}</p>
                        <p className="mt-2 text-xs text-stone-400">
                            Proposed: {message.action.toLowerCase().replaceAll('_', ' ')}
                            {message.location ? ` · ${message.location}` : ''}
                        </p>
                    </article>
                ))}
            </div>
            <p className="mt-2 text-xs text-stone-500">
                {feed.provider === 'gemini' ? 'Gemini conversation' : 'Scripted mock conversation'}
                {' · '}Pausing lets the current round finish.
            </p>
        </section>
    );
}
