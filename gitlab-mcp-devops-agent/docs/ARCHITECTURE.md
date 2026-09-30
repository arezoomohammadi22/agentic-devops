# Architecture

This project demonstrates a controlled DevOps agent workflow.

```text
Developer
   |
   v
GitLab Repository
   |
   v
GitLab CI/CD
   |
   v
GitLab Runner (shell executor)
   |
   v
Kind Kubernetes

Codex
   |
   | MCP over HTTPS
   v
GitLab MCP
   |
   +-- Repository
   +-- Pipelines
   +-- Jobs / Job logs
   +-- Commits
   +-- Merge Requests
```

## Security boundary

The intended model is:

- Codex authenticates to GitLab as `agent-bot`.
- `agent-bot` is a project Developer, not an administrator.
- `main` is protected.
- The agent may create a branch, commit a minimal fix, and open a Merge Request.
- The agent must not merge or approve the Merge Request.
- A human Maintainer reviews and merges.

## Why Kubernetes is not exposed directly to the agent

This first version intentionally gives Codex only GitLab MCP access.

The deploy job writes Kubernetes runtime evidence into the GitLab job log through `after_script`. The agent can therefore correlate CI evidence, Kubernetes diagnostics, repository configuration, and application behavior without receiving a kubeconfig or unrestricted shell access.

A later version can add a Kubernetes MCP server and turn the workflow into a multi-tool incident-response agent.
