package agent.authz_test
import rego.v1
import data.agent.authz

identity := {
  "agent_id":"incident-agent",
  "roles":["incident-responder"],
  "capabilities":["get_logs","restart_deployment"]
}
ctx := {"action_hash":"abc","calls_last_window":0,"max_calls":3,"window_seconds":600}

test_staging_restart_allowed if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-staging","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":ctx,
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "allow"
}

test_production_requires_approval if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-production","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":ctx,
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "require_approval"
}

test_approved_production_allowed if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-production","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":ctx,
    "approval":{"valid":true,"action_hash":"abc"}
  }
  r.effect == "allow"
}

test_delete_denied if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"delete_namespace","namespace":"agent-lab-production","resource_kind":"namespace","resource":"agent-lab-production","reason":"cleanup"},
    "context":ctx,
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "deny"
}

test_rate_limit_denied if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-staging","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":{"action_hash":"abc","calls_last_window":3,"max_calls":3,"window_seconds":600},
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "deny"
}
