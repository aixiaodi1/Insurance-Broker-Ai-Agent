from app.agents.nodes.intake_nodes import novice_intake, task_router


def run_intake_graph(state: dict) -> dict:
    state = novice_intake(state)
    state = task_router(state)
    return state
