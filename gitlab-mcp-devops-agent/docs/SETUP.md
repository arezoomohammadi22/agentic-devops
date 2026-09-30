# Environment setup

## Assumed environment

- GitLab Self-Managed 19.4.1
- GitLab MCP client access enabled
- Ubuntu 24.04 Runner host
- GitLab Runner using the shell executor
- Docker Engine
- kind 0.33.0
- kubectl 1.37.x
- Codex CLI
- HTTPS access to GitLab

## GitLab project

Create:

```text
Group: devops
Project: agent-demo
Path: devops/agent-demo
```

Create a separate GitLab user:

```text
agent-bot
```

Add it to the project as:

```text
Developer
```

After the first push to `main`, protect `main` so Developers cannot push directly and only Maintainers can merge.

## Runner

Create a project Runner with the tag:

```text
agent-lab
```

Use the Shell executor.

The `gitlab-runner` Linux user must be able to:

```text
docker build
kind load docker-image
kubectl apply
kubectl rollout status
```

Add the user to the Docker group if needed:

```bash
sudo usermod -aG docker gitlab-runner
sudo systemctl restart gitlab-runner
```

## Kind

Create the cluster as the Runner user:

```bash
sudo -u gitlab-runner \
  -H kind create cluster \
  --name agent-demo
```

Verify:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  get nodes
```

The node must be Ready.

## GitLab MCP

Enable MCP client access in the GitLab Admin settings.

The endpoint used by this lab is:

```text
https://gitlab.agent.lab/api/v4/mcp
```

Add the server to Codex:

```bash
codex mcp add GitLab \
  --url "https://gitlab.agent.lab/api/v4/mcp"
```

Authenticate:

```bash
codex mcp login GitLab
```

Complete OAuth using the `agent-bot` GitLab account.

## Expected first pipeline

The repository intentionally contains this incorrect readiness probe:

```yaml
readinessProbe:
  httpGet:
    path: /healthz
```

The application exposes only:

```text
/health
```

Therefore the initial pipeline should be:

```text
test     passed
build    passed
deploy   failed
```

The agent is expected to discover the mismatch and propose the minimal fix.
