#!/usr/bin/env python3
from __future__ import annotations

from itertools import product
from typing import Any, Iterable

from pyscipopt import Model as _ScipModel
from pyscipopt import SCIP_PARAMSETTING
from pyscipopt import quicksum as _scip_quicksum


class SCIP:
    CONTINUOUS = "C"
    BINARY = "B"
    INTEGER = "I"

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"

    OPTIMAL = 2
    INFEASIBLE = 3
    INF_OR_UNBD = 4
    TIME_LIMIT = 9
    SUBOPTIMAL = 13


SCIPError = Exception
tupledict = dict


def _unwrap(value: Any) -> Any:
    if isinstance(value, Expr):
        return value._expr
    if isinstance(value, Var):
        return value._var
    return value


def quicksum(values: Iterable[Any]) -> Any:
    return Expr(_scip_quicksum(_unwrap(value) for value in values))


def LinExpr(value: Any = 0.0) -> Any:
    return Expr(value)


class Expr:
    def __init__(self, expr: Any = 0.0) -> None:
        self._expr = expr

    def __repr__(self) -> str:
        return repr(self._expr)

    def __add__(self, other: Any) -> "Expr":
        return Expr(self._expr + _unwrap(other))

    def __radd__(self, other: Any) -> "Expr":
        return Expr(_unwrap(other) + self._expr)

    def __sub__(self, other: Any) -> "Expr":
        return Expr(self._expr - _unwrap(other))

    def __rsub__(self, other: Any) -> "Expr":
        return Expr(_unwrap(other) - self._expr)

    def __mul__(self, other: Any) -> "Expr":
        return Expr(self._expr * _unwrap(other))

    def __rmul__(self, other: Any) -> "Expr":
        return Expr(_unwrap(other) * self._expr)

    def __truediv__(self, other: Any) -> "Expr":
        return Expr(self._expr / _unwrap(other))

    def __neg__(self) -> "Expr":
        return Expr(-self._expr)

    def __le__(self, other: Any) -> Any:
        return self._expr <= _unwrap(other)

    def __ge__(self, other: Any) -> Any:
        return self._expr >= _unwrap(other)

    def __eq__(self, other: Any) -> Any:  # type: ignore[override]
        return self._expr == _unwrap(other)


class _Params:
    def __init__(self, model: "Model") -> None:
        object.__setattr__(self, "_model", model)

    def __setattr__(self, name: str, value: Any) -> None:
        self._model._set_param(name, value)

    def __getattr__(self, name: str) -> Any:
        return self._model._params.get(name)


class Var:
    def __init__(self, model: "Model", var: Any, vtype: str) -> None:
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_var", var)
        object.__setattr__(self, "_vtype", vtype)

    @property
    def X(self) -> float:
        return self._model.getVal(self)

    @property
    def VType(self) -> str:
        return self._vtype

    @property
    def UB(self) -> float | None:
        return self._model._upper_bounds.get(id(self._var))

    @UB.setter
    def UB(self, value: float) -> None:
        self._model._upper_bounds[id(self._var)] = value
        try:
            self._model._model.chgVarUb(self._var, value)
        except Exception:
            pass

    @property
    def Start(self) -> float | None:
        item = self._model._starts.get(id(self._var))
        return None if item is None else item[1]

    @Start.setter
    def Start(self, value: float) -> None:
        self._model._starts[id(self._var)] = (self._var, value)

    def __hash__(self) -> int:
        return hash(self._var)

    def __repr__(self) -> str:
        return repr(self._var)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._var, name)

    def __add__(self, other: Any) -> Any:
        return Expr(self._var + _unwrap(other))

    def __radd__(self, other: Any) -> Any:
        return Expr(_unwrap(other) + self._var)

    def __sub__(self, other: Any) -> Any:
        return Expr(self._var - _unwrap(other))

    def __rsub__(self, other: Any) -> Any:
        return Expr(_unwrap(other) - self._var)

    def __mul__(self, other: Any) -> Any:
        return Expr(self._var * _unwrap(other))

    def __rmul__(self, other: Any) -> Any:
        return Expr(_unwrap(other) * self._var)

    def __truediv__(self, other: Any) -> Any:
        return Expr(self._var / _unwrap(other))

    def __neg__(self) -> Any:
        return Expr(-self._var)

    def __le__(self, other: Any) -> Any:
        return self._var <= _unwrap(other)

    def __ge__(self, other: Any) -> Any:
        return self._var >= _unwrap(other)

    def __eq__(self, other: Any) -> Any:  # type: ignore[override]
        return self._var == _unwrap(other)


