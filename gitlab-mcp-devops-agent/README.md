# Building a GitLab MCP DevOps Agent with Codex

## A complete end-to-end lab for investigating and remediating a failed Kubernetes deployment through GitLab MCP

---

## 1. Lab overview

This lab demonstrates how an AI agent can participate in a real DevOps workflow without receiving unrestricted access to the infrastructure.

The environment contains a GitLab repository, a GitLab CI/CD pipeline, a GitLab Runner, a local Kubernetes cluster created with Kind, and Codex acting as the AI agent. GitLab exposes an MCP endpoint, and Codex connects to GitLab through that endpoint.

The application used in this lab contains an intentional Kubernetes configuration error. The application itself is healthy, but the Kubernetes `readinessProbe` points to the wrong HTTP path. As a result, the container starts successfully, but Kubernetes never marks the Pod as Ready. The deployment stage of the GitLab pipeline therefore fails.

The agent is not told exactly where the bug is. Instead, it receives a goal: investigate the latest failed pipeline, identify the root cause, propose the smallest safe change, create that change on a separate branch, and open a Merge Request. The agent is not allowed to merge the change into `main`. A human performs the final review and merge.

This distinction is important. The goal of the lab is not to automate a fixed sequence of commands. The goal is to show an agent that receives a task, chooses the appropriate GitLab tools, gathers evidence, reasons across several sources, and proposes a controlled change.

At the end of the lab, the workflow looks like this:

```text
Developer pushes code
        ↓
GitLab pipeline starts
        ↓
Application test passes
        ↓
Container image is built
        ↓
Application is deployed to Kind
        ↓
Kubernetes readiness check fails
        ↓
Deployment job fails
        ↓
Diagnostic data is captured in the GitLab job log
        ↓
Codex connects to GitLab through MCP
        ↓
Agent investigates pipeline, job log, and repository
        ↓
Agent identifies the readiness probe mismatch
        ↓
Agent creates a fix branch and Merge Request
        ↓
Merge Request pipeline passes
        ↓
Human reviews and merges
        ↓
Main pipeline passes
        ↓
Agent verifies the final result
```

---

## 2. What this lab teaches

This lab combines several topics that are often taught separately:

- GitLab CI/CD
- GitLab Runner
- Docker image build workflows
- Kubernetes deployments
- Kind
- Kubernetes health probes
- GitLab MCP
- Codex as an MCP client
- Agent tool use
- Root-cause analysis
- Least privilege
- Protected branches
- Human approval
- Post-change verification

The important architectural idea is that the agent does not receive cluster-admin access.

In the first version of the lab, Codex only receives GitLab tools through GitLab MCP. Kubernetes runtime information is captured by the CI job and written into the GitLab job log. The agent therefore investigates the runtime failure indirectly through GitLab.

A later version of the lab can add a second MCP server for Kubernetes and allow the same agent to use both GitLab and Kubernetes tools.

---

## 3. Lab architecture

The environment has three logical areas.

### GitLab server

GitLab is responsible for:

- storing the source code;
- running the CI/CD workflow;
- storing pipeline and job information;
- storing Kubernetes diagnostics generated during deployment;
- exposing GitLab functionality through MCP;
- hosting branches and Merge Requests;
- enforcing the human review boundary.

### Runner and Kubernetes host

The GitLab Runner runs on an Ubuntu machine.

The same machine also hosts:

- Docker Engine;
- Kind;
- `kubectl`;
- the Kubernetes cluster used by the lab.

Using one machine for both the Runner and Kind keeps the training environment simple. The GitLab Runner uses the Shell executor so that CI jobs can access the local Docker daemon and the local Kind cluster.

This is appropriate for a controlled lab, but it should not be treated as the default production security model.

### Agent workstation

Codex runs on a separate workstation or on the instructor's machine.

Codex connects to GitLab through the GitLab MCP endpoint.

The agent does not need direct SSH access to the Runner host and does not need a Kubernetes kubeconfig in this version of the lab.

The relationship between the components is:

```text
                        ┌──────────────────────┐
                        │   Codex / AI Agent   │
                        └──────────┬───────────┘
                                   │
                                   │ MCP over HTTPS
                                   ▼
                        ┌──────────────────────┐
                        │       GitLab         │
                        │ Repository           │
                        │ Pipelines            │
                        │ Job logs             │
                        │ Merge Requests       │
                        └──────────┬───────────┘
                                   │
                                   │ GitLab CI jobs
                                   ▼
                        ┌──────────────────────┐
                        │   GitLab Runner      │
                        │   Docker             │
                        │   kind               │
                        │   kubectl            │
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │  Kubernetes cluster  │
                        │  namespace: agent-demo
                        │  deployment: web     │
                        │  service: web        │
                        └──────────────────────┘
```

---

## 4. Version assumptions

This lab assumes the following environment:

| Component | Lab assumption |
|---|---|
| GitLab Self-Managed | 19.4.1 |
| GitLab package | `gitlab-ee` |
| GitLab MCP | enabled on the GitLab instance |
| Ubuntu | 24.04 LTS |
| GitLab Runner | current compatible version |
| Docker Engine | current stable version |
| Kind | 0.33.0 |
| kubectl | 1.37.x |
| Codex CLI | current stable version |

