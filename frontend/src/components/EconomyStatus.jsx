function robotName(robotNames, robotId) {
    return robotNames.get(robotId) ?? robotId;
}

function recentEconomyOutcome(economy, robotNames) {
    const outcomes = [
        ...economy.unlock_proposals
            .filter((proposal) => proposal.status !== 'PENDING')
            .map((proposal) => ({
                timestamp: proposal.resolved_at,
                message: proposal.status === 'COMPLETED'
                    ? `Stage ${proposal.stage} funded · ${Object.entries(proposal.contributions)
                        .map(([id, amount]) => `${robotName(robotNames, id)} ${amount}g`)
                        .join(' + ')}`
                    : `Stage ${proposal.stage} proposal ${proposal.status.toLowerCase()}`,
            })),
        ...economy.transfers.map((transfer) => ({
            timestamp: transfer.created_at,
            message: `${robotName(robotNames, transfer.sender_id)} sent ${transfer.amount}g to ${robotName(robotNames, transfer.recipient_id)}`,
        })),
        ...economy.money_requests
            .filter((request) => ['REJECTED', 'EXPIRED'].includes(request.status))
            .map((request) => ({
                timestamp: request.resolved_at,
                message: `${robotName(robotNames, request.requester_id)}'s ${request.amount}g request ${request.status.toLowerCase()}`,
            })),
    ];

    return outcomes
        .filter((outcome) => outcome.timestamp)
        .sort((first, second) => (
            Date.parse(second.timestamp) - Date.parse(first.timestamp)
        ))[0]?.message;
}

export default function EconomyStatus({ economy, robots }) {
    const robotNames = new Map(robots.map((robot) => [robot.id, robot.name]));
    const pendingProposal = [...economy.unlock_proposals]
        .reverse()
        .find((proposal) => proposal.status === 'PENDING');
    const pendingMoney = [...economy.money_requests]
        .reverse()
        .find((request) => request.status === 'PENDING');
    const unlockedStages = economy.unlocks.filter((rule) => rule.unlocked).length;
    const recentOutcome = recentEconomyOutcome(economy, robotNames);

    return (
        <div className="economy-status mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[11px] text-sky-950">
            <span className="shrink-0 font-black uppercase tracking-wide">
                Team economy
            </span>

            {pendingProposal && (
                <span className="min-w-0 font-semibold">
                    Stage {pendingProposal.stage} vote · {pendingProposal.accepted_by
                        .map((id) => `${robotName(robotNames, id)} ✓`)
                        .join(' · ')} · awaiting {robots
                        .filter((robot) => !pendingProposal.accepted_by.includes(robot.id))
                        .map((robot) => robot.name)
                        .join(', ')}
                </span>
            )}

            {pendingMoney && (
                <span className="min-w-0 font-semibold">
                    {robotName(robotNames, pendingMoney.requester_id)} asks{' '}
                    {robotName(robotNames, pendingMoney.recipient_id)} for{' '}
                    {pendingMoney.amount} gold
                </span>
            )}

            {!pendingProposal && !pendingMoney && (
                <span className="font-semibold text-sky-800">
                    {recentOutcome ?? 'No completed team transactions'} · {unlockedStages} of{' '}
                    {economy.unlocks.length} upgrades funded
                </span>
            )}
        </div>
    );
}