class Model:
    def __init__(self, name: str = "") -> None:
        self._model = _ScipModel(name)
        self._vars: list[Var] = []
        self._params: dict[str, Any] = {}
        self._starts: dict[int, tuple[Any, float]] = {}
        self._upper_bounds: dict[int, float] = {}
        self._constraint_count = 0
        self.Params = _Params(self)

    def _set_param(self, name: str, value: Any) -> None:
        self._params[name] = value
        if name == "SCIPGap":
            self._model.setParam("limits/gap", float(value))
        elif name == "TimeLimit":
            self._model.setParam("limits/time", float(value))
        elif name == "OutputFlag" and int(value) == 0:
            self._model.setParam("display/verblevel", 0)

    def addVar(
        self,
        lb: float | None = 0.0,
        ub: float | None = None,
        vtype: str = SCIP.CONTINUOUS,
        name: str = "",
        **_: Any,
    ) -> Var:
        raw = self._model.addVar(name=name, vtype=vtype, lb=lb, ub=ub)
        wrapped = Var(self, raw, vtype)
        self._vars.append(wrapped)
        if ub is not None:
            self._upper_bounds[id(raw)] = ub
        return wrapped

    def addVars(self, *indexes: Iterable[Any], lb: float = 0.0, ub: float | None = None, vtype: str = SCIP.CONTINUOUS, name: str = "") -> dict[Any, Var]:
        if not indexes:
            return {}
        if len(indexes) == 1:
            keys = list(indexes[0])
        else:
            keys = list(product(*indexes))

        variables: dict[Any, Var] = {}
        for key in keys:
            if isinstance(key, tuple):
                suffix = ",".join(str(part) for part in key)
            else:
                suffix = str(key)
            variables[key] = self.addVar(lb=lb, ub=ub, vtype=vtype, name=f"{name}[{suffix}]" if name else suffix)
        return variables

    def addConstr(self, constraint: Any, name: str = "", **_: Any) -> Any:
        self._constraint_count += 1
        return self._model.addCons(_unwrap(constraint), name=name)

    def setObjective(self, expression: Any, sense: str = SCIP.MINIMIZE) -> None:
        self._model.setObjective(_unwrap(expression), sense)

    def optimize(self) -> None:
        self._apply_starts()
        try:
            self._model.setHeuristics(SCIP_PARAMSETTING.AGGRESSIVE)
        except Exception:
            pass
        self._model.optimize()

    def _apply_starts(self) -> None:
        if not self._starts:
            return
        try:
            solution = self._model.createSol()
            for var, value in self._starts.values():
                self._model.setSolVal(solution, var, value)
            self._model.addSol(solution, free=True)
        except Exception:
            pass

    def getVal(self, value: Any) -> float:
        return float(self._model.getVal(_unwrap(value)))

    def getVars(self) -> list[Var]:
        return list(self._vars)

    @property
    def Status(self) -> int:
        return self._status_code()

    @property
    def status(self) -> int:
        return self.Status

    def _status_code(self) -> int:
        status = str(self._model.getStatus()).lower()
        if status in {"optimal", "gaplimit"}:
            return SCIP.OPTIMAL
        if status in {"timelimit", "userinterrupt", "nodelimit", "stallnodelimit", "totalnodelimit"}:
            return SCIP.TIME_LIMIT
        if status == "infeasible":
            return SCIP.INFEASIBLE
        if status in {"inforunbd", "unbounded"}:
            return SCIP.INF_OR_UNBD
        if self.SolCount:
            return SCIP.SUBOPTIMAL
        return 0

    @property
    def SolCount(self) -> int:
        try:
            return int(self._model.getNSols())
        except Exception:
            return 0

    @property
    def ObjVal(self) -> float:
        return float(self._model.getObjVal())

    @property
    def objVal(self) -> float:
        return self.ObjVal

    @property
    def ObjBound(self) -> float:
        return float(self._model.getDualbound())

    @property
    def SCIPGap(self) -> float | None:
        try:
            return float(self._model.getGap())
        except Exception:
            return None

    @property
    def NumVars(self) -> int:
        return len(self._vars)

    @property
    def NumBinVars(self) -> int:
        return sum(1 for var in self._vars if var.VType == SCIP.BINARY)

    @property
    def NumIntVars(self) -> int:
        return sum(1 for var in self._vars if var.VType == SCIP.INTEGER)

    @property
    def NumConstrs(self) -> int:
        return self._constraint_count
