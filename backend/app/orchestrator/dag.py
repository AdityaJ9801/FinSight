"""Job DAG: three sequential stage-gates (data -> analysis -> delivery), with the real
fan-out happening inside each stage (design doc §3.3). Templates only vary which analysis
modules run within stage 2 (see templates.py) -- the stage sequence itself is fixed, which
keeps every job resumable at the same three checkpoints regardless of template.
"""
STAGES = ["data", "analysis", "delivery"]


def build_stage_dag(plan_template: str) -> list[str]:
    return list(STAGES)
