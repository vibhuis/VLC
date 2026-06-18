# VCL policy bundle — the five written policies enforced at runtime. [spec §5.3]
#
# The agent runtime calls POST /v1/data/vcl/<rule> with {"input": {...}} for every
# data access and decision. Each rule returns a structured decision object:
#   {"policy": str, "allow": bool, "outcome": "allow"|"deny"|"mask", "reasons": [str]}
#
# Outcomes:
#   allow — proceed; deny — exclude the row + audit; mask — return redacted + audit.
package vcl

import rego.v1

# ----------------------------------------------------------------- shared helpers
outcome_for(true) := "allow"
outcome_for(false) := "deny"

# Organisational access: principal.org_access is a list of geos (or "*" for all).
default has_region_access := false
has_region_access if input.principal.org_access[_] == "*"
has_region_access if input.principal.org_access[_] == input.resource.geo

# Purpose binding: a non-empty, recognised processing purpose.
known_purposes := {"supplier_risk_review", "supplier_pii_processing"}
default has_purpose_binding := false
has_purpose_binding if {
	input.principal.purpose != ""
	known_purposes[input.principal.purpose]
}

# Consent validity by retention date (ISO-8601 strings sort chronologically).
default consent_valid := false
consent_valid if {
	input.resource.consent_retention_until != null
	input.resource.consent_retention_until != ""
	input.resource.consent_retention_until >= input.as_of
}

# ------------------------------------------------- 1. allow_supplier_query [§5.3.1]
allow_supplier_query := {
	"policy": "allow_supplier_query",
	"allow": has_region_access,
	"outcome": outcome_for(has_region_access),
	"reasons": supplier_reasons,
}

supplier_reasons := ["organisational access granted for the supplier's region"] if has_region_access
supplier_reasons := ["principal has no organisational access to this region"] if not has_region_access

# --------------------------------------------- 2. allow_pii_field_access [§5.3.2]
default pii_outcome := "deny"
pii_outcome := "allow" if {
	has_purpose_binding
	consent_valid
}
pii_outcome := "mask" if {
	has_purpose_binding
	not consent_valid
}

allow_pii_field_access := {
	"policy": "allow_pii_field_access",
	"allow": pii_outcome == "allow",
	"outcome": pii_outcome,
	"reasons": pii_reasons,
}

pii_reasons := ["purpose binding present and data-subject consent valid"] if pii_outcome == "allow"
pii_reasons := ["purpose binding present but data-subject consent expired or missing — PII fields masked"] if pii_outcome == "mask"
pii_reasons := ["no valid purpose binding for PII access"] if pii_outcome == "deny"

# --------------------------------------------- 3. require_residency_match [§5.3.3]
default residency_ok := false
residency_ok if input.context.residency_scope != "EU" # constraint only applies to EU-subject questions
residency_ok if {
	input.context.residency_scope == "EU"
	input.resource.data_residency == "EU"
}

require_residency_match := {
	"policy": "require_residency_match",
	"allow": residency_ok,
	"outcome": outcome_for(residency_ok),
	"reasons": residency_reasons,
}

residency_reasons := ["no residency constraint applies to this query"] if input.context.residency_scope != "EU"
residency_reasons := ["data residency matches the required EU scope"] if {
	input.context.residency_scope == "EU"
	residency_ok
}
residency_reasons := ["EU-subject query but data is hosted outside the EU — row excluded"] if {
	input.context.residency_scope == "EU"
	not residency_ok
}

# --------------------------------------------- 4. mask_secrets_in_response [§5.3.4]
default secrets_present := false
secrets_present if input.resource.contains_secrets == true

secrets_outcome := "mask" if secrets_present
secrets_outcome := "allow" if not secrets_present

mask_secrets_in_response := {
	"policy": "mask_secrets_in_response",
	"allow": secrets_outcome == "allow",
	"outcome": secrets_outcome,
	"reasons": secrets_reasons,
}

secrets_reasons := ["secret clauses must be summarised, not quoted — content masked"] if secrets_present
secrets_reasons := ["no secret clauses present"] if not secrets_present

# --------------------------------------------- 5. audit_required_on_decline [§5.3.5]
declining_outcomes := {"deny", "mask"}
default audit_req := false
audit_req if declining_outcomes[input.decision.outcome]

audit_required_on_decline := {
	"policy": "audit_required_on_decline",
	"audit_required": audit_req,
	"outcome": object.get(input, ["decision", "outcome"], "unknown"),
	"reasons": audit_reasons,
}

audit_reasons := ["a decline/mask outcome must emit a structured audit event with reason"] if audit_req
audit_reasons := ["no audit obligation for an allow outcome"] if not audit_req
