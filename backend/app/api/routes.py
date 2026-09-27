"""HTTP routes for authoritative world and robot state transitions."""

from fastapi import APIRouter

from app.api.errors import ApiError
from app.schemas import (
    AcceptedResponse,
    ArrivalReport,
    BlockedReport,
    EconomyResponseRequest,
    EconomyState,
    Goal,
    GoalRequest,
    GameStopRequest,
    HealthReport,
    Market,
    MoneyRequestCreate,
    MoneyRequestState,
    MoneyTransfer,
    MoneyTransferRequest,
    PoseReport,
    Robot,
    RobotsResponse,
    RobotTask,
    StageUnlockProposal,
    StageUnlockProposalRequest,
    TaskRequest,
    TasksResponse,
    WorldSnapshot,
)
from app.state import WorldStateError, WorldStore


ERROR_STATUS_CODES = {
    'PERSISTENCE_UNAVAILABLE': 503,
    'INVALID_REQUEST': 400,
    'NOT_FOUND': 404,
    'REQUEST_ID_CONFLICT': 409,
    'GAME_NOT_RUNNING': 409,
    'GAME_NOT_READY': 409,
    'GAME_COMPLETED': 409,
    'ROBOT_BUSY': 409,
    'ROBOT_STOPPED': 409,
    'ROBOT_UNAVAILABLE': 409,
    'TASK_MISMATCH': 409,
    'INSUFFICIENT_INVENTORY': 409,
    'INSUFFICIENT_FUNDS': 409,
    'OUT_OF_STOCK': 409,
    'SEED_LOCKED': 409,
    'PLOT_OCCUPIED': 409,
    'PLOT_NOT_READY': 409,
    'SESSION_MISMATCH': 409,
    'REQUEST_PENDING': 409,
    'REQUEST_RESOLVED': 409,
    'NOT_AUTHORIZED': 403,
    'INVALID_STAGE': 409,
    'STAGE_UNLOCKED': 409,
    'STAGE_NOT_ELIGIBLE': 409,
    'PROPOSAL_PENDING': 409,
    'PROPOSAL_RESOLVED': 409,
}


def translate_world_error(error: WorldStateError) -> ApiError:
    return ApiError(
        ERROR_STATUS_CODES.get(error.code, 500),
        error.code,
        error.message,
    )


def create_world_router(store: WorldStore) -> APIRouter:
    router = APIRouter(tags=['world'])

    @router.get('/world', response_model=WorldSnapshot)
    def world() -> WorldSnapshot:
        return store.snapshot()

    @router.get('/robots', response_model=RobotsResponse)
    def robots() -> RobotsResponse:
        return RobotsResponse(robots=store.robots())

    @router.get('/robots/{robot_id}', response_model=Robot)
    def robot(robot_id: str) -> Robot:
        try:
            return store.robot(robot_id)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.get('/market', response_model=Market)
    def market() -> Market:
        return store.market()

    @router.get('/economy', response_model=EconomyState)
    def economy() -> EconomyState:
        return store.economy()

    @router.post('/economy/transfers', response_model=MoneyTransfer, status_code=201)
    def transfer_money(request: MoneyTransferRequest) -> MoneyTransfer:
        try:
            return store.transfer_money(request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post(
        '/economy/money-requests',
        response_model=MoneyRequestState,
        status_code=201,
    )
    def create_money_request(request: MoneyRequestCreate) -> MoneyRequestState:
        try:
            return store.create_money_request(request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post(
        '/economy/money-requests/{money_request_id}/respond',
        response_model=MoneyRequestState,
    )
    def respond_money_request(
        money_request_id: str,
        request: EconomyResponseRequest,
    ) -> MoneyRequestState:
        try:
            return store.respond_money_request(money_request_id, request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post(
        '/economy/unlock-proposals',
        response_model=StageUnlockProposal,
        status_code=201,
    )
    def propose_stage_unlock(
        request: StageUnlockProposalRequest,
    ) -> StageUnlockProposal:
        try:
            return store.propose_stage_unlock(request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post(
        '/economy/unlock-proposals/{proposal_id}/respond',
        response_model=StageUnlockProposal,
    )
    def respond_stage_unlock(
        proposal_id: str,
        request: EconomyResponseRequest,
    ) -> StageUnlockProposal:
        try:
            return store.respond_stage_unlock(proposal_id, request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.get('/tasks', response_model=TasksResponse)
    def tasks() -> TasksResponse:
        return TasksResponse(tasks=store.tasks())

    @router.get('/tasks/{task_id}', response_model=RobotTask)
    def task(task_id: str) -> RobotTask:
        try:
            return store.task(task_id)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/goal', response_model=Goal)
    def configure_goal(request: GoalRequest) -> Goal:
        try:
            return store.configure_goal(request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/game/start', response_model=WorldSnapshot)
    def start_game() -> WorldSnapshot:
        try:
            return store.start_game()
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/game/stop', response_model=WorldSnapshot)
    def stop_game(request: GameStopRequest | None = None) -> WorldSnapshot:
        try:
            return store.stop_game(session_id=request.session_id if request else None)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/game/reset', response_model=WorldSnapshot)
    def reset_game() -> WorldSnapshot:
        try:
            return store.reset_game()
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/tasks', response_model=RobotTask, status_code=202)
    def create_task(request: TaskRequest) -> RobotTask:
        try:
            return store.assign_task(request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/robots/{robot_id}/pose', response_model=AcceptedResponse)
    def update_robot_pose(robot_id: str, report: PoseReport) -> AcceptedResponse:
        try:
            return AcceptedResponse(accepted=store.update_pose(robot_id, report))
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/robots/{robot_id}/health', response_model=AcceptedResponse)
    def update_robot_health(robot_id: str, report: HealthReport) -> AcceptedResponse:
        try:
            return AcceptedResponse(accepted=store.update_health(robot_id, report))
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/robots/{robot_id}/arrived', response_model=AcceptedResponse)
    def confirm_robot_arrival(robot_id: str, report: ArrivalReport) -> AcceptedResponse:
        try:
            return AcceptedResponse(accepted=store.confirm_arrival(robot_id, report))
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/robots/{robot_id}/blocked', response_model=AcceptedResponse)
    def report_robot_blocked(robot_id: str, report: BlockedReport) -> AcceptedResponse:
        try:
            return AcceptedResponse(accepted=store.report_blocked(robot_id, report))
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/robots/{robot_id}/stop', response_model=Robot)
    def stop_robot(robot_id: str) -> Robot:
        try:
            return store.stop_robot(robot_id)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/robots/{robot_id}/resume', response_model=Robot)
    def resume_robot(robot_id: str) -> Robot:
        try:
            return store.resume_robot(robot_id)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    return router
