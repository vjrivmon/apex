"""APEX MCP handlers -- factored from apex_server.py."""
from __future__ import annotations
from typing import Any

from apex_handlers.context import handle_apex_init_project
from apex_handlers.context import handle_apex_get_context
from apex_handlers.context import handle_apex_set_phase
from apex_handlers.context import handle_apex_search
from apex_handlers.context import handle_apex_log_session
from apex_handlers.decisions import handle_apex_add_decision
from apex_handlers.decisions import handle_apex_invalidate_decision
from apex_handlers.decisions import handle_apex_add_error
from apex_handlers.components import handle_apex_add_component
from apex_handlers.components import handle_apex_update_component
from apex_handlers.components import handle_apex_add_next_step
from apex_handlers.components import handle_apex_complete_step
from apex_handlers.advisor import handle_apex_advisor_review
from apex_handlers.advisor import handle_apex_record_advice
from apex_handlers.advisor import handle_apex_dismiss_advice
from apex_handlers.advisor import handle_apex_rate_advice
from apex_handlers.advisor import handle_apex_advisor_compute_outcomes
from apex_handlers.advisor import handle_apex_advisor_health
from apex_handlers.advisor import handle_apex_advisor_apply_tuning
from apex_handlers.grader import handle_apex_grader_evaluate
from apex_handlers.wiki import handle_apex_wiki_add
from apex_handlers.wiki import handle_apex_search_cross_project
from apex_handlers.wiki import handle_apex_ingest_source
from apex_handlers.wiki import handle_apex_lint_second_brain
from apex_handlers.wiki import handle_apex_synthesize
from apex_handlers.handoff import handle_apex_handoff_write
from apex_handlers.handoff import handle_apex_resume_session
from apex_handlers.handoff import handle_apex_archive_output
from apex_handlers.handoff import handle_apex_get_archived
from apex_handlers.goal import handle_apex_goal_loop
from apex_handlers.design import handle_apex_design_md_init
from apex_handlers.design import handle_apex_design_md_validate
from apex_handlers.security import handle_apex_security_gate
from apex_handlers.security import handle_apex_scaffold_devops
from apex_handlers.roles import handle_apex_install_roles
from apex_handlers.roles import handle_apex_recommend_role
from apex_handlers.roles import handle_apex_invoke_role
from apex_handlers.forge import handle_apex_skill_forge_scan
from apex_handlers.forge import handle_apex_skill_forge_approve
from apex_handlers.forge import handle_apex_skill_forge_reject
from apex_handlers.doctor import handle_apex_doctor_run
from apex_handlers.prototype import handle_apex_prototype_init
from apex_handlers.browser import handle_apex_browser_trace
from apex_handlers.reverse import handle_apex_reverse_scan
from apex_handlers.reverse import handle_apex_reverse_plan
from apex_handlers.reverse import handle_apex_onboard_apply
from apex_handlers.portfolio import handle_apex_set_portfolio_meta
from apex_handlers.portfolio import handle_apex_portfolio_draft
from apex_handlers.library import handle_apex_ingest_library_skills
from apex_handlers.trace import handle_apex_log_trace
from apex_handlers.trace import handle_apex_handoff_skill
from apex_handlers.trace import handle_apex_resume_skill_handoff
from apex_handlers.reverse import handle_apex_research_competitor
from apex_handlers.books import handle_apex_book_search
from apex_handlers.books import handle_apex_book_index
from apex_handlers.books import handle_apex_book_list
from apex_handlers.books import LIBRARY_TOOLS
from apex_handlers.phase_gate import handle_apex_phase_entry_check

HANDLERS: dict[str, Any] = {
    "apex_init_project": handle_apex_init_project,
    "apex_get_context": handle_apex_get_context,
    "apex_set_phase": handle_apex_set_phase,
    "apex_search": handle_apex_search,
    "apex_log_session": handle_apex_log_session,
    "apex_add_decision": handle_apex_add_decision,
    "apex_invalidate_decision": handle_apex_invalidate_decision,
    "apex_add_error": handle_apex_add_error,
    "apex_add_component": handle_apex_add_component,
    "apex_update_component": handle_apex_update_component,
    "apex_add_next_step": handle_apex_add_next_step,
    "apex_complete_step": handle_apex_complete_step,
    "apex_advisor_review": handle_apex_advisor_review,
    "apex_record_advice": handle_apex_record_advice,
    "apex_dismiss_advice": handle_apex_dismiss_advice,
    "apex_rate_advice": handle_apex_rate_advice,
    "apex_advisor_compute_outcomes": handle_apex_advisor_compute_outcomes,
    "apex_advisor_health": handle_apex_advisor_health,
    "apex_advisor_apply_tuning": handle_apex_advisor_apply_tuning,
    "apex_grader_evaluate": handle_apex_grader_evaluate,
    "apex_wiki_add": handle_apex_wiki_add,
    "apex_search_cross_project": handle_apex_search_cross_project,
    "apex_ingest_source": handle_apex_ingest_source,
    "apex_lint_second_brain": handle_apex_lint_second_brain,
    "apex_synthesize": handle_apex_synthesize,
    "apex_handoff_write": handle_apex_handoff_write,
    "apex_resume_session": handle_apex_resume_session,
    "apex_archive_output": handle_apex_archive_output,
    "apex_get_archived": handle_apex_get_archived,
    "apex_goal_loop": handle_apex_goal_loop,
    "apex_design_md_init": handle_apex_design_md_init,
    "apex_design_md_validate": handle_apex_design_md_validate,
    "apex_security_gate": handle_apex_security_gate,
    "apex_scaffold_devops": handle_apex_scaffold_devops,
    "apex_install_roles": handle_apex_install_roles,
    "apex_recommend_role": handle_apex_recommend_role,
    "apex_invoke_role": handle_apex_invoke_role,
    "apex_skill_forge_scan": handle_apex_skill_forge_scan,
    "apex_skill_forge_approve": handle_apex_skill_forge_approve,
    "apex_skill_forge_reject": handle_apex_skill_forge_reject,
    "apex_doctor_run": handle_apex_doctor_run,
    "apex_prototype_init": handle_apex_prototype_init,
    "apex_browser_trace": handle_apex_browser_trace,
    "apex_reverse_scan": handle_apex_reverse_scan,
    "apex_reverse_plan": handle_apex_reverse_plan,
    "apex_onboard_apply": handle_apex_onboard_apply,
    "apex_set_portfolio_meta": handle_apex_set_portfolio_meta,
    "apex_portfolio_draft": handle_apex_portfolio_draft,
    "apex_ingest_library_skills": handle_apex_ingest_library_skills,
    "apex_log_trace": handle_apex_log_trace,
    "apex_handoff_skill": handle_apex_handoff_skill,
    "apex_resume_skill_handoff": handle_apex_resume_skill_handoff,
    "apex_research_competitor": handle_apex_research_competitor,
    "apex_book_search": handle_apex_book_search,
    "apex_book_index": handle_apex_book_index,
    "apex_book_list": handle_apex_book_list,
    "apex_phase_entry_check": handle_apex_phase_entry_check,
}
