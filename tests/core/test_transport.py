from keysight_power_core.transport import dry_run_plan


def test_dry_run_plan_is_data_only() -> None:
    plan = dry_run_plan(
        command="set",
        resource="USB0::SIM::E36312A::INSTR",
        scpi=("CURR 0.05", "VOLT 1.0"),
        description="Preview setting current before voltage.",
    )

    assert plan == {
        "operation": {"name": "set"},
        "target": {"resource": "USB0::SIM::E36312A::INSTR", "model_profile": None},
        "steps": [
            {
                "index": 1,
                "type": "scpi",
                "command": "CURR 0.05",
            },
            {
                "index": 2,
                "type": "scpi",
                "command": "VOLT 1.0",
            },
        ],
        "description": "Preview setting current before voltage.",
        "hardware_touched": False,
    }
