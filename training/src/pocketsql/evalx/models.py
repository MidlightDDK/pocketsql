"""Models in the reports: pinned revisions, licenses, and browser download sizes.

Download sizes are the text-generation files Transformers.js fetches for a dtype
(ONNX graph + external data + tokenizer/config), summed from the Hub API
(https://huggingface.co/api/models/<repo>?blobs=true) at the pinned revision.
"""

MODELS: dict[str, dict] = {
    "qwen3-0.6b": {
        "hf_repo": "Qwen/Qwen3-0.6B",
        "revision": "c1899de289a04d12100db370d81485cdf75e47ca",
        "license": "apache-2.0",
        "params_b": 0.6,
        "onnx_repo": "onnx-community/Qwen3-0.6B-ONNX",
        "onnx_revision": "da1453100cf3ff33ef56d17983fc7a8648706db6",
        "download_mib": {"q4f16": 552, "q4": 885},
    },
    "qwen2.5-coder-0.5b": {
        "hf_repo": "Qwen/Qwen2.5-Coder-0.5B-Instruct",
        "revision": "ea3f2471cf1b1f0db85067f1ef93848e38e88c25",
        "license": "apache-2.0",
        "params_b": 0.5,
        "onnx_repo": "onnx-community/Qwen2.5-Coder-0.5B-Instruct",
        "onnx_revision": "f0292f665fd307846ff3c318a91a1bc29d091492",
        "download_mib": {"q4f16": 540, "q4": 833},
    },
    "qwen3.5-0.8b": {
        "hf_repo": "Qwen/Qwen3.5-0.8B",
        "revision": "2fc06364715b967f1860aea9cf38778875588b17",
        "license": "apache-2.0",
        "params_b": 0.8,
        "onnx_repo": "onnx-community/Qwen3.5-0.8B-ONNX",
        "onnx_revision": "c0d619322dad7c4441a8841a53fc59772ddddcc0",
        "download_mib": {"q4f16": 576, "q4": 637},
    },
    # Our re-exports (pocketsql.export.build); sizes summed from the local files.
    "qwen2.5-coder-0.5b-export": {
        "base": "qwen2.5-coder-0.5b",
        "hf_repo": "MidlightDDK/pocketsql-base-0.5b",
        "revision": "cdb0fbdbb0af527488cdae1029a0c11af0da8a5d",
        "recipe": "int4 block_size=32",
        "download_mib": {"q4f16": 276, "q4": 310},
    },
    "qwen3-0.6b-export": {
        "base": "qwen3-0.6b",
        "recipe": "int4 block_size=32",
        "download_mib": {"q4f16": 341, "q4": 387},
    },
    "qwen3-0.6b-kq": {
        "base": "qwen3-0.6b",
        "recipe": "int4 block_size=32, k_quant, last_matmul + mixed_layers int8",
        "download_mib": {"q4f16": 477, "q4": 523},
    },
    "qwen3-0.6b-official": {
        "base": "qwen3-0.6b",
        "hf_repo": "onnx-community/Qwen3-0.6B-ONNX",
        "revision": "da1453100cf3ff33ef56d17983fc7a8648706db6",
        "download_mib": {"q4f16": 552, "q4": 885},
    },
    # Fine-tuned runs (training/runs/<run_id>), release candidates for the gate. A
    # release holds merged fp16 weights and ONNX in one Hub repo; torch-cpu rows come
    # from the merged weights.
    "pocketsql-0.5b-v1": {
        "base": "qwen2.5-coder-0.5b",
        "run_id": "v1",  # refused by the gate, never uploaded
        "license": "apache-2.0",
        "params_b": 0.5,
        "recipe": "LoRA SFT on Spider (run v1), merged; int4 block_size=32",
        "download_mib": {"q4f16": 276, "q4": 310},
    },
    # Export experiment: run v1's merged weights, q4f16 with the builder's k-quant.
    "pocketsql-0.5b-v1-kq": {
        "base": "qwen2.5-coder-0.5b",
        "run_id": "v1",
        "license": "apache-2.0",
        "params_b": 0.5,
        "recipe": "run v1, merged; int4 block_size=32, algo_config=k_quant",
        "download_mib": {"q4f16": 283},
    },
    "pocketsql-0.5b-v2": {
        "base": "qwen2.5-coder-0.5b",
        "run_id": "v2",
        "hf_repo": "MidlightDDK/pocketsql-0.5b",
        "revision": "de60f0f6515208c9b24fe9d9d36f56f1dc336506",
        "license": "apache-2.0",
        "params_b": 0.5,
        "recipe": "LoRA SFT on Spider + 591 synthetic pairs (run v2), merged; "
        "int4 block_size=32",
        "download_mib": {"q4f16": 276, "q4": 310},
    },
    # Large API baseline (pocketsql.evalx.predict_groq).
    "gpt-oss-120b": {
        "hf_repo": "openai/gpt-oss-120b",
        "license": "apache-2.0",
        "params_b": 117,
        "provider": "groq",
        # Paid-tier list price, USD per 1M tokens (input, output):
        # https://console.groq.com/docs/model/openai/gpt-oss-120b
        "price_per_m_usd": [0.15, 0.60],
    },
}
