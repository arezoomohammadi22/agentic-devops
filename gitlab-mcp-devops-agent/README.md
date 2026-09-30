# GitLab MCP + Codex DevOps Agent Demo

This repository is a deliberately broken DevOps lab used to demonstrate an AI agent investigating and remediating a failed Kubernetes deployment through GitLab MCP.

## What happens

The application exposes:

```text
/
 /health
```

The Kubernetes Deployment intentionally configures the readiness probe as:

```text
/healthz
```

Because `/healthz` does not exist, the container runs but the Pods never become Ready.

The GitLab pipeline is designed to produce:

```text
test     passed
build    passed
deploy   failed
```

The deploy job captures Kubernetes diagnostics in its job log. Codex connects to GitLab through GitLab MCP, investigates the failed pipeline, reads the repository, identifies the mismatch, creates a minimal fix on a new branch, and opens a Merge Request.

A human reviews and merges the change.

## Repository structure

```text
.
├── app/
│   └── server.py
├── docs/
│   ├── ARCHITECTURE.md
│   └── SETUP.md
├── k8s/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── prompts/
│   ├── 01-investigate.txt
│   ├── 02-remediate.txt
│   ├── 03-verify-mr.txt
│   └── 04-verify-main.txt
├── .dockerignore
├── .gitignore
├── .gitlab-ci.yml
└── Dockerfile
```

## Prerequisites

The Runner host needs:

```text
Docker
GitLab Runner
kind
kubectl
curl
Python 3
Git
```

The GitLab Runner must use the tag:

```text
agent-lab
```

The Kind cluster name must be:

```text
agent-demo
```

The GitLab project path assumed by the provided prompts is:

```text
devops/agent-demo
```

## Local application test

Run:

```bash
PORT=18080 python3 app/server.py
```

Then test:

```bash
curl -i http://127.0.0.1:18080/
curl -i http://127.0.0.1:18080/health
curl -i http://127.0.0.1:18080/healthz
```

Expected behavior:

```text
/         -> 200
/health   -> 200
/healthz  -> 404
```

## Baseline failure

Do not fix `k8s/deployment.yaml` before the first pipeline.

The repository intentionally begins with:

```yaml
readinessProbe:
  httpGet:
    path: /healthz
```

That broken configuration is the starting point for the agent investigation.

## Agent flow

1. Push the repository to `main`.
2. Confirm that only the `deploy` stage fails.
3. Protect `main`.
4. Connect Codex to GitLab MCP as `agent-bot`.
5. Use `prompts/01-investigate.txt`.
6. Review the root-cause explanation.
7. Use `prompts/02-remediate.txt`.
8. Let the agent create a branch, commit, and Merge Request.
9. Wait for the Merge Request pipeline.
10. Use `prompts/03-verify-mr.txt`.
11. Review and merge the Merge Request as a human Maintainer.
12. Use `prompts/04-verify-main.txt`.

## Expected remediation

The agent should change only:

```diff
- path: /healthz
+ path: /health
```

After that change, the pipeline should be:

```text
test     passed
build    passed
deploy   passed
```

## Important security properties

- The agent should authenticate as a dedicated GitLab user.
- The agent should not be a GitLab administrator.
- `main` should be protected.
- The agent should not merge its own Merge Request.
- The agent does not need direct Kubernetes credentials in this version of the lab.