The important requirement is not the exact patch level of every local tool. The important compatibility point is that GitLab must expose the MCP functionality and GitLab tools required by this workflow.

For this lab, GitLab 19.4.1 is the assumed server version.

---

# Part I — Preparing GitLab

## 5. GitLab hostname and network access

Use a stable hostname for the GitLab server.

This guide uses:

```text
gitlab.agent.lab
```

The Runner host and the machine running Codex must both be able to resolve this hostname.

If the lab does not use internal DNS, add a hosts-file entry on the relevant machines.

Example:

```text
192.168.50.10 gitlab.agent.lab
```

The actual IP address will depend on the training environment.

Before continuing, verify that the hostname resolves from:

1. the GitLab Runner host;
2. the Codex workstation.

For example:

```bash
ping gitlab.agent.lab
```

The important result is successful name resolution. ICMP itself is not required for GitLab to work.

---

## 6. Why HTTPS matters

The GitLab MCP endpoint is accessed remotely by Codex. For that reason, the lab should use HTTPS rather than plain HTTP.

If the environment already has a valid certificate from an internal or public CA, use it.

For an isolated training environment, an internal CA is sufficient.

The purpose of the certificate in this lab is not to teach PKI in depth. The important requirement is that:

- GitLab serves HTTPS;
- the certificate contains `gitlab.agent.lab` in the SAN field;
- the Runner host trusts the CA;
- the Codex workstation trusts the CA.

A private CA may be created with OpenSSL if required.

A minimal CA creation example is:

```bash
openssl genrsa -out agent-lab-ca.key 4096

openssl req \
  -x509 \
  -new \
  -nodes \
  -key agent-lab-ca.key \
  -sha256 \
  -days 3650 \
  -out agent-lab-ca.crt \
  -subj "/CN=Agent Lab Root CA"
```

A server certificate for `gitlab.agent.lab` should then be signed by this CA.

After the certificate has been installed, test GitLab from both the Runner host and the Codex workstation with:

```bash
curl -I https://gitlab.agent.lab
```

A certificate validation error must be resolved before continuing.

---

## 7. Installing GitLab

Install GitLab Self-Managed on the GitLab VM.

The server should have enough resources for a training environment. A reasonable minimum for this lab is:

```text
4 vCPU
8 GB RAM
40 GB disk
```

The GitLab package repository can be added with:

```bash
curl --silent \
  "https://packages.gitlab.com/install/repositories/gitlab/gitlab-ee/script.deb.sh" \
  | sudo bash
```

Because this lab assumes GitLab 19.4.1, confirm that the package is available:

```bash
apt-cache madison gitlab-ee | grep 19.4.1
```

Install the desired package version with the GitLab external URL set to:

```text
https://gitlab.agent.lab
```

Example:

```bash
sudo EXTERNAL_URL="https://gitlab.agent.lab" \
  apt-get install -y \
  gitlab-ee=<19.4.1-package-version>
```

The exact Debian package string can be obtained from:

```bash
apt-cache madison gitlab-ee
```

If a private TLS certificate is used, configure the certificate paths in:

```text
/etc/gitlab/gitlab.rb
```

A typical configuration contains:

```ruby
external_url "https://gitlab.agent.lab"

letsencrypt['enable'] = false

nginx['ssl_certificate'] = "/etc/gitlab/ssl/gitlab.agent.lab.crt"
nginx['ssl_certificate_key'] = "/etc/gitlab/ssl/gitlab.agent.lab.key"
```

After changing the GitLab configuration, apply it with:

```bash
sudo gitlab-ctl reconfigure
```

Verify that GitLab services are running:

```bash
sudo gitlab-ctl status
```

Verify the installed GitLab version:

```bash
sudo gitlab-rake gitlab:env:info
```

The expected GitLab version for this lab is:

```text
19.4.1
```

---

## 8. Creating the human and agent identities

Do not use the GitLab root account for the application workflow.

Create two users.

### Human account

Create:

```text
lab-owner
```

This account represents the developer or platform engineer.

It will own or maintain the project and will be responsible for the final Merge Request review.

### Agent account

Create:

```text
agent-bot
```

This account is used by Codex when authenticating through GitLab MCP.

The agent account should not be an administrator.

This separation allows the lab to demonstrate a basic least-privilege model:

```text
Human identity:
  reviews and merges

Agent identity:
  investigates
  creates branches
  commits changes
  opens Merge Requests
```

---

## 9. Creating the GitLab group and project

Sign in as `lab-owner`.

Create a group:

```text
Name: devops
Path: devops
Visibility: Private
```

Inside the group, create the project:

```text
Name: agent-demo
Path: agent-demo
Visibility: Private
```

The resulting project path is:

```text
devops/agent-demo
```

Add `agent-bot` as a project member with the `Developer` role.

The reason for using `Developer` instead of a higher role is deliberate. The agent needs enough permission to work on a branch and create a Merge Request, but it should not automatically receive the same authority as a maintainer.

---

# Part II — Preparing the Runner and Kind cluster

## 10. Runner host responsibilities

The Runner host performs two jobs in this lab:

1. it executes GitLab CI jobs;
2. it hosts the Kind Kubernetes cluster.

Install these tools on the Runner host:

