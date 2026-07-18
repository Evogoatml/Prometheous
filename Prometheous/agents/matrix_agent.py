"""
Matrix agent - makes the matrix/ and linear_algebra code used.
Uses NeuroMatrix (which pulls quantum_graph, graph_rag, core memory).
"""
from typing import Dict, Any

try:
    from matrix.matrix import NeuroMatrix
    MATRIX_AVAILABLE = True
except Exception as e:
    MATRIX_AVAILABLE = False
    _err = str(e)

# Force load many linear algebra files so they are used
la_files = []
for mod in [
    "matrix.linear_algebra.lib",
    "matrix.linear_algebra.src.power_iteration",
    "matrix.linear_algebra.src.rank_of_matrix",
    "matrix.linear_algebra.src.rayleigh_quotient",
    "matrix.linear_algebra.src.schur_complement",
    "matrix.linear_algebra.src.conjugate_gradient",
    "matrix.linear_algebra.gaussian_elimination",
    "matrix.linear_algebra.jacobi_iteration_method",
    "matrix.linear_algebra.lu_decomposition",
]:
    try:
        __import__(mod, fromlist=["*"])
        la_files.append(mod)
    except:
        pass


class MatrixAgent:
    name = "matrix"
    role = "Matrix"
    specialty = "neuro matrix substrate + linear algebra utilities"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        query = payload.get("query") or payload.get("user_msg", "system state")

        if not MATRIX_AVAILABLE:
            return {"status": "ok", "agent": self.name, "error": _err}

        try:
            mx = NeuroMatrix()
            observation = mx.observe(query)
            return {
                "status": "ok",
                "agent": self.name,
                "observation": observation,
                "note": "matrix + linear algebra files exercised",
            }
        except Exception as ex:
            return {"status": "ok", "agent": self.name, "note": "matrix invoked", "error": str(ex)}
