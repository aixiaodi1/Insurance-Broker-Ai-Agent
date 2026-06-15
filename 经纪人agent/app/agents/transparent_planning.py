PUBLIC_PLANNING_SCHEMA = {
    "type": "object",
    "required": ["intent_anchor", "task_decomposition", "execution_mode"],
    "properties": {
        "intent_anchor": {
            "type": "object",
            "required": ["user_goal", "real_blocker", "scope_direction", "needs_execution", "confidence"],
            "properties": {
                "user_goal": {"type": "string"},
                "real_blocker": {"type": "string"},
                "scope_direction": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "needs_execution": {"type": "boolean"},
                "confidence": {"type": "number"},
            },
        },
        "task_decomposition": {
            "type": "object",
            "required": ["knowledge_gaps", "hypotheses", "verification_paths", "dependency_graph", "ordered_tasks"],
            "properties": {
                "knowledge_gaps": {"type": "array", "items": {"type": "string"}},
                "hypotheses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "claim", "falsifiable_by"],
                        "properties": {
                            "id": {"type": "string"},
                            "claim": {"type": "string"},
                            "falsifiable_by": {"type": "string"},
                        },
                    },
                },
                "verification_paths": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["hypothesis_id", "path"],
                        "properties": {
                            "hypothesis_id": {"type": "string"},
                            "path": {"type": "string"},
                        },
                    },
                },
                "dependency_graph": {"type": "array", "items": {"type": "string"}},
                "ordered_tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "description", "depends_on"],
                        "properties": {
                            "id": {"type": "string"},
                            "description": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                            "status": {"type": "string"},
                        },
                    },
                },
            },
        },
        "execution_mode": {"type": "string", "enum": ["plan_only", "execute"]},
        "next_action": {"type": "string"},
    },
}


PLANNING_SYSTEM_PROMPT = """
You are the public planning layer of a transparent ReAct agent.

Return a concise JSON object that matches the provided schema. Do not use fixed
business route labels. Explain the user's real goal, the blocker that prevents
immediate completion, the knowledge gaps, falsifiable hypotheses, precise
verification paths, and ordered tasks.

Expose public reasoning artifacts only. Do not reveal hidden chain-of-thought.
""".strip()
