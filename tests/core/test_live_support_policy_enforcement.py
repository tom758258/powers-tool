import pytest

from keysight_power_core.core import CoreValidationError, OperationRequest, RuntimeOptions
from keysight_power_core.instrument_io import run_instrument_io
from keysight_power_core.live_support import enforce_live_support
from keysight_power_core.operations import run_operation
from keysight_power_core.protection import run_protection
from keysight_power_core.readonly import run_readonly
from keysight_power_core.snapshot import run_snapshot
from keysight_power_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_PRODUCT,
    SUPPORT_POLICY_MODE_VALIDATION,
)


class FakeSession:
    def __init__(self, idn: str) -> None:
        self.idn = idn
        self.queries: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def query(self, command: str) -> str:
        self.queries.append(command)
        return {
            "*IDN?": self.idn,
            "MEAS:VOLT?": "1.0",
            "MEAS:CURR?": "0.1",
        }.get(command, '0,"No error"')

    def write(self, command: str) -> None:
        self.writes.append(command)


def _request(
    command: str,
    resource: str,
    *,
    backend: str | None = None,
    model: str | None = None,
    support_policy_mode: str = SUPPORT_POLICY_MODE_PRODUCT,
) -> OperationRequest:
    return OperationRequest(
        command,
        RuntimeOptions(
            resource=resource,
            backend=backend,
            model_profile=model,
            support_policy_mode=support_policy_mode,
        ),
    )


def test_runtime_options_defaults_to_product_support_policy_mode() -> None:
    assert RuntimeOptions().support_policy_mode == SUPPORT_POLICY_MODE_PRODUCT


@pytest.mark.parametrize(
    ("idn", "resource"),
    [
        ("KEYSIGHT,E36312A,SN,1.0", "USB0::1::INSTR"),
        ("KEYSIGHT,E36312A,SN,1.0", "TCPIP0::192.0.2.1::INSTR"),
        ("KEYSIGHT,EDU36311A,SN,1.0", "USB0::1::INSTR"),
        ("KEYSIGHT,EDU36311A,SN,1.0", "TCPIP0::192.0.2.1::INSTR"),
        ("KEYSIGHT,E3646A,SN,1.0", "ASRL1::INSTR"),
    ],
)
def test_validated_measure_scopes_authorize_after_idn(idn: str, resource: str) -> None:
    session = FakeSession(idn)
    data = run_instrument_io(_request("measure", resource), opener=lambda *args, **kwargs: session)
    assert data["measurements"] == {"voltage": 1.0, "current": 0.1}
    assert session.queries[0] == "*IDN?"
    assert "MEAS:VOLT?" in session.queries
    assert "MEAS:CURR?" in session.queries


@pytest.mark.parametrize(
    ("idn", "resource", "backend", "status"),
    [
        ("KEYSIGHT,E36312A,SN,1.0", "TCPIP0::192.0.2.1::INSTR", "@py", "transport_pending"),
        ("KEYSIGHT,EDU36311A,SN,1.0", "TCPIP0::192.0.2.1::INSTR", "@py", "transport_pending"),
        ("KEYSIGHT,E3646A,SN,1.0", "USB0::1::INSTR", None, "profile_validated"),
        ("KEYSIGHT,E36312A,SN,1.0", "GPIB0::1::INSTR", None, "profile_validated"),
        ("KEYSIGHT,E36312A,SN,1.0", "TCPIP0::192.0.2.1::INSTR", "@ivi", "profile_validated"),
    ],
)
def test_rejected_measure_scope_only_queries_idn(idn: str, resource: str, backend: str | None, status: str) -> None:
    session = FakeSession(idn)
    with pytest.raises(LiveSupportPolicyError, match=status) as raised:
        run_instrument_io(_request("measure", resource, backend=backend), opener=lambda *args, **kwargs: session)
    assert "policy_mode=product" in str(raised.value)
    assert session.queries == ["*IDN?"]
    assert session.closed


