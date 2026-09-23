from .ledger import Ledger, Requirement, RequirementKind, DuplicateRequirementError
from .model import Model, UnknownDataError, UnknownVariableError, UntaggedConstraintError
from .specs import (
    CapacityLimit,
    Constraint,
    CustomConstraint,
    DataValue,
    DecisionVariable,
    DemandCoverage,
    LinearObjective,
    RuleViolation,
    Spec,
)
from .solve import SolveResult, solve
from .validate import ConstraintViolation, FeasibilityReport, check_feasibility, quality_gap
from .infeasibility import Conflict, ConflictMember, RequirementViolation, InfeasibilityDiagnosis, explain_infeasibility, find_conflict
from .cbc_diagnostics import CbcDiagnostics, solve_with_diagnostics
from .report import build_report, diagnose
from .run import RunResult, run
from .graph import to_dot
from .debug_bundle import build_debug_bundle
from .sensitivity import (
    RequirementSensitivity,
    SensitivityReport,
    ImpactResult,
    SolveDiff,
    binding_report,
    requirement_impact,
    solve_diff,
)

__all__ = [
    "Ledger",
    "Requirement",
    "RequirementKind",
    "DuplicateRequirementError",
    "Model",
    "UntaggedConstraintError",
    "UnknownVariableError",
    "UnknownDataError",
    "Spec",
    "Constraint",
    "CapacityLimit",
    "DemandCoverage",
    "CustomConstraint",
    "DecisionVariable",
    "DataValue",
    "LinearObjective",
    "RuleViolation",
    "SolveResult",
    "solve",
    "ConstraintViolation",
    "FeasibilityReport",
    "check_feasibility",
    "quality_gap",
    "RequirementViolation",
    "InfeasibilityDiagnosis",
    "explain_infeasibility",
    "find_conflict",
    "Conflict",
    "ConflictMember",
    "CbcDiagnostics",
    "solve_with_diagnostics",
    "build_report",
    "diagnose",
    "RunResult",
    "run",
    "to_dot",
    "build_debug_bundle",
    "RequirementSensitivity",
    "SensitivityReport",
    "ImpactResult",
    "SolveDiff",
    "binding_report",
    "requirement_impact",
    "solve_diff",
]