```text
Docker
GitLab Runner
kind
kubectl
Git
curl
Python 3
```

The Runner host should also trust the GitLab CA if a private CA is used.

Verify GitLab access from the Runner host:

```bash
curl -I https://gitlab.agent.lab
```

---

## 11. Installing Docker

Install Docker Engine using the Docker package repository.

After installation, verify:

```bash
sudo docker version
```

The GitLab Runner service will run as the user:

```text
gitlab-runner
```

Because the Shell executor is used, this user must be able to talk to the Docker daemon.

Add it to the Docker group:

```bash
sudo usermod -aG docker gitlab-runner
```

Restart the Runner service after the Runner is installed, or log the service user into a new session.

A useful verification command later will be:

```bash
sudo -u gitlab-runner -H docker version
```

The command must succeed without `sudo docker`.

---

## 12. Installing kubectl

Install a compatible `kubectl` binary.

For the version used by this guide:

```bash
KUBECTL_VERSION="v1.37.0"
```

Download the binary that matches the machine architecture and install it into:

```text
/usr/local/bin/kubectl
```

Verify:

```bash
kubectl version --client
```

---

## 13. Installing Kind

Install Kind version:

```text
v0.33.0
```

After installation:

```bash
kind version
```

should return the installed version.

---

## 14. Installing GitLab Runner

Install GitLab Runner from the official GitLab Runner repository.

After installation, confirm the service is running:

```bash
sudo systemctl status gitlab-runner
```

The lab uses the Shell executor.

The reason is practical: the CI job must use the local Docker daemon and the local Kind cluster. A containerized executor would require additional Docker socket, kubeconfig, and networking configuration that is unnecessary for the learning objective of this lab.

---

## 15. Creating the Kind cluster as the Runner user

This detail is important.

Do not create the Kind cluster as `root`.

The pipeline runs as the `gitlab-runner` user. That user must own the kubeconfig and be able to access the Kind cluster.

Create the cluster as the Runner user:

```bash
sudo -u gitlab-runner \
  -H kind create cluster \
  --name agent-demo
```

Verify that the cluster exists:

```bash
sudo -u gitlab-runner \
  -H kind get clusters
```

Expected output includes:

```text
agent-demo
```

Verify Kubernetes access:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  get nodes
```

The Kind node must be:

```text
Ready
```

If this check fails, do not continue to the pipeline. The CI job must be able to access the cluster before the GitLab workflow is introduced.

---

## 16. Registering the GitLab Runner

Inside the GitLab project, open:

```text
Settings
→ CI/CD
→ Runners
```

Create a project Runner.

Use the tag:

```text
agent-lab
```

Disable untagged jobs if you want this Runner to execute only jobs that explicitly request this tag.

GitLab provides a Runner authentication token.

On the Runner host, register the Runner:

```bash
sudo gitlab-runner register
```

Provide:

```text
GitLab URL:
https://gitlab.agent.lab

Executor:
shell

Description:
agent-lab-runner

