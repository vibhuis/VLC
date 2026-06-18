# Rego unit tests for the VCL policies. Run with:  opa test services/policy-engine/policies
package vcl

import rego.v1

# 1. allow_supplier_query --------------------------------------------------------
test_supplier_query_allow_in_region if {
	allow_supplier_query.allow with input as {"principal": {"org_access": ["EMEA"]}, "resource": {"geo": "EMEA"}}
}

test_supplier_query_allow_wildcard if {
	allow_supplier_query.allow with input as {"principal": {"org_access": ["*"]}, "resource": {"geo": "APAC"}}
}

test_supplier_query_deny_out_of_region if {
	not allow_supplier_query.allow with input as {"principal": {"org_access": ["EMEA"]}, "resource": {"geo": "AMER"}}
}

# 2. allow_pii_field_access ------------------------------------------------------
test_pii_allow_with_purpose_and_consent if {
	d := allow_pii_field_access with input as {
		"as_of": "2026-06-18",
		"principal": {"purpose": "supplier_risk_review"},
		"resource": {"consent_retention_until": "2027-01-01"},
	}
	d.outcome == "allow"
	d.allow
}

test_pii_mask_when_consent_expired if {
	d := allow_pii_field_access with input as {
		"as_of": "2026-06-18",
		"principal": {"purpose": "supplier_risk_review"},
		"resource": {"consent_retention_until": "2026-01-01"},
	}
	d.outcome == "mask"
	not d.allow
}

test_pii_deny_without_purpose if {
	d := allow_pii_field_access with input as {
		"as_of": "2026-06-18",
		"principal": {"purpose": ""},
		"resource": {"consent_retention_until": "2027-01-01"},
	}
	d.outcome == "deny"
}

# 3. require_residency_match -----------------------------------------------------
test_residency_allow_eu_data if {
	d := require_residency_match with input as {"context": {"residency_scope": "EU"}, "resource": {"data_residency": "EU"}}
	d.allow
}

test_residency_deny_us_data_for_eu_query if {
	d := require_residency_match with input as {"context": {"residency_scope": "EU"}, "resource": {"data_residency": "US"}}
	not d.allow
	d.outcome == "deny"
}

test_residency_unconstrained_when_not_eu if {
	d := require_residency_match with input as {"context": {"residency_scope": "GLOBAL"}, "resource": {"data_residency": "US"}}
	d.allow
}

# 4. mask_secrets_in_response ----------------------------------------------------
test_secrets_masked_when_present if {
	d := mask_secrets_in_response with input as {"resource": {"contains_secrets": true}}
	d.outcome == "mask"
	not d.allow
}

test_secrets_allowed_when_absent if {
	d := mask_secrets_in_response with input as {"resource": {"contains_secrets": false}}
	d.outcome == "allow"
	d.allow
}

# 5. audit_required_on_decline ---------------------------------------------------
test_audit_required_on_deny if {
	audit_required_on_decline.audit_required with input as {"decision": {"outcome": "deny"}}
}

test_audit_required_on_mask if {
	audit_required_on_decline.audit_required with input as {"decision": {"outcome": "mask"}}
}

test_audit_not_required_on_allow if {
	not audit_required_on_decline.audit_required with input as {"decision": {"outcome": "allow"}}
}
