"""Export a Qwen3 checkpoint to a Transformers.js v4 model folder.

How the official build was made (checked once, 2026-09-26): the graphs in
onnx-community/Qwen3-0.6B-ONNX@da14531 have producer "onnxruntime-genai", i.e. they
come from the ONNX Runtime GenAI model builder (GroupQueryAttention + MatMulNBits
block 32, fp16 KV cache for q4f16), not from Optimum. We use the same builder:
https://github.com/microsoft/onnxruntime-genai/blob/v0.16.0/src/python/py/models/README.md
Transformers.js loads `onnx/model{suffix}.onnx` plus `<file>_data` external data and
reads `transformers.js_config` in config.json (dtype per device, KV cache dtype):
https://huggingface.co/docs/transformers.js/custom_usage

`uv run --project training --group export python -m pocketsql.export.build
--src <hf model dir> --out .cache/export/<name> [--dtypes q4f16 q4 fp16 fp32]`
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import onnx

# Transformers.js dtype -> (builder precision, execution provider, extra options).
VARIANTS = {
    "fp32": ("fp32", "cpu", []),
    "fp16": ("fp16", "webgpu", []),
    "q4": ("int4", "cpu", ["block_size=32"]),
    "q4f16": ("int4", "webgpu", ["block_size=32"]),
}
SUFFIX = {"fp32": "", "fp16": "_fp16", "q4": "_q4", "q4f16": "_q4f16"}
COPY = ("generation_config.json", "tokenizer.json", "tokenizer_config.json")
SINGLE_FILE_LIMIT = 1_900_000_000  # protobuf caps a single .onnx file at 2 GiB


def build_variant(src: Path, work: Path, dtype: str, quant: list[str]) -> Path:
    precision, ep, extra = VARIANTS[dtype]
    extra = extra + quant if precision == "int4" else extra
    out = work / dtype
    cmd = [
        sys.executable, "-m", "onnxruntime_genai.models.builder",
        "-i", str(src), "-o", str(out), "-p", precision, "-e", ep,
        "-c", str(work / "tmp"),
    ]  # fmt: skip
    if extra:
        cmd += ["--extra_options", *extra]
    subprocess.run(cmd, check=True)
    return out / "model.onnx"


def static_head_dim(model: onnx.ModelProto, head_dim: int) -> None:
    """Transformers.js sizes the empty KV cache from the declared input shapes, so
    the builder's symbolic `kv_cache_dim` would become 0; pin it to head_dim."""
    for v in (*model.graph.input, *model.graph.output):
        if v.name.startswith(("past_key_values.", "present.")):
            dim = v.type.tensor_type.shape.dim[3]
            if dim.dim_param:
                dim.dim_value = head_dim