@pytest.mark.parametrize("model", ["E36312A", "EDU36311A"])
def test_validation_mode_allows_registered_tcpip_pyvisa_py_measure_scope(model: str) -> None:
    session = FakeSession(f"KEYSIGHT,{model},SN,1.0")
    data = run_instrument_io(
        _request(
            "measure",
            "TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        opener=lambda *args, **kwargs: session,
    )
    assert data["measurements"] == {"voltage": 1.0, "current": 0.1}
    assert session.queries == ["*IDN?", "MEAS:VOLT?", "MEAS:CURR?"]
    assert session.closed


def test_validation_mode_keeps_unregistered_scopes_and_commands_closed() -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    with pytest.raises(LiveSupportPolicyError, match="no exact transport/backend scope"):
        run_instrument_io(
            _request(
                "measure",
                "USB0::1::INSTR",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


@pytest.mark.parametrize(
    ("operation_request", "detected_model", "message"),
    [
        (
            _request(
                "missing-command",
                "USB0::1::INSTR",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            "E36312A",
            "missing_or_unknown_metadata",
        ),
        (
            _request(
                "trigger-list",
                "TCPIP0::192.0.2.1::INSTR",
                backend="@py",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            "EDU36311A",
            "not_supported_by_model",
        ),
    ],
)
def test_validation_mode_keeps_missing_and_unsupported_metadata_closed(
    operation_request: OperationRequest,
    detected_model: str,
    message: str,
) -> None:
    with pytest.raises(LiveSupportPolicyError, match=message):
        enforce_live_support(operation_request, detected_model)


def test_unknown_runtime_policy_mode_rejects_after_idn_before_measurement() -> None:
    session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    with pytest.raises(LiveSupportPolicyError, match="unknown_policy_mode"):
        run_instrument_io(
            _request("measure", "USB0::1::INSTR", support_policy_mode="future"),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_expected_model_mismatch_precedes_validation_pending_scope_authorization() -> None:
    session = FakeSession("KEYSIGHT,EDU36311A,SN,1.0")
    with pytest.raises(CoreValidationError, match="Expected model E36312A"):
        run_instrument_io(
            _request(
                "measure",
                "TCPIP0::192.0.2.1::INSTR",
                backend="@py",
                model="E36312A",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_expected_model_mismatch_precedes_scope_rejection() -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    with pytest.raises(CoreValidationError, match="Expected model E36312A"):
        run_instrument_io(
            _request("measure", "USB0::1::INSTR", model="E36312A"),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]


@pytest.mark.parametrize(
    ("runner", "command", "parameters"),
    [
        (run_readonly, "read-status", {}),
        (run_readonly, "readback", {}),
        (run_readonly, "measure-all", {}),
        (run_protection, "protection-status", {}),
        (run_protection, "protection-set", {"channel": 1, "ovp_voltage": 2.0}),
        (run_protection, "clear-protection", {"channel": 1}),
        (run_snapshot, "snapshot", {}),
    ],
)
def test_model_aware_runners_reject_before_command_scpi(runner, command: str, parameters: dict[str, object]) -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    request = OperationRequest(command, RuntimeOptions(resource="USB0::1::INSTR", confirm=True), parameters)
    with pytest.raises(LiveSupportPolicyError):
        runner(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_output_without_exact_evidence_rejects_after_idn_before_write() -> None:
    session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    request = OperationRequest(
        "output-on", RuntimeOptions(resource="USB0::1::INSTR", confirm=True), {"channel": 1}
    )
    with pytest.raises(LiveSupportPolicyError, match="output-on"):
        run_operation(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_validation_mode_does_not_open_output_without_exact_scope() -> None:
    session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    request = OperationRequest(
        "output-on",
        RuntimeOptions(
            resource="USB0::1::INSTR",
            confirm=True,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"channel": 1},
    )
    with pytest.raises(LiveSupportPolicyError, match="no exact transport/backend scope"):
        run_operation(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_exempt_clear_keeps_its_existing_no_idn_behavior() -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    data = run_instrument_io(_request("clear", "USB0::1::INSTR"), opener=lambda *args, **kwargs: session)
    assert data["cleared"] is True
    assert session.queries == []
    assert session.writes == ["*CLS"]
