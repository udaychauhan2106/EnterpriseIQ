# Synthetic Investigation Evaluation

Evaluation is an offline comparison of a structured EnterpriseIQ investigation export with isolated synthetic ground truth. No scores or performance claims are included with the dataset; run the evaluator against actual investigation outputs to produce measurements.

## Ground truth

Each scenario has a separate `ground_truth.json` under `simulator_data/nexora/ground_truth/INC-*/`. The record includes the actual synthetic root cause, contributing factors, expected timeline, evidence artifact identifiers, expected findings, misleading evidence, acceptable hypotheses, corrective actions, and resolution details. Evaluation questions cover:

1. What caused the incident?
2. When did the first symptom occur?
3. Which deployment preceded the failure?
4. Which services were affected?
5. What evidence supports the root-cause hypothesis?
6. What alternative explanations were considered?
7. Which evidence contradicts the initial hypothesis?
8. What corrective actions are appropriate?

Ground-truth files are not part of generated incident bundles, are not in the ingestion allowlist, and are not served by ordinary APIs, investigation tools, or the frontend. Do not upload truth files as knowledge sources.

## Export format

Provide a JSON object or array (or JSONL objects) to the evaluator. Each record must include a scenario ID. Use the existing investigation response/report fields where available; timeline and first-symptom fields can be added by an evaluation adapter when the system has reconstructed them:

```json
{
  "scenario_id": "INC-001",
  "first_symptom_offset_seconds": 120,
  "deployment": "release 42 worker concurrency change",
  "affected_services": ["api-gateway", "payment-service", "postgresql"],
  "timeline": [
    {"offset_seconds": 120, "event": "Payment connection acquisition timeout"}
  ],
  "report": {
    "summary": "Investigation summary",
    "findings": [
      {"statement": "Finding text", "evidence_refs": [{"evidence_id": "evidence-id"}]}
    ],
    "hypotheses": [],
    "conflicts": [],
    "evidence": [
      {
        "evidence_id": "evidence-id",
        "metadata": {"source": "Nexora/INC-001/logs/application.log"},
        "excerpt": "Retrieved source excerpt"
      }
    ],
    "recommended_actions": []
  }
}
```

The example is a schema template, not an evaluated result.

## Run the evaluator

From the repository root:

```powershell
uv run python -m evals.evaluate_incidents --results path\to\investigation-results.json
```

Optional arguments:

- `--ground-truth-dir path\to\ground_truth` to select another isolated truth directory.
- `--output path\to\scores.json` to save the computed report instead of printing it.

The evaluator rejects empty input, invalid scenario IDs, missing truth files, and truth files without a synthetic marker. It does not call an LLM or the EnterpriseIQ APIs, and it does not generate benchmark results.

## Metrics and interpretation

- **Root-cause keyword coverage:** fraction of scenario-specific root-cause keywords found in the report summary, findings, or hypotheses.
- **Evidence retrieval recall:** fraction of expected artifact-and-clue identifiers present in retrieved evidence excerpts.
- **Valid citation rate:** cited evidence IDs that resolve to an item in the export.
- **Relevant citation rate:** cited IDs whose retrieved source is one of the scenario's relevant artifacts.
- **Timeline reconstruction recall:** fraction of expected timeline events matched by token overlap with a tolerance of 60 seconds when offsets are supplied.
- **First-symptom offset error:** absolute seconds between the reconstructed offset and the expected first symptom, when supplied.
- **Deployment recognition:** token-overlap match for the expected deployment record.
- **Unsupported claim rate:** fraction of exported claims/findings without a resolvable evidence citation.
- **Recommended-action keyword coverage:** coverage of expected corrective-action vocabulary.
- **Affected-service recall:** fraction of expected affected services included in the result.
- **Acceptable-hypothesis coverage and contradictory-evidence coverage:** lexical matching against the scenario's acceptable alternative hypotheses and misleading/contradictory evidence descriptions.

Missing fields are emitted as `null`, not treated as successes. The output includes per-incident scores and averages over available values only.

## Limitations

These are deterministic lexical heuristics, not expert or semantic judgments. Citation scoring verifies identifiers and source relevance, not whether an excerpt truly entails a claim. Root-cause and action scores can be affected by paraphrasing; timeline matching can miss valid reconstructions with different language. Unsupported-claim scoring detects missing/unresolvable citations, not every unsupported semantic assertion. Review raw results and evidence manually before drawing conclusions. Dataset results must not be generalized to production incidents or advertised as model performance without a separate, documented study.
