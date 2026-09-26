"""LoRA SFT with TRL + PEFT (.claude/rules/training.md): conversational
prompt-completion pairs in the app's chat format, so the loss covers only the SQL."""

from pathlib import Path

from pocketsql.data.schema import messages


def to_example(row: dict) -> dict:
    return {
        "prompt": messages(row["schema_text"], row["question"]),
        "completion": [{"role": "assistant", "content": row["sql"]}],
    }


def fit_length(tok, rows: list[dict], max_len: int) -> tuple[list[dict], list[str]]:
    """Keep pairs whose full chat (prompt + SQL + end of turn) fits in max_len tokens;
    TRL would otherwise cut the SQL off. Returns (kept rows, dropped ids)."""
    kept, dropped = [], []
    for row in rows:
        ex = to_example(row)
        n = len(
            tok.apply_chat_template(
                ex["prompt"] + ex["completion"], tokenize=True, return_dict=True
            )["input_ids"]
        )
        if n <= max_len:
            kept.append(row)
        else:
            dropped.append(row["id"])
    return kept, dropped


def train(
    cfg: dict,
    base_dir: Path,
    train_rows: list[dict],
    val_rows: list[dict],
    work: Path,
    max_steps: int | None = None,
):
    """Train LoRA adapters on the base model; returns (merged fp32 model, metrics)."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    t, lora = cfg["train"], cfg["lora"]
    gpu = torch.cuda.is_available()
    args = SFTConfig(
        output_dir=str(work / "checkpoints"),
        num_train_epochs=t["epochs"],
        max_steps=max_steps or -1,
        per_device_train_batch_size=t["per_device_batch"],
        per_device_eval_batch_size=t["per_device_batch"],
        gradient_accumulation_steps=t["grad_accum"],
        learning_rate=t["learning_rate"],
        lr_scheduler_type=t["lr_scheduler"],
        warmup_steps=t["warmup"],
        max_length=t["max_seq_len"],
        fp16=gpu,  # T4 and P100 have no bf16; the fp32 master weights stay in fp32
        bf16=False,
        use_cpu=not gpu,
        seed=t["seed"],
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=10,
        report_to="none",
    )
    peft_config = LoraConfig(
        r=lora["r"],
        lora_alpha=lora["alpha"],
        lora_dropout=lora["dropout"],
        target_modules=lora["target_modules"],
        task_type="CAUSAL_LM",
    )
    trainer = SFTTrainer(
        model=AutoModelForCausalLM.from_pretrained(base_dir, dtype=torch.float32),
        args=args,
        train_dataset=Dataset.from_list([to_example(r) for r in train_rows]),
        eval_dataset=Dataset.from_list([to_example(r) for r in val_rows]),
        processing_class=AutoTokenizer.from_pretrained(base_dir),
        peft_config=peft_config,
    )
    result = trainer.train()
    logs = trainer.state.log_history
    metrics = {
        "steps": trainer.state.global_step,
        "epochs": round(trainer.state.epoch or 0, 3),
        "train_loss": round(result.training_loss, 4),
        "train_runtime_s": round(result.metrics["train_runtime"], 1),
        "trainable_params": sum(
            p.numel() for p in trainer.model.parameters() if p.requires_grad
        ),
        "val_loss_by_epoch": [
            round(e["eval_loss"], 4) for e in logs if "eval_loss" in e
        ],
        "loss_curve": [
            {"step": e["step"], "loss": round(e["loss"], 4)}
            for e in logs
            if "loss" in e
        ],
    }
    return trainer.model.merge_and_unload(), metrics
