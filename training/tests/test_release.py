import pytest

from pocketsql.release import gate


def row(model: str, runtime: str, ex: float, missing: int = 0) -> dict:
    return {
        "model": model,
        "runtime": runtime,
        "set": "own_test",
        "ex": ex,
        "missing": missing,
    }


BASE = [
    row("qwen2.5-coder-0.5b", "torch-cpu", 0.36),
    row("qwen2.5-coder-0.5b-export", "onnx-q4f16-webgpu", 0.29),
    row("qwen2.5-coder-0.5b-export", "onnx-q4-cpu", 0.4),
    row("gpt-oss-120b", "groq", 0.77),
]
CANDIDATE = "pocketsql-0.5b-v1"


def test_base_ex_is_like_for_like() -> None:
    results = [*BASE, row(CANDIDATE, "onnx-q4-cpu", 0.9)]
    assert gate.base_ex("qwen2.5-coder-0.5b", "onnx-q4f16-webgpu", results) == 0.29
    assert gate.base_ex("qwen2.5-coder-0.5b", "onnx-q4-cpu", results) == 0.4
    assert gate.base_ex("qwen2.5-coder-0.5b", "onnx-fp16-webgpu", results) is None


@pytest.mark.parametrize(
    ("q4f16", "q4", "previous", "passed"),
    [
        (0.5, 0.48, None, True),
        (0.5, 0.39, None, False),  # q4 below the base model's q4 export
        (0.28, 0.48, None, False),  # q4f16 below the base model's q4f16 export
        (0.5, 0.48, 0.49, False),  # q4 below the previous release
        (0.5, 0.49, 0.49, True),
    ],
)
def test_gate(q4f16: float, q4: float, previous: float | None, passed: bool) -> None:
    results = [
        *BASE,
        row(CANDIDATE, "onnx-q4f16-webgpu", q4f16),
        row(CANDIDATE, "onnx-q4-cpu", q4),
    ]
    baseline = (
        None
        if previous is None
        else {"ex": {"own_test": dict.fromkeys(gate.SHIPPED, previous)}}
    )
    assert gate.gate(CANDIDATE, results, baseline)[0] is passed


def test_gate_needs_every_shipped_dtype_complete() -> None:
    results = [*BASE, row(CANDIDATE, "onnx-q4f16-webgpu", 0.6)]
    assert not gate.gate(CANDIDATE, results, None)[0]
    results.append(row(CANDIDATE, "onnx-q4-cpu", 0.6, missing=3))
    assert not gate.gate(CANDIDATE, results, None)[0]
