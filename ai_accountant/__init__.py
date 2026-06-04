"""AI Accountant — generate Financial Statement notes from transactional data.

Package layout:
    config            constants, model name, paths, ground-truth values
    llm.client        GPT-5.1 wrapper (JSON mode, retries, logging)
    ingestion.*       profile files -> sheets -> tables; load data
    routing.*         typed schemas + LLM value-routing map (file->sheet->table->role->note)
    policy.*          parse policy docs -> classification rules
    compute.*         AI codegen + guardrailed execution; the L4->L3->L2->L1 cascade
    validation.*      reconcile computed vs ground truth / uploaded levels
    export.*          Excel / PDF export
"""

__version__ = "0.1.0"
