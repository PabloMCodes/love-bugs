import { useEffect, useRef } from 'react';
import { useAgentChat } from '../hooks/useAgentChat.js';

export default function AgentChat({ world }) {
    const { feed, connected, error } = useAgentChat();
    const list = useRef(null);
    const follow = useRef(true);
    const messages = feed.session_id === world.session_id ? feed.messages : [];
    const lastMessage = messages.at(-1)?.id;

    useEffect(() => {
        if (follow.current && list.current) list.current.scrollTop = list.current.scrollHeight;
    }, [lastMessage]);

    return (
        <section className="flex h-full min-h-0 w-full flex-col" aria-label="Agent chat">
            <h2 className="section-title mb-3 text-lg font-semibold">Robot Conversation</h2>

            <div className="market-crate flex min-h-0 w-full flex-1 flex-col overflow-hidden p-5">
                <div className="chat-controls flex shrink-0 items-center gap-2 px-3 py-2.5">
                    <span className="min-w-0 flex-1 text-xs font-semibold">
                        {feed.running
                            ? 'Robots are thinking…'
                            : feed.mode === 'autonomous'
                                ? 'Backend autonomy active'
                                : 'Waiting for robot messages'}
                    </span>
                    <span
                        className={`size-2 shrink-0 ${
                            connected ? 'bg-emerald-300' : 'bg-amber-300'
                        }`}
                        title={connected ? 'Live feed connected' : 'Connecting to chat server'}
                    />
                </div>
                {(error || feed.error) && (
                    <p
                        role="alert"
                        className="market-parchment-card mt-3 px-3 py-2 text-xs font-semibold text-red-900"
                    >
                        {error || feed.error}
                    </p>
                )}
                <div
                    ref={list}
                    role="log"
                    aria-live="polite"
                    aria-relevant="additions"
                    onScroll={() => {
                        const element = list.current;
                        follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48;
                    }}
                    className="market-scrollbar mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1"
                >
                    {messages.length === 0 && (
                        <p className="chat-message-bubble px-5 pb-7 pt-4 text-sm text-[#46677c]">
                            Robot decisions will appear here after the game starts.
                        </p>
                    )}
                    {messages.map((message) => (
                        <article
                            key={message.id}
                            className={`chat-message-bubble px-5 pb-7 pt-4 text-[#15364a] ${
                                message.robot_id === 'robot-b' ? 'chat-message-bubble-reversed' : ''
                            }`}
                        >
                            <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                                <span className="font-bold text-[#287aa2]">{message.name}</span>
                                <time dateTime={message.timestamp} className="text-[#5b7990]">
                                    {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </time>
                            </div>
                            <p className="break-words text-sm">{message.text}</p>
                            {!['banter', 'traffic'].includes(message.kind) && <p className="mt-2 text-xs text-[#5b7990]">
                                {message.status === 'accepted'
                                    ? 'Accepted'
                                    : message.status === 'waiting'
                                        ? 'Waiting'
                                        : 'Proposed'}: {message.action.toLowerCase().replaceAll('_', ' ')}
                                {message.location ? ` · ${message.location}` : ''}
                                {message.parameters?.item
                                    ? ` · ${message.parameters.quantity} ${message.parameters.item}`
                                    : ''
                                }
                            </p>}
                        </article>
                    ))}
                </div>
            </div>
        </section>
    );
}
