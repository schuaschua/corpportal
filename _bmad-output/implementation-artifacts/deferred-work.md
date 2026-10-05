- source_plan: none
  summary: Portal UI — React + Fluent UI v9 matching approved mockup, wired to accounts/payments APIs (piece 2 of 5).
  evidence: Split from corportal code build 2026-09-30; depends on piece 1 APIs.
- source_plan: none
  summary: Event flow — outbox relay to Event Hubs and Databricks bronze/silver/gold pipelines runnable locally (piece 3 of 5).
  evidence: Split from corportal code build 2026-09-30; depends on piece 1 outbox.
- source_plan: none
  summary: ML — cash forecast + Isolation Forest anomaly models and insights API (piece 4 of 5).
  evidence: Split from corportal code build 2026-09-30; depends on piece 3 gold tables.
- source_plan: none
  summary: CI — Dockerfiles for every service and a Jenkinsfile building them in parallel with Kaniko on k8s agents (piece 5 of 5).
  evidence: Split from corportal code build 2026-09-30; depends on pieces 1-4 code.
