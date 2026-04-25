# Responsible AI Statement: HomeBound

## Overview

HomeBound is an AI-powered care coordination prototype in the AI-Powered Care Coordination track. The solution supports case managers in coordinating Durable Medical Equipment (DME) workflows to reduce avoidable delays and improve post-discharge continuity of care.

HomeBound uses the Llama3-OpenBioLLM-70B model specifically for its clinical text optimization capabilities, including structured interpretation of care coordination context and workflow-relevant summarization.

## Intended Use

HomeBound is designed to support operational coordination tasks such as:

- DME request interpretation and routing support.
- Workflow status summarization.
- Escalation support for delayed or pending orders.

All AI-generated outputs are intended for case manager review only. AI suggestions are never final actions on their own and must be validated by qualified care coordination staff before use.

## Data Privacy

HomeBound is built and tested using 100% de-identified Synthea synthetic data.

- No real patient PHI is required for this prototype.
- Synthetic patient records are used to simulate realistic care transitions.
- Development workflows are designed to minimize exposure to sensitive data.

## Bias Considerations

We recognize that model behavior can reflect imbalances in training and reference data, including demographic representation gaps.

Key considerations:

- Clinical language models may perform unevenly across demographic groups if training data is not fully representative.
- Workflow recommendations can inherit bias patterns from historical care processes.
- Outputs should be reviewed for fairness, especially when language could influence prioritization or escalation.

Mitigation approach in this prototype:

- Human-in-the-loop review by case managers for every AI output.
- Explicit requirement to verify recommendations against care context and policy.
- Ongoing monitoring and adjustment of prompts/workflows to reduce biased patterns.

## Safety Disclaimers

HomeBound is a coordination tool, not a diagnostic device.

- It does not diagnose, treat, or replace clinical judgment.
- It is not a substitute for licensed medical decision-making.
- It should not be used as the sole basis for patient care decisions.

All AI outputs are advisory and must be reviewed, interpreted, and approved by case managers before any downstream action is taken.

## Human Oversight and Accountability

- Case managers remain accountable for final coordination decisions.
- AI outputs are used to accelerate administrative workflows, not to automate unsupervised clinical determinations.
- Escalation and exception handling should follow established care team governance.

## Known Limitations

- Prototype scope and limited integration depth may not represent full production conditions.
- Readmission impact is hypothesis-driven and not yet validated through live clinical deployment.
- Additional safety, security, and performance testing is required before production use.

## Commitment

HomeBound is built with a safety-first, human-supervised approach to responsible AI in healthcare operations. Our goal is to reduce coordination friction and support lower 30-day readmissions while preserving clinical oversight and patient safety.