Tag:
agent-lab
```

Use the authentication token generated by GitLab.

After registration:

```bash
sudo systemctl restart gitlab-runner
```

Verify:

```bash
sudo gitlab-runner verify
```

The Runner should also appear online in the GitLab UI.

---

# Part III — Building the application repository

## 17. Repository structure

Create the following project structure:

```text
agent-demo/
├── app/
│   └── server.py
├── k8s/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── .dockerignore
├── .gitignore
├── Dockerfile
└── .gitlab-ci.yml
```

The repository is intentionally small because the focus is not application development. The application only needs to provide enough behavior to create a realistic Kubernetes readiness failure.

---

## 18. Application behavior

Create:

```text
app/server.py
```

with the following code:

```python
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = b"agent-demo\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/health":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = b"not found\n"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(
            "%s - - [%s] %s"
            % (
                self.client_address[0],
                self.log_date_time_string(),
                format % args,
            ),
            flush=True,
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"server listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()
```

The application exposes:

```text
GET /
GET /health
```

It does not expose:

```text
GET /healthz
```

This difference is the root cause that the agent must eventually discover.

---

## 19. Testing the application before containerization

Run the application locally:

```bash
PORT=18080 python3 app/server.py
```

From another terminal:

```bash
curl -i http://127.0.0.1:18080/
```

The response should be successful.

Test the health endpoint:

```bash
curl -i http://127.0.0.1:18080/health
```

Expected:

```text
HTTP 200
```

Now test the path that will later be configured incorrectly in Kubernetes:

```bash
curl -i http://127.0.0.1:18080/healthz
```

Expected:

```text
HTTP 404
```

This verification matters because it proves that the later Kubernetes failure is not random. The application behavior is known before the deployment is created.

---

## 20. Container image

Create:

```text
Dockerfile
```

with:

```dockerfile
FROM python:3.13-alpine

WORKDIR /app

COPY app/server.py /app/server.py

USER 65532:65532

EXPOSE 8080

CMD ["python", "/app/server.py"]
```

This container runs as a non-root numeric user.

The image does not require additional packages or Python dependencies.

Create `.dockerignore`:

```text
.git
.gitlab-ci.yml
k8s
README.md
__pycache__
*.pyc
```

Create `.gitignore`:

```text
__pycache__/
*.pyc
.DS_Store
```

---

# Part IV — Creating the intentional Kubernetes failure

## 21. Namespace

Create:

```text
k8s/namespace.yaml
```

with:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: agent-demo
```

All application resources will be placed in this namespace.

---

## 22. Deployment

Create:

```text
k8s/deployment.yaml
```

with:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: agent-demo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: IMAGE_PLACEHOLDER
          imagePullPolicy: IfNotPresent

          ports:
            - name: http
              containerPort: 8080

          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 2
            periodSeconds: 3
            timeoutSeconds: 2
            failureThreshold: 3

          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3

          resources:
            requests:
              cpu: 20m
              memory: 32Mi
            limits:
              cpu: 200m
              memory: 128Mi
```

The configuration contains one intentional error:

```yaml
readinessProbe:
  httpGet:
    path: /healthz
```

The real application endpoint is:

```text
/health
```

The liveness probe is intentionally correct.

This produces an important runtime state:

```text
Container process:
Running

Liveness:
Passing

Readiness:
Failing

Pod phase:
Running

Pod Ready:
False
```

This is more realistic than simply crashing the application because the container appears healthy at first glance.

---

## 23. Service

Create:

```text
k8s/service.yaml
```

with:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
  namespace: agent-demo
spec:
  type: ClusterIP
  selector:
    app: web
  ports:
    - name: http
      port: 80
      targetPort: http
```

The Service selector is correct.

The purpose of the lab is specifically to diagnose a readiness mismatch, so avoid adding unrelated Kubernetes errors.

---

# Part V — Building the GitLab pipeline

## 24. Pipeline design

The pipeline contains three stages:

```text
test
build
deploy
```

The test stage proves that the application works.

The build stage creates the container image.

The deploy stage loads that image into Kind and applies the Kubernetes manifests.

The deployment stage then waits for the Deployment rollout to complete.

Because the readiness probe is wrong, Kubernetes never considers the Pods Ready and the rollout command times out.

The deploy job includes an `after_script` section that captures runtime diagnostics. This design is central to the first version of the lab.

Codex does not have a Kubernetes MCP server yet, so Kubernetes evidence must be brought back into GitLab.

---

## 25. GitLab CI configuration

Create:

```text
.gitlab-ci.yml
```

with:

```yaml
stages:
  - test
  - build
  - deploy

workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - when: never

default:
  tags:
    - agent-lab

variables:
  IMAGE_REPOSITORY: "agent-demo"

test:
  stage: test

  script:
    - |
      set -euo pipefail

      TEST_PORT="$((18000 + CI_JOB_ID % 1000))"

      PORT="$TEST_PORT" \
      python3 app/server.py \
        > "/tmp/agent-demo-${CI_JOB_ID}.log" \
        2>&1 &

      APP_PID="$!"

      cleanup() {
        kill "$APP_PID" 2>/dev/null || true
      }

      trap cleanup EXIT

      for attempt in $(seq 1 20); do
        if curl -fsS \
          "http://127.0.0.1:${TEST_PORT}/health" \
          >/dev/null; then
          break
        fi

        sleep 1
      done

      curl -fsS \
        "http://127.0.0.1:${TEST_PORT}/" \
        | grep -qx "agent-demo"

      curl -fsS \
        "http://127.0.0.1:${TEST_PORT}/health" \
        | grep -qx "ok"

      if curl -fsS \
        "http://127.0.0.1:${TEST_PORT}/healthz"; then
        echo "Unexpected: /healthz returned success"
        exit 1
      fi

build:
  stage: build

  script:
    - |
      set -euo pipefail

      IMAGE="${IMAGE_REPOSITORY}:${CI_COMMIT_SHORT_SHA}"

      docker build \
        -t "$IMAGE" \
        .

      docker image inspect \
        "$IMAGE" \
        >/dev/null

deploy:
  stage: deploy

  script:
    - |
      set -euo pipefail

      IMAGE="${IMAGE_REPOSITORY}:${CI_COMMIT_SHORT_SHA}"

      kubectl config use-context \
        kind-agent-demo

      kind get clusters \
        | grep -qx "agent-demo"

      kind load docker-image \
        "$IMAGE" \
        --name agent-demo

      kubectl apply \
        -f k8s/namespace.yaml

      sed \
        "s|IMAGE_PLACEHOLDER|${IMAGE}|g" \
        k8s/deployment.yaml \
        | kubectl apply -f -

      kubectl apply \
        -f k8s/service.yaml

      kubectl rollout status \
        deployment/web \
        -n agent-demo \
        --timeout=60s

      kubectl get pods \
        -n agent-demo \
        -o wide

      PORT_FORWARD_PORT="$((20000 + CI_JOB_ID % 1000))"

      kubectl port-forward \
        -n agent-demo \
        service/web \
        "${PORT_FORWARD_PORT}:80" \
        > "/tmp/agent-demo-port-forward-${CI_JOB_ID}.log" \
        2>&1 &

      PF_PID="$!"

      cleanup_port_forward() {
        kill "$PF_PID" 2>/dev/null || true
      }

      trap cleanup_port_forward EXIT

      for attempt in $(seq 1 20); do
        if curl -fsS \
          "http://127.0.0.1:${PORT_FORWARD_PORT}/health" \
          >/dev/null; then
          break
        fi

        sleep 1
      done

      curl -fsS \
        "http://127.0.0.1:${PORT_FORWARD_PORT}/health" \
        | grep -qx "ok"

  after_script:
    - |
      echo "===== Kubernetes diagnostics ====="

      kubectl config use-context \
        kind-agent-demo \
        || true

      echo
      echo "===== Deployment ====="

      kubectl get deployment web \
        -n agent-demo \
        -o wide \
        || true

      echo
      echo "===== Pods ====="

      kubectl get pods \
        -n agent-demo \
        -l app=web \
        -o wide \
        || true

      echo
      echo "===== Pod describe ====="

      kubectl describe pods \
        -n agent-demo \
        -l app=web \
        || true

      echo
      echo "===== Application logs ====="

      kubectl logs \
        -n agent-demo \
        -l app=web \
        --tail=100 \
        --prefix=true \
        || true

      echo
      echo "===== Service ====="

      kubectl get service web \
        -n agent-demo \
        -o wide \
        || true

      echo
      echo "===== Endpoints ====="

      kubectl get endpoints web \
        -n agent-demo \
        -o wide \
        || true

      echo
      echo "===== Events ====="

      kubectl get events \
        -n agent-demo \
        --sort-by=.lastTimestamp \
        || true
```

---

## 26. Why the pipeline is written this way

The test stage verifies the application contract before Kubernetes is involved.

It proves that:

```text
/          works
/health    works
/healthz   does not exist
```

The build stage uses a local image name:

```text
agent-demo:<commit-sha>
```

No external registry is required.

The deploy stage loads the image directly into Kind:

```bash
kind load docker-image
```

This makes the lab usable in isolated environments.

The deployment YAML contains:

```text
IMAGE_PLACEHOLDER
```

The CI job replaces that placeholder with the commit-specific image name before applying the manifest.

The most important line is:

```bash
kubectl rollout status deployment/web -n agent-demo --timeout=60s
```

This command causes the deployment job to fail when the Pods never become Ready.

The `after_script` then gathers evidence even though the main deploy script failed.

That evidence includes:

- Deployment state;
- Pod state;
- Pod events;
- container logs;
- Service state;
- Endpoints;
- namespace events.

The agent will later use this evidence through GitLab MCP.

---

# Part VI — Creating the first failed pipeline

## 27. Initial Git commit

Initialize the repository:

```bash
git init
git branch -M main
```

Configure Git identity:

```bash
git config user.name "Lab Owner"
git config user.email "lab-owner@example.local"
```

Commit the project:

```bash
git add .
git commit -m "Initial application with intentionally broken readiness probe"
```

Add the GitLab remote:

```bash
git remote add origin \
  https://gitlab.agent.lab/devops/agent-demo.git
```

Push:

```bash
git push -u origin main
```

Use a suitable GitLab authentication method such as a short-lived Personal Access Token if HTTPS password authentication is not available.

---

## 28. Expected result of the first pipeline

Open:

```text
Build
→ Pipelines
```

The expected state is:

```text
test     passed
build    passed
deploy   failed
```

The deploy job should fail because the Deployment does not become Ready before the timeout expires.

Open the failed deploy job and inspect the log.

The diagnostics should contain evidence similar to:

```text
Readiness probe failed
```

and:

```text
HTTP probe failed with statuscode: 404
```

The Pods should appear as:

```text
0/1 Running
```

This is exactly the evidence the agent will later use.

---

# Part VII — Protecting the main branch

## 29. Creating the approval boundary

Before allowing the agent to make changes, protect the `main` branch.

Open:

```text
Settings
→ Repository
→ Branch rules
```

Create or edit the rule for:

```text
main
```

Configure the branch so that developers cannot push directly to it.

A suitable lab policy is:

```text
Allowed to push and merge:
No one

Allowed to merge:
Maintainers
```

The exact labels may vary slightly depending on the GitLab UI version.

The important behavior is:

```text
agent-bot can:
  create another branch
  commit to that branch
  create a Merge Request

agent-bot cannot:
  push directly to main
  merge into main
```

This creates the human approval boundary for the lab.

---

# Part VIII — Enabling GitLab MCP

## 30. Enabling MCP client access

Sign in as a GitLab administrator.

Open:

```text
Admin
→ Settings
→ General
→ Visibility and access controls
```

Find the MCP client access setting and enable connection to GitLab.

The MCP endpoint used by this lab is:

```text
https://gitlab.agent.lab/api/v4/mcp
```

Do not treat this endpoint like a normal REST endpoint that should be manually queried with arbitrary `curl` requests.

The MCP client handles the protocol and authentication flow.

---

# Part IX — Connecting Codex to GitLab MCP

## 31. Installing Codex

Install or update Codex CLI on the agent workstation.

For example:

```bash
npm install -g @openai/codex@latest
```

Verify:

```bash
codex --version
```

Sign in to Codex using the normal supported Codex authentication flow.

---

## 32. Adding GitLab as an MCP server

Add the GitLab MCP endpoint:

```bash
codex mcp add GitLab \
  --url "https://gitlab.agent.lab/api/v4/mcp"
```

Verify that the MCP server appears:

```bash
codex mcp list
```

Codex configuration is stored in:

```text
~/.codex/config.toml
```

The configuration should contain the GitLab MCP server entry.

If remote MCP support is represented by a feature flag in the Codex version being used, enable that feature in the same configuration file.

A typical configuration may look similar to:

```toml
[features]
rmcp_client = true

[mcp_servers.GitLab]
url = "https://gitlab.agent.lab/api/v4/mcp"
```

If Codex writes a slightly different configuration automatically, keep the generated structure rather than manually forcing this exact file layout.

---

## 33. Authenticating as the agent identity

Authenticate the MCP connection:

```bash
codex mcp login GitLab
```

The browser-based authorization should be completed using:

```text
agent-bot
```

Do not authorize with:

```text
root
```

or:

```text
lab-owner
```

The purpose is to make the agent's effective GitLab permissions match the `agent-bot` project membership.

After authorization:

```bash
codex mcp list
```

should show the GitLab connection as available.

---

## 34. Verifying GitLab MCP before investigation

Use a clean local directory so Codex does not accidentally inspect a local clone of the project.

Example:

```bash
mkdir -p ~/gitlab-agent-session
cd ~/gitlab-agent-session
codex
```

Ask Codex:

```text
Use the GitLab MCP server.

Get the GitLab project devops/agent-demo and report:
- project path
- default branch

Do not use local files or shell commands.
```

A successful response proves:

- the MCP connection works;
- authentication works;
- the agent account can access the project.

---

# Part X — Agent investigation

## 35. Investigation goal

The first real agent task should be read-only.

Give Codex the following goal:

```text
Use only the GitLab MCP tools.

Investigate the latest failed pipeline on the main branch of
devops/agent-demo.

Determine the root cause by inspecting the pipeline, failed job log,
and relevant repository files.

Do not create, update, retry, cancel, commit, or modify anything.

Report:
- failed stage and job
- runtime symptom
- repository file responsible
- exact configuration mismatch
- smallest recommended fix
```

Do not tell the agent which file contains the error.

Do not tell it to inspect the readiness probe.

Do not tell it which MCP tool to call first.

The purpose is to observe whether the agent can decide what evidence it needs.

---

## 36. Expected reasoning path

The exact sequence can vary, but a sensible investigation may look like:

```text
Find latest failed pipeline
        ↓
Inspect pipeline jobs
        ↓
Open failed deploy job
        ↓
Read job log
        ↓
Observe readiness probe 404
        ↓
Inspect repository tree
        ↓
Read k8s/deployment.yaml
        ↓
Read application source
        ↓
Compare configured path with real endpoint
        ↓
Identify mismatch
```

The important result is not the specific tool sequence.

The important result is that the agent combines:

```text
CI evidence
+
Kubernetes diagnostic evidence
+
repository configuration
+
application behavior
```

to reach the root cause.

---

## 37. Expected root cause

The agent should conclude that the application exposes:

```text
/health
```

while Kubernetes is checking:

```text
/healthz
```

The responsible file is:

```text
k8s/deployment.yaml
```

The minimal fix is:

```text
change readinessProbe path from /healthz to /health
```

Nothing else needs to be modified.

---

# Part XI — Agent remediation

## 38. Allowing the agent to prepare a change

After the investigation result has been reviewed, give the agent a second task:

```text
Using GitLab MCP only, implement the minimal fix you identified.

Requirements:
- do not modify main directly
- create a new branch from main
- change only what is necessary
- commit the fix
- create a Merge Request targeting main
- explain what changed
- do not merge the Merge Request
- do not approve the Merge Request
```

A suitable branch name is:

```text
fix/readiness-probe
```

The agent should update:

```text
k8s/deployment.yaml
```

from:

```yaml
path: /healthz
```

to:

```yaml
path: /health
```

The agent should not modify the application code.

The application is already correct.

---

## 39. Why the agent creates a Merge Request instead of deploying directly

This is one of the central lessons of the lab.

The agent has enough access to propose and prepare a change, but the workflow does not grant it the final authority to merge into `main`.

This allows the organization to keep:

```text
AI reasoning
```

separate from:

```text
human approval
```

The agent can perform useful work without becoming an unrestricted production operator.

---

# Part XII — Merge Request validation

## 40. Merge Request pipeline behavior

The pipeline uses:

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - when: never
```

This means the pipeline runs for:

```text
Merge Requests
main
```

A normal branch push does not create an additional branch pipeline.

When the agent creates the Merge Request, GitLab starts the Merge Request pipeline.

The expected result is:

```text
test     passed
build    passed
deploy   passed
```

The corrected readiness probe allows Kubernetes to mark the Pods Ready, so:

```bash
kubectl rollout status
```

succeeds.

---

## 41. Asking the agent to verify its change

After the Merge Request pipeline finishes, ask:

```text
Use GitLab MCP only.

Inspect the Merge Request you created.

Report:
- Merge Request IID
- current pipeline status
- status of test, build, and deploy
- whether the original readiness issue is still present

Do not merge or approve anything.
```

The agent should report that the pipeline is passing.

---

# Part XIII — Human review

## 42. Reviewing the Merge Request

Sign in with the human maintainer account.

Review the Merge Request diff.

The expected change should be only:

```text
k8s/deployment.yaml
```

and the effective diff should be:

```diff
- path: /healthz
+ path: /health
```

Verify that the Merge Request pipeline passed.

Only then merge the change.

The merge action is intentionally human-controlled.

---

# Part XIV — Final verification

## 43. Main pipeline

After the Merge Request is merged, GitLab starts a new pipeline on `main`.

The expected result is:

```text
test     passed
build    passed
deploy   passed
```

The production-like workflow is now complete.

---

## 44. Asking the agent for final verification

Ask Codex:

```text
Use GitLab MCP only.

Inspect the latest pipeline on main for devops/agent-demo.

Verify that the remediation has reached main and report the final
pipeline status.

Do not modify anything.
```

The agent should report a successful pipeline.

---

## 45. Direct Kubernetes verification

The human operator can also verify the cluster directly from the Runner host.

Check Pods:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  get pods \
  -n agent-demo \
  -l app=web
```

Expected:

```text
1/1 Running
```

for each Pod.

Check the Deployment:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  get deployment \
  -n agent-demo
```

Check the Service:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  get service web \
  -n agent-demo
```

Check Endpoints:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  get endpoints web \
  -n agent-demo
```

After the fix, the Service should have endpoints because the Pods are Ready.

---

# Part XV — Why this is an agent workflow and not only automation

Traditional automation defines the sequence in advance.

A traditional diagnostic script might be written to always do this:

```text
Open pipeline
Open deploy job
Read deployment.yaml
Replace /healthz with /health
Create Merge Request
```

That is not what this lab does.

The agent receives a goal:

```text
Investigate the latest failed pipeline and determine the root cause.
```

The system provides:

```text
Tools
Permissions
Context
Guardrails
Approval boundary
```

The agent chooses which GitLab information it needs.

It may inspect:

```text
pipeline
job
job log
repository tree
deployment manifest
application source
```

The sequence is selected at runtime based on the evidence.

That decision loop is the agentic part of the workflow.

---

# Part XVI — Security model

## 46. Separate agent identity

Codex authenticates to GitLab as:

```text
agent-bot
```

This makes its actions attributable to a dedicated identity.

Do not use:

```text
root
```

for the agent.

---

## 47. Least privilege

The agent account is assigned:

```text
Developer
```

instead of administrator-level access.

The branch rule prevents direct modification of `main`.

This is a simple but important control.

---

## 48. Human-in-the-loop boundary

The agent is allowed to:

```text
investigate
create a branch
commit a fix
create a Merge Request
verify the MR pipeline
```

The agent is not allowed to:

```text
merge into main
```

The final production-affecting decision belongs to the human maintainer.

---

## 49. Tool scope

In this version of the lab, the agent uses GitLab MCP.

It does not receive:

```text
unrestricted shell
SSH access
cluster-admin kubeconfig
direct kubectl access
```

This reduces the blast radius of an incorrect agent decision.

---

## 50. Repository content should be treated as untrusted input

An AI agent may encounter instructions inside:

```text
source files
issues
comments
job logs
documentation
Merge Requests
```

Those contents can influence model behavior if they are treated as instructions rather than data.

For this training lab, use a repository that you control.

The operational principle is:

```text
Repository content is evidence, not authority.
```

The task definition and the allowed tools should remain the primary control boundary.

---

# Part XVII — Troubleshooting

## 51. The Runner remains pending

Confirm that the Runner is online in GitLab.

Confirm the job tag:

```text
agent-lab
```

matches the Runner tag.

Verify:

```bash
sudo gitlab-runner verify
```

---

## 52. Docker access fails inside the CI job

Test Docker access as the Runner user:

```bash
sudo -u gitlab-runner -H docker ps
```

If this returns a permission error, verify that `gitlab-runner` belongs to the Docker group.

Check:

```bash
id gitlab-runner
```

Restart the Runner service after changing group membership.

---

## 53. The Runner cannot access Kubernetes

Verify the kubeconfig as the Runner user:

```bash
sudo -u gitlab-runner \
  -H kubectl config get-contexts
```

The context should include:

```text
kind-agent-demo
```

Verify:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  get nodes
```

If the cluster was created as `root`, recreate it as `gitlab-runner`.

---

## 54. The first pipeline unexpectedly passes

Check:

```text
k8s/deployment.yaml
```

The initial version must contain:

```yaml
path: /healthz
```

The application must only expose:

```text
/health
```

If `/healthz` has been added to the application, the intentional failure no longer exists.

---

## 55. Kubernetes diagnostics do not appear in the job log

Verify that the deploy job contains `after_script`.

The most important diagnostic command is:

```bash
kubectl describe pods \
  -n agent-demo \
  -l app=web
```

This is where readiness failures are normally visible.

---

## 56. Codex cannot connect to GitLab MCP

First verify HTTPS:

```bash
curl -I https://gitlab.agent.lab
```

Then verify Codex configuration:

```bash
codex mcp list
```

Common causes include:

- GitLab CA is not trusted;
- MCP client access is not enabled;
- GitLab hostname does not resolve;
- OAuth authentication has not completed.

---

## 57. Codex authenticated as the wrong GitLab user

If OAuth was completed while the browser was already signed in as an administrator, the MCP session may receive broader permissions than intended.

Re-authenticate using:

```text
agent-bot
```

The purpose of the lab is to demonstrate agent-specific permissions.

---

## 58. The agent can push directly to main

The branch protection rule is incorrect.

The agent should not have direct push access to `main`.

Review the branch rule and ensure that direct push is restricted.

---

## 59. The agent cannot create a branch or Merge Request

Verify:

```text
agent-bot
Role = Developer
```

Verify that the project membership is active.

Also verify that the agent is creating a new branch rather than attempting to change `main`.

---

# Part XVIII — Resetting the lab

## 60. Resetting Kubernetes

To remove the application but keep the cluster:

```bash
sudo -u gitlab-runner \
  -H kubectl \
  --context kind-agent-demo \
  delete namespace agent-demo
```

The next pipeline will recreate the namespace and resources.

To remove the whole Kind cluster:

```bash
sudo -u gitlab-runner \
  -H kind delete cluster \
  --name agent-demo
```

Recreate it with:

```bash
sudo -u gitlab-runner \
  -H kind create cluster \
  --name agent-demo
```

---

## 61. Restoring the broken repository state

For repeated demonstrations, restore:

```yaml
readinessProbe:
  httpGet:
    path: /healthz
```

A useful approach is to maintain a known baseline branch or tag such as:

```text
baseline/broken-readiness
```

This makes repeated recordings and classroom resets easier.

---

# Part XIX — Expected final repository

The final project structure is:

```text
agent-demo/
├── app/
│   └── server.py
├── k8s/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── .dockerignore
├── .gitignore
├── .gitlab-ci.yml
└── Dockerfile
```

The initial broken deployment contains:

```yaml
path: /healthz
```

The remediated deployment contains:

```yaml
path: /health
```

---

# Part XX — Completion checklist

The lab is complete when all of the following are true:

- [ ] GitLab Self-Managed is reachable over HTTPS.
- [ ] GitLab 19.4.1 is installed.
- [ ] GitLab MCP client access is enabled.
- [ ] Project `devops/agent-demo` exists.
- [ ] `agent-bot` is a Developer, not an administrator.
- [ ] GitLab Runner is online.
- [ ] The Runner can access Docker.
- [ ] The Runner can access the Kind cluster.
- [ ] The initial pipeline passes `test`.
- [ ] The initial pipeline passes `build`.
- [ ] The initial pipeline fails `deploy`.
- [ ] The deploy job log contains Kubernetes readiness diagnostics.
- [ ] Codex can connect to GitLab through MCP.
- [ ] Codex is authenticated as `agent-bot`.
- [ ] The agent can find the failed pipeline.
- [ ] The agent can inspect the failed job log.
- [ ] The agent can inspect repository files.
- [ ] The agent identifies `/health` versus `/healthz` as the root cause.
- [ ] The agent does not modify `main` directly.
- [ ] The agent creates a fix branch.
- [ ] The agent creates a minimal commit.
- [ ] The agent creates a Merge Request.
- [ ] The Merge Request pipeline passes.
- [ ] A human reviews the Merge Request.
- [ ] A human merges the change.
- [ ] The final pipeline on `main` passes.
- [ ] Kubernetes Pods become Ready.
- [ ] The Service has active endpoints.

---

# Part XXI — Extending the lab with Kubernetes MCP

The first version of this lab deliberately limits the agent to GitLab MCP.

The architecture is:

```text
Codex
  │
  └── GitLab MCP
```

GitLab provides:

```text
repository context
pipeline context
job logs
Merge Requests
commits
```

Kubernetes runtime evidence is copied into the GitLab job log.

A more advanced version can add a Kubernetes MCP server:

```text
                 ┌── GitLab MCP
Codex Agent ─────┤
                 └── Kubernetes MCP
```

The agent can then receive:

### From GitLab MCP

```text
Pipeline
Job
Repository
Commit
Merge Request
```

### From Kubernetes MCP

```text
Pod
Deployment
Service
Endpoint
Event
Log
```

In that version, the agent no longer depends entirely on diagnostics captured by the CI job.

It can correlate:

```text
source state
+
pipeline state
+
runtime state
```

directly.

That turns the lab from a CI/CD troubleshooting exercise into a multi-tool DevOps incident-response agent.

---

# Part XXII — Key architectural lessons

The most important lesson from this lab is not the readiness probe itself.

The failure is intentionally simple so that the architecture remains visible.

The real lessons are:

### GitLab can act as an MCP tool provider

Codex does not need custom GitLab REST integration code for every action.

GitLab MCP exposes GitLab capabilities to the agent in a tool-oriented form.

### The agent should have its own identity

The agent should not inherit the privileges of the administrator.

### The agent should not receive unrestricted infrastructure access by default

In this version, it does not need a Kubernetes kubeconfig.

### The agent can reason across multiple forms of evidence

It combines:

```text
pipeline result
job log
Kubernetes diagnostics
repository files
application behavior
```

### A useful agent is not necessarily an autonomous agent

The agent can prepare a technically correct change without owning the final production decision.

### Verification is part of remediation

The workflow does not stop after the fix is created.

The agent checks whether the new pipeline actually passes.

A complete remediation flow is:

```text
Detect
Investigate
Explain
Propose
Change
Review
Verify
```

That is the behavior this lab is designed to demonstrate.