def portable_embedding(model: onnx.ModelProto) -> None:
    """Replace the int4 GatherBlockQuantized embedding (tied to the lm_head's packed
    MatMulNBits weights), which onnxruntime-web's WASM build lacks, with standard ops
    that gather the packed rows first and dequantize only those: bit-exact, no new
    weights. Assumes uint8-packed int4 (low nibble first) and no zero points (8)."""
    g = model.graph
    old = next((n for n in g.node if n.op_type == "GatherBlockQuantized"), None)
    if old is None:
        return
    attrs = {a.name: onnx.helper.get_attribute_value(a) for a in old.attribute}
    assert attrs["bits"] == 4 and attrs["gather_axis"] == 0 and len(old.input) == 3
    packed, ids, scales = old.input
    p = "/model/embed_tokens/portable/"
    const = {
        "c16": onnx.helper.make_tensor(p + "c16", onnx.TensorProto.INT32, [], [16]),
        "zp": onnx.helper.make_tensor(p + "zp", onnx.TensorProto.FLOAT, [], [8.0]),
        "last": onnx.helper.make_tensor(p + "last", onnx.TensorProto.INT64, [1], [-1]),
        "blocks": onnx.helper.make_tensor(
            p + "blocks", onnx.TensorProto.INT64, [4], [0, 0, -1, attrs["block_size"]]
        ),
        "flat": onnx.helper.make_tensor(
            p + "flat", onnx.TensorProto.INT64, [3], [0, 0, -1]
        ),
    }
    g.initializer.extend(const.values())
    c = {k: t.name for k, t in const.items()}
    node = onnx.helper.make_node
    nodes = [
        node("Gather", [packed, ids], [p + "rows"], axis=0),
        node("Cast", [p + "rows"], [p + "rows_i32"], to=onnx.TensorProto.INT32),
        node("Mod", [p + "rows_i32", c["c16"]], [p + "lo"]),
        node("Div", [p + "rows_i32", c["c16"]], [p + "hi"]),
        node("Unsqueeze", [p + "lo", c["last"]], [p + "lo_u"]),
        node("Unsqueeze", [p + "hi", c["last"]], [p + "hi_u"]),
        node("Concat", [p + "lo_u", p + "hi_u"], [p + "pairs"], axis=-1),
        node("Reshape", [p + "pairs", c["blocks"]], [p + "q"]),
        node("Cast", [p + "q"], [p + "qf"], to=onnx.TensorProto.FLOAT),
        node("Sub", [p + "qf", c["zp"]], [p + "centered"]),
        node("Gather", [scales, ids], [p + "row_scales"], axis=0),
        node("Unsqueeze", [p + "row_scales", c["last"]], [p + "scales_u"]),
        node("Mul", [p + "centered", p + "scales_u"], [p + "deq"]),
        node("Reshape", [p + "deq", c["flat"]], list(old.output)),
    ]
    at = list(g.node).index(old)
    g.node.remove(old)
    for i, n in enumerate(nodes):
        g.node.insert(at + i, n)


def save_for_transformers_js(
    model_path: Path, dest: Path, head_dim: int, dtype: str
) -> bool:
    """Re-save under Transformers.js file names; True if external data was needed."""
    size = sum(f.stat().st_size for f in model_path.parent.glob("model.onnx*"))
    external = size > SINGLE_FILE_LIMIT
    model = onnx.load(str(model_path), load_external_data=True)
    static_head_dim(model, head_dim)
    if dtype == "q4":  # the WASM variant; WebGPU implements GatherBlockQuantized
        portable_embedding(model)
    onnx.save_model(
        model,
        str(dest),
        save_as_external_data=external,
        all_tensors_to_one_file=True,
        location=f"{dest.name}_data",
    )
    return external


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pocketsql.export.build")
    parser.add_argument("--src", type=Path, required=True, help="HF model directory")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--dtypes", nargs="+", choices=sorted(VARIANTS), default=list(VARIANTS)
    )
    parser.add_argument(
        "--quant", nargs="*", default=[], help="extra builder options for int4 variants"
    )
    args = parser.parse_args(argv)
    onnx_dir = args.out / "onnx"
    onnx_dir.mkdir(parents=True, exist_ok=True)
    work = args.out / "build"
    config = json.loads((args.src / "config.json").read_text(encoding="utf-8"))
    tjs = config.get("transformers.js_config", {})
    external = dict(tjs.get("use_external_data_format", {}))
    head_dim = (
        config.get("head_dim") or config["hidden_size"] // config["num_attention_heads"]
    )
    for dtype in args.dtypes:
        built = build_variant(args.src, work, dtype, args.quant)
        name = f"model{SUFFIX[dtype]}.onnx"
        if save_for_transformers_js(built, onnx_dir / name, head_dim, dtype):
            external[name] = 1
        else:
            external.pop(name, None)
        print(f"{dtype}: {name}", flush=True)
    config["transformers.js_config"] = {
        "kv_cache_dtype": {"q4f16": "float16", "fp16": "float16"},
        "use_external_data_format": external,
        "device_config": {"webgpu": {"dtype": "q4f16"}, "wasm": {"dtype": "q4"}},
    }
    (args.out / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for name in COPY:
        shutil.copyfile(args.src / name, args.out / name)
    shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
