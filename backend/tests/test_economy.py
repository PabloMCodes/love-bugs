import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import (
    EconomyResponseRequest,
    MoneyRequestCreate,
    MoneyTransferRequest,
    StageUnlockProposalRequest,
)
from app.state import WorldStateError, WorldStore, default_world


def running_store(*, robot_a_gold=40, robot_b_gold=40) -> WorldStore:
    world = default_world()
    world['robots'][0]['game']['money'] = robot_a_gold
    world['robots'][1]['game']['money'] = robot_b_gold
    world['game']['goal']['current'] = robot_a_gold + robot_b_gold
    store = WorldStore(world)
    store.start_game()
    return store


class EconomyTests(unittest.TestCase):
    def assert_world_error(self, code, callback):
        with self.assertRaises(WorldStateError) as context:
            callback()
        self.assertEqual(context.exception.code, code)

    def test_direct_transfer_is_atomic_and_retry_safe(self):
        store = running_store()
        request = MoneyTransferRequest(
            request_id='transfer-001',
            sender_id='robot-a',
            recipient_id='robot-b',
            amount=12,
            purpose='Help buy seeds',
        )

        first = store.transfer_money(request)
        revision = store.snapshot().revision
        retried = store.transfer_money(request)
        world = store.snapshot()

        self.assertEqual(retried.id, first.id)
        self.assertEqual(world.revision, revision)
        self.assertEqual([robot.game.money for robot in world.robots], [28, 52])
        self.assertEqual(world.game.goal.current, 80)
        self.assertEqual(len(world.economy.transfers), 1)
        self.assertEqual(world.events[-1].type, 'money_transferred')

        self.assert_world_error(
            'REQUEST_ID_CONFLICT',
            lambda: store.transfer_money(request.model_copy(update={'amount': 13})),
        )

    def test_transfer_rejects_invalid_participants_and_insufficient_funds(self):
        store = running_store()
        self.assert_world_error(
            'INVALID_REQUEST',
            lambda: store.transfer_money(MoneyTransferRequest(
                request_id='self-transfer',
                sender_id='robot-a',
                recipient_id='robot-a',
                amount=1,
                purpose='No-op',
            )),
        )
        self.assert_world_error(
            'INSUFFICIENT_FUNDS',
            lambda: store.transfer_money(MoneyTransferRequest(
                request_id='too-much',
                sender_id='robot-a',
                recipient_id='robot-b',
                amount=41,
                purpose='Too expensive',
            )),
        )

    def test_money_request_can_be_rejected(self):
        store = running_store()
        created = store.create_money_request(MoneyRequestCreate(
            request_id='ask-001',
            requester_id='robot-a',
            recipient_id='robot-b',
            amount=10,
            purpose='Buy a seed',
        ))

        rejected = store.respond_money_request(created.id, EconomyResponseRequest(
            request_id='answer-001',
            robot_id='robot-b',
            accepted=False,
        ))

        self.assertEqual(rejected.status, 'REJECTED')
        self.assertIsNone(rejected.transfer_id)
        self.assertEqual([robot.game.money for robot in store.snapshot().robots], [40, 40])
        self.assertEqual(store.snapshot().events[-1].type, 'money_request_rejected')

    def test_accepted_money_request_transfers_once(self):
        store = running_store()
        created = store.create_money_request(MoneyRequestCreate(
            request_id='ask-002',
            requester_id='robot-a',
            recipient_id='robot-b',
            amount=15,
            purpose='Fund the next crop',
        ))
        response = EconomyResponseRequest(
            request_id='answer-002',
            robot_id='robot-b',
            accepted=True,
        )

        accepted = store.respond_money_request(created.id, response)
        revision = store.snapshot().revision
        retried = store.respond_money_request(created.id, response)
        world = store.snapshot()

        self.assertEqual(retried.id, accepted.id)
        self.assertEqual(world.revision, revision)
        self.assertEqual(accepted.status, 'ACCEPTED')
        self.assertIsNotNone(accepted.transfer_id)
        self.assertEqual([robot.game.money for robot in world.robots], [55, 25])
        self.assertEqual(len(world.economy.transfers), 1)
        self.assertEqual(world.economy.transfers[0].money_request_id, created.id)

    def test_only_recipient_can_answer_and_requester_has_one_pending_request(self):
        store = running_store()
        created = store.create_money_request(MoneyRequestCreate(
            request_id='ask-003',
            requester_id='robot-a',
            recipient_id='robot-b',
            amount=5,
            purpose='Seed money',
        ))
        self.assert_world_error(
            'NOT_AUTHORIZED',
            lambda: store.respond_money_request(created.id, EconomyResponseRequest(
                request_id='wrong-answer',
                robot_id='robot-a',
                accepted=True,
            )),
        )
        self.assert_world_error(
            'REQUEST_PENDING',
            lambda: store.create_money_request(MoneyRequestCreate(
                request_id='ask-again',
                requester_id='robot-a',
                recipient_id='robot-b',
                amount=5,
                purpose='Another request',
            )),
        )

    def test_stage_two_requires_eligibility_and_exact_team_contributions(self):
        store = running_store()
        self.assert_world_error(
            'STAGE_NOT_ELIGIBLE',
            lambda: store.propose_stage_unlock(StageUnlockProposalRequest(
                request_id='early-stage-two',
                proposer_id='robot-a',
                stage=2,
                contributions={'robot-a': 15, 'robot-b': 15},
            )),
        )

        store = running_store(robot_a_gold=60, robot_b_gold=50)
        self.assert_world_error(
            'INVALID_REQUEST',
            lambda: store.propose_stage_unlock(StageUnlockProposalRequest(
                request_id='missing-contributor',
                proposer_id='robot-a',
                stage=2,
                contributions={'robot-a': 30},
            )),
        )
        self.assert_world_error(
            'INVALID_REQUEST',
            lambda: store.propose_stage_unlock(StageUnlockProposalRequest(
                request_id='wrong-total',
                proposer_id='robot-a',
                stage=2,
                contributions={'robot-a': 10, 'robot-b': 10},
            )),
        )

    def test_both_robots_must_accept_before_stage_unlocks(self):
        store = running_store(robot_a_gold=60, robot_b_gold=50)
        proposal_request = StageUnlockProposalRequest(
            request_id='propose-stage-two',
            proposer_id='robot-a',
            stage=2,
            contributions={'robot-a': 20, 'robot-b': 10},
        )
        proposal = store.propose_stage_unlock(proposal_request)
        pending_world = store.snapshot()

        self.assertEqual(proposal.status, 'PENDING')
        self.assertEqual(proposal.accepted_by, ['robot-a'])
        self.assertEqual(pending_world.game.stage, 1)
        self.assertEqual([robot.game.money for robot in pending_world.robots], [60, 50])

        response = EconomyResponseRequest(
            request_id='accept-stage-two',
            robot_id='robot-b',
            accepted=True,
        )
        completed = store.respond_stage_unlock(proposal.id, response)
        revision = store.snapshot().revision
        retried = store.respond_stage_unlock(proposal.id, response)
        world = store.snapshot()

        self.assertEqual(retried.id, completed.id)
        self.assertEqual(world.revision, revision)
        self.assertEqual(completed.status, 'COMPLETED')
        self.assertEqual(world.game.stage, 2)
        self.assertEqual([robot.game.money for robot in world.robots], [40, 40])
        self.assertEqual(world.game.goal.current, 80)
        self.assertTrue(world.economy.unlocks[0].unlocked)
        self.assertEqual(world.events[-1].type, 'stage_unlocked')

    def test_rejected_unlock_allows_a_new_proposal(self):
        store = running_store(robot_a_gold=60, robot_b_gold=50)
        first = store.propose_stage_unlock(StageUnlockProposalRequest(
            request_id='first-proposal',
            proposer_id='robot-a',
            stage=2,
            contributions={'robot-a': 15, 'robot-b': 15},
        ))
        rejected = store.respond_stage_unlock(first.id, EconomyResponseRequest(
            request_id='reject-first',
            robot_id='robot-b',
            accepted=False,
        ))
        second = store.propose_stage_unlock(StageUnlockProposalRequest(
            request_id='second-proposal',
            proposer_id='robot-b',
            stage=2,
            contributions={'robot-a': 15, 'robot-b': 15},
        ))

        self.assertEqual(rejected.status, 'REJECTED')
        self.assertEqual(second.status, 'PENDING')
        self.assertNotEqual(second.id, first.id)

    def test_stage_three_cannot_be_proposed_before_stage_two(self):
        store = running_store(robot_a_gold=100, robot_b_gold=100)
        self.assert_world_error(
            'INVALID_STAGE',
            lambda: store.propose_stage_unlock(StageUnlockProposalRequest(
                request_id='skip-stage-two',
                proposer_id='robot-a',
                stage=3,
                contributions={'robot-a': 30, 'robot-b': 30},
            )),
        )

    def test_final_stage_unlock_completes_an_already_funded_goal(self):
        world = default_world()
        world['game']['stage'] = 2
        world['game']['goal']['target'] = 200
        world['game']['goal']['current'] = 300
        world['robots'][0]['game']['money'] = 150
        world['robots'][1]['game']['money'] = 150
        world['economy']['unlocks'][0]['unlocked'] = True
        store = WorldStore(world)
        store.start_game()
        proposal = store.propose_stage_unlock(StageUnlockProposalRequest(
            request_id='funded-final-stage',
            proposer_id='robot-a',
            stage=3,
            contributions={'robot-a': 30, 'robot-b': 30},
        ))

        store.respond_stage_unlock(proposal.id, EconomyResponseRequest(
            request_id='accept-funded-final-stage',
            robot_id='robot-b',
            accepted=True,
        ))
        completed = store.snapshot()

        self.assertEqual(completed.game.status, 'COMPLETED')
        self.assertEqual(completed.game.stage, 3)
        self.assertEqual(completed.game.goal.current, 240)
        self.assertEqual(completed.events[-1].type, 'game_completed')

    def test_reset_clears_economy_history_and_request_ids(self):
        store = running_store()
        request = MoneyTransferRequest(
            request_id='reusable-after-reset',
            sender_id='robot-a',
            recipient_id='robot-b',
            amount=5,
            purpose='Before reset',
        )
        store.transfer_money(request)

        reset = store.reset_game()

        self.assertEqual(reset.economy.transfers, [])
        self.assertEqual(reset.economy.money_requests, [])
        self.assertEqual(reset.economy.unlock_proposals, [])
        store.start_game()
        transferred = store.transfer_money(request.model_copy(update={'purpose': 'After reset'}))
        self.assertEqual(transferred.amount, 5)

    def test_economy_changes_require_running_game(self):
        store = WorldStore()
        self.assert_world_error(
            'GAME_NOT_RUNNING',
            lambda: store.transfer_money(MoneyTransferRequest(
                request_id='not-running',
                sender_id='robot-a',
                recipient_id='robot-b',
                amount=1,
                purpose='Too soon',
            )),
        )

    def test_http_economy_routes_publish_canonical_results(self):
        store = WorldStore()
        with TestClient(create_app(world_store=store)) as client:
            client.post('/game/start')
            economy = client.get('/economy')
            transfer = client.post('/economy/transfers', json={
                'request_id': 'http-transfer',
                'sender_id': 'robot-a',
                'recipient_id': 'robot-b',
                'amount': 5,
                'purpose': 'HTTP contract test',
            })
            ineligible = client.post('/economy/unlock-proposals', json={
                'request_id': 'http-unlock',
                'proposer_id': 'robot-a',
                'stage': 2,
                'contributions': {'robot-a': 15, 'robot-b': 15},
            })

        self.assertEqual(economy.status_code, 200)
        self.assertEqual(economy.json()['unlocks'][0]['stage'], 2)
        self.assertEqual(transfer.status_code, 201)
        self.assertEqual(transfer.json()['amount'], 5)
        self.assertEqual(ineligible.status_code, 409)
        self.assertEqual(ineligible.json()['error']['code'], 'STAGE_NOT_ELIGIBLE')


if __name__ == '__main__':
    unittest.main()
