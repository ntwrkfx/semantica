from pathlib import Path

from integrations.shadow_projection_v1.verification import run_acceptance

FIXTURES = Path(__file__).parent / "fixtures"


def test_all_gates_pass(tmp_path):
    receipt = run_acceptance(
        tmp_path,
        [FIXTURES / "source_a.json", FIXTURES / "source_b_conflict.json"],
    )
    assert receipt.semantica_version_or_sha == (
        "v0.6.5@5b319560fb0b8403644b70bc592864418cdcc740"
    )
    assert receipt.projection_contract_version == "shadow-projection/v1"
    assert receipt.replay_run_1_digest == receipt.replay_run_2_digest
    assert receipt.provenance_integrity_status == "PASS"
    assert receipt.validation_status == "PASS"
    assert set(receipt.acceptance_gates) == {"G%d" % n for n in range(1, 13)}
    assert all(value == "PASS" for value in receipt.acceptance_gates.values())
