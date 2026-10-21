"""The controlled workflow graph. One graph serves every workspace: workspace differences live in
data (verticals/), so a bookkeeping request never touches rental-specific code."""
from langgraph.graph import END, START, StateGraph

from app.agents import nodes as n
from app.agents.state import WorkflowState


def build_graph(checkpointer):
    g = StateGraph(WorkflowState)
    for fn in (n.intake_request, n.classify_workspace_and_intent, n.extract_structured_facts,
               n.resolve_existing_records, n.select_approved_template, n.validate_required_fields,
               n.build_dynamic_ui_manifest, n.request_missing_information, n.apply_deterministic_rules,
               n.render_document_preview, n.request_human_review, n.export_approved_documents,
               n.persist_audit_event):
        g.add_node(fn.__name__, fn)

    g.add_edge(START, "intake_request")
    g.add_edge("intake_request", "classify_workspace_and_intent")
    g.add_edge("classify_workspace_and_intent", "extract_structured_facts")
    g.add_edge("extract_structured_facts", "resolve_existing_records")
    g.add_edge("resolve_existing_records", "select_approved_template")
    g.add_edge("select_approved_template", "validate_required_fields")
    g.add_conditional_edges("validate_required_fields", n.route_after_validation,
                            ["build_dynamic_ui_manifest", "apply_deterministic_rules"])
    g.add_conditional_edges("build_dynamic_ui_manifest", n.route_after_manifest,
                            ["request_missing_information", "request_human_review"])
    # After answers arrive, re-run template selection and validation with the new facts.
    g.add_conditional_edges("request_missing_information", lambda s: END if s.get("cancelled") else "select_approved_template",
                            [END, "select_approved_template"])
    g.add_edge("apply_deterministic_rules", "render_document_preview")
    g.add_edge("render_document_preview", "build_dynamic_ui_manifest")
    g.add_conditional_edges("request_human_review", n.route_after_review,
                            [END, "export_approved_documents", "build_dynamic_ui_manifest", "select_approved_template"])
    g.add_conditional_edges("export_approved_documents", n.route_after_export,
                            ["select_approved_template", "persist_audit_event", "export_approved_documents"])
    g.add_edge("persist_audit_event", END)
    return g.compile(checkpointer=checkpointer)
